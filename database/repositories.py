"""Data access helpers. Every function takes an AsyncSession; callers own the transaction."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Conversion, ProcessingTask, UploadedFile, User, WidgetSession, utcnow


# ----------------------------------------------------------------------------- users


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
) -> tuple[User, bool]:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is not None:
        changed = False
        if user.username != username:
            user.username, changed = username, True
        if user.first_name != first_name:
            user.first_name, changed = first_name, True
        if changed:
            await session.flush()
        return user, False
    language = "ru" if (language_code or "").lower().startswith(("ru", "uk", "be", "kk")) else "en"
    user = User(telegram_id=telegram_id, username=username, first_name=first_name, language=language)
    session.add(user)
    await session.flush()
    return user, True


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


# ----------------------------------------------------------------------------- files


async def add_uploaded_file(session: AsyncSession, **fields: Any) -> UploadedFile:
    meta = fields.pop("meta", {}) or {}
    item = UploadedFile(meta=json.dumps(meta, ensure_ascii=False), **fields)
    session.add(item)
    await session.flush()
    return item


async def get_uploaded_file(session: AsyncSession, file_id: int, user_id: int) -> UploadedFile | None:
    """Ownership is part of the lookup: a user can never reach another user's file."""
    return await session.scalar(
        select(UploadedFile).where(UploadedFile.id == file_id, UploadedFile.user_id == user_id)
    )


# ----------------------------------------------------------------------------- widget sessions


async def add_widget_session(
    session: AsyncSession,
    user_id: int,
    chat_id: int,
    message_id: int,
    widget_type: str,
    state: dict[str, Any],
    is_widget: bool,
) -> WidgetSession:
    item = WidgetSession(
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        widget_type=widget_type,
        is_widget=is_widget,
        state=json.dumps(state, ensure_ascii=False),
    )
    session.add(item)
    await session.flush()
    return item


async def get_widget_session(session: AsyncSession, chat_id: int, message_id: int) -> WidgetSession | None:
    return await session.scalar(
        select(WidgetSession).where(WidgetSession.chat_id == chat_id, WidgetSession.message_id == message_id)
    )


def session_state(item: WidgetSession) -> dict[str, Any]:
    try:
        value = json.loads(item.state or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def set_session_state(item: WidgetSession, state: dict[str, Any]) -> None:
    item.state = json.dumps(state, ensure_ascii=False)
    item.updated_at = utcnow()


# ----------------------------------------------------------------------------- tasks


async def create_task(session: AsyncSession, user_id: int, file_id: int | None, operation: str,
                      input_file: str | None) -> ProcessingTask:
    task = ProcessingTask(user_id=user_id, file_id=file_id, operation=operation, input_file=input_file)
    session.add(task)
    await session.flush()
    return task


async def update_task(session: AsyncSession, task_id: int, **fields: Any) -> None:
    task = await session.get(ProcessingTask, task_id)
    if task is None:
        return
    for key, value in fields.items():
        setattr(task, key, value)
    if fields.get("status") in {"completed", "failed", "cancelled"}:
        task.completed_at = utcnow()


# ----------------------------------------------------------------------------- history & stats


async def add_conversion(session: AsyncSession, **fields: Any) -> Conversion:
    item = Conversion(**fields)
    session.add(item)
    await session.flush()
    return item


async def list_conversions(session: AsyncSession, user_id: int, offset: int, limit: int) -> list[Conversion]:
    result = await session.scalars(
        select(Conversion)
        .where(Conversion.user_id == user_id)
        .order_by(Conversion.created_at.desc(), Conversion.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)


async def count_conversions(session: AsyncSession, user_id: int) -> int:
    return int(await session.scalar(select(func.count()).where(Conversion.user_id == user_id)) or 0)


async def clear_history(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(delete(Conversion).where(Conversion.user_id == user_id))
    return int(result.rowcount or 0)


@dataclass(frozen=True)
class UserStats:
    total: int
    completed: int
    failed: int
    conversions: int
    saved_bytes: int


async def user_stats(session: AsyncSession, user_id: int) -> UserStats:
    rows = (
        await session.execute(
            select(Conversion.status, Conversion.operation_type, Conversion.original_size, Conversion.output_size)
            .where(Conversion.user_id == user_id)
        )
    ).all()
    completed = [r for r in rows if r.status == "completed"]
    saved = sum(
        r.original_size - r.output_size
        for r in completed
        if r.operation_type == "compress" and r.output_size is not None and r.output_size < r.original_size
    )
    return UserStats(
        total=len(rows),
        completed=len(completed),
        failed=sum(1 for r in rows if r.status == "failed"),
        conversions=sum(1 for r in completed if r.operation_type == "convert"),
        saved_bytes=saved,
    )
