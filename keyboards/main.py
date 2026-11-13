"""Main menu, settings and history keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup

from utils.i18n import t

# Session-bound actions (same strings as widget requests) are prefixed with "u:".
UI_PREFIX = "u:"


def ui(data: str) -> str:
    value = UI_PREFIX + data
    if len(value.encode("utf-8")) > 64:
        raise ValueError("callback data exceeds 64 bytes")
    return value


def main_menu_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🔄 " + t(lang, "m_cv"), callback_data=ui("cv")),
         Btn(text="🗜 " + t(lang, "m_cz"), callback_data=ui("cz"))],
        [Btn(text="📄 " + t(lang, "m_pt"), callback_data=ui("pt")),
         Btn(text="🖼 " + t(lang, "m_it"), callback_data=ui("it"))],
        [Btn(text=t(lang, "m_hi"), callback_data=ui("hi")),
         Btn(text=t(lang, "m_se"), callback_data=ui("se")),
         Btn(text=t(lang, "m_ab"), callback_data=ui("ab"))],
    ])


def switch_ui_kb(lang: str, to_classic: bool) -> InlineKeyboardMarkup:
    if to_classic:
        return InlineKeyboardMarkup(inline_keyboard=[[Btn(text=t(lang, "btn_classic"), callback_data="s:ui:classic")]])
    return InlineKeyboardMarkup(inline_keyboard=[[Btn(text=t(lang, "btn_widgets"), callback_data="s:ui:widget")]])


QUALITY_STEPS = (95, 85, 75, 60, 45)
MODE_ORDER = ("mq", "bal", "max")


def settings_kb(lang: str, quality: int, mode: str, notifications: bool, ui_mode: str) -> InlineKeyboardMarkup:
    on_off = t(lang, "on") if notifications else t(lang, "off")
    ui_label = t(lang, "ui_widget") if ui_mode == "widget" else t(lang, "ui_classic")
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🇷🇺 Русский" + (" ✓" if lang == "ru" else ""), callback_data="s:lang:ru"),
         Btn(text="🇬🇧 English" + (" ✓" if lang == "en" else ""), callback_data="s:lang:en")],
        [Btn(text=t(lang, "s_quality", q=quality), callback_data="s:q")],
        [Btn(text=t(lang, "s_mode", mode=t(lang, "cz_" + mode)), callback_data="s:mode")],
        [Btn(text=t(lang, "s_notif", v=on_off), callback_data="s:notif")],
        [Btn(text=t(lang, "s_ui", v=ui_label), callback_data="s:ui:toggle")],
        [Btn(text=t(lang, "s_clear"), callback_data="s:clear")],
    ])


def confirm_clear_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        Btn(text=t(lang, "s_clear_yes"), callback_data="s:clear:yes"),
        Btn(text=t(lang, "s_clear_no"), callback_data="s:clear:no"),
    ]])


def history_kb(lang: str, page: int, pages: int) -> InlineKeyboardMarkup | None:
    if pages <= 1:
        return None
    row = []
    if page > 0:
        row.append(Btn(text=t(lang, "btn_prev"), callback_data=f"h:{page - 1}"))
    row.append(Btn(text=f"{page + 1}/{pages}", callback_data="h:noop"))
    if page < pages - 1:
        row.append(Btn(text=t(lang, "btn_next"), callback_data=f"h:{page + 1}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])
