"""Safe execution of external programs (LibreOffice, FFmpeg, Ghostscript).

* arguments are always a list (no shell, no string interpolation);
* user-supplied file names never reach the command line: inputs live under fixed names
  inside the task workspace;
* every run has a timeout; on timeout or task cancellation the whole process tree is killed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_LIMIT = 200_000  # bytes of stdout/stderr kept for diagnostics


class ToolError(Exception):
    """An external program failed. ``code`` maps to an i18n error key."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _kill_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            # soffice.exe starts soffice.bin as a child: kill the whole tree.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(process.pid, 9)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.kill()
    except ProcessLookupError:
        pass


async def run_process(args: list[str], timeout: float, cwd: Path | None = None,
                      env: dict[str, str] | None = None) -> ProcessResult:
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        raise ValueError("arguments must be a non-empty list of strings")
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    logger.debug("exec %s", Path(args[0]).name)
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        _kill_tree(process)
        await process.wait()
        logger.warning("%s timed out after %ss", Path(args[0]).name, timeout)
        raise ToolError("timeout") from exc
    except asyncio.CancelledError:
        _kill_tree(process)
        raise
    return ProcessResult(process.returncode or 0, stdout[-OUTPUT_LIMIT:], stderr[-OUTPUT_LIMIT:])


# ----------------------------------------------------------------------------- configured paths

_tools = None


def set_tools(tools) -> None:  # noqa: ANN001 - config.ExternalTools
    """Called once at startup with the programs found by config.load_settings()."""
    global _tools
    _tools = tools


def soffice_path() -> str | None:
    return getattr(_tools, "soffice", None)


def ffmpeg_path() -> str | None:
    return getattr(_tools, "ffmpeg", None)


def ffprobe_path() -> str | None:
    return getattr(_tools, "ffprobe", None)
