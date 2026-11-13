"""Registers/updates the user for every message and callback and injects ``db_user``."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from context import AppContext
from database import repositories as repo


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = event.from_user if isinstance(event, (Message, CallbackQuery)) else None
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        # Widgets work only in the private chat with the bot; FormatBot is a private-chat bot.
        chat = event.chat if isinstance(event, Message) else (event.message.chat if event.message else None)
        if chat is not None and chat.type != "private":
            return None
        app: AppContext = data["app"]
        async with app.db.session() as session:
            user, created = await repo.get_or_create_user(
                session, tg_user.id, tg_user.username, tg_user.first_name, tg_user.language_code
            )
            await session.commit()
        data["db_user"] = user
        data["is_new_user"] = created
        return await handler(event, data)
