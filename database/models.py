"""SQLAlchemy ORM models. User files themselves are never stored in the database."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Settings
    default_quality: Mapped[int] = mapped_column(Integer, default=85)
    compress_mode: Mapped[str] = mapped_column(String(8), default="bal")
    notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    ui_mode: Mapped[str] = mapped_column(String(8), default="widget")  # widget | classic
    # What the user picked in the main menu before sending a file (convert/compress/tools)
    pending_intent: Mapped[str | None] = mapped_column(String(8))


class UploadedFile(Base):
    """A file the user sent. Only Telegram's file_id is kept, the bytes are re-downloaded per task."""

    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_file_id: Mapped[str] = mapped_column(String(256))
    file_name: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(16))  # image | pdf | document | audio | video | other
    extension: Mapped[str] = mapped_column(String(16))
    mime_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(BigInteger)
    meta: Mapped[str] = mapped_column(Text, default="{}")  # JSON: width, height, duration, pages...
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversion(Base):
    """History of finished operations."""

    __tablename__ = "conversions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(256))
    output_filename: Mapped[str | None] = mapped_column(String(256))
    original_format: Mapped[str] = mapped_column(String(16))
    output_format: Mapped[str | None] = mapped_column(String(16))
    original_size: Mapped[int] = mapped_column(BigInteger)
    output_size: Mapped[int | None] = mapped_column(BigInteger)
    operation_type: Mapped[str] = mapped_column(String(32))  # convert | compress | tool:<id>
    status: Mapped[str] = mapped_column(String(16))  # completed | failed | cancelled
    processing_time: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WidgetSession(Base):
    """Authoritative state of an interactive message (a widget or a classic keyboard message)."""

    __tablename__ = "widget_sessions"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_widget_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(Integer)
    widget_type: Mapped[str] = mapped_column(String(16))  # main | file | convert | compress | tools | task
    is_widget: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(Text, default="{}")  # JSON, server-side only
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ProcessingTask(Base):
    __tablename__ = "processing_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("uploaded_files.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    operation: Mapped[str] = mapped_column(String(64))
    input_file: Mapped[str | None] = mapped_column(String(256))
    output_file: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
