#!/usr/bin/env python3
"""
Minimal FreeSWITCH outbound socket voice bot.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from app.dialog_manager import DialogState, create_dialog_manager
from config.settings import Settings, load_config


def setup_logging(cfg: Settings) -> None:
    logger.remove()
    log_path = Path(cfg.logging.file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_path = Path(__file__).parent / "logs" / "voice-bot.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        sys.stdout,
        level=cfg.logging.level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        colorize=True,
    )
    logger.add(str(log_path), level=cfg.logging.level, rotation=f"{cfg.logging.max_size} MB")
    logger.info(f"Logging to {log_path}")


class ESLFrame:
    def __init__(self, headers: dict[str, str], body: str = ""):
        self.headers = headers
        self.body = body

    @property
    def content_type(self) -> str:
        return self.headers.get("Content-Type", "")


class OutboundSession:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.channel_data: dict[str, str] = {}
        self.uuid: str = ""
        self.hangup_event = asyncio.Event()
        self.channel_answered = asyncio.Event()
        self.reader_task: Optional[asyncio.Task] = None
        self._command_lock = asyncio.Lock()
        self._reply_waiters: list[asyncio.Future[ESLFrame]] = []
        self._event_waiters: list[tuple[Callable[[dict[str, str]], bool], asyncio.Future[dict[str, str]]]] = []

    async def bootstrap(self) -> None:
        logger.info("Call state: INITIAL_SOCKET_CONNECT")
        initial_frame = await self._try_read_initial_frame(timeout=0.5)
        self.channel_data = self._extract_channel_data(initial_frame) if initial_frame else {}
        if not self.channel_data:
            logger.info("No initial CHANNEL_DATA frame, requesting via 'connect'")
            await self._send_prebootstrap_command("connect")
            self.channel_data = await self._read_channel_data()
        self.uuid = (
            self.channel_data.get("Unique-ID")
            or self.channel_data.get("Channel-Unique-ID")
            or self.channel_data.get("Caller-Unique-ID")
            or ""
        )
        logger.info(
            "Call state: INITIAL_HEADERS_READ "
            f"uuid={self.uuid or 'unknown'} caller={self.channel_data.get('Caller-Caller-ID-Number', 'unknown')} "
            f"destination={self.channel_data.get('Caller-Destination-Number', 'unknown')}"
        )
        self.reader_task = asyncio.create_task(self._read_events())
        logger.info("Call state: EVENT_LOOP_RUNNING")

    async def _read_events(self) -> None:
        try:
            while not self.reader.at_eof():
                frame = await self._read_frame()
                if frame.content_type in {"command/reply", "api/response"}:
                    if self._reply_waiters:
                        waiter = self._reply_waiters.pop(0)
                        if not waiter.done():
                            waiter.set_result(frame)
                    else:
                        logger.debug(f"Orphan command reply: headers={frame.headers} body={frame.body!r}")
                    continue

                event = self._frame_to_event(frame)
                if not event:
                    continue

                event_name = event.get("Event-Name", "")
                channel_state = event.get("Channel-State", "")

                if event_name == "CHANNEL_ANSWER" or channel_state == "CS_EXECUTE":
                    self.channel_answered.set()

                if event_name.startswith("CHANNEL_HANGUP") or frame.content_type == "text/disconnect-notice":
                    self.hangup_event.set()

                for idx, (predicate, waiter) in enumerate(list(self._event_waiters)):
                    if waiter.done():
                        continue
                    if predicate(event):
                        waiter.set_result(event)
                        self._event_waiters.pop(idx)
                        break
        except Exception as exc:
            logger.warning(f"ESL event reader stopped: {exc}")
            self.hangup_event.set()
        finally:
            for waiter in self._reply_waiters:
                if not waiter.done():
                    waiter.set_exception(ConnectionError("ESL connection closed"))
            self._reply_waiters.clear()
            for _, waiter in self._event_waiters:
                if not waiter.done():
                    waiter.set_exception(ConnectionError("ESL connection closed"))
            self._event_waiters.clear()

    async def execute(self, app: str, arg: str = "", complete_timeout: float = 30.0) -> dict[str, str]:
        sendmsg = f"sendmsg {self.uuid}" if self.uuid else "sendmsg"
        lines = [
            sendmsg,
            "call-command: execute",
            f"execute-app-name: {app}",
            "event-lock: true",
        ]
        if arg:
            lines.append(f"execute-app-arg: {arg}")
        payload = "\n".join(lines)

        execute_complete_waiter = self._register_event_waiter(
            lambda event: (
                event.get("Event-Name") == "CHANNEL_EXECUTE_COMPLETE"
                and event.get("Application") == app
                and (
                    not arg
                    or event.get("Application-Data", "") == arg
                    or event.get("Application-Data", "").endswith(arg)
                )
            )
        )
        logger.info(f"ESL execute: app={app!r} arg={arg!r}")
        reply = await self._send_command(payload)
        reply_text = reply.headers.get("Reply-Text", "") or reply.body
        if "+OK" not in reply_text:
            execute_complete_waiter.cancel()
            raise RuntimeError(f"FreeSWITCH execute rejected: app={app}, reply={reply_text or reply.body!r}")

        try:
            return await asyncio.wait_for(execute_complete_waiter, timeout=complete_timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Timeout waiting CHANNEL_EXECUTE_COMPLETE for app={app!r} arg={arg!r}") from exc

    async def playback(self, wav_path: Path) -> None:
        logger.info(f"Playback file: {wav_path} size={wav_path.stat().st_size if wav_path.exists() else 'missing'}")
        duration = max(get_wav_duration(wav_path), 0.1)
        await self.execute("playback", str(wav_path), complete_timeout=duration + 15.0)
        logger.info("Call state: PLAYBACK_GREETING_COMPLETE")

    async def record(self, wav_path: Path, max_seconds: int, silence_threshold: int = 200, silence_hits: int = 3) -> None:
        logger.info(
            f"Record target: {wav_path} max_seconds={max_seconds} silence_threshold={silence_threshold} silence_hits={silence_hits}"
        )
        await self.execute("record", f"{wav_path} {max_seconds} {silence_threshold} {silence_hits}", complete_timeout=max_seconds + 10.0)
        await self._wait_for_recording(wav_path, max_seconds + 2)

    async def answer(self) -> None:
        logger.info("Call state: ANSWER")
        await self.execute("answer", complete_timeout=10.0)
        self.channel_answered.set()
        logger.info("Call state: MEDIA_ESTABLISHED_WAIT")
        await self._sleep_or_hangup(0.25)
        logger.info("Call state: MEDIA_ESTABLISHED")

    async def enable_events(self) -> None:
        await self._send_command("myevents")
        await self._send_command("linger")

    async def hangup(self) -> None:
        await self.execute("hangup", complete_timeout=10.0)
        self.hangup_event.set()

    async def close(self) -> None:
        if self.reader_task:
            self.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader_task
        self.writer.close()
        await self.writer.wait_closed()

    async def _wait_for_recording(self, wav_path: Path, timeout_seconds: int) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_size = -1
        stable_since: Optional[float] = None

        while time.monotonic() < deadline and not self.hangup_event.is_set():
            if wav_path.exists():
                size = wav_path.stat().st_size
                if size > 44 and size == last_size:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 1.0:
                        return
                else:
                    stable_since = None
                    last_size = size
            await asyncio.sleep(0.25)

    async def _sleep_or_hangup(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.hangup_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return

    async def _send_command(self, payload: str, timeout: float = 5.0) -> ESLFrame:
        async with self._command_lock:
            loop = asyncio.get_running_loop()
            waiter: asyncio.Future[ESLFrame] = loop.create_future()
            self._reply_waiters.append(waiter)
            self.writer.write((payload + "\r\n\r\n").encode("utf-8"))
            await self.writer.drain()
            logger.debug(f"ESL command sent: {payload!r}")
            try:
                frame = await asyncio.wait_for(waiter, timeout=timeout)
            except Exception:
                if waiter in self._reply_waiters:
                    self._reply_waiters.remove(waiter)
                raise
            logger.debug(f"ESL command reply: headers={frame.headers} body={frame.body!r}")
            return frame

    async def _send_prebootstrap_command(self, payload: str) -> None:
        self.writer.write((payload + "\r\n\r\n").encode("utf-8"))
        await self.writer.drain()
        logger.debug(f"ESL prebootstrap command sent: {payload!r}")

    async def _read_channel_data(self) -> dict[str, str]:
        for _ in range(10):
            frame = await self._read_frame()
            if frame.content_type == "text/disconnect-notice":
                reason = frame.headers.get("Content-Disposition") or frame.body or "call disconnected"
                raise RuntimeError(f"FreeSWITCH closed outbound socket before CHANNEL_DATA: {reason}")

            channel_data = self._extract_channel_data(frame)
            if channel_data:
                logger.info(f"Received outbound socket channel data: {channel_data}")
                return channel_data

            if frame.content_type == "command/reply":
                logger.info(f"Received command reply before CHANNEL_DATA: headers={frame.headers}, body={frame.body!r}")
                continue

            if frame.headers:
                logger.warning(
                    f"Unexpected ESL frame while waiting for CHANNEL_DATA: headers={frame.headers}, body={frame.body!r}"
                )

        raise RuntimeError("Failed to receive CHANNEL_DATA from FreeSWITCH after connect")

    async def _read_frame(self) -> ESLFrame:
        headers: dict[str, str] = {}
        while True:
            raw_line = await self.reader.readline()
            if not raw_line:
                raise ConnectionError("ESL connection closed")
            line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
            if not line and not headers:
                continue
            if not line:
                break
            if ": " in line:
                key, value = line.split(": ", 1)
                headers[key] = value

        body = ""
        content_length = int(headers.get("Content-Length", "0") or "0")
        if content_length > 0:
            raw_body = await self.reader.readexactly(content_length)
            body = raw_body.decode("utf-8", errors="ignore")

        return ESLFrame(headers=headers, body=body)

    async def _try_read_initial_frame(self, timeout: float = 0.5) -> Optional[ESLFrame]:
        try:
            return await asyncio.wait_for(self._read_frame(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def _extract_channel_data(self, frame: Optional[ESLFrame]) -> dict[str, str]:
        if frame is None:
            return {}
        if frame.content_type == "text/disconnect-notice":
            reason = frame.headers.get("Content-Disposition") or frame.body or "call disconnected"
            raise RuntimeError(f"FreeSWITCH closed outbound socket before CHANNEL_DATA: {reason}")

        if frame.headers.get("Unique-ID") or frame.headers.get("Caller-Caller-ID-Number"):
            return frame.headers

        event_data = self._parse_event_body(frame.body)
        if event_data.get("Caller-Caller-ID-Number") or event_data.get("Unique-ID"):
            return event_data
        return {}

    def _register_event_waiter(self, predicate: Callable[[dict[str, str]], bool]) -> asyncio.Future[dict[str, str]]:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[dict[str, str]] = loop.create_future()
        self._event_waiters.append((predicate, waiter))
        return waiter

    def _frame_to_event(self, frame: ESLFrame) -> dict[str, str]:
        event: dict[str, str] = {}
        if frame.content_type == "text/event-plain":
            event.update(self._parse_event_body(frame.body))
        for key in ("Event-Name", "Unique-ID", "Channel-State", "Application", "Application-Data", "Reply-Text"):
            if key in frame.headers and key not in event:
                event[key] = frame.headers[key]
        if frame.content_type and "Content-Type" not in event:
            event["Content-Type"] = frame.content_type
        return event

    @staticmethod
    def _parse_event_body(body: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for raw_line in body.splitlines():
            if ": " in raw_line:
                key, value = raw_line.split(": ", 1)
                data[key] = value
        return data


def get_wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
        return frames / float(rate) if rate else 0.0


def read_env_file() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


async def run_test_dialog(cfg: Settings, force_mock: bool = False) -> None:
    dialog = create_dialog_manager(
        yandex_api_key=cfg.yandex_api_key or "",
        yandex_folder_id=cfg.yandex_folder_id,
        openai_api_key=cfg.openai_api_key or "",
        openai_api_base=cfg.openai_api_base,
        system_prompt=cfg.llm.system_prompt,
        voice_config={"tts": cfg.voice.tts.model_dump()},
        dialog_config={
            "greeting": cfg.dialog.greeting,
            "goodbye": cfg.dialog.goodbye,
            "not_understood": cfg.dialog.not_understood,
            "max_turns": cfg.dialog.max_turns,
            "llm_model": cfg.llm.model,
            "max_tokens": cfg.llm.max_tokens,
        },
        use_mock_asr_tts=(force_mock or not bool(cfg.yandex_api_key)),
        use_mock_llm=(force_mock or not bool(cfg.openai_api_key)),
    )
    greeting = await dialog.start_session("local-test")
    greeting_path = Path(tempfile.gettempdir()) / "voice_bot_test_greeting.wav"
    greeting_path.write_bytes(greeting)
    logger.info(f"Test greeting written to {greeting_path}")
    response = await dialog.process_text("Здравствуйте")
    response_path = Path(tempfile.gettempdir()) / "voice_bot_test_response.wav"
    response_path.write_bytes(response)
    logger.info(f"Test response written to {response_path}")


async def handle_call(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    cfg: Settings,
    force_mock: bool = False,
) -> None:
    session = OutboundSession(reader, writer)
    temp_dir = Path(tempfile.gettempdir()) / "voice-bot"
    temp_dir.mkdir(parents=True, exist_ok=True)

    dialog = create_dialog_manager(
        yandex_api_key=cfg.yandex_api_key or "",
        yandex_folder_id=cfg.yandex_folder_id,
        openai_api_key=cfg.openai_api_key or "",
        openai_api_base=cfg.openai_api_base,
        system_prompt=cfg.llm.system_prompt,
        voice_config={
            "tts": cfg.voice.tts.model_dump(),
            "asr": cfg.voice.asr.model_dump(),
        },
        dialog_config={
            "greeting": cfg.dialog.greeting,
            "goodbye": cfg.dialog.goodbye,
            "not_understood": cfg.dialog.not_understood,
            "max_turns": cfg.dialog.max_turns,
            "llm_model": cfg.llm.model,
            "max_tokens": cfg.llm.max_tokens,
        },
        use_mock_asr_tts=(force_mock or not bool(cfg.yandex_api_key)),
        use_mock_llm=(force_mock or not bool(cfg.openai_api_key)),
    )

    try:
        await session.bootstrap()
        uuid = session.channel_data.get("Unique-ID", f"call-{int(time.time())}")
        caller = session.channel_data.get("Caller-Caller-ID-Number", "unknown")
        destination = session.channel_data.get("Caller-Destination-Number", "unknown")
        logger.info(f"Incoming call {uuid}: {caller} -> {destination}")

        await session.answer()
        await session.enable_events()

        greeting_path = temp_dir / f"{uuid}_greeting.wav"
        greeting_path.write_bytes(await dialog.start_session(uuid))
        logger.info("Call state: PLAYBACK_GREETING")
        await session.playback(greeting_path)
        logger.info("Call state: MAIN_BOT_LOGIC")

        started_at = time.monotonic()
        for turn in range(cfg.dialog.max_turns):
            if session.hangup_event.is_set():
                break
            if time.monotonic() - started_at > cfg.dialog.max_duration:
                logger.info(f"Call {uuid}: max duration reached")
                break

            record_path = temp_dir / f"{uuid}_turn_{turn}.wav"
            if record_path.exists():
                record_path.unlink()

            await session.record(record_path, cfg.voice.asr.speech_timeout)
            if not record_path.exists() or record_path.stat().st_size <= 44:
                logger.info(f"Call {uuid}: empty recording")
                continue

            user_text = await dialog.asr.recognize_wav(record_path)
            if not user_text.strip():
                logger.info(f"Call {uuid}: ASR returned empty text")
                retry_path = temp_dir / f"{uuid}_retry_{turn}.wav"
                retry_path.write_bytes(await dialog.tts.synthesize(cfg.dialog.not_understood))
                await session.playback(retry_path)
                continue

            logger.info(f"Call {uuid}: user said {user_text!r}")
            response_audio = await dialog.process_text(user_text)
            response_path = temp_dir / f"{uuid}_response_{turn}.wav"
            response_path.write_bytes(response_audio)
            await session.playback(response_path)

            if dialog.state == DialogState.ENDED:
                break

        if not session.hangup_event.is_set():
            await session.hangup()
    except Exception as exc:
        logger.exception(f"Call handling error: {exc}")
        if not session.hangup_event.is_set():
            with contextlib.suppress(Exception):
                await session.hangup()
    finally:
        await dialog.asr.close()
        await dialog.tts.close()
        await dialog.llm.close()
        with contextlib.suppress(Exception):
            await session.close()


async def run_server(cfg: Settings, force_mock: bool = False) -> None:
    socket_host = os.getenv("VOICE_BOT_HOST", "127.0.0.1")
    socket_port = int(os.getenv("VOICE_BOT_PORT", "8084"))

    async def client_connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle_call(reader, writer, cfg, force_mock=force_mock)

    server = await asyncio.start_server(
        client_connected,
        socket_host,
        socket_port,
    )
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.info(f"Voice bot listening on {sockets}")

    async with server:
        await server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal FreeSWITCH voice bot")
    parser.add_argument("--config", "-c", default=None)
    parser.add_argument("--test", "-t", action="store_true")
    parser.add_argument("--mock", "-m", action="store_true")
    return parser.parse_args()


def main() -> None:
    read_env_file()
    args = parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg)

    if args.test:
        asyncio.run(run_test_dialog(cfg, force_mock=args.mock))
    else:
        asyncio.run(run_server(cfg, force_mock=args.mock))


if __name__ == "__main__":
    main()
