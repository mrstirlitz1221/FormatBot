"""Logging configuration: console + rotating file, with token masking."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


class SecretFilter(logging.Filter):
    """Masks anything that looks like a bot token (e.g. in aiohttp URLs of error messages)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if _TOKEN_RE.search(message):
            record.msg = _TOKEN_RE.sub("<token>", message)
            record.args = ()
        return True


def setup_logging(level: str, log_dir: Path | None) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(SecretFilter())
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "formatbot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(SecretFilter())
        root.addHandler(file_handler)

    # aiogram logs every update at INFO; keep it quieter unless debugging.
    if level != "DEBUG":
        logging.getLogger("aiogram.event").setLevel(logging.WARNING)
