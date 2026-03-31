#!/usr/bin/env python3
"""Voice Bot Main Application"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from config.settings import load_config, Settings

settings = None


def setup_logging(cfg: Settings) -> None:
    """Настройка логирования"""
    logger.remove()
    
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<level>{message}</level>"
    )
    
    # Консоль
    logger.add(sys.stdout, format=log_format, level=cfg.logging.level, colorize=True)
    
    # Файл
    log_file = Path(cfg.logging.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        str(log_file),
        format=log_format,
        level=cfg.logging.level,
        rotation=f"{cfg.logging.max_size} MB",
        retention=cfg.logging.backup_count,
    )
    
    logger.info(f"Logging initialized: {log_file}")


async def test_dialog(cfg: Settings) -> None:
    """Тестирование диалога"""
    from app.dialog_manager import create_dialog_manager
    
    logger.info("Testing dialog...")
    
    dialog = create_dialog_manager(
        yandex_api_key=os.getenv("YANDEX_API_KEY", ""),
        yandex_folder_id=os.getenv("YANDEX_FOLDER_ID"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        system_prompt=cfg.llm.system_prompt,
        voice_config={"tts": cfg.voice.tts.model_dump(), "asr": cfg.voice.asr.model_dump()},
        dialog_config={
            "greeting": cfg.dialog.greeting,
            "goodbye": cfg.dialog.goodbye,
            "not_understood": cfg.dialog.not_understood,
            "waiting": cfg.dialog.waiting,
            "max_turns": cfg.dialog.max_turns,
            "max_duration": cfg.dialog.max_duration,
        },
        use_mock=True,
    )
    
    greeting = await dialog.start_session("test-session")
    print(f"\nБот: {cfg.dialog.greeting}")
    print(f"(Аудио: {len(greeting)} байт)")
    
    test_messages = ["Здравствуйте!", "Какие у вас услуги?", "Спасибо, до свидания"]
    
    for msg in test_messages:
        print(f"\nПользователь: {msg}")
        response = await dialog.process_text(msg)
        print(f"Бот: [аудио {len(response)} байт]")
        if dialog.state.value == "ended":
            break
    
    print("\nТест завершен.")


async def run_server(cfg: Settings, use_mock: bool = False) -> None:
    """Запуск сервера"""
    from app.call_handler import create_call_handler
    
    logger.info(f"Starting Voice Bot: {cfg.agent.name} v{cfg.agent.version}")
    logger.info(f"Mock mode: {use_mock}")
    
    handler = create_call_handler(
        host=cfg.freeswitch.host,
        port=cfg.freeswitch.port,
        password=cfg.freeswitch.password,
        use_mock=use_mock,
    )
    
    if handler.connect():
        logger.info("Connected to FreeSWITCH")
        handler.run()
    else:
        logger.error("Failed to connect")


def main():
    global settings
    
    parser = argparse.ArgumentParser(description="Voice Bot")
    parser.add_argument("--config", "-c", default=None)
    parser.add_argument("--mock", "-m", action="store_true")
    parser.add_argument("--test", "-t", action="store_true")
    args = parser.parse_args()
    
    settings = load_config(args.config)
    
    # Загрузка .env
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value)
    
    setup_logging(settings)
    
    if args.test:
        asyncio.run(test_dialog(settings))
    else:
        asyncio.run(run_server(settings, use_mock=args.mock))


if __name__ == "__main__":
    main()
