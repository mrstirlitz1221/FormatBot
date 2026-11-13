"""Builds every screen of the bot (widget + classic fallback) and keeps task cards up to date."""
from __future__ import annotations

import html
import json
import time
from typing import Any

from aiogram import Bot

from database.models import UploadedFile, User
from keyboards.fallback import file_actions_kb, task_kb
from keyboards.formats import compress_kb, convert_kb, tools_kb
from keyboards.main import main_menu_kb
from services.operations import FileContext, Processor, available_actions, get_processor
from utils.i18n import t
from utils.size_formatter import format_size
from widgets import widget_state as ws
from widgets.widget_sender import Screen, edit_classic, edit_widget_state


def file_context(record: UploadedFile) -> FileContext:
    try:
        meta = json.loads(record.meta or "{}")
    except json.JSONDecodeError:
        meta = {}
    return FileContext(kind=record.kind, extension=record.extension, name=record.file_name,
                       size=record.size, meta=meta)


def kind_label(kind: str, lang: str) -> str:
    return t(lang, f"k_{kind}") if kind in {"image", "document", "audio", "video", "pdf"} else kind


# ----------------------------------------------------------------------------- screens


def main_screen(user: User, processed: int, saved: int) -> Screen:
    lang = user.language
    return Screen(
        widget_type="main",
        chat_data=ws.main_state(processed, saved),
        caption=t(lang, "cap_main"),
        classic_text=t(lang, "menu_text"),
        classic_kb=main_menu_kb(lang),
    )


def file_screen(user: User, record: UploadedFile, warning: str = "") -> Screen:
    lang = user.language
    ctx = file_context(record)
    actions = available_actions(ctx, lang)
    extra = []
    meta = ctx.meta
    if meta.get("width"):
        extra.append(f"{meta['width']}×{meta['height']}")
    if meta.get("pages"):
        extra.append(f"{meta['pages']} {t(lang, 'i_pages').lower()}")
    extra_text = (" · " + " · ".join(extra)) if extra else ""
    text = t(lang, "c_file", name=html.escape(ctx.name), kind=kind_label(ctx.kind, lang),
             ext=ctx.extension.upper(), size=format_size(ctx.size, lang), extra=extra_text)
    if warning:
        text += "\n\n⚠️ " + html.escape(warning)
    if not actions:
        text += "\n\n" + t(lang, "f_none")
    return Screen(
        widget_type="file",
        chat_data=ws.file_state(ctx, actions, warning),
        caption=t(lang, "cap_file", name=ctx.name, size=format_size(ctx.size, lang)),
        classic_text=text,
        classic_kb=file_actions_kb(actions, lang),
        session_state={"f": record.id},
    )


def convert_screen(user: User, record: UploadedFile, processor: Processor) -> Screen:
    lang = user.language
    ctx = file_context(record)
    targets = processor.convert_targets(ctx)
    lossy = processor.lossy_targets()
    return Screen(
        widget_type="convert",
        chat_data=ws.convert_state(ctx, targets, lossy, user.default_quality),
        caption=t(lang, "cap_convert", name=ctx.name),
        classic_text=t(lang, "c_convert", name=html.escape(ctx.name)),
        classic_kb=convert_kb(targets, lossy, user.default_quality),
        session_state={"f": record.id},
    )


def compress_screen(user: User, record: UploadedFile, processor: Processor) -> Screen | None:
    lang = user.language
    ctx = file_context(record)
    spec = processor.compress_spec(ctx, lang, user.default_quality, user.compress_mode)
    if spec is None:
        return None
    return Screen(
        widget_type="compress",
        chat_data=ws.compress_state(ctx, spec),
        caption=t(lang, "cap_compress", name=ctx.name),
        classic_text=t(lang, "c_compress", name=html.escape(ctx.name), size=format_size(ctx.size, lang)),
        classic_kb=compress_kb(spec, lang),
        session_state={"f": record.id},
    )


def tools_screen(user: User, record: UploadedFile, processor: Processor) -> Screen | None:
    lang = user.language
    ctx = file_context(record)
    tools = processor.tools(ctx, lang)
    if not tools:
        return None
    title = t(lang, processor.tools_title_key)
    return Screen(
        widget_type="tools",
        chat_data=ws.tools_state(ctx, tools),
        caption=t(lang, "cap_tools", name=ctx.name),
        classic_text=t(lang, "c_tools", title=title, name=html.escape(ctx.name)),
        classic_kb=tools_kb(tools),
        session_state={"f": record.id},
        title=title,
    )


def screen_for_action(user: User, record: UploadedFile, action: str) -> Screen | None:
    """'cv' / 'cz' / 'tl' -> the matching screen for this file, if the action is supported."""
    processor = get_processor(record.kind)
    if processor is None:
        return None
    if action == "cv":
        return convert_screen(user, record, processor) if processor.convert_targets(file_context(record)) else None
    if action == "cz":
        return compress_screen(user, record, processor)
    if action == "tl":
        return tools_screen(user, record, processor)
    return None


def task_screen(user: User, task_id: int, file_id: int, category: str, operation: str) -> Screen:
    lang = user.language
    state = ws.task_state("w", operation)
    return Screen(
        widget_type="task",
        chat_data=state,
        caption=t(lang, "cap_task", id=task_id, op=operation),
        classic_text=task_text(state, lang, task_id),
        classic_kb=task_kb("w", lang),
        session_state={"task": task_id, "f": file_id, "cat": category},
    )


# ----------------------------------------------------------------------------- task card


_STATUS_ICON = {"w": "⏳", "p": "⚙️", "d": "✅", "f": "⚠️", "c": "⏹"}


def task_text(state: dict[str, Any], lang: str, task_id: int) -> str:
    status = state.get("s", "w")
    lines = [t(lang, f"st_{status}")]
    if status == "w" and state.get("q"):
        lines[0] += f" · #{state['q']}"
    if status == "p" and state.get("p", -1) >= 0:
        lines[0] += f" {state['p']}%"
    if status == "d" and state.get("a"):
        original, result = state["a"], state["b"]
        lines.append(f"{t(lang, 't_orig')}: {format_size(original, lang)}")
        lines.append(f"{t(lang, 't_res')}: {format_size(result, lang)}")
        if state.get("c"):
            pct = round((original - result) / original * 100, 1)
            if result < original:
                lines.append(f"−{pct}% · {t(lang, 't_saved')} {format_size(original - result, lang)}")
            else:
                lines.append(f"+{-pct}% · {t(lang, 't_bigger')}")
        if state.get("x"):
            lines.append(html.escape(state["x"]))
        lines.append(f"⏱ {state.get('t', 0)} {t(lang, 'u_s')}")
    if status == "f" and state.get("e"):
        lines.append(html.escape(state["e"]))
    return t(lang, "c_task", icon=_STATUS_ICON.get(status, ""), id=task_id,
             op=html.escape(state.get("o", "")), status="\n".join(lines))


class TaskView:
    """Updates the task card: widget chat state or the classic message text."""

    PROGRESS_INTERVAL = 2.0  # editMessageWidgetData counts against the bot's message limits

    def __init__(self, bot: Bot, chat_id: int, message_id: int, is_widget: bool, lang: str, task_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.is_widget = is_widget
        self.lang = lang
        self.task_id = task_id
        self._last_progress_update = 0.0

    async def show(self, state: dict[str, Any]) -> None:
        if state.get("s") == "p" and state.get("p", -1) >= 0:
            now = time.monotonic()
            if now - self._last_progress_update < self.PROGRESS_INTERVAL:
                return
            self._last_progress_update = now
        if self.is_widget:
            await edit_widget_state(self.bot, self.chat_id, self.message_id, state)
        else:
            await edit_classic(self.bot, self.chat_id, self.message_id,
                               task_text(state, self.lang, self.task_id), task_kb(state.get("s", "w"), self.lang))
