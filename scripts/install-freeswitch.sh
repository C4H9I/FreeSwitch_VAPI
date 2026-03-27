#!/bin/bash
#
# Установка FreeSWITCH на Ubuntu 22.04
# Для голосового бота с SIP-транком
#

set -e

echo "=========================================="
echo "  FreeSWITCH Installation Script"
echo "  Ubuntu 22.04 LTS"
echo "=========================================="

# Проверка прав root
if [ "$EUID" -ne 0 ]; then
    echo "Запустите скрипт с правами root: sudo $0"
    exit 1
fi

# Обновление системы
echo "[1/8] Обновление системы..."
apt-get update
apt-get upgrade -y

# Установка зависимостей
echo "[2/8] Установка зависимостей..."
apt-get install -y \
    build-essential \
    cmake \
    automake \
    autoconf \
    libtool \
    pkg-config \
    libssl-dev \
    libsqlite3-dev \
    libpcre3-dev \
    libcurl4-openssl-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libtiff5-dev \
    libjpeg-dev \
    libspeex-dev \
    libspeexdsp-dev \
    libldns-dev \
    libedit-dev \
    liblua5.2-dev \
    libopus-dev \
    libsndfile1-dev \
    libopencv-dev \
    uuid-dev \
    libavformat-dev \
    libswscale-dev \
    libpq-dev \
    libmysqlclient-dev \
    unixodbc-dev \
    wget \
    git \
    curl \
    sox \
    ffmpeg

# Добавление репозитория FreeSWITCH
echo "[3/8] Добавление репозитория FreeSWITCH..."
wget -O - https://files.freeswitch.org/repo/deb/debian-release/freeswitch_archive_g0.pub | apt-key add -

echo "deb http://files.freeswitch.org/repo/deb/debian-release/ `lsb_release -sc` main" > /etc/apt/sources.list.d/freeswitch.list

apt-get update

# Установка FreeSWITCH
echo "[4/8] Установка FreeSWITCH..."
apt-get install -y \
    freeswitch \
    freeswitch-audio \
    freeswitch-lang-en \
    freeswitch-lang-ru \
    freeswitch-sounds-en-us-callie \
    freeswitch-sounds-ru-RU-elena \
    freeswitch-mod-commands \
    freeswitch-mod-conference \
    freeswitch-mod-db \
    freeswitch-mod-dialplan-xml \
    freeswitch-mod-dptools \
    freeswitch-mod-event-socket \
    freeswitch-mod-expr \
    freeswitch-mod-fifo \
    freeswitch-mod-g723-1 \
    freeswitch-mod-g729 \
    freeswitch-mod-hash \
    freeswitch-mod-httapi \
    freeswitch-mod-http-cache \
    freeswitch-mod-lua \
    freeswitch-mod-native-file \
    freeswitch-mod-opus \
    freeswitch-mod-portal \
    freeswitch-mod-say-en \
    freeswitch-mod-say-ru \
    freeswitch-mod-sndfile \
    freeswitch-mod-sofia \
    freeswitch-mod-spandsp \
    freeswitch-mod-valet-parking \
    freeswitch-mod-voicemail \
    freeswitch-mod-voicemail-ivr \
    freeswitch-mod-xml-cdr \
    freeswitch-mod-xml-curl \
    freeswitch-mod-enum \
    freeswitch-mod-directory \
    freeswitch-mod-rtc \
    freeswitch-mod-png \
    freeswitch-mod-vp8 \
    freeswitch-mod-h26x

# Включение модулей
echo "[5/8] Включение необходимых модулей..."
MODULES=(
    "mod_event_socket"
    "mod_sofia"
    "mod_dialplan_xml"
    "mod_commands"
    "mod_dptools"
    "mod_native_file"
    "mod_sndfile"
    "mod_g723_1"
    "mod_g729"
    "mod_opus"
    "mod_spandsp"
    "mod_conference"
    "mod_fifo"
    "mod_voicemail"
    "mod_db"
    "mod_hash"
    "mod_xml_cdr"
    "mod_cdr_csv"
    "mod_say_ru"
    "mod_lua"
)

for module in "${MODULES[@]}"; do
    if grep -q "#$module" /etc/freeswitch/autoload_modules.conf.xml; then
        sed -i "s/#$module/$module/" /etc/freeswitch/autoload_modules.conf.xml
        echo "  Включен: $module"
    fi
done

# Настройка Event Socket
echo "[6/8] Настройка Event Socket..."
cat > /etc/freeswitch/autoload_configs/event_socket.conf.xml << 'EOF'
<configuration name="event_socket.conf" description="Socket Client">
  <settings>
    <param name="nat-map" value="false"/>
    <param name="listen-ip" value="127.0.0.1"/>
    <param name="listen-port" value="8021"/>
    <param name="password" value="ClueCon"/>
    <param name="apply-inbound-acl" value="loopback.auto"/>
    <param name="stop-on-bind-error" value="true"/>
  </settings>
</configuration>
EOF

# Создание директории для записей
echo "[7/8] Создание директорий..."
mkdir -p /var/lib/freeswitch/recordings
mkdir -p /var/log/freeswitch
chown -R freeswitch:freeswitch /var/lib/freeswitch/recordings
chown -R freeswitch:freeswitch /var/log/freeswitch

# Запуск FreeSWITCH
echo "[8/8] Запуск FreeSWITCH..."
systemctl enable freeswitch
systemctl start freeswitch

echo ""
echo "=========================================="
echo "  Установка завершена!"
echo "=========================================="
echo ""
echo "FreeSWITCH установлен и запущен."
echo ""
echo "Полезные команды:"
echo "  fs_cli -u freeswitch -p ClueCon  # CLI консоль"
echo "  systemctl status freeswitch      # Статус"
echo "  systemctl restart freeswitch     # Перезапуск"
echo ""
echo "Логи: /var/log/freeswitch/freeswitch.log"
echo ""
