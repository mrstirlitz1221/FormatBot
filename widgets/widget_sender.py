"""Sends a screen as a widget (sendWidget) or, as a fallback, as a message with an inline keyboard,
and records the authoritative state of that message in ``widget_sessions``."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message

from api.widget_api import EditMessageWidgetData, SendWidget, WidgetLimitError
from context import AppContext
from database import repositories as repo
from database.models import User
from utils.i18n import t
from widgets.widget_state import dump
from widgets.widget_templates import get_widget_html

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


@dataclass
class Screen:
    widget_type: str                         # template name
    chat_data: dict[str, Any]                # widget chat state
    caption: str                             # caption under the widget (plain text)
    classic_text: str                        # HTML text for the fallback message
    classic_kb: InlineKeyboardMarkup | None  # fallback keyboard
    session_state: dict[str, Any] = field(default_factory=dict)  # server-side only
    title: str = ""                          # [[=title]] for templates that use it


async def send_screen(bot: Bot, app: AppContext, user: User, chat_id: int, screen: Screen) -> tuple[Message, bool]:
    """Send a screen. Returns (message, is_widget)."""
    lang = user.language
    message: Message | None = None
    is_widget = False

    if user.ui_mode == "widget":
        try:
            html = get_widget_html(screen.widget_type, lang, screen.title)
            message = await bot(SendWidget(
                chat_id=chat_id,
                html=html,
                chat_data=dump(screen.chat_data),
                caption=screen.caption[:CAPTION_LIMIT],
                allow_queries=True,
            ))
            is_widget = True
        except (TelegramBadRequest, WidgetLimitError, ValueError) as exc:
            logger.warning("sendWidget(%s) failed, falling back to keyboard: %s", screen.widget_type, exc)
            await bot.send_message(chat_id, t(lang, "widget_failed"))

    if message is None:
        message = await bot.send_message(chat_id, screen.classic_text, reply_markup=screen.classic_kb)

    async with app.db.session() as session:
        await repo.add_widget_session(
            session, user_id=user.id, chat_id=chat_id, message_id=message.message_id,
            widget_type=screen.widget_type, state=screen.session_state, is_widget=is_widget,
        )
        await session.commit()
    return message, is_widget


async def edit_widget_state(bot: Bot, chat_id: int, message_id: int, chat_data: dict[str, Any]) -> bool:
    """Change a widget's chat state. 'message is not modified' counts as success."""
    for attempt in range(3):
        try:
            await bot(EditMessageWidgetData(chat_id=chat_id, message_id=message_id, chat_data=dump(chat_data)))
            return True
        except TelegramRetryAfter as exc:
            if attempt == 2:
                break
            await asyncio.sleep(min(exc.retry_after, 10))
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return True
            logger.warning("editMessageWidgetData failed: %s", exc)
            return False
        except TelegramAPIError as exc:
            logger.warning("editMessageWidgetData failed: %s", exc)
            return False
    return False


async def edit_classic(bot: Bot, chat_id: int, message_id: int, text: str,
                       keyboard: InlineKeyboardMarkup | None) -> bool:
    try:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        return True
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        logger.warning("edit_message_text failed: %s", exc)
        return False
    except TelegramAPIError as exc:
        logger.warning("edit_message_text failed: %s", exc)
        return False
