"""Handles widget_query updates: validate, dispatch to the shared action handler, answer in time."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from api.widget_api import WIDGET_QUERY_ANSWER_TIMEOUT_SEC, AnswerWidgetQuery, SharedWidgetQuery, WidgetQuery
from context import AppContext
from database import repositories as repo
from handlers.actions import ActionRequest, handle_action
from utils.i18n import t
from widgets.widget_state import ActionAnswer

logger = logging.getLogger(__name__)

# Leave a margin for the network round trip of answerWidgetQuery itself.
HANDLER_BUDGET_SEC = WIDGET_QUERY_ANSWER_TIMEOUT_SEC - 3


async def answer_query(bot: Bot, query_id: str, answer: ActionAnswer) -> None:
    try:
        await bot(AnswerWidgetQuery(widget_query_id=query_id, data=answer.widget_data()))
    except TelegramAPIError as exc:
        logger.warning("answerWidgetQuery failed: %s", exc)


async def on_widget_query(query: WidgetQuery, data: dict[str, Any]) -> None:
    bot: Bot = data["bot"]
    app: AppContext = data["app"]
    dispatcher: Dispatcher | None = data.get("dispatcher")

    if query.query_type != "data" or query.chat is None or query.message_id is None \
            or query.chat.type != "private" or query.chat.id != query.from_user.id:
        # FormatBot widgets live only in the private chat with the bot and never use the wallet.
        await answer_query(bot, query.id, ActionAnswer(t("en", "ans_bad"), error=True))
        return

    async with app.db.session() as session:
        user, _ = await repo.get_or_create_user(
            session, query.from_user.id, query.from_user.username, query.from_user.first_name,
            query.from_user.language_code,
        )
        await session.commit()
        lang = user.language

    state = None
    if dispatcher is not None:
        state = FSMContext(storage=dispatcher.storage,
                           key=StorageKey(bot_id=bot.id, chat_id=query.chat.id, user_id=query.from_user.id))

    request = ActionRequest(telegram_user_id=query.from_user.id, chat_id=query.chat.id,
                            message_id=query.message_id, data=query.data)
    logger.debug("widget_query %s from %s: %r", query.id, query.from_user.id, query.data)
    try:
        answer = await asyncio.wait_for(handle_action(bot, app, request, state), timeout=HANDLER_BUDGET_SEC)
    except asyncio.TimeoutError:
        logger.warning("widget_query %r took too long", query.data)
        answer = ActionAnswer(t(lang, "e_fail"), error=True)
    except Exception:  # noqa: BLE001 - the widget must always get an answer
        logger.exception("widget_query %r failed", query.data)
        answer = ActionAnswer(t(lang, "e_fail"), error=True)
    await answer_query(bot, query.id, answer)


async def on_shared_widget_query(query: SharedWidgetQuery, data: dict[str, Any]) -> None:
    # FormatBot does not create shared widgets (production widgets cannot be forwarded anyway).
    await answer_query(data["bot"], query.id, ActionAnswer(t("en", "e_na"), error=True))
