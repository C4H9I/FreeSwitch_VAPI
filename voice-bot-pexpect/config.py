"""
Конфигурация подключения к FreeSWITCH
=====================================
Заполните параметры перед запуском. Файл можно также
переопределить через переменные окружения (см. ниже).
"""

# ─── SSH-подключение к серверу с FreeSWITCH ─────────────────────────
SSH_HOST = "localhost"       # IP-адрес сервера FreeSWITCH
SSH_PORT = 11221                  # SSH-порт
SSH_USER = "frsw"          # Пользователь SSH
SSH_PASSWORD = "password"        # Пароль SSH (можно использовать ключ вместо пароля)
SSH_KEY_FILE = None              # Путь к SSH-ключу (например "/home/user/.ssh/id_rsa").
                                 # Если указан — пароль игнорируется.

# ─── FreeSWITCH ESL / fs_cli ─────────────────────────────────────────
FS_CLI_PATH = "/usr/local/freeswitch/bin/fs_cli"  # Путь к fs_cli на удалённом сервере
FS_HOST = "127.0.0.1"            # Адрес FreeSWITCH (обычно localhost)
FS_PORT = 8021                   # ESL-порт FreeSWITCH
FS_PASSWORD = "ClueCon"          # Пароль ESL FreeSWITCH

# ─── Таймауты ────────────────────────────────────────────────────────
CONNECT_TIMEOUT = 10             # Таймаут SSH-подключения (секунды)
COMMAND_TIMEOUT = 5              # Таймаут выполнения команды fs_cli (секунды)
POLL_INTERVAL = 1                # Интервал опроса новых каналов (секунды)
RECONNECT_DELAY = 5              # Задержка перед переподключением при разрыве (секунды)
MAX_RECONNECT_ATTEMPTS = 10      # Максимальное число попыток переподключения (0 = бесконечно)

# ─── Пути к файлам ──────────────────────────────────────────────────
RECORD_DIR = "/tmp/voice-bot"    # Директория для записи звонков на сервере FreeSWITCH
AUDIO_DIR = "/usr/share/freeswitch/sounds"  # Корневая директория звуков

# Звуки по умолчанию
DEFAULT_GREETING = "ivr/ivr-hello.wav"           # Приветствие
DEFAULT_MENU = "ivr/ivr-enter_destination.wav"    # Меню
DEFAULT_GOODBYE = "voicemail/vm-goodbye.wav"      # Прощание

# ─── Логирование ─────────────────────────────────────────────────────
LOG_LEVEL = "INFO"               # Уровень логирования: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = None                  # Путь к файлу логов (None = логировать в stdout)
