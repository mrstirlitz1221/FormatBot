"""Objects shared by handlers (passed through aiogram's workflow data as ``app``)."""
from __future__ import annotations

from dataclasses import dataclass

from config import Settings
from database.database import Database
from tasks.task_manager import TaskManager


@dataclass
class AppContext:
    settings: Settings
    db: Database
    tasks: TaskManager
