import os
import asyncio
from pathlib import Path

# Загрузка .env
env_file = Path(".env")
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)

from app.dialog_manager import create_dialog_manager
from app.llm import LLMClient

async def test():
    print("=== Тест с реальным OpenAI API ===\n")
    
    # Тест LLM напрямую
    llm = LLMClient(
        api_key=os.getenv("OPENAI_API_KEY"),
        api_base=os.getenv("OPENAI_API_BASE"),
        model="gpt-4o-mini",
        max_tokens=100,
        system_prompt="Ты голосовой помощник. Отвечай кратко."
    )
    
    response = await llm.generate("Здравствуйте! Какие у вас услуги?", "test")
    print(f"LLM ответ: {response}\n")
    
    # Тест через dialog manager
    print("=== Тест через Dialog Manager ===\n")
    
    dialog = create_dialog_manager(
        yandex_api_key="",  # Mock TTS/ASR
        yandex_folder_id=None,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_api_base=os.getenv("OPENAI_API_BASE"),
        system_prompt="Ты голосовой помощник техподдержки. Отвечай кратко и вежливо.",
        voice_config={"tts": {}, "asr": {}},
        dialog_config={
            "greeting": "Добрый день! Чем могу помочь?",
            "goodbye": "Спасибо за звонок!",
            "not_understood": "Не расслышала.",
            "waiting": "Одну секунду...",
            "max_turns": 5,
            "max_duration": 60,
        },
        use_mock=True,  # Mock для ASR/TTS, реальный LLM
    )
    
    greeting = await dialog.start_session("test-real")
    print(f"Бот: Добрый день! Чем могу помочь?\n")
    
    messages = ["Здравствуйте, хочу узнать о ваших тарифах", "Спасибо, до свидания"]
    
    for msg in messages:
        print(f"Пользователь: {msg}")
        response = await dialog.process_text(msg)
        print(f"Бот: [ответ получен]\n")
        
        if dialog.state.value == "ended":
            break
    
    print("Тест завершен!")

asyncio.run(test())
