"""Text input for tools that need parameters (custom resize / crop)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from context import AppContext
from database import repositories as repo
from database.models import User
from services.image_processor import ImageProcessor
from services.operations import CATEGORY_TOOL, OperationError, OperationRequest
from states.file_states import ToolInput
from tasks.worker import start_operation
from utils.i18n import t
from widgets.widget_manager import file_context


async def on_tool_input(message: Message, bot: Bot, app: AppContext, db_user: User, state: FSMContext) -> None:
    lang = db_user.language
    data = await state.get_data()
    async with app.db.session() as session:
        record = await repo.get_uploaded_file(session, int(data.get("file_id", 0)), db_user.id)
    if record is None:
        await state.clear()
        await message.answer(t(lang, "ans_expired"))
        return

    ctx = file_context(record)
    width, height = ctx.meta.get("width", 0), ctx.meta.get("height", 0)
    tool = data.get("tool")
    try:
        if record.kind != "image" or not width or not height:
            raise OperationError("bad_params")
        if tool == "rs":
            params = {"option": "in", "size": ImageProcessor.parse_size_input(message.text, width, height)}
        elif tool == "cr":
            params = {"option": "in", "box": ImageProcessor.parse_crop_input(message.text, width, height)}
        else:
            raise OperationError("bad_params")
    except OperationError as exc:
        key = "err_crop_outside" if exc.code == "crop_outside" else "in_bad"
        await message.answer(t(lang, key))
        return

    await state.clear()
    answer = await start_operation(bot, app, db_user, message.chat.id, record,
                                   OperationRequest(CATEGORY_TOOL, tool, params))
    if answer.error:
        await message.answer(answer.text)


def build_router() -> Router:
    router = Router(name="tool_input")
    router.message.register(on_tool_input, ToolInput.waiting, F.text & ~F.text.startswith("/"))
    return router
