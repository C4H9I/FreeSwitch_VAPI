"""
Minimal fallback for environments without external loguru package.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


class _LoggerAdapter:
    def __init__(self) -> None:
        self._logger = logging.getLogger("voice-bot")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            self._logger.addHandler(handler)

    def remove(self) -> None:
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)

    def add(self, sink, level="INFO", format=None, colorize=False, rotation=None, retention=None) -> None:
        handler: logging.Handler
        if hasattr(sink, "write"):
            handler = logging.StreamHandler(sink)
        else:
            path = Path(str(sink))
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(getattr(logging, str(level).upper(), logging.INFO))
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
        self._logger.addHandler(handler)

    def debug(self, message: str) -> None:
        self._logger.debug(message)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)

    def exception(self, message: str) -> None:
        self._logger.exception(message)


logger = _LoggerAdapter()
