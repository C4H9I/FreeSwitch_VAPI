# Инструкция по установке и настройке

## Полное руководство по развертыванию голосового бота

---

## Содержание

1. [Требования к системе](#1-требования-к-системе)
2. [Установка FreeSWITCH](#2-установка-freeswitch)
3. [Настройка SIP-подключения](#3-настройка-sip-подключения)
4. [Установка Voice Bot](#4-установка-voice-bot)
5. [Получение API ключей](#5-получение-api-ключей)
6. [Конфигурация](#6-конфигурация)
7. [Запуск и тестирование](#7-запуск-и-тестирование)
8. [Диагностика проблем](#8-диагностика-проблем)

---

## 1. Требования к системе

### Минимальные требования

| Параметр | Значение |
|----------|----------|
| ОС | Ubuntu 22.04 LTS |
| CPU | 2 ядра |
| RAM | 4 GB |
| Диск | 20 GB |
| Сеть | Статический IP, открытые порты 5060 (SIP), 16384-16398 (RTP) |

### Рекомендуемые требования

| Параметр | Значение |
|----------|----------|
| CPU | 4 ядра |
| RAM | 8 GB |
| Диск | 50 GB SSD |

### Необходимые порты

```
5060/udp   - SIP сигнализация
5080/udp   - SIP External профиль
8021/tcp   - Event Socket Layer (ESL)
16384-16398/udp - RTP медиа-потоки
```

---

## 2. Установка FreeSWITCH

### Шаг 2.1: Подготовка системы

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка необходимых пакетов
sudo apt install -y wget curl git sox ffmpeg
```

### Шаг 2.2: Установка через скрипт

```bash
# Клонирование проекта (если еще не сделано)
git clone <repository-url> freeswitch-vapi
cd freeswitch-vapi

# Запуск скрипта установки
chmod +x scripts/install-freeswitch.sh
sudo ./scripts/install-freeswitch.sh
```

### Шаг 2.3: Проверка установки

```bash
# Проверка статуса
sudo systemctl status freeswitch

# Подключение к CLI
fs_cli -u freeswitch -p ClueCon

# В CLI проверить статус
sofia status
sofia status profile external

# Выход из CLI
/exit
```

---

## 3. Настройка SIP-подключения

### Шаг 3.1: Копирование конфигураций

```bash
# Резервное копирование оригиналов
sudo cp /etc/freeswitch/sip_profiles/external.xml /etc/freeswitch/sip_profiles/external.xml.bak

# Копирование наших конфигураций
sudo cp freeswitch-config/sip-trunk-external.xml /etc/freeswitch/sip_profiles/external/ips-provider.xml
sudo cp freeswitch-config/external.xml /etc/freeswitch/sip_profiles/external.xml
sudo cp freeswitch-config/dialplan-public.xml /etc/freeswitch/dialplan/public.xml
sudo cp freeswitch-config/event_socket.conf.xml /etc/freeswitch/autoload_configs/event_socket.conf.xml
```

### Шаг 3.2: Настройка переменных FreeSWITCH

Отредактируйте `/etc/freeswitch/vars.xml`:

```xml
<!-- Замените на ваш внешний IP -->
<X-PRE-PROCESS cmd="set" data="external_rtp_ip=YOUR_EXTERNAL_IP"/>
<X-PRE-PROCESS cmd="set" data="external_sip_ip=YOUR_EXTERNAL_IP"/>
<X-PRE-PROCESS cmd="set" data="local_ip_v4=YOUR_LOCAL_IP"/>
```

### Шаг 3.3: Настройка SIP-провайдера

Отредактируйте `/etc/freeswitch/sip_profiles/external/ips-provider.xml`:

```xml
<gateway name="ips-provider">
    <param name="username" value="sipuser"/>
    <param name="password" value="sippassword"/>
    <param name="proxy" value="sip.ips.com:5060"/>
    <param name="register" value="true"/>
    <!-- ... остальные параметры ... -->
</gateway>
```

### Шаг 3.4: Перезапуск FreeSWITCH

```bash
sudo systemctl restart freeswitch
```

### Шаг 3.5: Проверка регистрации SIP

```bash
fs_cli -u freeswitch -p ClueCon

# Проверка регистрации
sofia status profile external

# Проверка gateway
sofia status

# Должно показать REGISTERED для ips-provider
```

---

## 4. Установка Voice Bot

### Шаг 4.1: Установка Python 3.10+

```bash
# Ubuntu 22.04 уже имеет Python 3.10
python3 --version

# Установка pip и venv
sudo apt install -y python3-pip python3-venv
```

### Шаг 4.2: Создание виртуального окружения

```bash
cd freeswitch-vapi/voice-bot

# Создание venv
python3 -m venv venv

# Активация
source venv/bin/activate
```

### Шаг 4.3: Установка зависимостей

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Шаг 4.4: Установка ESL (Event Socket Library)

```bash
# Python ESL для FreeSWITCH
pip install python-esl

# Или альтернатива
pip install eventsocket
```

---

## 5. Получение API ключей

### 5.1 Yandex Cloud (SpeechKit)

1. Перейдите в [Yandex Cloud Console](https://console.cloud.yandex.ru/)
2. Создайте платежный аккаунт
3. Перейдите в **IAM и администрирование** → **Сервисные аккаунты**
4. Создайте сервисный аккаунт
5. Добавьте роль `ai.speechkit-tts.user` и `ai.speechkit-stt.user`
6. Создайте API-ключ

```bash
# Сохраните ключ
export YANDEX_API_KEY="your-api-key"
export YANDEX_FOLDER_ID="your-folder-id"
```

### 5.2 OpenAI API

1. Перейдите на [OpenAI Platform](https://platform.openai.com/)
2. Зарегистрируйтесь / войдите
3. Перейдите в **API Keys**
4. Создайте новый ключ

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_API_BASE="https://api.openai.com/v1"
```

---

## 6. Конфигурация

### 6.1 Создание .env файла

```bash
cd voice-bot
cp .env.example .env
nano .env
```

Заполните файл:

```env
YANDEX_API_KEY=your-yandex-api-key
YANDEX_FOLDER_ID=your-folder-id
OPENAI_API_KEY=sk-your-openai-key
OPENAI_API_BASE=https://api.openai.com/v1
```

### 6.2 Настройка агента

Отредактируйте `config/agent.yaml`:

```yaml
# Голос бота
voice:
  tts:
    voice: "алена"      # Голос: алена, филарет, ева, саша, антон, федор
    emotion: "good"     # Эмоция: good, evil, neutral
    speed: 1.0          # Скорость: 0.1 - 3.0

# LLM настройки
llm:
  model: "gpt-4o"
  max_tokens: 150
  temperature: 0.7
  system_prompt: |
    Твой системный промпт здесь...

# Диалог
dialog:
  greeting: "Добрый день! Меня зовут Алёна. Чем могу помочь?"
  goodbye: "Спасибо за звонок! Хорошего дня!"
  max_duration: 300     # 5 минут максимум
```

---

## 7. Запуск и тестирование

### 7.1 Тестовый режим (без FreeSWITCH)

```bash
cd voice-bot
source venv/bin/activate

# Тест диалога
python app/main.py --test
```

### 7.2 Mock режим (без реальных API)

```bash
python app/main.py --mock
```

### 7.3 Полный запуск

```bash
# Запуск FreeSWITCH (если не запущен)
sudo systemctl start freeswitch

# Запуск Voice Bot
./scripts/start-bot.sh
```

### 7.4 Проверка входящих звонков

Позвоните на номер, подключенный к вашему SIP-транку. В логах должно появиться:

```
Channel created: xxx-xxx-xxx - 7495xxxxxxx -> 7495xxxxxxx
Channel answered: xxx-xxx-xxx
Processing call: xxx-xxx-xxx
```

---

## 8. Диагностика проблем

### 8.1 FreeSWITCH не запускается

```bash
# Проверка логов
tail -f /var/log/freeswitch/freeswitch.log

# Проверка портов
sudo netstat -tulpn | grep freeswitch

# Перезапуск
sudo systemctl restart freeswitch
```

### 8.2 SIP не регистрируется

```bash
fs_cli -u freeswitch -p ClueCon

# Включить отладку SIP
sofia global siptrace on

# Перезагрузить профиль
reloadxml
sofia profile external restart

# Проверить статус
sofia status profile external
```

### 8.3 Нет звука

1. Проверьте RTP порты (16384-16398)
2. Проверьте NAT настройки
3. Проверьте кодеки:

```bash
fs_cli -u freeswitch -p ClueCon
show codec
```

### 8.4 ASR/TTS не работает

1. Проверьте API ключи:

```bash
curl -X POST \
  "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize" \
  -H "Authorization: Api-Key $YANDEX_API_KEY" \
  --data-binary @audio.raw
```

2. Проверьте баланс Yandex Cloud

### 8.5 LLM не отвечает

```bash
# Тест OpenAI API
curl https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello"}]}'
```

---

## Дополнительные ресурсы

- [FreeSWITCH Documentation](https://freeswitch.org/confluence/)
- [Yandex SpeechKit API](https://cloud.yandex.ru/docs/speechkit/)
- [OpenAI API Reference](https://platform.openai.com/docs/)

---

## Контакты и поддержка

При возникновении проблем проверьте логи:
- FreeSWITCH: `/var/log/freeswitch/freeswitch.log`
- Voice Bot: `/var/log/voice-bot/bot.log`
