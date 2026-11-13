"""Task queue: concurrency, per-user limit, cancellation, timeout; workspace cleanup."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tasks.task_manager import TaskHooks, TaskLimitError, TaskManager
from utils.file_manager import TaskWorkspace, cleanup_stale_workspaces


class Recorder:
    def __init__(self, work=None):  # noqa: ANN001
        self.events: list[tuple] = []
        self.work = work or (lambda: asyncio.sleep(0))

    def hooks(self, task_id: int) -> TaskHooks:
        async def run():
            self.events.append(("run", task_id))
            await self.work()

        async def on_start():
            self.events.append(("start", task_id))

        async def on_finish(status, error):  # noqa: ANN001
            self.events.append(("finish", task_id, status, error))

        return TaskHooks(run=run, on_start=on_start, on_finish=on_finish)

    def finished(self) -> dict[int, tuple]:
        return {e[1]: (e[2], e[3]) for e in self.events if e[0] == "finish"}


async def _drain(manager: TaskManager) -> None:
    for _ in range(200):
        if not manager._entries:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("tasks did not finish")


async def test_runs_and_limits_concurrency():
    running, peak = 0, 0

    async def work():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1

    recorder = Recorder(work)
    manager = TaskManager(max_concurrent=2, max_per_user=10, timeout_sec=5)
    for task_id in range(1, 6):
        manager.submit(task_id, user_id=task_id, hooks=recorder.hooks(task_id))
    await _drain(manager)
    assert peak == 2
    assert all(v == ("completed", None) for v in recorder.finished().values())


async def test_per_user_limit():
    manager = TaskManager(max_concurrent=1, max_per_user=1, timeout_sec=5)
    recorder = Recorder(lambda: asyncio.sleep(0.05))
    manager.submit(1, user_id=7, hooks=recorder.hooks(1))
    with pytest.raises(TaskLimitError):
        manager.submit(2, user_id=7, hooks=recorder.hooks(2))
    manager.submit(3, user_id=8, hooks=recorder.hooks(3))  # another user is fine
    await _drain(manager)


async def test_cancel_only_own_task():
    manager = TaskManager(max_concurrent=1, max_per_user=5, timeout_sec=5)
    recorder = Recorder(lambda: asyncio.sleep(10))
    manager.submit(1, user_id=7, hooks=recorder.hooks(1))
    await asyncio.sleep(0.02)
    assert manager.cancel(1, user_id=8) is False   # someone else's task
    assert manager.cancel(1, user_id=7) is True
    await _drain(manager)
    assert recorder.finished()[1] == ("cancelled", None)


async def test_cancel_waiting_task_never_runs():
    manager = TaskManager(max_concurrent=1, max_per_user=5, timeout_sec=5)
    recorder = Recorder(lambda: asyncio.sleep(0.1))
    manager.submit(1, user_id=7, hooks=recorder.hooks(1))
    position = manager.submit(2, user_id=7, hooks=recorder.hooks(2))
    assert position == 1
    manager.cancel(2, user_id=7)
    await _drain(manager)
    assert ("run", 2) not in recorder.events
    assert recorder.finished()[2] == ("cancelled", None)


async def test_timeout_and_errors():
    class Boom(Exception):
        code = "broken_file"

    async def fail():
        raise Boom()

    manager = TaskManager(max_concurrent=2, max_per_user=5, timeout_sec=0.05)
    slow, failing = Recorder(lambda: asyncio.sleep(1)), Recorder(fail)
    manager.submit(1, user_id=1, hooks=slow.hooks(1))
    manager.submit(2, user_id=2, hooks=failing.hooks(2))
    await _drain(manager)
    assert slow.finished()[1] == ("failed", "timeout")
    assert failing.finished()[2] == ("failed", "broken_file")


def test_workspace_is_isolated_and_removed(tmp_path: Path):
    with TaskWorkspace(tmp_path, "t1") as workspace:
        path = workspace.input_path("png")
        path.write_bytes(b"x")
        assert path.parent == workspace.path and path.name == "input_0.png"
    assert not workspace.path.exists()


def test_stale_workspace_cleanup(tmp_path: Path):
    TaskWorkspace(tmp_path, "old")
    (tmp_path / "keep.txt").write_text("x")
    assert cleanup_stale_workspaces(tmp_path, max_age_sec=-1) == 1
    assert (tmp_path / "keep.txt").exists()
