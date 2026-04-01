"""
Конфигурация подключения к FreeSWITCH
=====================================
Заполните параметры перед запуском. Файл можно также
переопределить через переменные окружения (см. ниже).
"""
import os
from dotenv import load_dotenv

load_dotenv()


# ─── SSH-подключение к серверу с FreeSWITCH ─────────────────────────
SSH_HOST = os.getenv("SSH_HOST")  # IP-адрес сервера FreeSWITCH
SSH_PORT = int(os.getenv("SSH_PORT", 22))  # SSH-порт
SSH_USER = os.getenv("SSH_USER")  # Пользователь SSH
SSH_PASSWORD = os.getenv("SSH_PASSWORD")  # Пароль SSH (можно использовать ключ вместо пароля)
SSH_KEY_FILE = os.getenv("SSH_KEY_FILE", None)  # Путь к SSH-ключу (например "/home/user/.ssh/id_rsa").
# Если указан — пароль игнорируется.

# ─── FreeSWITCH ESL / fs_cli ─────────────────────────────────────────
FS_CLI_PATH = os.getenv("FS_CLI_PATH")  # Путь к fs_cli на удалённом сервере
FS_HOST = os.getenv("FS_HOST")  # Адрес FreeSWITCH (обычно localhost)
FS_PORT = os.getenv("FS_PORT")  # ESL-порт FreeSWITCH
FS_PASSWORD = os.getenv("FS_PASSWORD")  # Пароль ESL FreeSWITCH

# ─── Таймауты ────────────────────────────────────────────────────────
CONNECT_TIMEOUT = int(os.getenv("CONNECT_TIMEOUT", 10))  # Таймаут SSH-подключения (секунды)
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", 5))  # Таймаут выполнения команды fs_cli (секунды)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 1))  # Интервал опроса новых каналов (секунды)
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", 5))  # Задержка перед переподключением при разрыве (секунды)
MAX_RECONNECT_ATTEMPTS = int(os.getenv("MAX_RECONNECT_ATTEMPTS", 10))  # бесконечно)

# ─── Пути к файлам ──────────────────────────────────────────────────
RECORD_DIR = os.getenv("RECORD_DIR")  # Директория для записи звонков на сервере FreeSWITCH
AUDIO_DIR = os.getenv("AUDIO_DIR")  # Корневая директория звуков

# Звуки по умолчанию
DEFAULT_GREETING = os.getenv("DEFAULT_GREETING")  # Приветствие
DEFAULT_MENU = os.getenv("DEFAULT_MENU")  # Меню
DEFAULT_GOODBYE = os.getenv("DEFAULT_GOODBYE")  # Прощание

# ─── Логирование ─────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # Уровень логирования: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = os.getenv("LOG_FILE", None)  # Либо логировать в stdout)

print(LOG_LEVEL)
