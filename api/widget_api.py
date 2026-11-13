"""Telegram Bot API 10.4 widget support for aiogram.

aiogram 3.31.0 (the latest release) implements Bot API 10.3, which has no widgets.
This module adds the missing pieces without patching aiogram:

* methods (sendWidget, sendSharedWidget, answerWidgetQuery, editMessageWidgetData,
  editSharedWidgetData) as regular aiogram ``TelegramMethod`` subclasses, so they are
  called with ``await bot(SendWidget(...))`` and share the bot session, retries and
  error classes (TelegramBadRequest, TelegramRetryAfter ...);
* the update types ``WidgetQuery`` / ``SharedWidgetQuery``;
* ``WidgetQueryMiddleware`` — an outer update middleware that picks the unknown
  ``widget_query`` / ``shared_widget_query`` fields out of ``Update.model_extra``
  (aiogram keeps unknown fields because its models use ``extra="allow"``).

Names and fields follow https://core.telegram.org/bots/api and
https://core.telegram.org/bots/widgets exactly.
"""
from __future__ import annotations

import logging
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.methods.base import TelegramMethod
from aiogram.types import (
    Chat,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    ReplyParameters,
    TelegramObject,
    Update,
    User,
)
from pydantic import Field

logger = logging.getLogger(__name__)

# Limits from https://core.telegram.org/bots/widgets#limits
WIDGET_HTML_MAX_BYTES = 32768
WIDGET_HTML_MAX_COMPRESSED = 4096
WIDGET_DATA_MAX_BYTES = 1024
WIDGET_QUERY_DATA_MAX_BYTES = 64
WIDGET_ANSWER_MAX_BYTES = 1024
WIDGET_QUERY_ANSWER_TIMEOUT_SEC = 15

WIDGET_UPDATE_TYPES = ("widget_query", "shared_widget_query")


class WidgetLimitError(ValueError):
    """The widget HTML or data breaks a Bot API limit (checked before sending)."""


@dataclass(frozen=True)
class WidgetSize:
    raw: int
    compressed: int

    @property
    def fits(self) -> bool:
        return self.raw <= WIDGET_HTML_MAX_BYTES and self.compressed <= WIDGET_HTML_MAX_COMPRESSED


def measure_widget_html(html: str) -> WidgetSize:
    """Size the way the server counts it: UTF-8 bytes and zlib level 9."""
    raw = html.encode("utf-8")
    return WidgetSize(raw=len(raw), compressed=len(zlib.compress(raw, 9)))


def validate_widget_html(html: str) -> WidgetSize:
    if "\x00" in html:
        raise WidgetLimitError("Widget HTML must not contain NUL characters")
    size = measure_widget_html(html)
    if size.raw == 0 or not size.fits:
        raise WidgetLimitError(
            f"Widget HTML is {size.raw} B raw / {size.compressed} B compressed "
            f"(limits {WIDGET_HTML_MAX_BYTES} / {WIDGET_HTML_MAX_COMPRESSED})"
        )
    return size


def validate_widget_data(data: str | None, name: str = "data") -> None:
    if data is None:
        return
    if "\x00" in data:
        raise WidgetLimitError(f"Widget {name} must not contain NUL characters")
    if len(data.encode("utf-8")) > WIDGET_DATA_MAX_BYTES:
        raise WidgetLimitError(f"Widget {name} exceeds {WIDGET_DATA_MAX_BYTES} bytes")


# --------------------------------------------------------------------------- methods


class SendWidget(TelegramMethod[Message]):
    """https://core.telegram.org/bots/api#sendwidget"""

    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int | str
    html: str
    message_thread_id: int | None = None
    width: int | None = None
    height: int | None = None
    public_data: str | None = None
    chat_data: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    caption_entities: list[MessageEntity] | None = None
    show_caption_above_media: bool | None = None
    allow_queries: bool | None = None
    is_shared: bool | None = None
    disable_notification: bool | None = None
    protect_content: bool | None = None
    allow_paid_broadcast: bool | None = None
    message_effect_id: str | None = None
    reply_parameters: ReplyParameters | None = None
    reply_markup: InlineKeyboardMarkup | None = None


class SendSharedWidget(TelegramMethod[Message]):
    """https://core.telegram.org/bots/api#sendsharedwidget"""

    __returning__ = Message
    __api_method__ = "sendSharedWidget"

    chat_id: int | str
    widget_id: str
    message_thread_id: int | None = None
    chat_data: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    caption_entities: list[MessageEntity] | None = None
    show_caption_above_media: bool | None = None
    disable_notification: bool | None = None
    protect_content: bool | None = None
    allow_paid_broadcast: bool | None = None
    message_effect_id: str | None = None
    reply_parameters: ReplyParameters | None = None
    reply_markup: InlineKeyboardMarkup | None = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    """https://core.telegram.org/bots/api#answerwidgetquery"""

    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: str | None = None


class EditMessageWidgetData(TelegramMethod[bool]):
    """https://core.telegram.org/bots/api#editmessagewidgetdata"""

    __returning__ = bool
    __api_method__ = "editMessageWidgetData"

    chat_id: int | str | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    public_data: str | None = None
    chat_data: str | None = None


class EditSharedWidgetData(TelegramMethod[bool]):
    """https://core.telegram.org/bots/api#editsharedwidgetdata"""

    __returning__ = bool
    __api_method__ = "editSharedWidgetData"

    widget_id: str
    public_data: str
    cache_time: int | None = None


# --------------------------------------------------------------------------- types


class Widget(TelegramObject):
    """https://core.telegram.org/bots/api#widget"""

    html: str
    id: str | None = None
    width: int | None = None
    height: int | None = None
    public_data: str | None = None
    chat_data: str | None = None


class WidgetQuery(TelegramObject):
    """https://core.telegram.org/bots/api#widgetquery"""

    id: str
    from_user: User = Field(..., alias="from")
    data: str = ""
    chat: Chat | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    chat_instance: str | None = None
    chat_type: str | None = None
    type: dict[str, Any] | None = None
    widget_id: str | None = None

    @property
    def query_type(self) -> str:
        return (self.type or {}).get("type", "data")


class SharedWidgetQuery(TelegramObject):
    """https://core.telegram.org/bots/api#sharedwidgetquery"""

    id: str
    from_user: User = Field(..., alias="from")
    widget_id: str
    data: str = ""
    type: dict[str, Any] | None = None


def message_widget(message: Message) -> Widget | None:
    """Return the ``widget`` field of a Message (unknown to aiogram 3.31)."""
    raw = (message.model_extra or {}).get("widget")
    return Widget.model_validate(raw) if raw else None


# --------------------------------------------------------------------------- dispatching

WidgetQueryHandler = Callable[[WidgetQuery, dict[str, Any]], Awaitable[Any]]
SharedWidgetQueryHandler = Callable[[SharedWidgetQuery, dict[str, Any]], Awaitable[Any]]


class WidgetQueryMiddleware(BaseMiddleware):
    """Outer middleware for ``dp.update`` that routes widget updates to plain handlers.

    aiogram cannot route update types it does not know, so the update is intercepted
    before routing. Other updates pass through untouched.
    """

    def __init__(
        self,
        on_widget_query: WidgetQueryHandler,
        on_shared_widget_query: SharedWidgetQueryHandler | None = None,
    ) -> None:
        self.on_widget_query = on_widget_query
        self.on_shared_widget_query = on_shared_widget_query

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        extra = event.model_extra or {}
        bot: Bot | None = data.get("bot")
        context = {"bot": bot} if bot else None

        raw = extra.get("widget_query")
        if raw is not None:
            query = WidgetQuery.model_validate(raw, context=context)
            await self.on_widget_query(query, data)
            return True

        raw = extra.get("shared_widget_query")
        if raw is not None:
            query = SharedWidgetQuery.model_validate(raw, context=context)
            if self.on_shared_widget_query is not None:
                await self.on_shared_widget_query(query, data)
            elif bot is not None:
                # FormatBot never creates shared widgets; answer so the widget does not hang.
                await bot(AnswerWidgetQuery(widget_query_id=query.id))
            return True

        return await handler(event, data)
