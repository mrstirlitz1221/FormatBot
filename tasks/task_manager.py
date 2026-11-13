"""In-process task queue: a global concurrency limit, a per-user limit, timeouts and cancellation.

asyncio is enough for the first version: heavy work runs in worker threads
(``asyncio.to_thread``) or external processes, so the event loop stays free.
The interface (submit / cancel / position) can later be backed by Celery/RQ.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

STATUS_WAITING = "waiting"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


class TaskLimitError(Exception):
    def __init__(self, active: int) -> None:
        super().__init__(f"user already has {active} active tasks")
        self.active = active


@dataclass
class TaskHooks:
    """Callbacks of one task. ``run`` does the work; the others report state."""

    run: Callable[[], Awaitable[None]]
    on_start: Callable[[], Awaitable[None]]
    on_finish: Callable[[str, str | None], Awaitable[None]]  # (status, error code)


@dataclass
class _Entry:
    task_id: int
    user_id: int
    hooks: TaskHooks
    started: bool = False
    future: asyncio.Task | None = field(default=None, repr=False)


class TaskManager:
    def __init__(self, max_concurrent: int, max_per_user: int, timeout_sec: float) -> None:
        self.max_concurrent = max_concurrent
        self.max_per_user = max_per_user
        self.timeout_sec = timeout_sec
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._entries: dict[int, _Entry] = {}

    # ------------------------------------------------------------------ queries

    def active_for_user(self, user_id: int) -> int:
        return sum(1 for e in self._entries.values() if e.user_id == user_id)

    def queue_position(self, task_id: int) -> int:
        """1-based position among waiting tasks, 0 if running or unknown."""
        waiting = [e.task_id for e in self._entries.values() if not e.started]
        return waiting.index(task_id) + 1 if task_id in waiting else 0

    def is_active(self, task_id: int) -> bool:
        return task_id in self._entries

    # ------------------------------------------------------------------ control

    def submit(self, task_id: int, user_id: int, hooks: TaskHooks) -> int:
        """Queue a task. Returns its queue position (0 = a slot is free right now)."""
        active = self.active_for_user(user_id)
        if active >= self.max_per_user:
            raise TaskLimitError(active)
        entry = _Entry(task_id, user_id, hooks)
        self._entries[task_id] = entry
        position = self.queue_position(task_id)
        entry.future = asyncio.create_task(self._runner(entry), name=f"task-{task_id}")
        entry.future.add_done_callback(lambda _future, e=entry: self._on_done(e))
        free_slots = self.max_concurrent - sum(1 for e in self._entries.values() if e.started)
        return 0 if position <= free_slots else position - free_slots

    def cancel(self, task_id: int, user_id: int) -> bool:
        """Cancel a task of this user. Another user's task id is treated as unknown."""
        entry = self._entries.get(task_id)
        if entry is None or entry.user_id != user_id or entry.future is None:
            return False
        entry.future.cancel()
        return True

    async def shutdown(self) -> None:
        futures = [e.future for e in self._entries.values() if e.future]
        for future in futures:
            future.cancel()
        if futures:
            await asyncio.gather(*futures, return_exceptions=True)

    # ------------------------------------------------------------------ internals

    def _on_done(self, entry: _Entry) -> None:
        """A task cancelled before its first step never enters ``_runner``: report it here."""
        if self._entries.pop(entry.task_id, None) is None:
            return
        logger.info("Task %s cancelled before start", entry.task_id)
        asyncio.get_running_loop().create_task(entry.hooks.on_finish(STATUS_CANCELLED, None))

    async def _runner(self, entry: _Entry) -> None:
        loop = asyncio.get_running_loop()
        status, error = STATUS_COMPLETED, None
        started_at = None
        try:
            async with self._semaphore:
                entry.started = True
                started_at = loop.time()
                await entry.hooks.on_start()
                async with asyncio.timeout(self.timeout_sec):
                    await entry.hooks.run()
        except TimeoutError:
            status, error = STATUS_FAILED, "timeout"
        except asyncio.CancelledError:
            status = STATUS_CANCELLED
        except Exception as exc:  # noqa: BLE001 - reported to the user, logged with traceback
            code = getattr(exc, "code", None)
            status, error = STATUS_FAILED, code or "generic"
            if code is None:
                logger.exception("Task %s failed", entry.task_id)
            else:
                logger.info("Task %s failed: %s", entry.task_id, code)
        finally:
            duration = loop.time() - started_at if started_at is not None else 0.0
            logger.info("Task %s %s in %.2fs", entry.task_id, status, duration)
            try:
                await entry.hooks.on_finish(status, error)
            except Exception:  # noqa: BLE001
                logger.exception("on_finish hook of task %s failed", entry.task_id)
            finally:
                # Removed only after the result card is updated, so the per-user limit stays accurate.
                self._entries.pop(entry.task_id, None)
