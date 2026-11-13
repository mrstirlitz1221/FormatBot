"""One processing task end to end: download, verify, process, send, record, clean up."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from context import AppContext
from database import repositories as repo
from database.models import UploadedFile, User
from services.file_detector import detect_file
from services.operations import (
    CATEGORY_COMPRESS,
    CATEGORY_TOOL,
    FileContext,
    OperationError,
    OperationRequest,
    get_processor,
)
from tasks.task_manager import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_PROCESSING, TaskHooks, TaskLimitError
from utils.file_manager import TaskWorkspace
from utils.i18n import t
from utils.size_formatter import compare_sizes, format_size
from utils.validators import file_stem, sanitize_filename
from widgets import widget_state as ws
from widgets.widget_manager import TaskView, file_context, task_screen
from widgets.widget_sender import send_screen

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SEC = 180


@dataclass(frozen=True)
class UserSnapshot:
    """Plain copy of the fields a background task needs (ORM objects are session-bound)."""

    id: int
    telegram_id: int
    language: str
    notifications: bool


def output_name(original: str, extension: str, request: OperationRequest) -> str:
    stem = file_stem(original)
    if request.category == CATEGORY_COMPRESS:
        stem += "_compressed"
    elif request.category == CATEGORY_TOOL:
        stem += f"_{request.name}"
    return sanitize_filename(f"{stem}.{extension}")


async def start_operation(bot: Bot, app: AppContext, user: User, chat_id: int, record: UploadedFile,
                          request: OperationRequest) -> ws.ActionAnswer:
    lang = user.language
    processor = get_processor(record.kind)
    if processor is None:
        return ws.ActionAnswer(t(lang, "ans_bad"), error=True)
    active = app.tasks.active_for_user(user.id)
    if active >= app.tasks.max_per_user:
        return ws.ActionAnswer(t(lang, "ans_limit", n=active), error=True)

    ctx = file_context(record)
    label = processor.operation_label(ctx, request, lang)
    async with app.db.session() as session:
        task = await repo.create_task(session, user.id, record.id, request.history_type, record.file_name)
        await session.commit()
        task_id = task.id

    message, is_widget = await send_screen(bot, app, user, chat_id,
                                           task_screen(user, task_id, record.id, request.category, label))
    view = TaskView(bot, chat_id, message.message_id, is_widget, lang, task_id)
    job = OperationJob(
        bot=bot, app=app, chat_id=chat_id, task_id=task_id, view=view, label=label, request=request,
        user=UserSnapshot(user.id, user.telegram_id, lang, user.notifications),
        file=ctx, telegram_file_id=record.telegram_file_id,
    )
    try:
        position = app.tasks.submit(task_id, user.id, TaskHooks(run=job.run, on_start=job.on_start,
                                                                 on_finish=job.on_finish))
    except TaskLimitError as exc:
        await job.on_finish(STATUS_CANCELLED, None)
        return ws.ActionAnswer(t(lang, "ans_limit", n=exc.active), error=True)
    if position:
        await view.show(ws.task_state("w", label, queue=position))
    logger.info("Task %s queued: user=%s op=%s kind=%s", task_id, user.id, request.history_type, record.kind)
    return ws.ActionAnswer(t(lang, "ans_started", id=task_id))


class OperationJob:
    def __init__(self, *, bot: Bot, app: AppContext, chat_id: int, task_id: int, view: TaskView, label: str,
                 request: OperationRequest, user: UserSnapshot, file: FileContext, telegram_file_id: str) -> None:
        self.bot = bot
        self.app = app
        self.chat_id = chat_id
        self.task_id = task_id
        self.view = view
        self.label = label
        self.request = request
        self.user = user
        self.file = file
        self.telegram_file_id = telegram_file_id
        self.lang = user.language
        # filled by run()
        self.output_size: int | None = None
        self.output_filename: str | None = None
        self.output_format: str | None = None
        self.details = ""
        self.elapsed: float | None = None
        self.error_text: str | None = None

    async def on_start(self) -> None:
        async with self.app.db.session() as session:
            await repo.update_task(session, self.task_id, status=STATUS_PROCESSING)
            await session.commit()
        await self.view.show(ws.task_state("p", self.label))

    def _progress(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        asyncio.get_running_loop().create_task(self.view.show(ws.task_state("p", self.label, progress=percent)))

    async def run(self) -> None:
        workspace = TaskWorkspace(self.app.settings.temp_dir, str(self.task_id))
        try:
            source = workspace.input_path(self.file.extension)
            if self.file.size > self.app.settings.download_limit_bytes:
                raise OperationError("file_too_big")
            try:
                await self.bot.download(self.telegram_file_id, destination=source, timeout=DOWNLOAD_TIMEOUT_SEC)
            except (TelegramAPIError, OSError, asyncio.TimeoutError) as exc:
                logger.warning("Task %s: download failed: %s", self.task_id, exc)
                raise OperationError("download_failed") from exc

            info = await asyncio.to_thread(detect_file, source, self.file.name)
            if info.error or info.kind != self.file.kind or info.extension != self.file.extension:
                raise OperationError(info.error or "type_changed")

            processor = get_processor(self.file.kind)
            if processor is None:
                raise OperationError("bad_params")
            started = time.monotonic()
            result = await processor.run(self.file, self.request, source, workspace, self._progress, self.lang)
            self.elapsed = time.monotonic() - started

            size = result.path.stat().st_size if result.path.exists() else 0
            if size == 0:
                raise OperationError("generic", "empty output")
            self.output_size = size
            self.output_format = result.extension
            self.details = result.details
            self.output_filename = output_name(self.file.name, result.extension, self.request)
            logger.info("Task %s processed in %.2fs: %d -> %d bytes", self.task_id, self.elapsed, self.file.size, size)

            if self.request.category == CATEGORY_COMPRESS and size >= self.file.size:
                # Honest result: do not send a copy that is not smaller.
                self.output_filename = None
                await self.bot.send_message(self.chat_id, t(
                    self.lang, "res_not_smaller",
                    res=format_size(size, self.lang), orig=format_size(self.file.size, self.lang)))
                return
            if size > self.app.settings.upload_limit_bytes:
                self.error_text = t(self.lang, "res_too_big", size=format_size(size, self.lang),
                                    limit=format_size(self.app.settings.upload_limit_bytes, self.lang))
                raise OperationError("result_too_big")

            await self.bot.send_document(
                self.chat_id,
                FSInputFile(result.path, filename=self.output_filename),
                caption=self._caption(size),
                parse_mode=None,
                disable_notification=not self.user.notifications,
            )
        finally:
            workspace.cleanup()

    def _caption(self, size: int) -> str:
        elapsed = f"{self.elapsed or 0:.1f}"
        orig, res = format_size(self.file.size, self.lang), format_size(size, self.lang)
        if self.request.category == CATEGORY_COMPRESS:
            pct = compare_sizes(self.file.size, size).reduction_percent
            return t(self.lang, "res_caption_saved", name=self.output_filename, orig=orig, res=res, pct=pct,
                     time=elapsed)
        return t(self.lang, "res_caption", name=self.output_filename, orig=orig, res=res, time=elapsed)

    async def on_finish(self, status: str, error_code: str | None) -> None:
        error_message = None
        if error_code:
            error_message = self.error_text or t(self.lang, f"err_{error_code}")
        async with self.app.db.session() as session:
            await repo.update_task(session, self.task_id, status=status, error_message=error_code,
                                   output_file=self.output_filename)
            await repo.add_conversion(
                session,
                user_id=self.user.id,
                original_filename=self.file.name,
                output_filename=self.output_filename if status == STATUS_COMPLETED else None,
                original_format=self.file.extension,
                output_format=self.output_format,
                original_size=self.file.size,
                output_size=self.output_size if status == STATUS_COMPLETED else None,
                operation_type=self.request.history_type,
                status=status,
                processing_time=round(self.elapsed, 3) if self.elapsed is not None else None,
            )
            await session.commit()

        if status == STATUS_COMPLETED and self.output_size is not None:
            state = ws.task_state(
                "d", self.label, original=self.file.size, result=self.output_size, seconds=self.elapsed,
                output_name=self.output_filename or "", is_compression=self.request.category == CATEGORY_COMPRESS,
                details=self.details,
            )
        elif status == STATUS_CANCELLED:
            state = ws.task_state("c", self.label)
        else:
            state = ws.task_state("f", self.label, error=error_message or t(self.lang, "err_generic"))
        await self.view.show(state)
        if status not in (STATUS_COMPLETED, STATUS_CANCELLED) and self.user.notifications:
            # Widget edits are silent, so a failure also gets a short message.
            try:
                await self.bot.send_message(self.chat_id, f"⚠️ #{self.task_id}: {error_message}", parse_mode=None)
            except TelegramAPIError:
                logger.warning("Could not notify user about failed task %s", self.task_id)
