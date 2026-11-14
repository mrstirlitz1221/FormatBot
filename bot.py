"""FormatBot entry point: python bot.py"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import services.document_processor  # noqa: F401 - registers PDF and document processors
import services.image_processor  # noqa: F401 - registers the image processor
from api.widget_api import WIDGET_UPDATE_TYPES, WidgetQueryMiddleware
from config import ConfigError, Settings, load_settings
from context import AppContext
from database.database import Database
from services.external_tools import set_tools
from handlers import callbacks, files, history, settings as settings_handlers, start, tools
from handlers.middlewares import UserMiddleware
from tasks.task_manager import TaskManager
from utils.file_manager import cleanup_stale_workspaces
from utils.logging_setup import setup_logging
from widgets.widget_handlers import on_shared_widget_query, on_widget_query

logger = logging.getLogger("formatbot")

COMMANDS = {
    "ru": [("start", "Начать"), ("menu", "Главное меню"), ("history", "История операций"),
           ("settings", "Настройки"), ("about", "О боте"), ("cancel", "Отменить ввод")],
    "en": [("start", "Start"), ("menu", "Main menu"), ("history", "Operation history"),
           ("settings", "Settings"), ("about", "About"), ("cancel", "Cancel input")],
}


def build_dispatcher(app: AppContext) -> Dispatcher:
    dp = Dispatcher()
    dp["app"] = app
    dp.update.outer_middleware(WidgetQueryMiddleware(on_widget_query, on_shared_widget_query))
    user_middleware = UserMiddleware()
    dp.message.outer_middleware(user_middleware)
    dp.callback_query.outer_middleware(user_middleware)
    # Order matters: text input for tools is checked before generic handlers.
    dp.include_routers(start.build_router(), tools.build_router(), files.build_router(),
                       callbacks.build_router(), history.build_router(), settings_handlers.build_router())
    return dp


def build_bot(settings: Settings) -> Bot:
    session = None
    if settings.telegram_api_url:
        session = AiohttpSession(api=TelegramAPIServer.from_base(settings.telegram_api_url, is_local=True))
    return Bot(settings.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def periodic_cleanup(settings: Settings) -> None:
    while True:
        await asyncio.sleep(3600)
        cleanup_stale_workspaces(settings.temp_dir, max_age_sec=max(settings.task_timeout_sec * 2, 3600))


async def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    setup_logging(settings.log_level, settings.log_dir)
    tools_found = {name: bool(path) for name, path in vars(settings.tools).items()}
    logger.info("Starting FormatBot. Max file %s MB, local API: %s, tools: %s",
                settings.download_limit_bytes // (1024 * 1024), settings.uses_local_api, tools_found)

    set_tools(settings.tools)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_workspaces(settings.temp_dir, max_age_sec=0)

    db = Database(settings.database_url)
    await db.init()
    task_manager = TaskManager(settings.max_concurrent_tasks, settings.max_tasks_per_user, settings.task_timeout_sec)
    app = AppContext(settings=settings, db=db, tasks=task_manager)

    bot = build_bot(settings)
    dp = build_dispatcher(app)
    for lang, commands in COMMANDS.items():
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in commands],
                                  language_code=None if lang == "en" else lang)
    me = await bot.get_me()
    logger.info("Authorized as @%s (id %s)", me.username, me.id)

    allowed = sorted(set(dp.resolve_used_update_types()) | set(WIDGET_UPDATE_TYPES))
    cleaner = asyncio.create_task(periodic_cleanup(settings))
    try:
        await dp.start_polling(bot, allowed_updates=allowed, handle_signals=True)
    finally:
        cleaner.cancel()
        await task_manager.shutdown()
        await bot.session.close()
        await db.close()
        logger.info("FormatBot stopped")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
