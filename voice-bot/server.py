#!/usr/bin/env python3
"""
Асинхронный голосовой бот для FreeSWITCH
Использует ESL, Yandex ASR/TTS, OpenAI LLM
"""

import asyncio
import tempfile
from loguru import logger
from pathlib import Path

from app.call_handler import create_call_handler
from app.dialog_manager import create_dialog_manager

# --- Конфигурация ---
YANDEX_API_KEY = "ВАШ_YANDEX_API_KEY"          # Если нет — бот работает в mock
YANDEX_FOLDER_ID = None
OPENAI_API_KEY = "ВАШ_OPENAI_API_KEY"          # Если нет — бот работает в mock

USE_MOCK_ASR_TTS = not YANDEX_API_KEY
USE_MOCK_LLM = not OPENAI_API_KEY

# ESL конфиг
ESL_HOST = "127.0.0.1"
ESL_PORT = 8021
ESL_PASSWORD = "ClueCon"


# --- Обработчик звонка ---
async def voice_bot_callback(call_info, esl_connection):
    """
    Основная логика голосового бота
    Args:
        call_info: CallInfo
        esl_connection: ESL connection
    """
    logger.info(f"Handling call {call_info.uuid} from {call_info.caller_number}")

    # Создаём диалог
    dialog = create_dialog_manager(
        yandex_api_key=YANDEX_API_KEY,
        yandex_folder_id=YANDEX_FOLDER_ID,
        openai_api_key=OPENAI_API_KEY,
        use_mock_asr_tts=USE_MOCK_ASR_TTS,
        use_mock_llm=USE_MOCK_LLM,
    )

    # Ответ на звонок
    if not esl_connection.api(f"uuid_answer {call_info.uuid}").getBody().startswith("+OK"):
        logger.warning(f"Failed to answer call {call_info.uuid}")
        return

    # Приветствие
    greeting_audio = await dialog.start_session(call_info.uuid)
    greeting_file = Path(tempfile.gettempdir()) / f"greeting_{call_info.uuid}.wav"
    greeting_file.write_bytes(greeting_audio)
    esl_connection.api(f"uuid_broadcast {call_info.uuid} play:{greeting_file} both")

    # Основной цикл диалога
    max_turns = dialog.max_turns
    turns = 0

    while turns < max_turns:
        turns += 1

        # Здесь можно подключить реальное получение аудио с канала
        # Для демонстрации используем mock ASR
        user_text = await dialog.asr.recognize_file(b"")  # пустой байт-код -> mock
        if not user_text:
            continue

        logger.info(f"User said: {user_text}")

        # Генерация ответа
        response_audio = await dialog.process_text(user_text)
        response_file = Path(tempfile.gettempdir()) / f"response_{call_info.uuid}_{turns}.wav"
        response_file.write_bytes(response_audio)

        # Проигрываем
        esl_connection.api(f"uuid_broadcast {call_info.uuid} play:{response_file} both")

        # Проверка, завершился ли диалог
        if dialog.state == dialog.dialog_state.ENDED:
            break

    # Завершение звонка
    esl_connection.api(f"uuid_kill {call_info.uuid} NORMAL_CLEARING")
    logger.info(f"Call {call_info.uuid} ended")


# --- Main ---
def main():
    logger.info("Starting FreeSWITCH Voice Bot Server...")

    # Создаём обработчик звонков
    call_handler = create_call_handler(
        host=ESL_HOST,
        port=ESL_PORT,
        password=ESL_PASSWORD,
        use_mock=False,
        voice_bot_callback=voice_bot_callback,
    )

    if not call_handler.connect():
        logger.error("Failed to connect to FreeSWITCH ESL")
        return

    call_handler.subscribe_events()

    try:
        logger.info("Voice bot running. Waiting for calls...")
        call_handler.run()
    except KeyboardInterrupt:
        logger.info("Stopping voice bot...")
    finally:
        call_handler.stop()
        call_handler.disconnect()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()