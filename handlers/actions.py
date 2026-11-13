"""One dispatcher for actions coming from widgets (widget_query) and fallback keyboards (callback_query).

Every action is checked against the authoritative server-side session of the message it came from:
the message must belong to this user, and the action must be valid for that screen.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.fsm.context import FSMContext

from context import AppContext
from database import repositories as repo
from database.models import UploadedFile, User
from services.operations import OperationError, get_processor
from states.file_states import ToolInput
from tasks.worker import start_operation
from utils.i18n import t, t_map
from utils.size_formatter import format_size
from widgets.widget_manager import file_context, main_screen, screen_for_action
from widgets.widget_sender import send_screen
from widgets.widget_state import ActionAnswer

logger = logging.getLogger(__name__)

MAIN_ACTIONS = {"cv", "cz", "pt", "it", "hi", "se", "ab"}
FILE_ACTIONS = {"cv", "cz", "tl"}


@dataclass
class ActionRequest:
    telegram_user_id: int
    chat_id: int
    message_id: int
    data: str


async def handle_action(bot: Bot, app: AppContext, request: ActionRequest, state: FSMContext | None) -> ActionAnswer:
    async with app.db.session() as session:
        user = await repo.get_user_by_telegram_id(session, request.telegram_user_id)
        widget = await repo.get_widget_session(session, request.chat_id, request.message_id)
        if user is None or widget is None:
            return ActionAnswer(t(user.language if user else "en", "ans_expired"), error=True)
        if widget.user_id != user.id:
            logger.warning("User %s tried to use a session of user %s", user.id, widget.user_id)
            return ActionAnswer(t(user.language, "ans_bad"), error=True)
        session_data = repo.session_state(widget)
        widget_type = widget.widget_type
        record = None
        if "f" in session_data:
            record = await repo.get_uploaded_file(session, int(session_data["f"]), user.id)

    lang = user.language
    data = request.data
    if not data or len(data.encode("utf-8")) > 64:
        return ActionAnswer(t(lang, "ans_bad"), error=True)

    try:
        if widget_type == "main":
            return await _main_action(bot, app, user, request.chat_id, data)
        if record is None:
            return ActionAnswer(t(lang, "ans_expired"), error=True)
        if widget_type == "file":
            return await _open_screen(bot, app, user, request.chat_id, record, data)
        if widget_type == "convert":
            request_op = _processor(record).parse_convert(file_context(record), data, user.default_quality)
            return await start_operation(bot, app, user, request.chat_id, record, request_op)
        if widget_type == "compress":
            request_op = _processor(record).parse_compress(file_context(record), data, lang)
            return await start_operation(bot, app, user, request.chat_id, record, request_op)
        if widget_type == "tools":
            return await _tool_action(bot, app, user, request.chat_id, record, data, state)
        if widget_type == "task":
            return await _task_action(bot, app, user, request.chat_id, record, session_data, data)
    except OperationError as exc:
        logger.info("Rejected action %r on %s: %s", data, widget_type, exc.code)
        return ActionAnswer(t(lang, "ans_bad"), error=True)
    return ActionAnswer(t(lang, "ans_bad"), error=True)


def _processor(record: UploadedFile):  # noqa: ANN202
    processor = get_processor(record.kind)
    if processor is None:
        raise OperationError("bad_params")
    return processor


async def _main_action(bot: Bot, app: AppContext, user: User, chat_id: int, data: str) -> ActionAnswer:
    lang = user.language
    if data not in MAIN_ACTIONS:
        return ActionAnswer(t(lang, "ans_bad"), error=True)
    if data in {"cv", "cz", "pt", "it"}:
        async with app.db.session() as session:
            db_user = await repo.get_user_by_telegram_id(session, user.telegram_id)
            db_user.pending_intent = data
            await session.commit()
        return ActionAnswer(t_map(lang, "send_file_for")[data])
    # Lazy imports: these modules import this one for their own callbacks.
    if data == "hi":
        from handlers.history import send_history
        await send_history(bot, app, user, chat_id, page=0)
    elif data == "se":
        from handlers.settings import send_settings
        await send_settings(bot, app, user, chat_id)
    else:
        await bot.send_message(chat_id, t(lang, "about", limit=format_size(app.settings.download_limit_bytes, lang)))
    return ActionAnswer(t(lang, "ans_sent"))


async def _open_screen(bot: Bot, app: AppContext, user: User, chat_id: int, record: UploadedFile,
                       action: str) -> ActionAnswer:
    if action not in FILE_ACTIONS:
        return ActionAnswer(t(user.language, "ans_bad"), error=True)
    screen = screen_for_action(user, record, action)
    if screen is None:
        return ActionAnswer(t(user.language, "ans_bad"), error=True)
    await send_screen(bot, app, user, chat_id, screen)
    return ActionAnswer(t(user.language, "ans_open_below"))


async def _tool_action(bot: Bot, app: AppContext, user: User, chat_id: int, record: UploadedFile, data: str,
                       state: FSMContext | None) -> ActionAnswer:
    lang = user.language
    ctx = file_context(record)
    request_op, needs_input = _processor(record).parse_tool(ctx, data, lang)
    if not needs_input:
        return await start_operation(bot, app, user, chat_id, record, request_op)
    if state is None:
        return ActionAnswer(t(lang, "ans_bad"), error=True)
    await state.set_state(ToolInput.waiting)
    await state.update_data(file_id=record.id, tool=request_op.name)
    width, height = ctx.meta.get("width", 0), ctx.meta.get("height", 0)
    prompt_key = {"rs": "in_resize", "cr": "in_crop"}.get(request_op.name)
    if prompt_key is None:
        await state.clear()
        return ActionAnswer(t(lang, "ans_bad"), error=True)
    await bot.send_message(chat_id, f"<b>{html.escape(ctx.name)}</b>\n" + t(lang, prompt_key, w=width, h=height))
    return ActionAnswer(t(lang, "ans_input"))


async def _task_action(bot: Bot, app: AppContext, user: User, chat_id: int, record: UploadedFile,
                       session_data: dict, data: str) -> ActionAnswer:
    lang = user.language
    task_id = int(session_data.get("task", 0))
    if data == "x":
        if app.tasks.cancel(task_id, user.id):
            return ActionAnswer(t(lang, "ans_cancelled"))
        return ActionAnswer(t(lang, "ans_not_running"), error=True)
    if data == "rp":
        action = {"convert": "cv", "compress": "cz", "tool": "tl"}.get(session_data.get("cat", ""), "")
        screen = screen_for_action(user, record, action)
        if screen is None:
            return ActionAnswer(t(lang, "ans_bad"), error=True)
        await send_screen(bot, app, user, chat_id, screen)
        return ActionAnswer(t(lang, "ans_open_below"))
    if data == "mn":
        await send_main_menu(bot, app, user, chat_id)
        return ActionAnswer(t(lang, "ans_open_below"))
    return ActionAnswer(t(lang, "ans_bad"), error=True)


async def send_main_menu(bot: Bot, app: AppContext, user: User, chat_id: int) -> None:
    async with app.db.session() as session:
        stats = await repo.user_stats(session, user.id)
    await send_screen(bot, app, user, chat_id, main_screen(user, stats.completed, stats.saved_bytes))
