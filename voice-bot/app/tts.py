"""
Yandex SpeechKit TTS.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Optional, Union

import aiohttp
from loguru import logger


class YandexTTS:
    """TTS client via Yandex SpeechKit REST API."""

    ENDPOINT = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"

    VOICES = {
        "алена": "alena",
        "филарет": "filaret",
        "ева": "eva",
        "саша": "sasha",
        "антон": "anton",
        "федор": "fedor",
    }

    def __init__(
        self,
        api_key: str,
        folder_id: Optional[str] = None,
        voice: str = "алена",
        emotion: str = "good",
        speed: float = 1.0,
        volume: float = 1.0,
        audio_format: str = "lpcm",
        sample_rate: int = 8000,
        use_cache: bool = False,
    ):
        self.api_key = api_key
        self.folder_id = folder_id
        self.voice = voice.lower()
        self.emotion = emotion
        self.speed = speed
        self.volume = volume
        self.audio_format = audio_format
        self.sample_rate = sample_rate
        self.use_cache = use_cache
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        logger.info(f"Yandex TTS: connected (voice: {self.voice})")

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            return b""

        await self.connect()
        assert self._session is not None

        data = {
            "text": text,
            "lang": "ru-RU",
            "voice": self.VOICES.get(self.voice, self.voice),
            "emotion": self.emotion,
            "speed": str(self.speed),
            "format": "lpcm",
            "sampleRateHertz": str(self.sample_rate),
        }
        headers = {"Authorization": f"Api-Key {self.api_key}"}

        async with self._session.post(self.ENDPOINT, data=data, headers=headers) as response:
            pcm_audio = await response.read()
            if response.status >= 400:
                raise RuntimeError(f"Yandex TTS error {response.status}: {pcm_audio.decode(errors='ignore')}")

        return self._pcm_to_wav(pcm_audio)

    async def synthesize_to_file(self, text: str, output_path: Union[str, Path]) -> Path:
        audio_data = await self.synthesize(text)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "wb") as file_obj:
            file_obj.write(audio_data)
        return output_file

    def _pcm_to_wav(self, pcm_audio: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm_audio)
        return buffer.getvalue()


class MockTTS:
    """Mock TTS for offline testing."""

    def __init__(self, **kwargs):
        self.voice = kwargs.get("voice", "алена")
        self.sample_rate = kwargs.get("sample_rate", 8000)
        logger.info(f"MockTTS initialized (voice: {self.voice})")

    async def connect(self) -> None:
        logger.info("MockTTS: connected")

    async def close(self) -> None:
        logger.info("MockTTS: closed")

    async def synthesize(self, text: str) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b"\x00\x00" * self.sample_rate)
        return buffer.getvalue()

    async def synthesize_to_file(self, text: str, output_path: Union[str, Path]) -> Path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "wb") as file_obj:
            file_obj.write(await self.synthesize(text))
        return output_file


def create_tts(api_key: str, folder_id: Optional[str] = None, use_mock: bool = False, **kwargs):
    if use_mock or not api_key:
        logger.warning("Using Mock TTS")
        return MockTTS(api_key=api_key, folder_id=folder_id, **kwargs)
    return YandexTTS(api_key=api_key, folder_id=folder_id, **kwargs)
