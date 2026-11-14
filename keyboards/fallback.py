"""Classic keyboards for the file card and task status (used when widgets are off or fail)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup

from keyboards.main import ui
from utils.i18n import t


def file_actions_kb(actions: list[str], lang: str) -> InlineKeyboardMarkup | None:
    labels = {"cv": "🔄 " + t(lang, "a_cv"), "cz": "🗜 " + t(lang, "a_cz"), "tl": "🛠 " + t(lang, "a_tl")}
    buttons = [Btn(text=labels[a], callback_data=ui(a)) for a in actions if a in labels]
    return InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None


def task_kb(status: str, lang: str) -> InlineKeyboardMarkup | None:
    """status: w/p — cancel; d/f/c — repeat and menu."""
    if status in ("w", "p"):
        return InlineKeyboardMarkup(inline_keyboard=[[Btn(text=t(lang, "t_cancel"), callback_data=ui("x"))]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        Btn(text="↻ " + t(lang, "t_rp"), callback_data=ui("rp")),
        Btn(text="☰ " + t(lang, "t_mn"), callback_data=ui("mn")),
    ]])


def collect_kb(lang: str, count: int) -> InlineKeyboardMarkup:
    """Shown while the user sends more files for a multi-file tool."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        Btn(text=t(lang, "btn_col_go", n=count), callback_data="c:go"),
        Btn(text=t(lang, "btn_col_cancel"), callback_data="c:x"),
    ]])
