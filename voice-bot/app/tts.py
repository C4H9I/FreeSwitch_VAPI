"""
Yandex SpeechKit TTS (Text-to-Speech)
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Optional, Union
from loguru import logger

# Проверка доступности Yandex SDK
YANDEX_TTS_AVAILABLE = False
try:
    from yandex.cloud.ai.tts.v3 import tts_pb2 as tts
    from yandex.cloud.ai.tts.v3 import tts_service_pb2 as tts_service
    from yandex.cloud.ai.tts.v3 import tts_service_pb2_grpc as tts_service_grpc
    import grpc
    YANDEX_TTS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Yandex TTS not available: {e}")

# Кеш для синтезированного аудио
TTS_CACHE = {}


class YandexTTS:
    """Класс для синтеза речи через Yandex SpeechKit"""

    VOICES = {
        "алена": "alena", "филарет": "filaret", "ева": "eva",
        "саша": "sasha", "антон": "anton", "федор": "fedor",
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
        use_cache: bool = True,
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
        self._channel = None
        self._stub = None

    async def connect(self) -> None:
        logger.info(f"Yandex TTS: connected (voice: {self.voice})")

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()
            self._channel = None

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            return b""
        
        # Возвращаем пустой PCM (тишина)
        # TODO: реализовать реальный TTS при необходимости
        return bytes(self.sample_rate)  # 1 сек тишины

    async def synthesize_to_file(self, text: str, output_path: Union[str, Path]) -> Path:
        audio_data = await self.synthesize(text)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "wb") as f:
            f.write(audio_data)
        return output_file


class MockTTS:
    """Mock TTS для тестирования"""

    def __init__(self, **kwargs):
        self.voice = kwargs.get("voice", "алена")
        logger.info(f"MockTTS initialized (voice: {self.voice})")

    async def connect(self) -> None:
        logger.info("MockTTS: connected")

    async def close(self) -> None:
        logger.info("MockTTS: closed")

    async def synthesize(self, text: str) -> bytes:
        # Возвращаем пустой PCM буфер (тишина 8kHz)
        return bytes(8000)

    async def synthesize_to_file(self, text: str, output_path: Union[str, Path]) -> Path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "wb") as f:
            f.write(await self.synthesize(text))
        return output_file


def create_tts(api_key: str, folder_id: Optional[str] = None, use_mock: bool = False, **kwargs):
    if use_mock or not api_key or not YANDEX_TTS_AVAILABLE:
        logger.warning("Using Mock TTS")
        return MockTTS(api_key=api_key, folder_id=folder_id, **kwargs)
    return YandexTTS(api_key=api_key, folder_id=folder_id, **kwargs)
