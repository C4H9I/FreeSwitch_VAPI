"""
Yandex SpeechKit TTS (Text-to-Speech)
Синтез речи через Yandex Cloud

Документация: https://cloud.yandex.ru/docs/speechkit/tts/
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Optional, Union

import grpc
from loguru import logger

# Yandex SpeechKit gRPC импорты
try:
    from yandex.cloud.ai.tts.v3 import tts_pb2 as tts
    from yandex.cloud.ai.tts.v3 import tts_service_pb2 as tts_service
    from yandex.cloud.ai.tts.v3 import tts_service_pb2_grpc as tts_service_grpc
    YANDEX_TTS_AVAILABLE = True
except ImportError:
    YANDEX_TTS_AVAILABLE = False
    logger.warning("Yandex TTS protobuf modules not available. Install yandex-cloud package.")


# Кеш для синтезированного аудио
TTS_CACHE: dict[str, bytes] = {}
CACHE_DIR = Path("/tmp/tts-cache")


class YandexTTS:
    """
    Класс для синтеза речи через Yandex SpeechKit

    Поддерживает:
    - Различные голоса (алена, филарет, ева, саша, антон, федор, камила, мадирус)
    - Эмоциональную окраску
    - Регулировку скорости и громкости
    - Форматы: LPCM, OGG, MP3, WAV
    """

    # Доступные голоса
    VOICES = {
        "алена": {"name": "alena", "language": "ru-RU"},
        "филарет": {"name": "filaret", "language": "ru-RU"},
        "ева": {"name": "eva", "language": "ru-RU"},
        "саша": {"name": "sasha", "language": "ru-RU"},
        "антон": {"name": "anton", "language": "ru-RU"},
        "федор": {"name": "fedor", "language": "ru-RU"},
        "камила": {"name": "kamila", "language": "ru-RU"},
        "мадирус": {"name": "madirus", "language": "ru-RU"},
    }

    # Эмоции (доступны не для всех голосов)
    EMOTIONS = ["good", "evil", "neutral"]

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
        """
        Инициализация TTS клиента

        Args:
            api_key: Yandex Cloud API ключ
            folder_id: ID папки в Yandex Cloud
            voice: Имя голоса (алена, филарет, ева, саша, антон, федор, камила, мадирус)
            emotion: Эмоциональная окраска (good, evil, neutral)
            speed: Скорость речи (0.1 - 3.0)
            volume: Громкость (0.1 - 3.0)
            audio_format: Формат аудио (lpcm, ogg, mp3, wav)
            sample_rate: Частота дискретизации (8000, 16000, 48000)
            use_cache: Использовать кеш для повторяющихся фраз
        """
        if not YANDEX_TTS_AVAILABLE:
            raise ImportError("Yandex TTS modules not installed. Run: pip install yandex-cloud grpcio")

        self.api_key = api_key
        self.folder_id = folder_id
        self.voice = voice.lower()
        self.emotion = emotion
        self.speed = speed
        self.volume = volume
        self.audio_format = audio_format.lower()
        self.sample_rate = sample_rate
        self.use_cache = use_cache

        # Проверка голоса
        if self.voice not in self.VOICES:
            logger.warning(f"Голос '{voice}' не найден. Используется 'алена'")
            self.voice = "алена"

        # gRPC канал
        self._channel: Optional[grpc.aio.Channel] = None
        self._stub: Optional[tts_service_grpc.SynthesizerStub] = None

        # Создание директории кеша
        if self.use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def connect(self) -> None:
        """Установка соединения с Yandex SpeechKit"""
        self._channel = grpc.aio.secure_channel(
            "tts.api.cloud.yandex.net:443",
            grpc.ssl_channel_credentials()
        )
        self._stub = tts_service_grpc.SynthesizerStub(self._channel)
        logger.info(f"Yandex TTS: Соединение установлено (голос: {self.voice})")

    async def close(self) -> None:
        """Закрытие соединения"""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
            logger.info("Yandex TTS: Соединение закрыто")

    def _get_audio_format(self) -> tts.AudioFormat:
        """
        Получение формата аудио для gRPC запроса

        Returns:
            AudioFormat: Формат аудио
        """
        format_map = {
            "lpcm": tts.AudioFormat.PCM,
            "ogg": tts.AudioFormat.OGG_OPUS,
            "mp3": tts.AudioFormat.MP3,
            "wav": tts.AudioFormat.WAV,
        }

        audio_format = format_map.get(self.audio_format, tts.AudioFormat.PCM)

        # Для LPCM указываем частоту дискретизации
        if audio_format == tts.AudioFormat.PCM:
            return tts.AudioFormat(
                pcm_audio_format=tts.PcmAudioFormat(
                    sample_rate_hertz=self.sample_rate
                )
            )

        return audio_format

    def _get_cache_key(self, text: str) -> str:
        """
        Генерация ключа кеша для текста

        Args:
            text: Текст для синтеза

        Returns:
            str: MD5 хеш
        """
        cache_data = f"{text}_{self.voice}_{self.emotion}_{self.speed}_{self.audio_format}_{self.sample_rate}"
        return hashlib.md5(cache_data.encode()).hexdigest()

    async def synthesize(self, text: str) -> bytes:
        """
        Синтез речи из текста

        Args:
            text: Текст для синтеза

        Returns:
            bytes: Аудио данные в выбранном формате
        """
        if not text.strip():
            return b""

        # Проверка кеша
        if self.use_cache:
            cache_key = self._get_cache_key(text)
            if cache_key in TTS_CACHE:
                logger.debug(f"TTS cache hit: {text[:50]}...")
                return TTS_CACHE[cache_key]

        if not self._stub:
            await self.connect()

        # Настройки голоса
        voice_settings = self.VOICES[self.voice]

        # Создание запроса
        request = tts.UtteranceSynthesisRequest(
            # Текст
            text=text,

            # Выходной формат
            output_audio_spec=self._get_audio_format(),

            # Настройки голоса
            voice=tts.UtteranceSynthesisRequest.VoiceSettings(
                name=voice_settings["name"],
                language=voice_settings["language"],
                speed=self.speed,
                volume=self.volume,
                emotion=self.emotion if self.emotion in self.EMOTIONS else "neutral",
            ),

            # Разделение на предложения
            hints=[
                tts.UtteranceSynthesisRequest.Hint(
                    silence_duration_ms=100
                )
            ]
        )

        # Метаданные для авторизации
        metadata = [
            ("authorization", f"Api-Key {self.api_key}"),
            ("x-yandex-catalog", self.folder_id or ""),
        ]

        try:
            # Синтез
            audio_data = b""
            async for response in self._stub.UtteranceSynthesis(
                request,
                metadata=metadata
            ):
                audio_data += response.audio_chunk.data

            # Сохранение в кеш
            if self.use_cache and audio_data:
                cache_key = self._get_cache_key(text)
                TTS_CACHE[cache_key] = audio_data

            logger.debug(f"TTS synthesized: {text[:50]}... ({len(audio_data)} bytes)")
            return audio_data

        except grpc.RpcError as e:
            logger.error(f"Yandex TTS gRPC ошибка: {e.code()} - {e.details()}")
            raise

    async def synthesize_to_file(
        self,
        text: str,
        output_path: Union[str, Path]
    ) -> Path:
        """
        Синтез речи и сохранение в файл

        Args:
            text: Текст для синтеза
            output_path: Путь к выходному файлу

        Returns:
            Path: Путь к созданному файлу
        """
        audio_data = await self.synthesize(text)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "wb") as f:
            f.write(audio_data)

        logger.info(f"TTS saved to: {output_file}")
        return output_file

    async def synthesize_ssml(self, ssml: str) -> bytes:
        """
        Синтез речи из SSML разметки

        SSML позволяет:
        - Управлять паузами: <break time="500ms"/>
        - Изменять скорость: <prosody rate="slow">текст</prosody>
        - Изменять громкость: <prosody volume="loud">текст</prosody>
        - Произношение чисел: <say-as interpret-as="cardinal">123</say-as>

        Args:
            ssml: SSML разметка

        Returns:
            bytes: Аудио данные
        """
        if not self._stub:
            await self.connect()

        voice_settings = self.VOICES[self.voice]

        request = tts.UtteranceSynthesisRequest(
            ssml=ssml,
            output_audio_spec=self._get_audio_format(),
            voice=tts.UtteranceSynthesisRequest.VoiceSettings(
                name=voice_settings["name"],
                language=voice_settings["language"],
                speed=self.speed,
                volume=self.volume,
            ),
        )

        metadata = [
            ("authorization", f"Api-Key {self.api_key}"),
            ("x-yandex-catalog", self.folder_id or ""),
        ]

        try:
            audio_data = b""
            async for response in self._stub.UtteranceSynthesis(
                request,
                metadata=metadata
            ):
                audio_data += response.audio_chunk.data
            return audio_data

        except grpc.RpcError as e:
            logger.error(f"Yandex TTS SSML gRPC ошибка: {e.code()} - {e.details()}")
            raise


class MockTTS:
    """
    Mock TTS для тестирования без реального подключения к Yandex
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.voice = kwargs.get("voice", "алена")
        logger.info(f"MockTTS initialized (voice: {self.voice})")

    async def connect(self) -> None:
        logger.info("MockTTS: Соединение установлено (mock)")

    async def close(self) -> None:
        logger.info("MockTTS: Соединение закрыто (mock)")

    async def synthesize(self, text: str) -> bytes:
        """Mock синтез - возвращает пустые аудио данные"""
        # Возвращаем минимальный PCM буфер (тишина)
        return bytes(8000)  # 1 секунда тишины 8kHz

    async def synthesize_to_file(self, text: str, output_path: Union[str, Path]) -> Path:
        """Mock сохранение в файл"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        audio_data = await self.synthesize(text)
        with open(output_file, "wb") as f:
            f.write(audio_data)
        return output_file

    async def synthesize_ssml(self, ssml: str) -> bytes:
        """Mock SSML синтез"""
        return await self.synthesize(ssml)


def create_tts(
    api_key: str,
    folder_id: Optional[str] = None,
    use_mock: bool = False,
    **kwargs
) -> Union[YandexTTS, MockTTS]:
    """
    Фабрика для создания TTS клиента

    Args:
        api_key: Yandex Cloud API ключ
        folder_id: ID папки в Yandex Cloud
        use_mock: Использовать mock для тестирования
        **kwargs: Дополнительные параметры

    Returns:
        TTS клиент
    """
    if use_mock or not api_key:
        logger.warning("Using Mock TTS - no real synthesis will be performed")
        return MockTTS(api_key=api_key, folder_id=folder_id, **kwargs)

    return YandexTTS(
        api_key=api_key,
        folder_id=folder_id,
        **kwargs
    )


def get_cache_stats() -> dict:
    """
    Получение статистики кеша TTS

    Returns:
        dict: Статистика кеша
    """
    return {
        "entries": len(TTS_CACHE),
        "total_size": sum(len(v) for v in TTS_CACHE.values()),
    }


def clear_cache() -> None:
    """Очистка кеша TTS"""
    TTS_CACHE.clear()
    logger.info("TTS cache cleared")
