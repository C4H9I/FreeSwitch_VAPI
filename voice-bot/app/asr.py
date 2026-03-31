"""
Yandex SpeechKit ASR.
"""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from typing import Optional

import aiohttp
from loguru import logger


class YandexASR:
    """ASR client via Yandex SpeechKit REST API."""

    ENDPOINT = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"

    def __init__(
        self,
        api_key: str,
        folder_id: Optional[str] = None,
        language: str = "ru-RU",
        model: str = "general",
        sample_rate: int = 8000,
        partial_results: bool = False,
        silence_threshold: float = 1.0,
    ):
        self.api_key = api_key
        self.folder_id = folder_id
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        self.partial_results = partial_results
        self.silence_threshold = silence_threshold
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        logger.info("Yandex ASR: connected")

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def recognize_stream(self, audio_generator):
        raise NotImplementedError("Streaming ASR is not implemented for this minimal agent")

    async def recognize_file(self, audio_data: bytes, sample_rate: Optional[int] = None) -> str:
        if not audio_data:
            return ""

        await self.connect()
        assert self._session is not None

        params = {
            "lang": self.language,
            "topic": self.model,
            "format": "lpcm",
            "sampleRateHertz": str(sample_rate or self.sample_rate),
        }
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/octet-stream",
        }

        async with self._session.post(
            self.ENDPOINT,
            params=params,
            headers=headers,
            data=audio_data,
        ) as response:
            response_text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"Yandex ASR error {response.status}: {response_text}")

        payload = json.loads(response_text)
        result = (payload.get("result") or "").strip()
        logger.info(f"ASR text: {result!r}")
        return result

    async def recognize_wav(self, wav_path: str | Path) -> str:
        path = Path(wav_path)
        if not path.exists():
            return ""

        with wave.open(str(path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            audio_data = wav_file.readframes(wav_file.getnframes())

        return await self.recognize_file(audio_data, sample_rate=sample_rate)


class MockASR:
    """Mock ASR for offline testing."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        logger.info("MockASR initialized")

    async def connect(self) -> None:
        logger.info("MockASR: connected")

    async def close(self) -> None:
        logger.info("MockASR: closed")

    async def recognize_stream(self, audio_generator):
        yield {"text": "тестовое сообщение", "is_final": True, "confidence": 1.0}

    async def recognize_file(self, audio_data: bytes, sample_rate: Optional[int] = None) -> str:
        return "тестовое сообщение"

    async def recognize_wav(self, wav_path: str | Path) -> str:
        return "тестовое сообщение"


def create_asr(api_key: str, folder_id: Optional[str] = None, use_mock: bool = False, **kwargs):
    if use_mock or not api_key:
        logger.warning("Using Mock ASR")
        return MockASR(api_key=api_key, folder_id=folder_id, **kwargs)
    return YandexASR(api_key=api_key, folder_id=folder_id, **kwargs)
