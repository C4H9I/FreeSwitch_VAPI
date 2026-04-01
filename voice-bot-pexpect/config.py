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
SSH_PORT = os.getenv("SSH_PORT")  # SSH-порт
SSH_USER = os.getenv("SSH_USER")  # Пользователь SSH
SSH_PASSWORD = os.getenv("SSH_PASSWORD")  # Пароль SSH (можно использовать ключ вместо пароля)
SSH_KEY_FILE = os.getenv("SSH_KEY_FILE")  # Путь к SSH-ключу (например "/home/user/.ssh/id_rsa").
# Если указан — пароль игнорируется.

# ─── FreeSWITCH ESL / fs_cli ─────────────────────────────────────────
FS_CLI_PATH = os.getenv("FS_CLI_PATH")  # Путь к fs_cli на удалённом сервере
FS_HOST = os.getenv("FS_HOST")  # Адрес FreeSWITCH (обычно localhost)
FS_PORT = os.getenv("FS_PORT")  # ESL-порт FreeSWITCH
FS_PASSWORD = os.getenv("FS_PASSWORD")  # Пароль ESL FreeSWITCH

# ─── Таймауты ────────────────────────────────────────────────────────
CONNECT_TIMEOUT = os.getenv("CONNECT_TIMEOUT")  # Таймаут SSH-подключения (секунды)
COMMAND_TIMEOUT = os.getenv("COMMAND_TIMEOUT")  # Таймаут выполнения команды fs_cli (секунды)
POLL_INTERVAL = os.getenv("POLL_INTERVAL")  # Интервал опроса новых каналов (секунды)
RECONNECT_DELAY = os.getenv("RECONNECT_DELAY")  # Задержка перед переподключением при разрыве (секунды)
MAX_RECONNECT_ATTEMPTS = os.getenv("MAX_RECONNECT_ATTEMPTS")  # бесконечно)

# ─── Пути к файлам ──────────────────────────────────────────────────
RECORD_DIR = os.getenv("RECORD_DIR")  # Директория для записи звонков на сервере FreeSWITCH
AUDIO_DIR = os.getenv("AUDIO_DIR")  # Корневая директория звуков

# Звуки по умолчанию
DEFAULT_GREETING = os.getenv("DEFAULT_GREETING")  # Приветствие
DEFAULT_MENU = os.getenv("DEFAULT_MENU")  # Меню
DEFAULT_GOODBYE = os.getenv("DEFAULT_GOODBYE")  # Прощание

# ─── Логирование ─────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL")  # Уровень логирования: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = os.getenv("LOG_FILE")  # логировать в stdout)

print(LOG_LEVEL)
