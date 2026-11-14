"""Shared fixtures: sample files and a fake Telegram Bot API (no network, no real bot)."""
from __future__ import annotations

import io
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore", category=FutureWarning)

from PIL import Image, ImageDraw  # noqa: E402

import services.document_processor  # noqa: E402,F401 - registers PDF/document processors
import services.image_processor  # noqa: E402,F401 - registers the image processor
from config import _find_executable  # noqa: E402
from services.external_tools import set_tools  # noqa: E402

SOFFICE = _find_executable(
    "SOFFICE_PATH", ["soffice", "libreoffice"],
    [r"C:\Program Files\LibreOffice\program\soffice.exe", r"E:\Programs\LibreOffice\program\soffice.exe"],
)


@pytest.fixture(autouse=True)
def _external_tools():
    from config import ExternalTools

    set_tools(ExternalTools(ffmpeg=None, ffprobe=None, soffice=SOFFICE, ghostscript=None))
    yield


# ----------------------------------------------------------------------------- sample files


@pytest.fixture
def samples(tmp_path: Path) -> dict[str, Path]:
    """Real files created on the fly."""
    out: dict[str, Path] = {}

    photo = Image.effect_mandelbrot((1200, 900), (-2, -1.2, 1, 1.2), 120).convert("RGB")
    exif = photo.getexif()
    exif[0x010F] = "FormatBotTestCam"
    out["jpg"] = tmp_path / "photo.jpg"
    photo.save(out["jpg"], quality=95, exif=exif.tobytes())

    rgba = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(rgba)
    draw.ellipse((40, 40, 360, 260), fill=(220, 40, 40, 255))
    draw.rectangle((150, 100, 250, 200), fill=(40, 40, 220, 128))
    out["png"] = tmp_path / "logo.png"
    rgba.save(out["png"])

    frames = [Image.new("RGB", (120, 80), (i * 50, 100, 200 - i * 40)) for i in range(4)]
    out["gif"] = tmp_path / "anim.gif"
    frames[0].save(out["gif"], save_all=True, append_images=frames[1:], duration=120, loop=0)

    out["bmp"] = tmp_path / "plain.bmp"
    photo.resize((300, 200)).save(out["bmp"])

    import pymupdf

    doc = pymupdf.open()
    for number in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"FormatBot test page {number + 1}")
    out["pdf"] = tmp_path / "doc.pdf"
    doc.save(out["pdf"])
    doc.close()

    out["txt"] = tmp_path / "notes.txt"
    out["txt"].write_text("Привет, FormatBot!\nSecond line.\n", encoding="utf-8")
    out["html"] = tmp_path / "page.html"
    out["html"].write_text("<!DOCTYPE html><html><body><p>Hi</p></body></html>", encoding="utf-8")
    out["rtf"] = tmp_path / "doc.rtf"
    out["rtf"].write_text(r"{\rtf1\ansi Hello}", encoding="ascii")
    out["csv"] = tmp_path / "table.csv"
    out["csv"].write_text("a,b\n1,2\n", encoding="utf-8")

    from docx import Document

    word = Document()
    word.add_paragraph("FormatBot DOCX sample")
    out["docx"] = tmp_path / "report.docx"
    word.save(out["docx"])

    out["broken_png"] = tmp_path / "broken.png"
    out["broken_png"].write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00garbage" * 20)
    out["random"] = tmp_path / "data.bin"
    out["random"].write_bytes(bytes(range(256)) * 8)
    return out


# ----------------------------------------------------------------------------- fake Telegram


class FakeTelegram:
    """Records every Bot API call and returns plausible results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.files: dict[str, bytes] = {}       # file_id -> content (for getFile/download)
        self.sent_documents: list[tuple[str, bytes]] = []
        self.fail_methods: dict[str, str] = {}  # method -> error description
        self._message_id = 100

    def next_message_id(self) -> int:
        self._message_id += 1
        return self._message_id

    def methods(self) -> list[str]:
        return [name for name, _ in self.calls]

    def last(self, method: str) -> dict[str, Any]:
        for name, params in reversed(self.calls):
            if name == method:
                return params
        raise AssertionError(f"{method} was not called; calls: {self.methods()}")

    def all(self, method: str) -> list[dict[str, Any]]:
        return [params for name, params in self.calls if name == method]


def make_fake_session(fake: FakeTelegram):
    from aiogram.client.session.base import BaseSession
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.types import File, InputFile, Message, User

    class FakeSession(BaseSession):
        async def close(self) -> None:
            return None

        async def make_request(self, bot, method, timeout=None):  # noqa: ANN001
            name = method.__api_method__
            params = {k: v for k, v in method.model_dump(warnings=False).items() if v is not None}
            if name == "sendDocument":
                document = method.document
                assert isinstance(document, InputFile)
                chunks = [chunk async for chunk in document.read(bot)]
                fake.sent_documents.append((document.filename, b"".join(chunks)))
                params.pop("document", None)
            fake.calls.append((name, params))
            if name in fake.fail_methods:
                raise TelegramBadRequest(method=method, message=fake.fail_methods[name])

            chat_id = params.get("chat_id", 1)
            if name in {"sendMessage", "sendWidget", "sendDocument"}:
                params["_mid"] = fake.next_message_id()
                return Message.model_validate(
                    {"message_id": params["_mid"], "date": 0, "chat": {"id": chat_id, "type": "private"},
                     "text": params.get("text")},
                    context={"bot": bot},
                )
            if name == "getMe":
                return User(id=42, is_bot=True, first_name="FormatBot", username="formatbot_test_bot")
            if name == "getFile":
                return File.model_validate(
                    {"file_id": params["file_id"], "file_unique_id": "u" + params["file_id"],
                     "file_path": f"documents/{params['file_id']}"}, context={"bot": bot})
            return True

        async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536,  # noqa: ANN001
                                 raise_for_status=True):
            file_id = url.rsplit("/", 1)[-1]
            data = fake.files[file_id]
            for start in range(0, len(data), chunk_size):
                yield data[start:start + chunk_size]

    return FakeSession()


@pytest.fixture
async def env(tmp_path: Path):
    """A bot with a fake API, a real SQLite database and a real task manager."""
    from aiogram import Bot

    from bot import build_dispatcher
    from config import ExternalTools, Settings
    from context import AppContext
    from database.database import Database
    from tasks.task_manager import TaskManager

    settings = Settings(
        bot_token="42:TEST",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        max_file_size_mb=20,
        temp_dir=tmp_path / "work",
        log_level="INFO",
        log_dir=tmp_path / "logs",
        max_concurrent_tasks=2,
        max_tasks_per_user=2,
        task_timeout_sec=60,
        telegram_api_url=None,
        tools=ExternalTools(None, None, None, None),
    )
    db = Database(settings.database_url)
    await db.init()
    app = AppContext(settings=settings, db=db, tasks=TaskManager(2, 2, 60))
    fake = FakeTelegram()
    bot = Bot(settings.bot_token, session=make_fake_session(fake))
    dp = build_dispatcher(app)

    class Env:
        pass

    e = Env()
    e.app, e.bot, e.dp, e.fake, e.settings, e.tmp = app, bot, dp, fake, settings, tmp_path
    yield e
    await app.tasks.shutdown()
    await db.close()


def image_bytes(fmt: str, size=(64, 48), color=(10, 200, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()
