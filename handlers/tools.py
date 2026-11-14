"""Chat steps of tools: typed parameters (sizes, crop box, page lists) and collecting extra files."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from context import AppContext
from database import repositories as repo
from database.models import User
from services.operations import CATEGORY_TOOL, OperationError, OperationRequest, get_processor
from states.file_states import CollectFiles, ToolInput
from tasks.worker import start_operation
from utils.i18n import t
from widgets.widget_manager import file_context

_INPUT_ERRORS = {
    "crop_outside": "err_crop_outside",
    "delete_all": "in_bad_delete_all",
    "bad_reorder": "in_bad_reorder",
}


async def on_tool_input(message: Message, bot: Bot, app: AppContext, db_user: User, state: FSMContext) -> None:
    lang = db_user.language
    data = await state.get_data()
    async with app.db.session() as session:
        record = await repo.get_uploaded_file(session, int(data.get("file_id", 0)), db_user.id)
    processor = get_processor(record.kind) if record else None
    if record is None or processor is None:
        await state.clear()
        await message.answer(t(lang, "ans_expired"))
        return

    tool = str(data.get("tool", ""))
    try:
        params = processor.parse_text_input(file_context(record), tool, message.text or "")
    except OperationError as exc:
        await message.answer(t(lang, _INPUT_ERRORS.get(exc.code, "in_bad")))
        return

    await state.clear()
    answer = await start_operation(bot, app, db_user, message.chat.id, record,
                                   OperationRequest(CATEGORY_TOOL, tool, params))
    if answer.error:
        await message.answer(answer.text)


async def on_collect_button(callback: CallbackQuery, bot: Bot, app: AppContext, db_user: User,
                            state: FSMContext) -> None:
    lang = db_user.language
    if await state.get_state() != CollectFiles.waiting.state or callback.message is None:
        await callback.answer(t(lang, "ans_expired"), show_alert=True)
        return
    data = await state.get_data()
    if callback.data == "c:x":
        await state.clear()
        await callback.answer(t(lang, "in_cancelled"))
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    extra_ids = [int(i) for i in data.get("extra", [])]
    if not extra_ids:
        await callback.answer(t(lang, "col_need_more"), show_alert=True)
        return
    async with app.db.session() as session:
        record = await repo.get_uploaded_file(session, int(data.get("file_id", 0)), db_user.id)
        extras = [await repo.get_uploaded_file(session, i, db_user.id) for i in extra_ids]
    if record is None or any(e is None for e in extras):
        await state.clear()
        await callback.answer(t(lang, "ans_expired"), show_alert=True)
        return

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    request = OperationRequest(CATEGORY_TOOL, str(data.get("tool")), {"option": data.get("option")})
    answer = await start_operation(bot, app, db_user, callback.message.chat.id, record, request, extras)
    await callback.answer(answer.text[:200], show_alert=answer.error)


def build_router() -> Router:
    router = Router(name="tool_input")
    router.message.register(on_tool_input, ToolInput.waiting, F.text & ~F.text.startswith("/"))
    router.callback_query.register(on_collect_button, F.data.in_({"c:go", "c:x"}))
    return router
