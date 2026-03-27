"""
Yandex SpeechKit ASR (Automatic Speech Recognition)
Распознавание речи через Yandex Cloud

Документация: https://cloud.yandex.ru/docs/speechkit/stt/
"""

import asyncio
import json
from typing import AsyncGenerator, Optional

import grpc
from loguru import logger

# Yandex SpeechKit gRPC импорты
try:
    from yandex.cloud.ai.stt.v3 import stt_pb2 as stt
    from yandex.cloud.ai.stt.v3 import stt_service_pb2 as stt_service
    from yandex.cloud.ai.stt.v3 import stt_service_pb2_grpc as stt_service_grpc
    YANDEX_STT_AVAILABLE = True
except ImportError:
    YANDEX_STT_AVAILABLE = False
    logger.warning("Yandex STT protobuf modules not available. Install yandex-cloud package.")


class YandexASR:
    """
    Класс для распознавания речи через Yandex SpeechKit

    Поддерживает:
    - Потоковое распознавание
    - Промежуточные результаты
    - Автоматическое определение окончания речи
    """

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
        """
        Инициализация ASR клиента

        Args:
            api_key: Yandex Cloud API ключ
            folder_id: ID папки в Yandex Cloud
            language: Код языка (ru-RU, en-US)
            model: Модель распознавания (general, maps, dates, numbers, shopping)
            sample_rate: Частота дискретизации (8000, 16000, 48000)
            partial_results: Возвращать промежуточные результаты
            silence_threshold: Порог тишины для окончания фразы
        """
        if not YANDEX_STT_AVAILABLE:
            raise ImportError("Yandex STT modules not installed. Run: pip install yandex-cloud grpcio")

        self.api_key = api_key
        self.folder_id = folder_id
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        self.partial_results = partial_results
        self.silence_threshold = silence_threshold

        # gRPC канал
        self._channel: Optional[grpc.aio.Channel] = None
        self._stub: Optional[stt_service_grpc.SttServiceStub] = None

    async def connect(self) -> None:
        """Установка соединения с Yandex SpeechKit"""
        # Создание gRPC канала
        self._channel = grpc.aio.secure_channel(
            "stt.api.cloud.yandex.net:443",
            grpc.ssl_channel_credentials()
        )
        self._stub = stt_service_grpc.SttServiceStub(self._channel)
        logger.info("Yandex ASR: Соединение установлено")

    async def close(self) -> None:
        """Закрытие соединения"""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
            logger.info("Yandex ASR: Соединение закрыто")

    def _get_recognition_config(self) -> stt.RecognitionConfig:
        """
        Создание конфигурации распознавания

        Returns:
            RecognitionConfig: Конфигурация для gRPC запроса
        """
        config = stt.RecognitionConfig(
            # Настройки аудио
            audio_encoding=stt.RecognitionConfig.AudioEncoding.LINEAR16_PCM,
            sample_rate_hertz=self.sample_rate,

            # Настройки языка
            language_code=self.language,

            # Модель распознавания
            model=self.model,

            # Промежуточные результаты
            partial_results=self.partial_results,

            # Автоматическое определение окончания речи
            speech_model=stt.RecognitionConfig.SpeechModel(
                # Время тишины для окончания фразы (миллисекунды)
                silence_duration_threshold_ms=int(self.silence_threshold * 1000),
            ),

            # Фильтр ненормативной лексики
            profanity_filter=False,

            # Нормализация текста (числа прописью)
            literature_text=True,
        )

        # Добавление folder_id если указан
        if self.folder_id:
            config.folder_id = self.folder_id

        return config

    async def recognize_stream(
        self,
        audio_generator: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[dict, None]:
        """
        Потоковое распознавание речи

        Args:
            audio_generator: Асинхронный генератор аудио данных (PCM 16-bit)

        Yields:
            dict: Результаты распознавания:
                - text: Распознанный текст
                - is_final: Финальный результат
                - confidence: Уверенность (0-1)
        """
        if not self._stub:
            await self.connect()

        # Конфигурация распознавания
        config = self._get_recognition_config()

        # Создание генератора запросов
        async def request_generator():
            # Первый запрос с конфигурацией
            yield stt.StreamingRecognizeRequest(
                session_settings=stt.SessionSettings(
                    default_config=config
                )
            )

            # Последующие запросы с аудио данными
            async for audio_chunk in audio_generator:
                yield stt.StreamingRecognizeRequest(
                    audio_chunk=stt.AudioChunk(data=audio_chunk)
                )

        # Метаданные для авторизации
        metadata = [
            ("authorization", f"Api-Key {self.api_key}"),
            ("x-yandex-catalog", self.folder_id or ""),
        ]

        try:
            # Стриминг распознавания
            async for response in self._stub.StreamingRecognize(
                request_generator(),
                metadata=metadata
            ):
                # Обработка результатов
                for result in response.results:
                    if result.alternatives:
                        alternative = result.alternatives[0]
                        yield {
                            "text": alternative.text,
                            "is_final": result.is_final,
                            "confidence": getattr(alternative, "confidence", 1.0),
                        }

        except grpc.RpcError as e:
            logger.error(f"Yandex ASR gRPC ошибка: {e.code()} - {e.details()}")
            raise

    async def recognize_file(self, audio_data: bytes) -> str:
        """
        Распознавание аудио файла

        Args:
            audio_data: Аудио данные (PCM 16-bit)

        Returns:
            str: Распознанный текст
        """
        if not self._stub:
            await self.connect()

        config = self._get_recognition_config()

        metadata = [
            ("authorization", f"Api-Key {self.api_key}"),
            ("x-yandex-catalog", self.folder_id or ""),
        ]

        try:
            response = await self._stub.Recognize(
                stt.RecognizeRequest(
                    config=config,
                    audio=stt.AudioChunk(data=audio_data)
                ),
                metadata=metadata
            )

            if response.results and response.results[0].alternatives:
                return response.results[0].alternatives[0].text
            return ""

        except grpc.RpcError as e:
            logger.error(f"Yandex ASR gRPC ошибка: {e.code()} - {e.details()}")
            raise


class MockASR:
    """
    Mock ASR для тестирования без реального подключения к Yandex
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        logger.info("MockASR initialized for testing")

    async def connect(self) -> None:
        logger.info("MockASR: Соединение установлено (mock)")

    async def close(self) -> None:
        logger.info("MockASR: Соединение закрыто (mock)")

    async def recognize_stream(
        self,
        audio_generator: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[dict, None]:
        """Mock распознавание - возвращает тестовый текст"""
        yield {"text": "тестовое сообщение", "is_final": True, "confidence": 1.0}

    async def recognize_file(self, audio_data: bytes) -> str:
        """Mock распознавание файла"""
        return "тестовое сообщение"


def create_asr(
    api_key: str,
    folder_id: Optional[str] = None,
    use_mock: bool = False,
    **kwargs
) -> YandexASR | MockASR:
    """
    Фабрика для создания ASR клиента

    Args:
        api_key: Yandex Cloud API ключ
        folder_id: ID папки в Yandex Cloud
        use_mock: Использовать mock для тестирования
        **kwargs: Дополнительные параметры

    Returns:
        ASR клиент
    """
    if use_mock or not api_key:
        logger.warning("Using Mock ASR - no real recognition will be performed")
        return MockASR(api_key=api_key, folder_id=folder_id, **kwargs)

    return YandexASR(
        api_key=api_key,
        folder_id=folder_id,
        **kwargs
    )
