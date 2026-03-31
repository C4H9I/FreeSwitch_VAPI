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
from typing import Optional

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
        self.hangup_event = asyncio.Event()
        self.reader_task: Optional[asyncio.Task] = None

    async def bootstrap(self) -> None:
        await self._send_command("connect")
        self.channel_data = await self._read_channel_data()
        await self._send_command("myevents")
        await self._send_command("linger")
        self.reader_task = asyncio.create_task(self._read_events())

    async def _read_events(self) -> None:
        try:
            while not self.reader.at_eof():
                frame = await self._read_frame()
                if frame.content_type == "text/event-plain":
                    event = self._parse_event_body(frame.body)
                    event_name = event.get("Event-Name", "")
                    if event_name.startswith("CHANNEL_HANGUP"):
                        self.hangup_event.set()
                        return
        except Exception as exc:
            logger.warning(f"ESL event reader stopped: {exc}")
            self.hangup_event.set()

    async def execute(self, app: str, arg: str = "") -> None:
        lines = [
            "sendmsg",
            "call-command: execute",
            "event-lock: true",
            f"execute-app-name: {app}",
        ]
        if arg:
            lines.append(f"execute-app-arg: {arg}")
        await self._send_command("\n".join(lines))

    async def playback(self, wav_path: Path) -> None:
        await self.execute("playback", str(wav_path))
        duration = get_wav_duration(wav_path)
        await self._sleep_or_hangup(duration + 0.2)

    async def record(self, wav_path: Path, max_seconds: int, silence_threshold: int = 200, silence_hits: int = 3) -> None:
        await self.execute("record", f"{wav_path} {max_seconds} {silence_threshold} {silence_hits}")
        await self._wait_for_recording(wav_path, max_seconds + 2)

    async def hangup(self) -> None:
        await self.execute("hangup")
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

    async def _send_command(self, payload: str) -> None:
        self.writer.write((payload + "\n\n").encode("utf-8"))
        await self.writer.drain()

    async def _read_channel_data(self) -> dict[str, str]:
        for _ in range(10):
            frame = await self._read_frame()
            if frame.content_type == "text/disconnect-notice":
                reason = frame.headers.get("Content-Disposition") or frame.body or "call disconnected"
                raise RuntimeError(f"FreeSWITCH closed outbound socket before CHANNEL_DATA: {reason}")

            if frame.content_type == "command/reply":
                continue

            event_data = self._parse_event_body(frame.body)
            if event_data.get("Caller-Caller-ID-Number") or event_data.get("Unique-ID"):
                return event_data

            if frame.headers:
                logger.debug(f"Skipping ESL frame while waiting for CHANNEL_DATA: {frame.headers}")

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

        greeting_path = temp_dir / f"{uuid}_greeting.wav"
        greeting_path.write_bytes(await dialog.start_session(uuid))
        await session.playback(greeting_path)

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
