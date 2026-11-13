"""/settings: language, defaults, notifications, interface mode, history cleanup, statistics."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from context import AppContext
from database import repositories as repo
from database.models import User
from keyboards.main import MODE_ORDER, QUALITY_STEPS, confirm_clear_kb, settings_kb
from utils.i18n import LANGUAGES, t
from utils.size_formatter import format_size


async def render_settings(app: AppContext, user: User) -> str:
    lang = user.language
    async with app.db.session() as session:
        stats = await repo.user_stats(session, user.id)
    body = t(lang, "settings_body",
             lang="Русский" if lang == "ru" else "English",
             q=user.default_quality,
             mode=t(lang, "cz_" + user.compress_mode),
             notif=t(lang, "on") if user.notifications else t(lang, "off"),
             ui=t(lang, "ui_widget") if user.ui_mode == "widget" else t(lang, "ui_classic"))
    stats_text = t(lang, "stats_body", total=stats.total, ok=stats.completed, failed=stats.failed,
                   conv=stats.conversions, saved=format_size(stats.saved_bytes, lang))
    return f"{t(lang, 'settings_title')}\n\n{body}{stats_text}"


def _kb(user: User):  # noqa: ANN202
    return settings_kb(user.language, user.default_quality, user.compress_mode, user.notifications, user.ui_mode)


async def send_settings(bot: Bot, app: AppContext, user: User, chat_id: int) -> None:
    await bot.send_message(chat_id, await render_settings(app, user), reply_markup=_kb(user))


async def cmd_settings(message: Message, bot: Bot, app: AppContext, db_user: User) -> None:
    await send_settings(bot, app, db_user, message.chat.id)


async def on_settings(callback: CallbackQuery, app: AppContext, db_user: User) -> None:
    parts = (callback.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    note = ""

    async with app.db.session() as session:
        user = await repo.get_user_by_telegram_id(session, db_user.telegram_id)
        if action == "lang" and arg in LANGUAGES:
            user.language = arg
        elif action == "q":
            steps = list(QUALITY_STEPS)
            index = steps.index(user.default_quality) if user.default_quality in steps else -1
            user.default_quality = steps[(index + 1) % len(steps)]
        elif action == "mode":
            order = list(MODE_ORDER)
            index = order.index(user.compress_mode) if user.compress_mode in order else -1
            user.compress_mode = order[(index + 1) % len(order)]
        elif action == "notif":
            user.notifications = not user.notifications
        elif action == "ui":
            target = {"classic": "classic", "widget": "widget"}.get(arg)
            if target is None:
                target = "classic" if user.ui_mode == "widget" else "widget"
            user.ui_mode = target
            note = t(user.language, "classic_ui_on" if target == "classic" else "widget_ui_on")
        elif action == "clear":
            if arg == "yes":
                removed = await repo.clear_history(session, user.id)
                note = t(user.language, "s_cleared", n=removed)
            elif arg != "no":
                await callback.message.edit_text(t(user.language, "s_clear_confirm"),
                                                 reply_markup=confirm_clear_kb(user.language))
                await callback.answer()
                return
        else:
            await callback.answer()
            return
        await session.commit()

    if callback.message is not None:
        is_settings_message = callback.message.reply_markup is not None and any(
            button.callback_data in {"s:q", "s:clear:yes", "s:clear:no"}
            for row in callback.message.reply_markup.inline_keyboard for button in row
        )
        if is_settings_message:
            try:
                await callback.message.edit_text(await render_settings(app, user), reply_markup=_kb(user))
            except TelegramBadRequest:
                pass
    await callback.answer(note[:200] if note else None)
    if note and action == "ui" and callback.message is not None:
        await callback.message.answer(note)


def build_router() -> Router:
    router = Router(name="settings")
    router.message.register(cmd_settings, Command("settings"))
    router.callback_query.register(on_settings, F.data.startswith("s:"))
    return router
