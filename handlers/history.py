"""/history with pagination."""
from __future__ import annotations

import html
import math

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from context import AppContext
from database import repositories as repo
from database.models import Conversion, User
from keyboards.main import history_kb
from utils.i18n import t
from utils.size_formatter import format_size

PAGE_SIZE = 5


def _row(item: Conversion, lang: str) -> str:
    if item.operation_type.startswith("tool:"):
        op = t(lang, "op_tool")
    else:
        op = t(lang, f"op_{item.operation_type}") if item.operation_type in {"convert", "compress"} \
            else item.operation_type
    sizes = format_size(item.original_size, lang)
    if item.output_size is not None:
        sizes += f" → {format_size(item.output_size, lang)}"
        if item.operation_type == "compress" and item.original_size:
            pct = round((item.original_size - item.output_size) / item.original_size * 100, 1)
            sizes += f" ({'−' if pct >= 0 else '+'}{abs(pct)}%)"
    return t(lang, "hist_row", icon=t(lang, f"st_{item.status}"), op=op,
             date=f"{item.created_at:%d.%m.%Y %H:%M} UTC",
             src=html.escape(item.original_filename),
             dst=html.escape(item.output_filename or (item.output_format or "—").upper()),
             sizes=sizes)


async def render_history(app: AppContext, user: User, page: int) -> tuple[str, int]:
    async with app.db.session() as session:
        total = await repo.count_conversions(session, user.id)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(0, min(page, pages - 1))
        items = await repo.list_conversions(session, user.id, page * PAGE_SIZE, PAGE_SIZE)
    lang = user.language
    if not items:
        return t(lang, "hist_empty"), 1
    body = "\n\n".join(_row(item, lang) for item in items)
    return f"{t(lang, 'hist_title', total=total)}\n\n{body}", pages


async def send_history(bot: Bot, app: AppContext, user: User, chat_id: int, page: int = 0) -> None:
    text, pages = await render_history(app, user, page)
    await bot.send_message(chat_id, text, reply_markup=history_kb(user.language, page, pages))


async def cmd_history(message: Message, bot: Bot, app: AppContext, db_user: User) -> None:
    await send_history(bot, app, db_user, message.chat.id)


async def on_history_page(callback: CallbackQuery, app: AppContext, db_user: User) -> None:
    value = callback.data[2:]
    if not value.isdigit() or callback.message is None:
        await callback.answer()
        return
    page = int(value)
    text, pages = await render_history(app, db_user, page)
    await callback.message.edit_text(text, reply_markup=history_kb(db_user.language, page, pages))
    await callback.answer()


def build_router() -> Router:
    router = Router(name="history")
    router.message.register(cmd_history, Command("history"))
    router.callback_query.register(on_history_page, F.data.startswith("h:"))
    return router
