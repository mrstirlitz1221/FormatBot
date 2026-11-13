"""/start, /menu, /about, /cancel."""
from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from context import AppContext
from database.models import User
from handlers.actions import send_main_menu
from keyboards.main import switch_ui_kb
from utils.i18n import t
from utils.size_formatter import format_size

logger = logging.getLogger(__name__)


async def cmd_start(message: Message, bot: Bot, app: AppContext, db_user: User, is_new_user: bool,
                    state: FSMContext) -> None:
    await state.clear()
    lang = db_user.language
    if is_new_user:
        logger.info("New user %s", db_user.id)
    await message.answer(t(lang, "greeting"))
    await message.answer(t(lang, "greeting_hint"), reply_markup=switch_ui_kb(lang, to_classic=db_user.ui_mode == "widget"))
    await send_main_menu(bot, app, db_user, message.chat.id)


async def cmd_menu(message: Message, bot: Bot, app: AppContext, db_user: User) -> None:
    await send_main_menu(bot, app, db_user, message.chat.id)


async def cmd_about(message: Message, app: AppContext, db_user: User) -> None:
    lang = db_user.language
    await message.answer(t(lang, "about", limit=format_size(app.settings.download_limit_bytes, lang)))


async def cmd_cancel(message: Message, db_user: User, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t(db_user.language, "in_cancelled"))


def build_router() -> Router:
    router = Router(name="start")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_menu, Command("menu"))
    router.message.register(cmd_about, Command("about", "help"))
    router.message.register(cmd_cancel, Command("cancel"))
    return router
