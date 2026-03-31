import os
import asyncio
from pathlib import Path

# Загрузка .env
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)

from app.dialog_manager import create_dialog_manager

async def test():
    print("=== Тест: Mock ASR/TTS + Реальный LLM ===\n")
    
    dialog = create_dialog_manager(
        yandex_api_key="",  # Пустой -> Mock ASR/TTS
        yandex_folder_id=None,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_api_base=os.getenv("OPENAI_API_BASE"),
        system_prompt="Ты голосовой помощник техподдержки интернет-провайдера. Отвечай кратко, не более 2 предложений.",
        voice_config={"tts": {}, "asr": {}},
        dialog_config={
            "greeting": "Добрый день! Техподдержка слушает. Чем могу помочь?",
            "goodbye": "Спасибо за обращение! Хорошего дня!",
            "not_understood": "Извините, не расслышала. Повторите.",
            "waiting": "Одну секунду...",
            "max_turns": 5,
            "max_duration": 60,
        },
        use_mock_asr_tts=True,   # Mock для ASR/TTS
        use_mock_llm=False,      # Реальный LLM!
    )
    
    greeting = await dialog.start_session("test-hybrid")
    print(f"Бот: Добрый день! Техподдержка слушает. Чем могу помочь?\n")
    
    messages = [
        "Здравствуйте, у меня не работает интернет",
        "Что нужно проверить?",
        "Спасибо, попробую. До свидания"
    ]
    
    for msg in messages:
        print(f"Пользователь: {msg}")
        response_audio = await dialog.process_text(msg)
        
        # Получить текст ответа из истории LLM
        if dialog.llm and hasattr(dialog.llm, '_contexts'):
            ctx = dialog.llm.get_context("test-hybrid")
            if ctx.messages:
                last_msg = ctx.messages[-1]
                print(f"Бот: {last_msg.content}\n")
        else:
            print(f"Бот: [аудио {len(response_audio)} байт]\n")
        
        if dialog.state.value == "ended":
            break
    
    print(f"\nСтатистика: {dialog.get_stats()}")

asyncio.run(test())
