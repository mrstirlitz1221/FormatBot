"""Classic keyboards for convert / compress / tools screens."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup

from keyboards.main import ui
from services.operations import CompressSpec, ToolSpec
from utils.i18n import t


def _rows(buttons: list[Btn], per_row: int) -> list[list[Btn]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def convert_kb(targets: list[str], lossy: set[str], quality: int) -> InlineKeyboardMarkup:
    buttons = [
        Btn(text=fmt.upper(), callback_data=ui(f"go:{fmt}:{quality}" if fmt in lossy else f"go:{fmt}"))
        for fmt in targets
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 4))


CUSTOM_QUALITIES = (90, 70, 50, 30)


def compress_kb(spec: CompressSpec, lang: str) -> InlineKeyboardMarkup:
    rows = [
        [Btn(text=f"{mode.label} — {mode.description}", callback_data=ui(f"go:{mode.id}"))]
        for mode in spec.modes if mode.id != "cus"
    ]
    if spec.custom:
        rows.append([
            Btn(text=f"{t(lang, 'q_t')} {q}", callback_data=ui(f"go:cus:{q}:o")) for q in CUSTOM_QUALITIES
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tools_kb(tools: list[ToolSpec]) -> InlineKeyboardMarkup:
    rows: list[list[Btn]] = []
    for tool in tools:
        if not tool.options:
            rows.append([Btn(text=tool.label, callback_data=ui(f"t:{tool.id}"))])
            continue
        option_buttons = [
            Btn(text=f"{tool.label}: {label}" if i == 0 else label, callback_data=ui(f"t:{tool.id}:{opt}"))
            for i, (opt, label) in enumerate(tool.options)
        ]
        rows.extend(_rows(option_buttons, 3))
    return InlineKeyboardMarkup(inline_keyboard=rows)
