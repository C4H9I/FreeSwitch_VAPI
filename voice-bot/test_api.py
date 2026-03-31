#!/usr/bin/env python3
import os
import asyncio

# Загрузка переменных из .env
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key] = value

print("=== Проверка API ключей ===\n")

yandex_key = os.getenv("YANDEX_API_KEY", "")
openai_key = os.getenv("OPENAI_API_KEY", "")
openai_base = os.getenv("OPENAI_API_BASE", "")

print(f"YANDEX_API_KEY: {yandex_key[:10]}...{'✅' if yandex_key else '❌'}")
print(f"OPENAI_API_KEY: {openai_key[:10]}...{'✅' if openai_key else '❌'}")
print(f"OPENAI_API_BASE: {openai_base}")

print("\n=== Тест OpenAI API ===\n")

async def test_openai():
    from openai import AsyncOpenAI
    
    client = AsyncOpenAI(
        api_key=openai_key,
        base_url=openai_base
    )
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Скажи 'Привет' одним словом"}],
            max_tokens=20
        )
        print("✅ OpenAI API работает!")
        print(f"Ответ: {response.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"❌ Ошибка OpenAI: {e}")
        return False

async def test_yandex():
    import grpc
    
    print("\n=== Тест Yandex SpeechKit ===\n")
    
    try:
        channel = grpc.secure_channel(
            "tts.api.cloud.yandex.net:443",
            grpc.ssl_channel_credentials()
        )
        # Проверяем что канал работает
        grpc.channel_ready_future(channel).result(timeout=5)
        print("✅ Подключение к Yandex TTS успешно!")
        return True
    except Exception as e:
        print(f"❌ Ошибка Yandex: {e}")
        return False

async def main():
    await test_openai()
    await test_yandex()

if __name__ == "__main__":
    asyncio.run(main())
