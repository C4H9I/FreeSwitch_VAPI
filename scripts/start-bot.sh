#!/bin/bash
#
# Запуск Voice Bot
#

set -e

# Переход в директорию voice-bot
cd "$(dirname "$0")/../voice-bot"

# Активация виртуального окружения если есть
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Экспорт переменных окружения из .env файла если есть
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Запуск
echo "Starting Voice Bot..."
echo ""

# Проверка аргументов
if [ "$1" = "--mock" ] || [ "$1" = "-m" ]; then
    echo "Running in MOCK mode (no real services)"
    python app/main.py --mock
elif [ "$1" = "--test" ] || [ "$1" = "-t" ]; then
    echo "Running in TEST mode (dialog test)"
    python app/main.py --test
else
    echo "Running in PRODUCTION mode"
    python app/main.py "$@"
fi
