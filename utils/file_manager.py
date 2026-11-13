"""Per-task temporary directories and cleanup."""
from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path

from utils.validators import safe_join

logger = logging.getLogger(__name__)


class TaskWorkspace:
    """An isolated directory for one task. Input is always stored under a fixed name,
    so user-supplied file names never reach the file system or external programs."""

    def __init__(self, root: Path, task_key: str | None = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.key = task_key or uuid.uuid4().hex
        self.path = safe_join(self.root, f"task_{self.key}")
        self.path.mkdir(parents=False, exist_ok=False)

    def input_path(self, extension: str, index: int = 0) -> Path:
        suffix = f".{extension}" if extension else ""
        return safe_join(self.path, f"input_{index}{suffix}")

    def output_path(self, extension: str, name: str = "output") -> Path:
        suffix = f".{extension}" if extension else ""
        return safe_join(self.path, f"{name}{suffix}")

    def subdir(self, name: str) -> Path:
        path = safe_join(self.path, name)
        path.mkdir(exist_ok=True)
        return path

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
        if self.path.exists():
            logger.warning("Could not fully remove %s", self.path)

    def __enter__(self) -> "TaskWorkspace":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cleanup()


def cleanup_stale_workspaces(root: Path, max_age_sec: int) -> int:
    """Remove task directories left behind by crashes. Returns the number removed."""
    if not root.exists():
        return 0
    removed = 0
    deadline = time.time() - max_age_sec
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.startswith("task_") and entry.stat().st_mtime < deadline:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    if removed:
        logger.info("Removed %d stale task directories", removed)
    return removed
