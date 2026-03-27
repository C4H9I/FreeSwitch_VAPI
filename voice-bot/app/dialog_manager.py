"""
Dialog Manager
Управление диалогом между пользователем и голосовым ботом

Связывает:
- ASR (распознавание речи)
- LLM (генерация ответов)
- TTS (синтез речи)
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, AsyncGenerator

from loguru import logger

from .asr import YandexASR, MockASR, create_asr
from .tts import YandexTTS, MockTTS, create_tts
from .llm import LLMClient, MockLLM, create_llm


class DialogState(Enum):
    """Состояния диалога"""
    IDLE = "idle"                      # Ожидание
    LISTENING = "listening"            # Прослушивание
    PROCESSING = "processing"          # Обработка (ASR -> LLM)
    SPEAKING = "speaking"              # Озвучивание ответа
    ENDED = "ended"                    # Диалог завершен


@dataclass
class DialogTurn:
    """Один шаг диалога"""
    user_text: Optional[str] = None    # Текст пользователя
    assistant_text: Optional[str] = None  # Текст ассистента
    confidence: float = 0.0            # Уверенность ASR
    processing_time: float = 0.0       # Время обработки


class DialogManager:
    """
    Менеджер диалога

    Управляет потоком:
    1. Получение аудио от пользователя
    2. Распознавание речи (ASR)
    3. Генерация ответа (LLM)
    4. Синтез речи (TTS)
    5. Отправка аудио пользователю
    """

    def __init__(
        self,
        asr: YandexASR | MockASR,
        tts: YandexTTS | MockTTS,
        llm: LLMClient | MockLLM,
        greeting: str = "Добрый день! Чем могу помочь?",
        goodbye: str = "Спасибо за звонок! Хорошего дня!",
        not_understood: str = "Извините, не расслышала. Повторите, пожалуйста.",
        waiting: str = "Одну секунду...",
        max_turns: int = 50,
        max_duration: int = 300,
        silence_timeout: float = 5.0,
    ):
        """
        Инициализация менеджера диалога

        Args:
            asr: Клиент ASR
            tts: Клиент TTS
            llm: Клиент LLM
            greeting: Приветствие
            goodbye: Прощание
            not_understood: Фраза при непонимании
            waiting: Фраза ожидания
            max_turns: Максимальное количество реплик
            max_duration: Максимальная длительность разговора (секунды)
            silence_timeout: Таймаут тишины для завершения (секунды)
        """
        self.asr = asr
        self.tts = tts
        self.llm = llm

        # Фразы
        self.greeting = greeting
        self.goodbye = goodbye
        self.not_understood = not_understood
        self.waiting = waiting

        # Лимиты
        self.max_turns = max_turns
        self.max_duration = max_duration
        self.silence_timeout = silence_timeout

        # Состояние
        self.state = DialogState.IDLE
        self.turn_count = 0
        self.start_time: Optional[float] = None
        self.session_id: Optional[str] = None

        # История диалога
        self.history: list[DialogTurn] = []

        # Callback для отправки аудио
        self._audio_callback: Optional[Callable[[bytes], None]] = None

    def set_audio_callback(self, callback: Callable[[bytes], None]) -> None:
        """
        Установка callback для отправки аудио пользователю

        Args:
            callback: Функция, принимающая bytes (аудио данные)
        """
        self._audio_callback = callback

    async def start_session(self, session_id: str) -> bytes:
        """
        Начало сессии диалога

        Args:
            session_id: ID сессии/звонка

        Returns:
            bytes: Аудио приветствия
        """
        self.session_id = session_id
        self.state = DialogState.SPEAKING
        self.start_time = time.time()
        self.turn_count = 0
        self.history = []

        logger.info(f"Dialog session started: {session_id}")

        # Озвучивание приветствия
        greeting_audio = await self.tts.synthesize(self.greeting)

        return greeting_audio

    async def process_audio(
        self,
        audio_generator: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[bytes, None]:
        """
        Обработка аудио потока от пользователя

        Args:
            audio_generator: Генератор аудио данных

        Yields:
            bytes: Аудио ответы для пользователя
        """
        self.state = DialogState.LISTENING

        try:
            # Распознавание речи
            recognized_text = ""
            confidence = 0.0

            async for result in self.asr.recognize_stream(audio_generator):
                if result.get("text"):
                    recognized_text = result["text"]
                    confidence = result.get("confidence", 0.0)

                    # Промежуточные результаты - логируем
                    if not result.get("is_final"):
                        logger.debug(f"Partial: {recognized_text}")

            # Если ничего не распознано
            if not recognized_text.strip():
                logger.warning("No speech recognized")
                self.state = DialogState.SPEAKING
                yield await self.tts.synthesize(self.not_understood)
                return

            logger.info(f"Recognized: {recognized_text} (confidence: {confidence:.2f})")

            # Проверка на команды завершения
            if self._is_goodbye(recognized_text):
                yield await self._end_dialog()
                return

            # Проверка лимитов
            if self._check_limits():
                yield await self._end_dialog()
                return

            # Обработка через LLM
            self.state = DialogState.PROCESSING
            processing_start = time.time()

            response_text = await self.llm.generate(recognized_text, self.session_id or "default")

            processing_time = time.time() - processing_start
            logger.info(f"LLM response ({processing_time:.2f}s): {response_text[:100]}...")

            # Сохранение в историю
            turn = DialogTurn(
                user_text=recognized_text,
                assistant_text=response_text,
                confidence=confidence,
                processing_time=processing_time,
            )
            self.history.append(turn)
            self.turn_count += 1

            # Синтез ответа
            self.state = DialogState.SPEAKING
            response_audio = await self.tts.synthesize(response_text)

            yield response_audio

        except Exception as e:
            logger.error(f"Dialog processing error: {e}")
            self.state = DialogState.SPEAKING
            yield await self.tts.synthesize(self.not_understood)

    async def process_text(self, text: str) -> bytes:
        """
        Обработка текстового сообщения (для тестирования)

        Args:
            text: Текст пользователя

        Returns:
            bytes: Аудио ответ
        """
        if not self.session_id:
            self.session_id = "test-session"

        # Проверка на команды завершения
        if self._is_goodbye(text):
            return await self._end_dialog()

        # Генерация ответа
        response_text = await self.llm.generate(text, self.session_id)
        self.turn_count += 1

        # Синтез
        return await self.tts.synthesize(response_text)

    async def _end_dialog(self) -> bytes:
        """
        Завершение диалога

        Returns:
            bytes: Аудио прощания
        """
        self.state = DialogState.ENDED
        logger.info(f"Dialog ended: {self.session_id} (turns: {self.turn_count})")

        # Очистка контекста LLM
        if self.session_id:
            self.llm.clear_context(self.session_id)

        return await self.tts.synthesize(self.goodbye)

    def _is_goodbye(self, text: str) -> bool:
        """
        Проверка на фразу завершения

        Args:
            text: Текст пользователя

        Returns:
            bool: True если это прощание
        """
        goodbye_phrases = [
            "до свидания",
            "до свиданья",
            "пока",
            "прощай",
            "всё",
            "все",
            "хватит",
            "стоп",
            "закончить",
            "завершить",
            "отбой",
            "бай",
            "bye",
            "goodbye",
            "stop",
        ]

        text_lower = text.lower().strip()
        return any(phrase in text_lower for phrase in goodbye_phrases)

    def _check_limits(self) -> bool:
        """
        Проверка лимитов диалога

        Returns:
            bool: True если нужно завершить диалог
        """
        # Проверка количества реплик
        if self.turn_count >= self.max_turns:
            logger.info(f"Max turns reached: {self.turn_count}")
            return True

        # Проверка длительности
        if self.start_time:
            duration = time.time() - self.start_time
            if duration >= self.max_duration:
                logger.info(f"Max duration reached: {duration:.0f}s")
                return True

        return False

    def get_stats(self) -> dict:
        """
        Получение статистики диалога

        Returns:
            dict: Статистика
        """
        duration = 0
        if self.start_time:
            duration = time.time() - self.start_time

        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "turn_count": self.turn_count,
            "duration": duration,
            "history_size": len(self.history),
        }


def create_dialog_manager(
    yandex_api_key: str,
    yandex_folder_id: Optional[str],
    openai_api_key: str,
    openai_api_base: str,
    system_prompt: str,
    voice_config: dict,
    dialog_config: dict,
    use_mock: bool = False,
) -> DialogManager:
    """
    Фабрика для создания менеджера диалога

    Args:
        yandex_api_key: Yandex Cloud API ключ
        yandex_folder_id: Yandex Cloud folder ID
        openai_api_key: OpenAI API ключ
        openai_api_base: OpenAI API base URL
        system_prompt: Системный промпт
        voice_config: Конфигурация голоса
        dialog_config: Конфигурация диалога
        use_mock: Использовать mock клиенты

    Returns:
        DialogManager: Настроенный менеджер диалога
    """
    # ASR клиент
    asr = create_asr(
        api_key=yandex_api_key,
        folder_id=yandex_folder_id,
        use_mock=use_mock,
        language=voice_config.get("asr", {}).get("language", "ru-RU"),
        model=voice_config.get("asr", {}).get("model", "general"),
        sample_rate=voice_config.get("asr", {}).get("sample_rate", 8000),
        partial_results=voice_config.get("asr", {}).get("partial_results", True),
        silence_threshold=voice_config.get("asr", {}).get("silence_threshold", 1.0),
    )

    # TTS клиент
    tts = create_tts(
        api_key=yandex_api_key,
        folder_id=yandex_folder_id,
        use_mock=use_mock,
        voice=voice_config.get("tts", {}).get("voice", "алена"),
        emotion=voice_config.get("tts", {}).get("emotion", "good"),
        speed=voice_config.get("tts", {}).get("speed", 1.0),
        volume=voice_config.get("tts", {}).get("volume", 1.0),
        audio_format=voice_config.get("tts", {}).get("format", "lpcm"),
        sample_rate=voice_config.get("tts", {}).get("sample_rate", 8000),
    )

    # LLM клиент
    llm = create_llm(
        api_key=openai_api_key,
        api_base=openai_api_base,
        use_mock=use_mock,
        model=dialog_config.get("llm_model", "gpt-4o"),
        max_tokens=dialog_config.get("max_tokens", 150),
        temperature=dialog_config.get("temperature", 0.7),
        system_prompt=system_prompt,
    )

    # Менеджер диалога
    return DialogManager(
        asr=asr,
        tts=tts,
        llm=llm,
        greeting=dialog_config.get("greeting", "Добрый день! Чем могу помочь?"),
        goodbye=dialog_config.get("goodbye", "Спасибо за звонок! Хорошего дня!"),
        not_understood=dialog_config.get("not_understood", "Извините, не расслышала."),
        waiting=dialog_config.get("waiting", "Одну секунду..."),
        max_turns=dialog_config.get("max_turns", 50),
        max_duration=dialog_config.get("max_duration", 300),
    )
