"""Application configuration loaded from environment variables / .env."""
from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Limits of the cloud Bot API (https://core.telegram.org/bots/api#getfile, #senddocument).
CLOUD_DOWNLOAD_LIMIT_MB = 20
CLOUD_UPLOAD_LIMIT_MB = 50
# Limits of a self-hosted Bot API server (https://github.com/tdlib/telegram-bot-api).
LOCAL_API_LIMIT_MB = 2000


class ConfigError(RuntimeError):
    """Raised when the configuration is invalid."""


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


def _find_executable(env_name: str, names: list[str], globs: list[str] = ()) -> str | None:
    """Find an external program: explicit env var, then PATH, then typical install dirs."""
    explicit = os.getenv(env_name, "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() else None
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for pattern in globs:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None


def _normalize_db_url(url: str) -> str:
    """Turn sqlite:///relative.db into an absolute async URL for SQLAlchemy."""
    if url.startswith("sqlite+aiosqlite://"):
        return url
    if url.startswith("sqlite:///"):
        raw_path = url[len("sqlite:///"):]
        if raw_path == ":memory:":
            return "sqlite+aiosqlite:///:memory:"
        return "sqlite+aiosqlite:///" + _resolve_path(raw_path).as_posix()
    raise ConfigError("Only SQLite DATABASE_URL values (sqlite:///...) are supported in this version")


@dataclass(frozen=True)
class ExternalTools:
    ffmpeg: str | None
    ffprobe: str | None
    soffice: str | None
    ghostscript: str | None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    max_file_size_mb: int
    temp_dir: Path
    log_level: str
    log_dir: Path
    max_concurrent_tasks: int
    max_tasks_per_user: int
    task_timeout_sec: int
    telegram_api_url: str | None
    tools: ExternalTools

    @property
    def uses_local_api(self) -> bool:
        return bool(self.telegram_api_url)

    @property
    def download_limit_bytes(self) -> int:
        """Max size of a file the bot accepts (min of the user setting and the Bot API limit)."""
        api_limit = LOCAL_API_LIMIT_MB if self.uses_local_api else CLOUD_DOWNLOAD_LIMIT_MB
        return min(self.max_file_size_mb, api_limit) * 1024 * 1024

    @property
    def upload_limit_bytes(self) -> int:
        api_limit = LOCAL_API_LIMIT_MB if self.uses_local_api else CLOUD_UPLOAD_LIMIT_MB
        return api_limit * 1024 * 1024


def load_settings(env_file: str | os.PathLike | None = None, require_token: bool = True) -> Settings:
    load_dotenv(env_file or BASE_DIR / ".env", override=False)

    token = os.getenv("BOT_TOKEN", "").strip()
    if require_token and not token:
        raise ConfigError(
            "BOT_TOKEN is not set. Copy .env.example to .env and put the token from @BotFather there."
        )

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(f"LOG_LEVEL has an unknown value: {log_level}")

    tools = ExternalTools(
        ffmpeg=_find_executable("FFMPEG_PATH", ["ffmpeg"]),
        ffprobe=_find_executable("FFPROBE_PATH", ["ffprobe"]),
        soffice=_find_executable(
            "SOFFICE_PATH",
            ["soffice", "libreoffice"],
            [r"C:\Program Files\LibreOffice\program\soffice.exe",
             r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"],
        ),
        ghostscript=_find_executable(
            "GHOSTSCRIPT_PATH",
            ["gs", "gswin64c", "gswin32c"],
            [r"C:\Program Files\gs\gs*\bin\gswin64c.exe"],
        ),
    )

    temp_dir = _resolve_path(os.getenv("TEMP_DIR", "./temp").strip() or "./temp")
    return Settings(
        bot_token=token,
        database_url=_normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///formatbot.db").strip()),
        max_file_size_mb=_env_int("MAX_FILE_SIZE_MB", 20, 1, LOCAL_API_LIMIT_MB),
        temp_dir=temp_dir,
        log_level=log_level,
        log_dir=_resolve_path(os.getenv("LOG_DIR", "./logs").strip() or "./logs"),
        max_concurrent_tasks=_env_int("MAX_CONCURRENT_TASKS", 2, 1, 32),
        max_tasks_per_user=_env_int("MAX_TASKS_PER_USER", 2, 1, 10),
        task_timeout_sec=_env_int("TASK_TIMEOUT_SEC", 600, 10, 7200),
        telegram_api_url=os.getenv("TELEGRAM_API_URL", "").strip().rstrip("/") or None,
        tools=tools,
    )
