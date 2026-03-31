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

print("=== Тест Yandex SpeechKit TTS ===\n")

async def test_tts():
    import grpc
    
    api_key = os.getenv("YANDEX_API_KEY")
    print(f"API Key: {api_key[:15]}...")
    
    # Тест подключения к TTS
    try:
        channel = grpc.secure_channel(
            "tts.api.cloud.yandex.net:443",
            grpc.ssl_channel_credentials()
        )
        
        # Ждём готовности канала
        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, lambda: grpc.channel_ready_future(channel).result()
            ),
            timeout=10
        )
        print("✅ Подключение к Yandex TTS успешно!\n")
        
        # TODO: Реальный синтез при необходимости
        # Нужно установить правильные protobuf классы
        
        channel.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

asyncio.run(test_tts())
