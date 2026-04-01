#!/usr/bin/env python3
"""
main.py — Демон мониторинга входящих звонков FreeSWITCH
========================================================
Пример использования модуля freeswitch_manager.

Скрипт подключается к FreeSWITCH, отслеживает новые входящие звонки
и выполняет настроенную логику обработки:

  1. При входящем звонке — воспроизводит приветствие
  2. Начинает запись разговора
  3. При завершении звонка — останавливает запись
  4. Логирует все события

Запуск:
    python main.py

Для интерактивного режима (ручное управление):
    python main.py --interactive

Для помощи:
    python main.py --help
"""

import argparse
import logging
import sys
import time

from freeswitch_manager import FreeSwitchManager, Channel, FreeSwitchError
import config

# ─── Настройка логирования ──────────────────────────────────────────────────

def setup_logging():
    """Настраивает логирование на основе config.py."""
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        filename=config.LOG_FILE,
    )
    # Если лог-файл не указан, выводим и в stdout
    if not config.LOG_FILE:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(log_level)
        console.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logging.getLogger().addHandler(console)


# ─── Callback-обработчики ────────────────────────────────────────────────────

def on_new_call(channel: Channel, mgr: FreeSwitchManager):
    """
    Обработчик нового входящего звонка.

    Вызывается автоматически при обнаружении нового канала.
    Здесь описывается логика обработки: воспроизведение приветствия,
    начало записи, и т.д.
    """
    print(f"\n{'='*60}")
    print(f"📞 НОВЫЙ ВХОДЯЩИЙ ЗВОНОК")
    print(f"   UUID:        {channel.uuid}")
    print(f"   Номер:       {channel.cid_num}")
    print(f"   Имя:         {channel.cid_name}")
    print(f"   Направление: {channel.dest}")
    print(f"   Состояние:   {channel.state}")
    print(f"   IP:          {channel.ip_addr}")
    print(f"{'='*60}\n")

    try:
        # 1. Начинаем запись разговора
        filepath = f"{config.RECORD_DIR}/{channel.uuid}_record.wav"
        mgr.start_recording(channel.uuid, filepath)
        print(f"🎙️  Запись начата: {filepath}")

        # 2. Проигрываем приветствие
        time.sleep(0.5)  # Небольшая пауза перед воспроизведением
        mgr.broadcast_audio(channel.uuid, config.DEFAULT_GREETING, leg="aleg")
        print(f"🔊 Приветствие воспроизведено: {config.DEFAULT_GREETING}")

    except FreeSwitchError as e:
        print(f"❌ Ошибка при обработке звонка: {e}")


def on_call_end(uuid: str, mgr: FreeSwitchManager):
    """
    Обработчик завершения звонка.

    Вызывается, когда UUID исчезает из списка активных каналов.
    """
    print(f"\n{'='*60}")
    print(f"🔚 ЗВОНОК ЗАВЕРШЁН")
    print(f"   UUID: {uuid}")
    print(f"{'='*60}\n")

    try:
        # Останавливаем запись
        filepath = f"{config.RECORD_DIR}/{uuid}_record.wav"
        mgr.stop_recording(uuid, filepath)
        print(f"💾 Запись сохранена: {filepath}")

    except FreeSwitchError as e:
        print(f"⚠️  Не удалось остановить запись: {e}")


def on_error(error: FreeSwitchError):
    """Обработчик ошибок."""
    print(f"\n❌ ОШИБКА: {error}\n")


# ─── Интерактивный режим ─────────────────────────────────────────────────────

def interactive_mode(mgr: FreeSwitchManager):
    """
    Интерактивный режим управления FreeSWITCH.

    Предоставляет командную строку для ручного управления звонками.
    """
    print("\n" + "=" * 60)
    print("  INTERACTIVE MODE — FreeSWITCH Manager")
    print("  Доступные команды:")
    print("    list          — показать все активные каналы")
    print("    inbound       — показать только входящие каналы")
    print("    play <UUID> <file> — воспроизвести аудиофайл")
    print("    record <UUID>     — начать запись")
    print("    stop <UUID>       — остановить запись")
    print("    kill <UUID>       — завершить звонок")
    print("    greet <UUID>      — воспроизвести приветствие")
    print("    status        — статус подключения")
    print("    help          — показать справку")
    print("    quit / exit   — выход")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("freeswitch> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход...")
            break

        if not user_input:
            continue

        parts = user_input.split(maxsplit=2)
        cmd = parts[0].lower()

        try:
            if cmd in ("quit", "exit"):
                break

            elif cmd == "help":
                print(__doc__)

            elif cmd == "status":
                print(f"Подключение: {'✅ Активно' if mgr.is_connected() else '❌ Отключено'}")
                print(f"Сервер: {mgr.ssh_host}:{mgr.ssh_port}")
                print(f"Известных звонков: {len(mgr._known_uuids)}")

            elif cmd == "list":
                channels = mgr.get_active_channels()
                if not channels:
                    print("  Нет активных каналов.")
                for i, ch in enumerate(channels, 1):
                    direction_icon = "📥" if "inbound" in ch.direction else "📤"
                    print(f"  {i}. {direction_icon} {ch.uuid[:12]}...  "
                          f"от: {ch.cid_num or 'N/A'}  →  {ch.dest or 'N/A'}  "
                          f"({ch.direction}, {ch.state})")

            elif cmd == "inbound":
                channels = mgr.get_inbound_channels()
                if not channels:
                    print("  Нет входящих звонков.")
                for i, ch in enumerate(channels, 1):
                    print(f"  {i}. {ch.uuid[:12]}...  "
                          f"от: {ch.cid_num or 'N/A'}  "
                          f"({ch.state})")

            elif cmd == "play" and len(parts) >= 3:
                uuid, audio = parts[1], parts[2]
                # Если передано только 12 символов UUID — ищем полное совпадение
                if len(uuid) < 36:
                    for ch in mgr.get_active_channels():
                        if ch.uuid.startswith(uuid):
                            uuid = ch.uuid
                            break
                print(f"🔊 Воспроизведение {audio} → {uuid}")
                result = mgr.broadcast_audio(uuid, audio)
                print(f"   Результат: {result}")

            elif cmd == "greet" and len(parts) >= 2:
                uuid = parts[1]
                if len(uuid) < 36:
                    for ch in mgr.get_active_channels():
                        if ch.uuid.startswith(uuid):
                            uuid = ch.uuid
                            break
                print(f"🔊 Приветствие → {uuid}")
                mgr.broadcast_audio(uuid, config.DEFAULT_GREETING)
                print("   ✅ Готово")

            elif cmd == "record" and len(parts) >= 2:
                uuid = parts[1]
                if len(uuid) < 36:
                    for ch in mgr.get_active_channels():
                        if ch.uuid.startswith(uuid):
                            uuid = ch.uuid
                            break
                mgr.start_recording(uuid)
                print(f"🎙️  Запись начата для {uuid[:12]}...")

            elif cmd == "stop" and len(parts) >= 2:
                uuid = parts[1]
                if len(uuid) < 36:
                    for ch in mgr.get_active_channels():
                        if ch.uuid.startswith(uuid):
                            uuid = ch.uuid
                            break
                mgr.stop_recording(uuid)
                print(f"⏹️  Запись остановлена для {uuid[:12]}...")

            elif cmd == "kill" and len(parts) >= 2:
                uuid = parts[1]
                if len(uuid) < 36:
                    for ch in mgr.get_active_channels():
                        if ch.uuid.startswith(uuid):
                            uuid = ch.uuid
                            break
                mgr.kill_call(uuid)
                print(f"🔴 Звонок {uuid[:12]}... завершён")

            else:
                # Произвольная команда FreeSWITCH
                result = mgr.execute(user_input)
                print(result)

        except FreeSwitchError as e:
            print(f"❌ Ошибка: {e}")
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")


# ─── Основной поток ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="FreeSWITCH Manager — мониторинг и управление входящими звонками",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python main.py                    # Мониторинг с callback-обработчиками
  python main.py --interactive     # Интерактивный режим
  python main.py --once            # Показать каналы и выйти
  python main.py --poll 5          # Опрос каждые 5 секунд
        """
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Запустить интерактивный режим (ручное управление)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Показать активные каналы один раз и выйти"
    )
    parser.add_argument(
        "--poll", type=float, default=None,
        help="Интервал опроса в секундах (по умолчанию из config.py)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Мониторить все звонки, а не только входящие"
    )

    args = parser.parse_args()

    # Настройка логирования
    setup_logging()
    logger = logging.getLogger("main")

    # Инициализация менеджера
    mgr = FreeSwitchManager()

    try:
        # Подключение
        mgr.connect()

        if args.once:
            # Режим "показать и выйти"
            channels = mgr.get_active_channels()
            if not channels:
                print("Нет активных каналов.")
            else:
                print(f"\nАктивные каналы ({len(channels)}):\n")
                for ch in channels:
                    icon = "📥" if "inbound" in ch.direction else "📤"
                    print(f"  {icon} {ch.uuid}")
                    print(f"     Направление: {ch.direction}")
                    print(f"     От: {ch.cid_num} ({ch.cid_name})")
                    print(f"     Куда: {ch.dest}")
                    print(f"     Состояние: {ch.state}")
                    print(f"     Приложение: {ch.application}")
                    print()
            return

        if args.interactive:
            # Интерактивный режим
            interactive_mode(mgr)
            return

        # Режим мониторинга с callback
        # Регистрируем обработчики
        mgr.register_callback("new_call", lambda channel: on_new_call(channel, mgr))
        mgr.register_callback("call_end", lambda uuid: on_call_end(uuid, mgr))
        mgr.register_callback("error", on_error)

        logger.info("Запуск мониторинга входящих звонков...")
        print(f"\n🟢 Мониторинг запущен. Ожидание входящих звонков...")
        print(f"   Сервер: {mgr.ssh_host}:{mgr.ssh_port}")
        print(f"   Опрос каждые {args.poll or mgr.poll_interval} сек.")
        print(f"   Нажмите Ctrl+C для остановки\n")

        mgr.monitor_loop(
            poll_interval=args.poll,
            inbound_only=not args.all,
        )

    except FreeSwitchError as e:
        logger.critical("Критическая ошибка: %s", e)
        print(f"\n❌ Критическая ошибка: {e}")
        print("   Проверьте настройки подключения в config.py")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Остановка по запросу пользователя")
        print("\n\n⏹️  Остановлено.")
    finally:
        mgr.disconnect()


if __name__ == "__main__":
    main()
