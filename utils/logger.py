# /utils/logger.py
"""Colored console + rotating file logging for JARVIS.

Uses ``rich`` when available for pretty console output and falls back to plain
ANSI colours so the assistant never dies because of a missing dependency.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

try:  # pragma: no cover - purely cosmetic
    from rich.logging import RichHandler

    _HAS_RICH = True
except Exception:  # pragma: no cover
    RichHandler = None  # type: ignore[assignment]
    _HAS_RICH = False


_ANSI = {
    "DEBUG": "\033[38;5;244m",
    "INFO": "\033[38;5;39m",
    "WARNING": "\033[38;5;214m",
    "ERROR": "\033[38;5;196m",
    "CRITICAL": "\033[48;5;196m\033[38;5;231m",
}
_RESET = "\033[0m"

_CONFIGURED = False
_ROOT_NAME = "jarvis"


class _ColorFormatter(logging.Formatter):
    """Minimal ANSI colour formatter used when rich is unavailable."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        color = _ANSI.get(record.levelname, "")
        base = super().format(record)
        if color and sys.stderr.isatty():
            return f"{color}{base}{_RESET}"
        return base


def setup_logging(config: Optional[Dict[str, Any]] = None) -> logging.Logger:
    """Configure the root ``jarvis`` logger.

    Args:
        config: Optional mapping with ``level``, ``file``, ``max_bytes``,
            ``backups``, ``color`` and ``quiet_libraries`` keys.

    Returns:
        The configured root ``jarvis`` logger.
    """
    global _CONFIGURED

    config = dict(config or {})
    level_name = str(config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = config.get("file", "logs/jarvis.log")
    max_bytes = int(config.get("max_bytes", 2_000_000))
    backups = int(config.get("backups", 3))
    use_color = bool(config.get("color", True))

    logger = logging.getLogger(_ROOT_NAME)
    logger.setLevel(level)
    logger.propagate = False

    # Wipe previous handlers so repeated calls stay idempotent.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    # ---- console -----------------------------------------------------------
    if _HAS_RICH and use_color:
        from rich.console import Console as _RichConsole

        console_handler: logging.Handler = RichHandler(
            console=_RichConsole(stderr=True),  # keep stdout clean for piped output
            rich_tracebacks=True,
            show_path=False,
            markup=False,
            log_time_format="%H:%M:%S",
        )
        console_handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        console_handler = logging.StreamHandler(stream=sys.stderr)
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        console_handler.setFormatter(
            _ColorFormatter(fmt, datefmt="%H:%M:%S")
            if use_color
            else logging.Formatter(fmt, datefmt="%H:%M:%S")
        )
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # ---- file --------------------------------------------------------------
    if log_file:
        try:
            path = Path(log_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
                )
            )
            logger.addHandler(file_handler)
        except Exception as exc:  # pragma: no cover - disk issues only
            logger.warning("File logging disabled: %s", exc)

    if config.get("quiet_libraries", True):
        for noisy in (
            "httpx",
            "httpcore",
            "urllib3",
            "chromadb",
            "chromadb.telemetry",
            "faster_whisper",
            "asyncio",
            "PIL",
            "matplotlib",
            "numba",
            "primp",
        ):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
        os.environ.setdefault("CHROMA_TELEMETRY_IMPL", "none")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    _CONFIGURED = True
    return logger


def get_logger(name: str = _ROOT_NAME) -> logging.Logger:
    """Return a namespaced child logger, configuring defaults on first use.

    Args:
        name: Dotted logger name, e.g. ``"core.brain"``.

    Returns:
        A ``logging.Logger`` under the ``jarvis`` namespace.
    """
    if not _CONFIGURED:
        setup_logging()
    if name == _ROOT_NAME or name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
