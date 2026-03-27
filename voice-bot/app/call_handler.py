"""
FreeSWITCH Call Handler
Обработка звонков через Event Socket Layer (ESL)

Документация ESL: https://freeswitch.org/confluence/display/FREESWITCH/Event+Socket+Library
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Callable

from loguru import logger

try:
    from ESL import ESLconnection
    ESL_AVAILABLE = True
except ImportError:
    ESL_AVAILABLE = False
    logger.warning("ESL module not available. Install: pip install python-esl")


@dataclass
class CallInfo:
    """Информация о звонке"""
    uuid: str
    caller_number: str
    destination_number: str
    channel: str
    start_time: float
    answer_time: Optional[float] = None
    end_time: Optional[float] = None
    direction: str = "inbound"


class FreeSWITCHCallHandler:
    """
    Обработчик звонков FreeSWITCH

    Работает через Event Socket Layer (ESL) в режиме inbound.
    Подключается к FreeSWITCH и обрабатывает события звонков.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8021,
        password: str = "ClueCon",
        voice_bot_callback: Optional[Callable] = None,
    ):
        """
        Инициализация обработчика

        Args:
            host: Хост FreeSWITCH ESL
            port: Порт ESL
            password: Пароль ESL
            voice_bot_callback: Callback функция для обработки звонка
        """
        if not ESL_AVAILABLE:
            raise ImportError("ESL module not installed. Run: pip install python-esl")

        self.host = host
        self.port = port
        self.password = password
        self.voice_bot_callback = voice_bot_callback

        # Соединение с ESL
        self._connection: Optional[ESLconnection] = None

        # Активные звонки
        self._active_calls: dict[str, CallInfo] = {}

        # Флаг работы
        self._running = False

    def connect(self) -> bool:
        """
        Подключение к FreeSWITCH ESL

        Returns:
            bool: True если подключение успешно
        """
        try:
            self._connection = ESLconnection(self.host, str(self.port), self.password)

            if not self._connection.connected():
                logger.error("Failed to connect to FreeSWITCH ESL")
                return False

            logger.info(f"Connected to FreeSWITCH ESL: {self.host}:{self.port}")
            return True

        except Exception as e:
            logger.error(f"ESL connection error: {e}")
            return False

    def disconnect(self) -> None:
        """Отключение от FreeSWITCH ESL"""
        if self._connection:
            self._connection.disconnect()
            self._connection = None
            logger.info("Disconnected from FreeSWITCH ESL")

    def subscribe_events(self) -> None:
        """Подписка на события FreeSWITCH"""
        if not self._connection:
            return

        # Подписка на все события
        self._connection.events("plain", "all")

        # Или можно подписаться на конкретные события:
        # events = "CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_HANGUP DTMF CUSTOM"
        # self._connection.events("plain", events)

        logger.info("Subscribed to FreeSWITCH events")

    def run(self) -> None:
        """
        Основной цикл обработки событий

        Блокирующий вызов, запускает обработку событий в бесконечном цикле
        """
        if not self._connection:
            if not self.connect():
                return

        self.subscribe_events()
        self._running = True

        logger.info("Starting event loop...")

        while self._running:
            try:
                # Получение события
                event = self._connection.recvEvent()

                if not event:
                    continue

                # Обработка события
                self._handle_event(event)

            except KeyboardInterrupt:
                logger.info("Stopping event loop...")
                break
            except Exception as e:
                logger.error(f"Event loop error: {e}")
                continue

        self._running = False

    def _handle_event(self, event) -> None:
        """
        Обработка события FreeSWITCH

        Args:
            event: Событие ESL
        """
        # Получение заголовков события
        headers = event.headers
        event_name = headers.get("Event-Name", "")

        # UUID канала
        channel_uuid = headers.get("Unique-ID", "")

        if event_name == "CHANNEL_CREATE":
            self._handle_channel_create(headers)

        elif event_name == "CHANNEL_ANSWER":
            self._handle_channel_answer(headers)

        elif event_name == "CHANNEL_HANGUP":
            self._handle_channel_hangup(headers)

        elif event_name == "DTMF":
            self._handle_dtmf(headers)

        elif event_name == "CUSTOM":
            # Кастомные события
            subclass = headers.get("Event-Subclass", "")
            logger.debug(f"Custom event: {subclass}")

    def _handle_channel_create(self, headers: dict) -> None:
        """Обработка создания канала"""
        call_uuid = headers.get("Unique-ID", "")
        caller_number = headers.get("Caller-Caller-ID-Number", "unknown")
        destination_number = headers.get("Caller-Destination-Number", "unknown")
        channel = headers.get("Channel-Name", "")

        call_info = CallInfo(
            uuid=call_uuid,
            caller_number=caller_number,
            destination_number=destination_number,
            channel=channel,
            start_time=time.time(),
            direction=headers.get("Call-Direction", "inbound"),
        )

        self._active_calls[call_uuid] = call_info

        logger.info(f"Channel created: {call_uuid} - {caller_number} -> {destination_number}")

    def _handle_channel_answer(self, headers: dict) -> None:
        """Обработка ответа на звонок"""
        call_uuid = headers.get("Unique-ID", "")

        if call_uuid in self._active_calls:
            call_info = self._active_calls[call_uuid]
            call_info.answer_time = time.time()

            logger.info(f"Channel answered: {call_uuid}")

            # Запуск обработки звонка в отдельном потоке/задаче
            if self.voice_bot_callback:
                asyncio.create_task(self._run_voice_bot(call_info))

    def _handle_channel_hangup(self, headers: dict) -> None:
        """Обработка завершения звонка"""
        call_uuid = headers.get("Unique-ID", "")
        hangup_cause = headers.get("Hangup-Cause", "unknown")

        if call_uuid in self._active_calls:
            call_info = self._active_calls[call_uuid]
            call_info.end_time = time.time()

            duration = 0
            if call_info.answer_time:
                duration = call_info.end_time - call_info.answer_time

            logger.info(
                f"Channel hangup: {call_uuid} - Cause: {hangup_cause}, "
                f"Duration: {duration:.1f}s"
            )

            # Удаление из активных
            del self._active_calls[call_uuid]

    def _handle_dtmf(self, headers: dict) -> None:
        """Обработка DTMF сигналов"""
        call_uuid = headers.get("Unique-ID", "")
        dtmf_digit = headers.get("DTMF-Digit", "")

        logger.info(f"DTMF: {call_uuid} - Digit: {dtmf_digit}")

    async def _run_voice_bot(self, call_info: CallInfo) -> None:
        """
        Запуск голосового бота для звонка

        Args:
            call_info: Информация о звонке
        """
        if not self.voice_bot_callback:
            return

        try:
            await self.voice_bot_callback(call_info, self._connection)
        except Exception as e:
            logger.error(f"Voice bot error for call {call_info.uuid}: {e}")

    # API команды для управления звонками

    def answer(self, call_uuid: str) -> bool:
        """
        Ответ на звонок

        Args:
            call_uuid: UUID канала

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_answer {call_uuid}")

    def hangup(self, call_uuid: str, cause: str = "NORMAL_CLEARING") -> bool:
        """
        Завершение звонка

        Args:
            call_uuid: UUID канала
            cause: Причина завершения

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_kill {call_uuid} {cause}")

    def playback(self, call_uuid: str, file_path: str) -> bool:
        """
        Проигрывание файла

        Args:
            call_uuid: UUID канала
            file_path: Путь к файлу

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_broadcast {call_uuid} play:{file_path} both")

    def say(self, call_uuid: str, text: str, lang: str = "ru") -> bool:
        """
        Произношение текста (через say)

        Args:
            call_uuid: UUID канала
            text: Текст
            lang: Язык

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_say {call_uuid} {lang} name_spelled iterated {text}")

    def set(self, call_uuid: str, variable: str, value: str) -> bool:
        """
        Установка переменной канала

        Args:
            call_uuid: UUID канала
            variable: Имя переменной
            value: Значение

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_setvar {call_uuid} {variable} {value}")

    def record(self, call_uuid: str, file_path: str, limit: int = 60) -> bool:
        """
        Запись разговора

        Args:
            call_uuid: UUID канала
            file_path: Путь к файлу
            limit: Лимит записи (секунды)

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_record {call_uuid} start {file_path} {limit}")

    def stop_record(self, call_uuid: str, file_path: str) -> bool:
        """
        Остановка записи

        Args:
            call_uuid: UUID канала
            file_path: Путь к файлу

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_record {call_uuid} stop {file_path}")

    def bridge(self, call_uuid: str, destination: str) -> bool:
        """
        Переключение звонка

        Args:
            call_uuid: UUID канала
            destination: Номер назначения

        Returns:
            bool: True если успешно
        """
        return self._send_api(f"uuid_transfer {call_uuid} {destination}")

    def _send_api(self, command: str) -> bool:
        """
        Отправка API команды

        Args:
            command: Команда

        Returns:
            bool: True если успешно
        """
        if not self._connection:
            return False

        try:
            result = self._connection.api(command)
            response = result.getBody()

            if "+OK" in response or "success" in response.lower():
                logger.debug(f"API success: {command}")
                return True
            else:
                logger.warning(f"API response: {response}")
                return False

        except Exception as e:
            logger.error(f"API error: {command} - {e}")
            return False

    def _send_bgapi(self, command: str) -> str:
        """
        Отправка фоновой API команды

        Args:
            command: Команда

        Returns:
            str: Job ID
        """
        if not self._connection:
            return ""

        try:
            result = self._connection.bgapi(command)
            return result.getBody()
        except Exception as e:
            logger.error(f"BGAPI error: {command} - {e}")
            return ""

    def get_active_calls(self) -> dict[str, CallInfo]:
        """
        Получение списка активных звонков

        Returns:
            dict: Словарь активных звонков
        """
        return self._active_calls.copy()

    def stop(self) -> None:
        """Остановка обработчика"""
        self._running = False


class MockCallHandler:
    """
    Mock обработчик для тестирования без FreeSWITCH
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._running = False
        self._active_calls: dict[str, CallInfo] = {}
        logger.info("MockCallHandler initialized for testing")

    def connect(self) -> bool:
        logger.info("MockCallHandler: Connected (mock)")
        return True

    def disconnect(self) -> None:
        logger.info("MockCallHandler: Disconnected (mock)")

    def subscribe_events(self) -> None:
        logger.info("MockCallHandler: Subscribed to events (mock)")

    def run(self) -> None:
        logger.info("MockCallHandler: Running event loop (mock)")

    def answer(self, call_uuid: str) -> bool:
        return True

    def hangup(self, call_uuid: str, cause: str = "NORMAL_CLEARING") -> bool:
        return True

    def playback(self, call_uuid: str, file_path: str) -> bool:
        return True

    def get_active_calls(self) -> dict[str, CallInfo]:
        return {}

    def stop(self) -> None:
        self._running = False


def create_call_handler(
    host: str = "127.0.0.1",
    port: int = 8021,
    password: str = "ClueCon",
    use_mock: bool = False,
    voice_bot_callback: Optional[Callable] = None,
) -> FreeSWITCHCallHandler | MockCallHandler:
    """
    Фабрика для создания обработчика звонков

    Args:
        host: Хост FreeSWITCH ESL
        port: Порт ESL
        password: Пароль ESL
        use_mock: Использовать mock
        voice_bot_callback: Callback для голосового бота

    Returns:
        Обработчик звонков
    """
    if use_mock:
        return MockCallHandler(
            host=host,
            port=port,
            password=password,
            voice_bot_callback=voice_bot_callback,
        )

    return FreeSWITCHCallHandler(
        host=host,
        port=port,
        password=password,
        voice_bot_callback=voice_bot_callback,
    )
