#!/usr/bin/env python3
"""
Voice Bot Main Application
Точка входа для голосового бота FreeSWITCH + LLM

Usage:
    python main.py --config ../config/agent.yaml
    python main.py --mock  # Для тестирования без реальных сервисов
"""

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

# Добавление путей
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import load_config, Settings
from app.dialog_manager import DialogManager, create_dialog_manager
from app.call_handler import (
    FreeSWITCHCallHandler,
    MockCallHandler,
    create_call_handler,
    CallInfo,
)


# Глобальные переменные
settings: Optional[Settings] = None
dialog_managers: dict[str, DialogManager] = {}
call_handler: Optional[FreeSWITCHCallHandler | MockCallHandler] = None


def setup_logging(settings: Settings) -> None:
    """
    Настройка логирования

    Args:
        settings: Настройки приложения
    """
    # Удаление стандартного обработчика
    logger.remove()

    # Формат логов
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # Консольный вывод
    logger.add(
        sys.stdout,
        format=log_format,
        level=settings.logging.level,
        colorize=True,
    )

    # Файловый вывод
    log_file = Path(settings.logging.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_file),
        format=log_format,
        level=settings.logging.level,
        rotation=f"{settings.logging.max_size} MB",
        retention=f"{settings.logging.backup_count} files",
        compression="zip",
    )

    logger.info(f"Logging initialized: {log_file}")


async def handle_call(call_info: CallInfo, connection) -> None:
    """
    Обработка входящего звонка

    Args:
        call_info: Информация о звонке
        connection: ESL соединение
    """
    session_id = call_info.uuid

    logger.info(
        f"Processing call: {session_id} "
        f"from {call_info.caller_number} to {call_info.destination_number}"
    )

    try:
        # Создание менеджера диалога для этого звонка
        dialog = create_dialog_manager(
            yandex_api_key=settings.yandex_api_key or "",
            yandex_folder_id=settings.yandex_folder_id,
            openai_api_key=settings.openai_api_key or "",
            openai_api_base=settings.openai_api_base,
            system_prompt=settings.llm.system_prompt,
            voice_config={
                "tts": settings.voice.tts.model_dump(),
                "asr": settings.voice.asr.model_dump(),
            },
            dialog_config={
                "greeting": settings.dialog.greeting,
                "goodbye": settings.dialog.goodbye,
                "not_understood": settings.dialog.not_understood,
                "waiting": settings.dialog.waiting,
                "max_turns": settings.dialog.max_turns,
                "max_duration": settings.dialog.max_duration,
            },
            use_mock=False,  # Используем реальные сервисы
        )

        # Сохранение в словаре
        dialog_managers[session_id] = dialog

        # Подключение к сервисам
        await dialog.asr.connect()
        await dialog.tts.connect()

        # Запуск сессии и получение приветствия
        greeting_audio = await dialog.start_session(session_id)

        # Отправка приветствия через FreeSWITCH
        # Сохранение во временный файл и проигрывание
        temp_file = f"/tmp/greeting_{session_id}.raw"
        with open(temp_file, "wb") as f:
            f.write(greeting_audio)

        # Проигрывание приветствия
        connection.api(f"uuid_broadcast {session_id} play:{temp_file} both")

        # Основной цикл диалога
        while dialog.state.value != "ended":
            # Запись речи пользователя
            record_file = f"/tmp/user_audio_{session_id}.raw"

            # Запись в течение определенного времени
            connection.api(f"uuid_record {session_id} start {record_file} 30")

            # Ожидание окончания речи (VAD)
            # В реальной реализации здесь должен быть VAD
            await asyncio.sleep(5)

            # Остановка записи
            connection.api(f"uuid_record {session_id} stop {record_file}")

            # Чтение записанного аудио
            if os.path.exists(record_file):
                with open(record_file, "rb") as f:
                    audio_data = f.read()

                # Обработка через диалог-менеджер
                async def audio_generator():
                    yield audio_data

                async for response_audio in dialog.process_audio(audio_generator()):
                    # Сохранение и проигрывание ответа
                    response_file = f"/tmp/response_{session_id}.raw"
                    with open(response_file, "wb") as f:
                        f.write(response_audio)

                    connection.api(f"uuid_broadcast {session_id} play:{response_file} both")
                    await asyncio.sleep(1)

                # Очистка временных файлов
                for f in [record_file, f"/tmp/response_{session_id}.raw"]:
                    if os.path.exists(f):
                        os.remove(f)

    except Exception as e:
        logger.error(f"Call handling error: {session_id} - {e}")

    finally:
        # Очистка
        if session_id in dialog_managers:
            dialog = dialog_managers[session_id]
            await dialog.asr.close()
            await dialog.tts.close()
            await dialog.llm.close()
            del dialog_managers[session_id]

        # Очистка временных файлов
        for pattern in [f"/tmp/*{session_id}*"]:
            import glob
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except:
                    pass

        logger.info(f"Call ended: {session_id}")


async def run_server(settings: Settings, use_mock: bool = False) -> None:
    """
    Запуск сервера

    Args:
        settings: Настройки
        use_mock: Использовать mock режим
    """
    global call_handler

    logger.info(f"Starting Voice Bot: {settings.agent.name} v{settings.agent.version}")
    logger.info(f"Mock mode: {use_mock}")

    # Создание обработчика звонков
    call_handler = create_call_handler(
        host=settings.freeswitch.host,
        port=settings.freeswitch.port,
        password=settings.freeswitch.password,
        use_mock=use_mock,
        voice_bot_callback=handle_call,
    )

    # Подключение к FreeSWITCH
    if not use_mock:
        if not call_handler.connect():
            logger.error("Failed to connect to FreeSWITCH")
            return

    # Запуск обработчика событий
    try:
        # Запуск в отдельном потоке для asyncio
        loop = asyncio.get_event_loop()

        # Запуск обработчика событий в executor
        await loop.run_in_executor(None, call_handler.run)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if call_handler:
            call_handler.disconnect()


async def test_dialog(settings: Settings) -> None:
    """
    Тестирование диалога без FreeSWITCH

    Args:
        settings: Настройки
    """
    logger.info("Testing dialog without FreeSWITCH...")

    # Создание диалог-менеджера с mock ASR/TTS
    dialog = create_dialog_manager(
        yandex_api_key="",  # Пустой ключ -> Mock
        yandex_folder_id=None,
        openai_api_key=settings.openai_api_key or "",  # LLM может быть реальным
        openai_api_base=settings.openai_api_base,
        system_prompt=settings.llm.system_prompt,
        voice_config={
            "tts": settings.voice.tts.model_dump(),
            "asr": settings.voice.asr.model_dump(),
        },
        dialog_config={
            "greeting": settings.dialog.greeting,
            "goodbye": settings.dialog.goodbye,
            "not_understood": settings.dialog.not_understood,
            "waiting": settings.dialog.waiting,
            "max_turns": settings.dialog.max_turns,
            "max_duration": settings.dialog.max_duration,
        },
        use_mock=not bool(settings.openai_api_key),  # Mock если нет ключа
    )

    # Запуск сессии
    greeting = await dialog.start_session("test-session")
    print(f"\nБот: {settings.dialog.greeting}")
    print(f"(Аудио: {len(greeting)} байт)")

    # Тестовый диалог
    test_messages = [
        "Здравствуйте, я хочу сделать заказ",
        "Какие у вас есть тарифы?",
        "Спасибо, до свидания",
    ]

    for msg in test_messages:
        print(f"\nПользователь: {msg}")
        response = await dialog.process_text(msg)
        print(f"Бот: [аудио {len(response)} байт]")
        print(f"Статистика: {dialog.get_stats()}")

        if dialog.state.value == "ended":
            break

    print("\nТест завершен.")


def main():
    """Главная функция"""
    global settings

    # Парсинг аргументов
    parser = argparse.ArgumentParser(
        description="Voice Bot - голосовой бот на FreeSWITCH + LLM"
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Путь к файлу конфигурации (YAML)"
    )
    parser.add_argument(
        "--mock", "-m",
        action="store_true",
        help="Запуск в mock режиме (без реальных сервисов)"
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="Тестирование диалога без FreeSWITCH"
    )

    args = parser.parse_args()

    # Загрузка конфигурации
    settings = load_config(args.config)

    # Настройка логирования
    setup_logging(settings)

    # Проверка API ключей
    if not args.mock:
        missing_keys = []
        if not settings.yandex_api_key:
            missing_keys.append("YANDEX_API_KEY")
        if not settings.openai_api_key:
            missing_keys.append("OPENAI_API_KEY")

        if missing_keys:
            logger.warning(
                f"Missing API keys: {', '.join(missing_keys)}. "
                f"Set environment variables or use --mock flag."
            )

    # Запуск
    if args.test:
        asyncio.run(test_dialog(settings))
    else:
        asyncio.run(run_server(settings, use_mock=args.mock))


if __name__ == "__main__":
    main()
