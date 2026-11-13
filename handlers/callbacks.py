"""Fallback keyboard buttons: the same actions as widget requests, prefixed with 'u:'."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from context import AppContext
from handlers.actions import ActionRequest, handle_action
from keyboards.main import UI_PREFIX


async def on_ui_callback(callback: CallbackQuery, bot: Bot, app: AppContext, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer()
        return
    request = ActionRequest(
        telegram_user_id=callback.from_user.id,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        data=callback.data[len(UI_PREFIX):],
    )
    answer = await handle_action(bot, app, request, state)
    await callback.answer(answer.text[:200], show_alert=answer.error)


def build_router() -> Router:
    router = Router(name="ui_callbacks")
    router.callback_query.register(on_ui_callback, F.data.startswith(UI_PREFIX))
    return router
