"""Receiving files: size check, real type detection, file card."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from context import AppContext
from database import repositories as repo
from database.models import User
from services.file_detector import FileInfo, detect_file
from utils.file_manager import TaskWorkspace
from utils.i18n import t
from utils.size_formatter import format_size
from utils.validators import sanitize_filename
from widgets.widget_manager import file_screen, screen_for_action
from widgets.widget_sender import send_screen

logger = logging.getLogger(__name__)

DETECT_TIMEOUT_SEC = 60
INTENT_TO_ACTION = {"cv": "cv", "cz": "cz", "pt": "tl", "it": "tl"}
INTENT_KIND = {"pt": "pdf", "it": "image"}


@dataclass
class IncomingFile:
    file_id: str
    name: str
    size: int | None
    is_photo: bool = False


def extract_file(message: Message) -> IncomingFile | None:
    if message.document:
        doc = message.document
        return IncomingFile(doc.file_id, doc.file_name or "file", doc.file_size)
    if message.photo:
        photo = message.photo[-1]  # the largest size
        return IncomingFile(photo.file_id, f"photo_{message.date:%Y%m%d_%H%M%S}.jpg", photo.file_size, True)
    if message.video:
        return IncomingFile(message.video.file_id, message.video.file_name or "video.mp4", message.video.file_size)
    if message.audio:
        return IncomingFile(message.audio.file_id, message.audio.file_name or "audio.mp3", message.audio.file_size)
    if message.voice:
        return IncomingFile(message.voice.file_id, f"voice_{message.date:%Y%m%d_%H%M%S}.ogg", message.voice.file_size)
    if message.animation:
        anim = message.animation
        return IncomingFile(anim.file_id, anim.file_name or "animation.mp4", anim.file_size)
    if message.video_note:
        return IncomingFile(message.video_note.file_id, "video_note.mp4", message.video_note.file_size)
    return None


def _error_text(info: FileInfo, lang: str) -> str:
    return {
        "unknown_type": t(lang, "file_unknown"),
        "unsupported_type": t(lang, "file_unknown"),
        "encrypted_pdf": t(lang, "file_encrypted"),
        "image_too_large": t(lang, "file_too_large_image"),
    }.get(info.error or "", t(lang, "file_broken"))


async def on_file(message: Message, bot: Bot, app: AppContext, db_user: User, state: FSMContext) -> None:
    await state.clear()
    lang = db_user.language
    incoming = extract_file(message)
    if incoming is None:
        return
    limit = app.settings.download_limit_bytes
    if incoming.size is not None and incoming.size > limit:
        hint = "" if app.settings.uses_local_api else "\n" + t(lang, "file_too_big_hint")
        await message.answer(t(lang, "file_too_big", size=format_size(incoming.size, lang),
                               limit=format_size(limit, lang)) + hint)
        return

    name = sanitize_filename(incoming.name)
    logger.info("File received: user=%s size=%s", db_user.id, incoming.size)
    status = await message.answer(t(lang, "file_received"))

    workspace = TaskWorkspace(app.settings.temp_dir)
    try:
        ext_hint = name.rpartition(".")[2] if "." in name else ""
        path = workspace.input_path(ext_hint if ext_hint.isalnum() else "")
        try:
            await bot.download(incoming.file_id, destination=path, timeout=180)
        except (TelegramAPIError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("Download failed: %s", exc)
            await status.edit_text(t(lang, "download_failed"))
            return
        if path.stat().st_size > limit:
            await status.edit_text(t(lang, "file_too_big", size=format_size(path.stat().st_size, lang),
                                     limit=format_size(limit, lang)))
            return
        try:
            info = await asyncio.wait_for(asyncio.to_thread(detect_file, path, name), DETECT_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            info = None
    finally:
        workspace.cleanup()

    if info is None or info.error:
        await status.edit_text(t(lang, "file_broken") if info is None else _error_text(info, lang))
        return

    warnings = []
    if info.extension_mismatch:
        warnings.append(t(lang, "file_mismatch", claimed=info.claimed_extension, real=info.extension.upper()))
        name = sanitize_filename(f"{name.rpartition('.')[0] or name}.{info.extension}")
    if incoming.is_photo:
        warnings.append(t(lang, "file_photo_note"))

    async with app.db.session() as session:
        record = await repo.add_uploaded_file(
            session, user_id=db_user.id, telegram_file_id=incoming.file_id, file_name=name, kind=info.kind,
            extension=info.extension, mime_type=info.mime_type, size=info.size, meta=info.meta,
        )
        user = await repo.get_user_by_telegram_id(session, db_user.telegram_id)
        intent = user.pending_intent
        user.pending_intent = None
        await session.commit()

    try:
        await status.delete()
    except TelegramAPIError:
        pass
    await send_screen(bot, app, db_user, message.chat.id, file_screen(db_user, record, " ".join(warnings)))

    if intent and INTENT_KIND.get(intent, info.kind) == info.kind:
        screen = screen_for_action(db_user, record, INTENT_TO_ACTION[intent])
        if screen is not None:
            await send_screen(bot, app, db_user, message.chat.id, screen)


def build_router() -> Router:
    router = Router(name="files")
    router.message.register(on_file, F.document | F.photo | F.video | F.audio | F.voice | F.animation | F.video_note)
    return router
