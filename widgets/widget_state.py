"""Builders for the widgets' chat state (chat_data).

Keys are short to stay far below the 1024-byte limit. The JSON shapes here are the
contract with the templates in widgets/templates/*.html.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from api.widget_api import WIDGET_DATA_MAX_BYTES
from services.file_detector import KIND_IMAGE
from services.operations import CompressSpec, FileContext, ToolSpec
from utils.size_formatter import format_duration


@dataclass(frozen=True)
class ActionAnswer:
    """Reply to a widget request / callback query: a short status line for the user."""

    text: str = ""
    error: bool = False

    def widget_data(self) -> str:
        payload: dict[str, Any] = {"m": self.text}
        if self.error:
            payload["e"] = 1
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def dump(data: dict[str, Any]) -> str:
    """Compact JSON that fits the chat state limit (long text fields are shortened)."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) <= WIDGET_DATA_MAX_BYTES:
        return text
    if isinstance(data.get("n"), str) and len(data["n"]) > 24:
        shortened = dict(data, n=_shorten(data["n"], 24))
        return dump(shortened)
    raise ValueError("widget state does not fit 1024 bytes")


def _shorten(name: str, limit: int) -> str:
    if len(name) <= limit:
        return name
    head = limit - 8
    return name[:head] + "…" + name[-7:]


def main_state(processed: int, saved_bytes: int) -> dict[str, Any]:
    return {"n": processed, "s": saved_bytes}


def file_state(file: FileContext, actions: list[str], warning: str = "") -> dict[str, Any]:
    meta = file.meta
    state: dict[str, Any] = {
        "n": _shorten(file.name, 60),
        "e": file.extension.upper(),
        "k": file.kind,
        "z": file.size,
        "a": actions,
    }
    if meta.get("width") and meta.get("height"):
        state["r"] = f"{meta['width']}×{meta['height']}"
        if file.kind == KIND_IMAGE and meta.get("frames", 1) > 1:
            state["r"] += f" · {meta['frames']} fr"
    if meta.get("duration"):
        state["d"] = format_duration(meta["duration"])
    if meta.get("pages"):
        state["p"] = meta["pages"]
    if warning:
        state["w"] = warning[:160]
    return state


def convert_state(file: FileContext, targets: list[str], lossy: set[str], default_quality: int) -> dict[str, Any]:
    return {
        "n": _shorten(file.name, 40),
        "f": file.extension,
        "o": targets,
        "l": sorted(lossy & set(targets)),
        "q": default_quality,
    }


def compress_state(file: FileContext, spec: CompressSpec) -> dict[str, Any]:
    return {
        "n": _shorten(file.name, 40),
        "z": file.size,
        "m": [[m.id, m.label, m.description] for m in spec.modes],
        "d": spec.default_mode,
        "q": spec.default_quality,
        "r": [[r_id, label] for r_id, label in spec.resolutions] if spec.custom else [],
    }


def tools_state(file: FileContext, tools: list[ToolSpec]) -> dict[str, Any]:
    return {
        "n": _shorten(file.name, 40),
        "t": [[tool.id, tool.label, tool.icon, [[o, label] for o, label in tool.options]] for tool in tools],
    }


def task_state(
    status: str,
    operation: str,
    *,
    queue: int = 0,
    progress: int = -1,
    original: int | None = None,
    result: int | None = None,
    seconds: float | None = None,
    output_name: str = "",
    error: str = "",
    is_compression: bool = False,
    details: str = "",
) -> dict[str, Any]:
    """status: w (waiting), p (processing), d (done), f (failed), c (cancelled)."""
    state: dict[str, Any] = {"s": status, "o": operation}
    if status == "w" and queue:
        state["q"] = queue
    if status == "p":
        state["p"] = progress
    if status == "d":
        state.update(a=original, b=result, t=round(seconds or 0, 1), n=_shorten(output_name, 40))
        if is_compression:
            state["c"] = 1
        if details:
            state["x"] = details[:80]
    if status == "f":
        state["e"] = error[:300]
    return state
