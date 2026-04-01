"""
FreeSWITCH Manager — интерфейс управления FreeSWITCH через pexpect
==================================================================
Модуль обеспечивает:
  • SSH-подключение к серверу FreeSWITCH и запуск fs_cli
  • Мониторинг активных каналов (входящие/исходящие звонки)
  • Воспроизведение аудиофайлов (uuid_broadcast)
  • Запись разговора (uuid_record start/stop)
  • Завершение звонка (uuid_kill)
  • Callback-механизм для обработки новых входящих звонков
  • Автоматическое переподключение при обрыве связи

Использование:
    from freeswitch_manager import FreeSwitchManager

    mgr = FreeSwitchManager()

    def on_new_call(channel):
        print(f"Новый звонок от {channel.cid_num}")

    mgr.register_callback("new_call", on_new_call)
    mgr.connect()
    mgr.monitor_loop()
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import pexpect

import config

logger = logging.getLogger("freeswitch_manager")


# ─── Data-классы ──────────────────────────────────────────────────────────────

@dataclass
class Channel:
    """Представляет активный канал (звонок) в FreeSWITCH."""
    uuid: str = ""
    direction: str = ""       # inbound / outbound
    created: str = ""
    name: str = ""
    state: str = ""
    cid_name: str = ""        # Имя вызывающего абонента (Caller ID Name)
    cid_num: str = ""         # Номер вызывающего абонента (Caller ID Number)
    dest: str = ""            # Номер назначения
    ip_addr: str = ""         # IP-адрес
    application: str = ""     # Текущее приложение (playback, park, etc.)
    read_codec: str = ""
    write_codec: str = ""

    def __str__(self) -> str:
        return (f"Channel(uuid={self.uuid}, dir={self.direction}, "
                f"from={self.cid_num} \"{self.cid_name}\", "
                f"to={self.dest}, app={self.application}, state={self.state})")


@dataclass
class FreeSwitchError(Exception):
    """Ошибка выполнения команды FreeSWITCH."""
    command: str = ""
    message: str = ""

    def __str__(self) -> str:
        return f"FreeSWITCH Error [{self.command}]: {self.message}"


# ─── Основной класс ──────────────────────────────────────────────────────────

class FreeSwitchManager:
    """
    Менеджер управления FreeSWITCH через SSH + fs_cli (pexpect).

    Подключается по SSH к серверу FreeSWITCH, запускает fs_cli в интерактивном
    режиме и предоставляет высокоуровневый API для управления звонками.

    Пример:
        mgr = FreeSwitchManager()
        mgr.connect()

        channels = mgr.get_active_channels()
        for ch in channels:
            if ch.direction == "inbound":
                mgr.broadcast_audio(ch.uuid, "ivr/ivr-hello.wav")
    """

    # Регулярное выражение для парсинга вывода "show channels" (формат с разделителями)
    _CHANNEL_PATTERN = re.compile(
        r"^(?P<uuid>[0-9a-f-]+)\|"
        r"(?P<direction>\w+)\|"
        r"(?P<created>[^|]*)\|"
        r"(?P<name>[^|]*)\|"
        r"(?P<state>[^|]*)\|"
        r"(?P<cid_name>[^|]*)\|"
        r"(?P<cid_num>[^|]*)\|"
        r"(?P<ip_addr>[^|]*)\|"
        r"(?P<dest>[^|]*)\|"
        r"(?P<application>[^|]*)\|"
        r"(?P<app_data>[^|]*)\|"
        r"(?P<dialplan>[^|]*)\|"
        r"(?P<context>[^|]*)\|"
        r"(?P<read_codec>[^|]*)\|"
        r"(?P<read_rate>[^|]*)\|"
        r"(?P<write_codec>[^|]*)\|"
        r"(?P<write_rate>[^|]*)",
        re.IGNORECASE
    )

    def __init__(
        self,
        ssh_host: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_user: Optional[str] = None,
        ssh_password: Optional[str] = None,
        ssh_key_file: Optional[str] = None,
        fs_cli_path: Optional[str] = None,
        fs_host: Optional[str] = None,
        fs_port: Optional[int] = None,
        fs_password: Optional[str] = None,
        connect_timeout: Optional[int] = None,
        command_timeout: Optional[int] = None,
        poll_interval: Optional[float] = None,
        reconnect_delay: Optional[int] = None,
        max_reconnect_attempts: Optional[int] = None,
        record_dir: Optional[str] = None,
    ):
        """
        Инициализация менеджера. Все параметры необязательны —
        значения по умолчанию берутся из config.py.

        Можно переопределить любой параметр явно:
            mgr = FreeSwitchManager(ssh_host="10.0.0.1", ssh_password="secret")
        """
        # SSH
        self.ssh_host = ssh_host or config.SSH_HOST
        self.ssh_port = ssh_port or config.SSH_PORT
        self.ssh_user = ssh_user or config.SSH_USER
        self.ssh_password = ssh_password or config.SSH_PASSWORD
        self.ssh_key_file = ssh_key_file or config.SSH_KEY_FILE

        # FreeSWITCH
        self.fs_cli_path = fs_cli_path or config.FS_CLI_PATH
        self.fs_host = fs_host or config.FS_HOST
        self.fs_port = fs_port or config.FS_PORT
        self.fs_password = fs_password or config.FS_PASSWORD

        # Таймауты
        self.connect_timeout = connect_timeout or config.CONNECT_TIMEOUT
        self.command_timeout = command_timeout or config.COMMAND_TIMEOUT
        self.poll_interval = poll_interval or config.POLL_INTERVAL
        self.reconnect_delay = reconnect_delay or config.RECONNECT_DELAY
        self.max_reconnect_attempts = max_reconnect_attempts or config.MAX_RECONNECT_ATTEMPTS

        # Пути
        self.record_dir = record_dir or config.RECORD_DIR

        # Внутреннее состояние
        self._session: Optional[pexpect.spawn] = None
        self._connected: bool = False
        self._known_uuids: set = set()          # UUID уже обработанных каналов
        self._callbacks: Dict[str, List[Callable]] = {
            "new_call": [],
            "call_end": [],
            "error": [],
        }

    # ─── Подключение / отключение ────────────────────────────────────

    def connect(self) -> None:
        """
        Подключается к серверу FreeSWITCH по SSH и запускает fs_cli.

        Raises:
            FreeSwitchError: если подключение не удалось
        """
        logger.info("Подключение к %s@%s:%d ...", self.ssh_user, self.ssh_host, self.ssh_port)

        try:
            # Формируем команду SSH
            ssh_cmd = f"ssh -o StrictHostKeyChecking=no -p {self.ssh_port}"

            if self.ssh_key_file:
                ssh_cmd += f" -i {self.ssh_key_file}"
            else:
                ssh_cmd += f" {self.ssh_user}@{self.ssh_host}"

            # Запускаем SSH-сессию
            self._session = pexpect.spawn(
                ssh_cmd,
                timeout=self.connect_timeout,
                encoding="utf-8",
                codec_errors="replace",
            )

            # Авторизация по паролю (если не используется ключ)
            if not self.ssh_key_file:
                self._session.expect(["password:", pexpect.TIMEOUT, pexpect.EOF])
                if self._session.match_index == 0:
                    self._session.sendline(self.ssh_password)
                else:
                    raise FreeSwitchError(
                        command="ssh",
                        message="Не удалось получить приглашение ввода пароля SSH"
                    )

            # Ждём приглашение оболочки
            self._session.expect(r"[\$#]\s*$", timeout=self.connect_timeout)

            # Создаём директорию для записей на сервере
            self._session.sendline(f"mkdir -p {self.record_dir}")
            self._session.expect(r"[\$#]\s*$", timeout=self.command_timeout)

            # Запускаем fs_cli
            fs_cmd = (
                f"{self.fs_cli_path} "
                f"-H {self.fs_host} "
                f"-P {self.fs_port} "
                f"-p {self.fs_password}"
            )
            logger.info("Запуск fs_cli: %s", fs_cmd)
            self._session.sendline(fs_cmd)

            # Ждём приглашение fs_cli
            self._session.expect(r"freeswitch@", timeout=self.command_timeout)

            self._connected = True
            self._known_uuids = set()
            logger.info("Успешное подключение к FreeSWITCH")

        except pexpect.TIMEOUT:
            self._connected = False
            msg = f"Таймаут подключения к {self.ssh_host}:{self.ssh_port}"
            logger.error(msg)
            raise FreeSwitchError(command="connect", message=msg)
        except pexpect.EOF:
            self._connected = False
            msg = f"SSH-соединение закрыто (EOF). Проверьте учётные данные и доступность сервера."
            logger.error(msg)
            raise FreeSwitchError(command="connect", message=msg)
        except Exception as e:
            self._connected = False
            raise FreeSwitchError(command="connect", message=str(e))

    def disconnect(self) -> None:
        """Закрывает SSH-сессию и fs_cli."""
        if self._session and self._session.isalive():
            logger.info("Закрытие соединения с FreeSWITCH...")
            try:
                self._session.sendline("/exit")
                self._session.sendline("exit")
                self._session.expect(pexpect.EOF, timeout=3)
            except Exception:
                pass
            self._session.close()
        self._connected = False
        self._session = None
        logger.info("Соединение закрыто")

    def is_connected(self) -> bool:
        """Возвращает True, если сессия активна."""
        if not self._connected or not self._session:
            return False
        return self._session.isalive()

    def _ensure_connected(self) -> None:
        """Проверяет подключение, при необходимости переподключается."""
        if not self.is_connected():
            logger.warning("Соединение потеряно, переподключение...")
            self.reconnect()

    def reconnect(self) -> None:
        """
        Переподключается к FreeSWITCH с учётом настроек задержки и лимита попыток.

        Raises:
            FreeSwitchError: если переподключение не удалось
        """
        attempts = 0
        max_attempts = self.max_reconnect_attempts if self.max_reconnect_attempts > 0 else float("inf")

        while attempts < max_attempts:
            attempts += 1
            logger.info("Попытка переподключения %d/%s ...", attempts,
                        max_attempts if max_attempts != float("inf") else "∞")
            try:
                self.disconnect()
                time.sleep(self.reconnect_delay)
                self.connect()
                logger.info("Переподключение успешно")
                return
            except FreeSwitchError as e:
                logger.warning("Попытка %d не удалась: %s", attempts, e)
                self._fire_callback("error", error=e)

        msg = f"Не удалось переподключиться за {attempts} попыток"
        logger.error(msg)
        raise FreeSwitchError(command="reconnect", message=msg)

    # ─── Выполнение команд ───────────────────────────────────────────

    def execute(self, command: str, timeout: Optional[float] = None) -> str:
        """
        Выполняет произвольную команду в fs_cli и возвращает результат.

        Args:
            command: Команда FreeSWITCH (например "show channels")
            timeout: Таймаут ожидания ответа (по умолчанию из конфига)

        Returns:
            Строка с выводом команды

        Raises:
            FreeSwitchError: если команда не выполнена или таймаут
        """
        self._ensure_connected()

        timeout = timeout or self.command_timeout
        logger.debug("Выполнение команды: %s", command)

        try:
            self._session.sendline(command)

            # Читаем вывод до следующего приглашения fs_cli
            # Приглашение обычно выглядит как "freeswitch@hostname>"
            self._session.expect(r"freeswitch@", timeout=timeout)

            output = self._session.before
            if output is None:
                output = ""

            # Очищаем от управляющих символов и лишних пробелов
            output = re.sub(r"\x1b\[[0-9;]*m", "", output)  # ANSI-цвета
            output = output.strip()

            logger.debug("Ответ (%d символов): %.200s...", len(output), output)
            return output

        except pexpect.TIMEOUT:
            msg = f"Таймаут выполнения команды: {command}"
            logger.error(msg)
            raise FreeSwitchError(command=command, message=msg)
        except Exception as e:
            raise FreeSwitchError(command=command, message=str(e))

    # ─── Парсинг каналов ─────────────────────────────────────────────

    def get_active_channels(self) -> List[Channel]:
        """
        Получает список всех активных каналов (звонков) из FreeSWITCH.

        Выполняет команду "show channels" и парсит результат,
        извлекая UUID, направление, Caller ID, и другую информацию.

        Returns:
            Список объектов Channel для каждого активного канала

        Raises:
            FreeSwitchError: если не удалось получить список каналов
        """
        output = self.execute("show channels")
        channels = self._parse_channels(output)

        logger.info("Найдено %d активных каналов", len(channels))
        for ch in channels:
            logger.debug("  %s", ch)

        return channels

    def _parse_channels(self, output: str) -> List[Channel]:
        """
        Парсит вывод команды "show channels" в список объектов Channel.

        FreeSWITCH может выводить данные в двух форматах:
          1) CSV-подобный (через |) — при "show channels as delim |"
          2) Форматированная таблица — при "show channels"

        Метод автоматически определяет формат и извлекает данные.
        """
        channels: List[Channel] = []

        if not output or "0 total" in output.lower():
            return channels

        lines = output.split("\n")
        logger.debug("Парсинг %d строк вывода show channels", len(lines))

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Пропускаем заголовки и разделители
            if any(skip in line.lower() for skip in [
                "uuid", "total", "====", "----", "regex", "count"
            ]):
                continue

            # Попытка 1: CSV-формат через "|" (при "show channels as delim |")
            if "|" in line:
                match = self._CHANNEL_PATTERN.match(line)
                if match:
                    ch = Channel(
                        uuid=match.group("uuid").strip(),
                        direction=match.group("direction").strip().lower(),
                        created=match.group("created").strip(),
                        name=match.group("name").strip(),
                        state=match.group("state").strip(),
                        cid_name=match.group("cid_name").strip(),
                        cid_num=match.group("cid_num").strip(),
                        ip_addr=match.group("ip_addr").strip(),
                        dest=match.group("dest").strip(),
                        application=match.group("application").strip(),
                        read_codec=match.group("read_codec").strip(),
                        write_codec=match.group("write_codec").strip(),
                    )
                    channels.append(ch)
                    continue

            # Попытка 2: Форматированная таблица (колонки выровнены пробелами)
            # Пример строки:
            # a3b2c1d4-...  inbound  sofia/internal/...  CS_EXECUTE  +79161234567  ...
            # Используем UUID как якорь — он имеет формат xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            uuid_match = re.match(
                r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s+(.+)",
                line,
                re.IGNORECASE
            )
            if uuid_match:
                ch = self._parse_table_row(uuid_match.group(1), uuid_match.group(2))
                if ch:
                    channels.append(ch)

        return channels

    def _parse_table_row(self, uuid: str, rest: str) -> Optional[Channel]:
        """
        Парсит одну строку форматированной таблицы show channels.
        Поля разделены пробелами, но некоторые (например, sofia/...) содержат пробелы внутри.
        Используем эвристику: после UUID идёт direction, затем name (до пробела+большой буквы или
        до колонки state).
        """
        parts = rest.split()
        if len(parts) < 6:
            return None

        try:
            direction = parts[0].lower()

            # Имя канала может содержать пробелы, но обычно это один токен
            name = parts[1]

            # Ищем позицию состояния — стандартные состояния FreeSWITCH
            state_idx = 2
            known_states = {"CS_NEW", "CS_INIT", "CS_ROUTING", "CS_EXECUTE",
                            "CS_HANGUP", "CS_REPORTING", "CS_RING", "CS_DESTROY",
                            "CS_CONSUME_MEDIA", "CS_EXCHANGE_MEDIA", "CS_SOFT_EXECUTE"}
            for i, p in enumerate(parts[2:], start=2):
                if p in known_states:
                    state_idx = i
                    break

            state = parts[state_idx] if state_idx < len(parts) else "UNKNOWN"

            # После state обычно идут cid_name, cid_num, dest, ip, application...
            remaining = parts[state_idx + 1:]

            cid_name = ""
            cid_num = ""
            dest = ""
            ip_addr = ""
            application = ""

            if remaining:
                cid_num = remaining[0] if remaining else ""
            if len(remaining) > 1:
                dest = remaining[1]
            if len(remaining) > 2:
                application = remaining[2]

            return Channel(
                uuid=uuid,
                direction=direction,
                name=name,
                state=state,
                cid_num=cid_num,
                cid_name=cid_name,
                dest=dest,
                ip_addr=ip_addr,
                application=application,
            )
        except (IndexError, ValueError):
            return None

    # ─── Управление звонками ─────────────────────────────────────────

    def broadcast_audio(
        self,
        uuid: str,
        audio_file: str,
        leg: str = "aleg"
    ) -> str:
        """
        Проигрывает аудиофайл указанному звонку (каналу).

        Args:
            uuid: UUID канала FreeSWITCH
            audio_file: Путь к аудиофайлу (относительно звуков FreeSWITCH,
                       например "ivr/ivr-hello.wav" или абсолютный путь)
            leg: Нога звонка — "aleg" (вызывающая сторона) или "bleg"
                 (вызываемая сторона)

        Returns:
            Вывод команды FreeSWITCH

        Raises:
            FreeSwitchError: если команда не выполнена

        Example:
            >>> mgr.broadcast_audio("abc123-def456", "ivr/ivr-hello.wav")
        """
        if not uuid:
            raise ValueError("UUID не может быть пустым")
        if not audio_file:
            raise ValueError("Путь к аудиофайлу не может быть пустым")

        command = f"uuid_broadcast {uuid} {audio_file} {leg}"
        logger.info("Воспроизведение аудио: %s", command)

        output = self.execute(command)
        logger.info("Результат: %s", output)
        return output

    def start_recording(
        self,
        uuid: str,
        filepath: Optional[str] = None
    ) -> str:
        """
        Начинает запись разговора в файл.

        Если filepath не указан, файл создаётся автоматически:
        {RECORD_DIR}/{uuid}_record.wav

        Args:
            uuid: UUID канала FreeSWITCH
            filepath: Полный путь к файлу записи на сервере FreeSWITCH.
                      Если None — используется путь по умолчанию.

        Returns:
            Вывод команды FreeSWITCH

        Raises:
            FreeSwitchError: если команда не выполнена
        """
        if not uuid:
            raise ValueError("UUID не может быть пустым")

        if filepath is None:
            filepath = f"{self.record_dir}/{uuid}_record.wav"

        command = f"uuid_record {uuid} start {filepath}"
        logger.info("Начало записи: %s", command)

        # Убедимся, что директория существует
        record_dir = os.path.dirname(filepath)
        self.execute(f"mkdir -p {record_dir}")

        output = self.execute(command)
        logger.info("Запись начата: %s", filepath)
        return output

    def stop_recording(
        self,
        uuid: str,
        filepath: Optional[str] = None
    ) -> str:
        """
        Останавливает запись разговора.

        Args:
            uuid: UUID канала FreeSWITCH
            filepath: Путь к файлу записи (должен совпадать с путём
                      из start_recording). Если None — используется путь по умолчанию.

        Returns:
            Вывод команды FreeSWITCH

        Raises:
            FreeSwitchError: если команда не выполнена
        """
        if not uuid:
            raise ValueError("UUID не может быть пустым")

        if filepath is None:
            filepath = f"{self.record_dir}/{uuid}_record.wav"

        command = f"uuid_record {uuid} stop {filepath}"
        logger.info("Остановка записи: %s", command)

        output = self.execute(command)
        logger.info("Запись остановлена: %s", filepath)
        return output

    def kill_call(self, uuid: str) -> str:
        """
        Завершает (сбрасывает) звонок.

        Args:
            uuid: UUID канала FreeSWITCH

        Returns:
            Вывод команды FreeSWITCH

        Raises:
            FreeSwitchError: если команда не выполнена
        """
        if not uuid:
            raise ValueError("UUID не может быть пустым")

        command = f"uuid_kill {uuid}"
        logger.info("Завершение звонка: %s", command)

        output = self.execute(command)
        logger.info("Звонок %s завершён", uuid)
        return output

    # ─── Callback-система ────────────────────────────────────────────

    def register_callback(self, event: str, callback: Callable) -> None:
        """
        Регистрирует callback-функцию для события.

        Доступные события:
          - "new_call":     новый входящий звонок обнаружен.
                            Callback получает объект Channel.
          - "call_end":     звонок завершён (UUID больше не в списке каналов).
                            Callback получает UUID (str).
          - "error":        произошла ошибка.
                            Callback получает объект FreeSwitchError.

        Args:
            event: Название события
            callback: Функция для вызова

        Example:
            >>> def on_new_call(channel: Channel):
            ...     print(f"Новый звонок от {channel.cid_num}")
            >>> mgr.register_callback("new_call", on_new_call)
        """
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)
        logger.debug("Зарегистрирован callback для события '%s': %s", event, callback.__name__)

    def unregister_callback(self, event: str, callback: Callable) -> None:
        """Удаляет callback-функцию для указанного события."""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    def _fire_callback(self, event: str, **kwargs) -> None:
        """Вызывает все зарегистрированные callback для события."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(**kwargs)
            except Exception as e:
                logger.error("Ошибка в callback '%s' для события '%s': %s",
                             cb.__name__, event, e)

    # ─── Цикл мониторинга ────────────────────────────────────────────

    def monitor_loop(
        self,
        poll_interval: Optional[float] = None,
        inbound_only: bool = True,
    ) -> None:
        """
        Запускает бесконечный цикл мониторинга входящих звонков.

        Периодически опрашивает FreeSWITCH через "show channels" и вызывает
        соответствующие callback при обнаружении новых или завершённых звонков.

        Цикл автоматически восстанавливает соединение при обрыве.

        Args:
            poll_interval: Интервал опроса в секундах (по умолчанию из конфига)
            inbound_only: Обрабатывать только входящие звонки (direction == "inbound")

        Example:
            >>> mgr.connect()
            >>> def on_call(ch):
            ...     mgr.broadcast_audio(ch.uuid, "ivr/ivr-hello.wav")
            >>> mgr.register_callback("new_call", on_call)
            >>> mgr.monitor_loop()  # Блокирует поток
        """
        interval = poll_interval or self.poll_interval
        logger.info("Запуск цикла мониторинга (интервал: %.1f сек, inbound_only: %s)",
                    interval, inbound_only)

        try:
            while True:
                try:
                    self._ensure_connected()
                    channels = self.get_active_channels()

                    current_uuids: set = set()

                    for ch in channels:
                        current_uuids.add(ch.uuid)

                        # Пропускаем исходящие, если включён фильтр
                        if inbound_only and ch.direction not in ("inbound", "inbound-local"):
                            continue

                        # Новый звонок?
                        if ch.uuid not in self._known_uuids:
                            logger.info("🔔 Новый звонок: %s", ch)
                            self._fire_callback("new_call", channel=ch)

                    # Определяем завершённые звонки
                    ended_uuids = self._known_uuids - current_uuids
                    for uuid in ended_uuids:
                        logger.info("🔚 Звонок завершён: %s", uuid)
                        self._fire_callback("call_end", uuid=uuid)

                    self._known_uuids = current_uuids

                except FreeSwitchError as e:
                    logger.error("Ошибка мониторинга: %s", e)
                    self._fire_callback("error", error=e)

                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Мониторинг остановлен пользователем (Ctrl+C)")
        finally:
            self.disconnect()

    # ─── Утилиты ─────────────────────────────────────────────────────

    def get_inbound_channels(self) -> List[Channel]:
        """Возвращает только входящие каналы (inbound)."""
        return [ch for ch in self.get_active_channels()
                if ch.direction in ("inbound", "inbound-local")]

    def get_channel_by_uuid(self, uuid: str) -> Optional[Channel]:
        """Ищет канал по UUID."""
        for ch in self.get_active_channels():
            if ch.uuid == uuid:
                return ch
        return None

    def get_channel_by_cid(self, cid_num: str) -> Optional[Channel]:
        """Ищет канал по номеру вызывающего (CID Number)."""
        for ch in self.get_active_channels():
            if ch.cid_num == cid_num:
                return ch
        return None

    def play_and_record(
        self,
        uuid: str,
        audio_files: Optional[List[str]] = None,
        record: bool = True,
    ) -> None:
        """
        Удобный метод: проигрывает список аудиофайлов и параллельно записывает разговор.

        Args:
            uuid: UUID канала
            audio_files: Список путей к аудиофайлам для последовательного воспроизведения.
                        Если None — воспроизводится приветствие по умолчанию.
            record: Записывать ли разговор
        """
        if audio_files is None:
            audio_files = [config.DEFAULT_GREETING]

        # Начинаем запись (если нужно)
        if record:
            self.start_recording(uuid)

        # Проигрываем файлы
        for audio in audio_files:
            try:
                self.broadcast_audio(uuid, audio)
            except FreeSwitchError as e:
                logger.warning("Не удалось воспроизвести %s: %s", audio, e)

    def __repr__(self) -> str:
        status = "подключён" if self.is_connected() else "отключён"
        return (f"FreeSwitchManager(host={self.ssh_host}, "
                f"status={status}, "
                f"known_calls={len(self._known_uuids)})")

    def __enter__(self):
        """Поддержка контекстного менеджера (with ... as ...)."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Автоматическое отключение при выходе из контекста."""
        self.disconnect()
