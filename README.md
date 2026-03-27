# FreeSWITCH Voice Bot с LLM Integration

Голосовой бот на базе FreeSWITCH с подключением к LLM через API и Yandex SpeechKit для ASR/TTS.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                         ВАШ СЕРВЕР                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐      ┌──────────────────────────────────────┐ │
│  │ FreeSWITCH  │◄────►│      Voice Bot Application           │ │
│  │             │      │  (Python)                            │ │
│  │ - SIP UA    │      │                                      │ │
│  │ - RTP       │      │  ┌─────────────────────────────────┐ │ │
│  │ - Event Socket│    │  │ ESL Client (greenlet-esl)       │ │ │
│  └──────┬──────┘      │  └─────────────────────────────────┘ │ │
│         │             │                                      │ │
│         │ SIP         │  ┌──────────┐  ┌──────────┐          │ │
│         ▼             │  │   ASR    │  │   TTS    │          │ │
│  ┌─────────────┐      │  │ Yandex   │  │ Yandex   │          │ │
│  │ SIP Trunk   │      │  │ SpeechKit│  │ SpeechKit│          │ │
│  │ sip.ips.com │      │  └────┬─────┘  └────┬─────┘          │ │
│  └─────────────┘      │       │             │                │ │
│                       │       ▼             ▼                │ │
│                       │  ┌─────────────────────────────────┐ │ │
│                       │  │    OpenAI-compatible LLM API    │ │ │
│                       │  └─────────────────────────────────┘ │ │
│                       └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Компоненты

### 1. FreeSWITCH
- SIP-сервер для обработки звонков
- Кодек G.711 (PCMU/PCMA)
- Event Socket Layer для управления

### 2. Voice Bot Application (Python)
- ESL-клиент для связи с FreeSWITCH
- Управление диалогом
- Интеграция с Yandex SpeechKit
- Интеграция с LLM API

### 3. Yandex SpeechKit
- ASR (Automatic Speech Recognition) - распознавание речи
- TTS (Text-to-Speech) - синтез речи
- Русский язык

### 4. LLM API
- OpenAI-совместимый API
- Управление контекстом диалога

## Структура проекта

```
freeswitch-vapi/
├── README.md                    # Документация
├── freeswitch-config/           # Конфигурации FreeSWITCH
│   ├── sip-profile.xml          # SIP профиль
│   ├── dialplan.xml             # Dialplan
│   └── event_socket.conf.xml    # Event Socket
├── voice-bot/                   # Python приложение
│   ├── app/
│   │   ├── main.py              # Точка входа
│   │   ├── call_handler.py      # Обработка звонков
│   │   ├── asr.py               # Yandex ASR
│   │   ├── tts.py               # Yandex TTS
│   │   ├── llm.py               # LLM интеграция
│   │   └── dialog_manager.py    # Управление диалогом
│   ├── config/
│   │   ├── settings.py          # Настройки
│   │   └── agent.yaml           # Конфигурация агента
│   └── requirements.txt
├── scripts/
│   ├── install-freeswitch.sh    # Скрипт установки
│   └── start-bot.sh             # Запуск бота
└── docs/
    └── setup-guide.md           # Инструкция по установке
```

## Быстрый старт

### 1. Установка FreeSWITCH
```bash
chmod +x scripts/install-freeswitch.sh
sudo ./scripts/install-freeswitch.sh
```

### 2. Настройка FreeSWITCH
```bash
# Копировать конфигурации
sudo cp freeswitch-config/*.xml /etc/freeswitch/autoload_configs/
sudo cp freeswitch-config/sip-profile.xml /etc/freeswitch/sip_profiles/external/
```

### 3. Установка Python-приложения
```bash
cd voice-bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Настройка переменных окружения
```bash
export YANDEX_API_KEY="your-yandex-api-key"
export OPENAI_API_KEY="your-openai-api-key"
export OPENAI_API_BASE="https://api.openai.com/v1"  # или ваш endpoint
```

### 5. Запуск
```bash
./scripts/start-bot.sh
```

## Требования

- Ubuntu 22.04 LTS
- Python 3.10+
- FreeSWITCH 1.10+
- API ключи:
  - Yandex Cloud (SpeechKit)
  - OpenAI-совместимый LLM
