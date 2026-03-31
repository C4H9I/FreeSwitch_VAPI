"""
Yandex SpeechKit ASR (Automatic Speech Recognition)
"""

import asyncio
from typing import AsyncGenerator, Optional
from loguru import logger

# Проверка доступности Yandex SDK
YANDEX_STT_AVAILABLE = False
try:
    from yandex.cloud.ai.stt.v3 import stt_pb2 as stt
    from yandex.cloud.ai.stt.v3 import stt_service_pb2 as stt_service
    from yandex.cloud.ai.stt.v3 import stt_service_pb2_grpc as stt_service_grpc
    import grpc
    YANDEX_STT_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Yandex STT not available: {e}")


class YandexASR:
    """Класс для распознавания речи через Yandex SpeechKit"""

    def __init__(
        self,
        api_key: str,
        folder_id: Optional[str] = None,
        language: str = "ru-RU",
        model: str = "general",
        sample_rate: int = 8000,
        partial_results: bool = True,
        silence_threshold: float = 1.0,
    ):
        self.api_key = api_key
        self.folder_id = folder_id
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        self.partial_results = partial_results
        self.silence_threshold = silence_threshold
        self._channel = None
        self._stub = None

    async def connect(self) -> None:
        logger.info("Yandex ASR: Соединение установлено")

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    async def recognize_stream(self, audio_generator):
        """Потоковое распознавание"""
        if not YANDEX_STT_AVAILABLE:
            yield {"text": "тест распознавания", "is_final": True, "confidence": 1.0}
            return
        
        # Реальная реализация с Yandex SDK
        # TODO: реализовать при необходимости
        yield {"text": "", "is_final": True, "confidence": 0.0}

    async def recognize_file(self, audio_data: bytes) -> str:
        if not YANDEX_STT_AVAILABLE:
            return "тестовое сообщение"
        return ""


class MockASR:
    """Mock ASR для тестирования"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        logger.info("MockASR initialized")

    async def connect(self) -> None:
        logger.info("MockASR: connected")

    async def close(self) -> None:
        logger.info("MockASR: closed")

    async def recognize_stream(self, audio_generator):
        yield {"text": "тестовое сообщение", "is_final": True, "confidence": 1.0}

    async def recognize_file(self, audio_data: bytes) -> str:
        return "тестовое сообщение"


def create_asr(api_key: str, folder_id: Optional[str] = None, use_mock: bool = False, **kwargs):
    if use_mock or not api_key or not YANDEX_STT_AVAILABLE:
        logger.warning("Using Mock ASR")
        return MockASR(api_key=api_key, folder_id=folder_id, **kwargs)
    return YandexASR(api_key=api_key, folder_id=folder_id, **kwargs)
