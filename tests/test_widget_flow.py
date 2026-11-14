"""End-to-end flow through the real dispatcher, handlers, database and task queue,
with a fake Telegram Bot API. This verifies the backend contract, not a real Telegram client."""
from __future__ import annotations

import asyncio
import io
import json

from PIL import Image

USER_ID = 7001
OTHER_USER_ID = 7002


def _user(uid: int = USER_ID) -> dict:
    return {"id": uid, "is_bot": False, "first_name": "Tester", "language_code": "ru"}


def _chat(uid: int = USER_ID) -> dict:
    return {"id": uid, "type": "private", "first_name": "Tester"}


class Updates:
    def __init__(self) -> None:
        self.n = 0
        self.q = 0

    def _id(self) -> int:
        self.n += 1
        return self.n

    def text(self, text: str, uid: int = USER_ID) -> dict:
        message = {"message_id": self._id(), "date": 0, "chat": _chat(uid), "from": _user(uid), "text": text}
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return {"update_id": self._id(), "message": message}

    def document(self, file_id: str, name: str, size: int, uid: int = USER_ID) -> dict:
        return {"update_id": self._id(), "message": {
            "message_id": self._id(), "date": 0, "chat": _chat(uid), "from": _user(uid),
            "document": {"file_id": file_id, "file_unique_id": "u" + file_id, "file_name": name, "file_size": size},
        }}

    def widget(self, message_id: int, data: str, uid: int = USER_ID, chat_uid: int | None = None) -> dict:
        self.q += 1
        return {"update_id": self._id(), "widget_query": {
            "id": f"q{self.q}", "from": _user(uid), "chat": _chat(chat_uid or uid), "message_id": message_id,
            "chat_instance": "1", "type": {"type": "data"}, "data": data,
        }}

    def callback(self, message_id: int, data: str, uid: int = USER_ID) -> dict:
        self.q += 1
        return {"update_id": self._id(), "callback_query": {
            "id": f"c{self.q}", "from": _user(uid), "chat_instance": "1", "data": data,
            "message": {"message_id": message_id, "date": 0, "chat": _chat(uid), "text": "x"},
        }}


async def feed(env, update: dict) -> None:
    await env.dp.feed_raw_update(env.bot, update)


async def wait_tasks(env, timeout: float = 30) -> None:
    for _ in range(int(timeout / 0.05)):
        if not env.app.tasks._entries:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("tasks did not finish")


def widget_answer(env, query_id: str) -> dict:
    for name, params in env.fake.calls:
        if name == "answerWidgetQuery" and params["widget_query_id"] == query_id:
            return json.loads(params["data"])
    raise AssertionError(f"query {query_id} was not answered")


def sent_widgets(env) -> list[dict]:
    return env.fake.all("sendWidget")


def widget_of_type(env, marker: str) -> dict:
    """Find the last sent widget whose caption contains ``marker``."""
    for params in reversed(sent_widgets(env)):
        if marker in params.get("caption", ""):
            return params
    raise AssertionError(f"no widget with caption containing {marker!r}")


async def upload_png(env, u: Updates, samples, file_id: str = "F1") -> dict:
    data = samples["png"].read_bytes()
    env.fake.files[file_id] = data
    await feed(env, u.document(file_id, "logo.png", len(data)))
    return widget_of_type(env, "logo.png")


# ----------------------------------------------------------------------------- tests


async def test_start_sends_greeting_and_main_widget(env):
    u = Updates()
    await feed(env, u.text("/start"))
    texts = [p["text"] for p in env.fake.all("sendMessage")]
    assert texts[0].startswith("Привет! Я FormatBot")
    main = sent_widgets(env)[-1]
    assert main["allow_queries"] is True
    assert "<script>" in main["html"] and len(main["html"].encode()) <= 32768
    assert json.loads(main["chat_data"]) == {"n": 0, "s": 0}
    assert main["caption"]


async def test_main_menu_actions(env):
    u = Updates()
    await feed(env, u.text("/start"))
    main_id = sent_widgets(env)[-1]["_mid"]

    await feed(env, u.widget(main_id, "cv"))
    assert "конвертировать" in widget_answer(env, "q1")["m"]

    await feed(env, u.widget(main_id, "hi"))
    assert widget_answer(env, "q2")["m"]
    assert "История пуста" in env.fake.last("sendMessage")["text"]

    await feed(env, u.widget(main_id, "rm -rf /"))
    assert widget_answer(env, "q3").get("e") == 1


async def test_file_upload_convert_flow(env, samples):
    u = Updates()
    await feed(env, u.text("/start"))
    file_widget = await upload_png(env, u, samples)
    state = json.loads(file_widget["chat_data"])
    assert state["k"] == "image" and state["e"] == "PNG" and state["r"] == "400×300"
    assert state["z"] == samples["png"].stat().st_size
    assert state["a"] == ["cv", "cz", "tl"]

    await feed(env, u.widget(file_widget["_mid"], "cv"))
    convert = widget_of_type(env, "Конвертация")
    convert_state = json.loads(convert["chat_data"])
    assert "webp" in convert_state["o"] and "png" not in convert_state["o"]

    await feed(env, u.widget(convert["_mid"], "go:webp:80"))
    assert "создана" in widget_answer(env, "q2")["m"]
    await wait_tasks(env)

    name, content = env.fake.sent_documents[-1]
    assert name == "logo.webp"
    with Image.open(io.BytesIO(content)) as result:
        assert result.format == "WEBP" and result.size == (400, 300) and result.mode == "RGBA"

    final = json.loads(env.fake.all("editMessageWidgetData")[-1]["chat_data"])
    assert final["s"] == "d"
    assert final["a"] == samples["png"].stat().st_size and final["b"] == len(content)

    # history recorded with real sizes
    await feed(env, u.text("/history"))
    assert "logo.webp" in env.fake.last("sendMessage")["text"]


async def test_compress_flow_reports_real_sizes(env, samples):
    u = Updates()
    await feed(env, u.text("/start"))
    data = samples["jpg"].read_bytes()
    env.fake.files["J1"] = data
    await feed(env, u.document("J1", "photo.jpg", len(data)))
    file_widget = widget_of_type(env, "photo.jpg")
    await feed(env, u.widget(file_widget["_mid"], "cz"))
    compress = widget_of_type(env, "Сжатие")
    modes = [m[0] for m in json.loads(compress["chat_data"])["m"]]
    assert modes == ["mq", "bal", "max", "cus"]

    await feed(env, u.widget(compress["_mid"], "go:max"))
    await wait_tasks(env)
    name, content = env.fake.sent_documents[-1]
    assert name == "photo_compressed.jpg"
    final = json.loads(env.fake.all("editMessageWidgetData")[-1]["chat_data"])
    assert final["c"] == 1 and final["a"] == len(data) and final["b"] == len(content) < len(data)


async def test_invalid_and_foreign_actions_are_rejected(env, samples):
    u = Updates()
    await feed(env, u.text("/start"))
    file_widget = await upload_png(env, u, samples)
    await feed(env, u.widget(file_widget["_mid"], "cv"))
    convert = widget_of_type(env, "Конвертация")
    widgets_before = len(sent_widgets(env))

    await feed(env, u.widget(convert["_mid"], "go:exe"))            # unsupported format
    await feed(env, u.widget(convert["_mid"], "go:webp:999"))       # quality out of range
    await feed(env, u.widget(convert["_mid"], "go:../../etc"))      # garbage
    await feed(env, u.widget(999999, "go:webp"))                    # unknown message
    await feed(env, u.text("/start", uid=OTHER_USER_ID))
    await feed(env, u.widget(convert["_mid"], "go:webp", uid=OTHER_USER_ID, chat_uid=OTHER_USER_ID))

    for qid in ("q2", "q3", "q4", "q5", "q6"):
        assert widget_answer(env, qid).get("e") == 1, qid
    # nothing was started: only the other user's main menu widget was sent
    assert len(sent_widgets(env)) == widgets_before + 1
    assert not env.fake.sent_documents


async def test_cancel_task(env, samples, monkeypatch):
    from services.image_processor import ImageProcessor

    release = asyncio.Event()
    original_run = ImageProcessor.run

    async def slow_run(self, *args, **kwargs):  # noqa: ANN001
        await release.wait()
        return await original_run(self, *args, **kwargs)

    monkeypatch.setattr(ImageProcessor, "run", slow_run)
    u = Updates()
    await feed(env, u.text("/start"))
    file_widget = await upload_png(env, u, samples)
    await feed(env, u.widget(file_widget["_mid"], "cv"))
    convert = widget_of_type(env, "Конвертация")
    await feed(env, u.widget(convert["_mid"], "go:jpg:85"))
    task_widget = widget_of_type(env, "Задача #")
    await asyncio.sleep(0.2)

    await feed(env, u.widget(task_widget["_mid"], "x"))
    await wait_tasks(env)
    assert json.loads(env.fake.all("editMessageWidgetData")[-1]["chat_data"])["s"] == "c"
    assert not env.fake.sent_documents
    assert not list((env.settings.temp_dir).glob("task_*")), "workspace must be removed"


async def test_fallback_to_keyboard_when_widgets_fail(env, samples):
    env.fake.fail_methods["sendWidget"] = "Bad Request: method not found"
    u = Updates()
    await feed(env, u.text("/start"))
    menu = env.fake.last("sendMessage")
    assert menu["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "u:cv"

    data = samples["png"].read_bytes()
    env.fake.files["F9"] = data
    await feed(env, u.document("F9", "logo.png", len(data)))
    card = env.fake.last("sendMessage")
    assert "logo.png" in card["text"]
    buttons = [b["callback_data"] for row in card["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons == ["u:cv", "u:cz", "u:tl"]

    await feed(env, u.callback(card["_mid"], "u:tl"))
    tools = env.fake.last("sendMessage")
    tool_buttons = [b["callback_data"] for row in tools["reply_markup"]["inline_keyboard"] for b in row]
    assert "u:t:ro:90" in tool_buttons and "u:t:gr" in tool_buttons

    await feed(env, u.callback(tools["_mid"], "u:t:ro:90"))
    await wait_tasks(env)
    name, content = env.fake.sent_documents[-1]
    assert name == "logo_ro.png"
    with Image.open(io.BytesIO(content)) as rotated:
        assert rotated.size == (300, 400)
    assert "✅" in env.fake.all("editMessageText")[-1]["text"]


async def test_custom_resize_via_chat_input(env, samples):
    u = Updates()
    await feed(env, u.text("/start"))
    file_widget = await upload_png(env, u, samples)
    await feed(env, u.widget(file_widget["_mid"], "tl"))
    tools = widget_of_type(env, "Инструменты")
    await feed(env, u.widget(tools["_mid"], "t:rs:in"))
    assert "1280x720" in env.fake.last("sendMessage")["text"]

    await feed(env, u.text("not a size"))
    assert "Не понял" in env.fake.last("sendMessage")["text"]
    await feed(env, u.text("200x"))
    await wait_tasks(env)
    _, content = env.fake.sent_documents[-1]
    with Image.open(io.BytesIO(content)) as resized:
        assert resized.size == (200, 150)


async def test_mismatched_extension_is_detected(env, samples):
    u = Updates()
    await feed(env, u.text("/start"))
    data = samples["jpg"].read_bytes()
    env.fake.files["M1"] = data
    await feed(env, u.document("M1", "fake.png", len(data)))
    card = json.loads(sent_widgets(env)[-1]["chat_data"])
    assert card["e"] == "JPG" and ".png" in card["w"]


async def test_too_big_and_broken_files(env, samples):
    u = Updates()
    await feed(env, u.text("/start"))
    await feed(env, u.document("BIG", "huge.png", 25 * 1024 * 1024))
    assert "слишком большой" in env.fake.last("sendMessage")["text"]

    env.fake.files["B1"] = samples["broken_png"].read_bytes()
    await feed(env, u.document("B1", "broken.png", 200))
    assert "повреждён" in env.fake.all("editMessageText")[-1]["text"]
    assert not list(env.settings.temp_dir.glob("task_*"))


# ----------------------------------------------------------------------------- stage 5: PDF


async def upload(env, u: Updates, path, file_id: str, name: str) -> dict:
    data = path.read_bytes()
    env.fake.files[file_id] = data
    await feed(env, u.document(file_id, name, len(data)))
    return widget_of_type(env, name)


async def test_pdf_card_and_delete_pages_via_chat(env, samples):
    import pymupdf

    u = Updates()
    await feed(env, u.text("/start"))
    card = await upload(env, u, samples["pdf"], "P1", "doc.pdf")
    state = json.loads(card["chat_data"])
    assert state["k"] == "pdf" and state["p"] == 3 and state["a"] == ["cv", "cz", "tl"]

    await feed(env, u.widget(card["_mid"], "tl"))
    tools = widget_of_type(env, "Инструменты")
    tool_ids = [tool[0] for tool in json.loads(tools["chat_data"])["t"]]
    assert tool_ids == ["mg", "sp", "im", "tx", "ro", "dl", "ex", "rd"]

    await feed(env, u.widget(tools["_mid"], "t:dl"))
    assert "Всего страниц: 3" in env.fake.last("sendMessage")["text"]
    await feed(env, u.text("1-3"))
    assert "Нельзя удалить все" in env.fake.last("sendMessage")["text"]
    await feed(env, u.text("2"))
    await wait_tasks(env)
    name, content = env.fake.sent_documents[-1]
    assert name == "doc_dl.pdf"
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        assert [p.get_text().strip() for p in doc] == ["FormatBot test page 1", "FormatBot test page 3"]


async def test_pdf_merge_collects_files(env, samples, tmp_path):
    import pymupdf

    u = Updates()
    await feed(env, u.text("/start"))
    card = await upload(env, u, samples["pdf"], "P1", "doc.pdf")
    await feed(env, u.widget(card["_mid"], "tl"))
    tools = widget_of_type(env, "Инструменты")
    await feed(env, u.widget(tools["_mid"], "t:mg"))
    prompt = env.fake.last("sendMessage")
    assert prompt["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "c:go"
    widgets_before = len(sent_widgets(env))

    png = samples["png"].read_bytes()
    env.fake.files["IMG"] = png
    await feed(env, u.document("IMG", "logo.png", len(png)))   # wrong kind: skipped
    assert "не подходит" in env.fake.last("sendMessage")["text"]
    second = tmp_path / "second.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Second file")
    doc.save(second)
    data = second.read_bytes()
    env.fake.files["P2"] = data
    await feed(env, u.document("P2", "second.pdf", len(data)))
    assert "Файлов: 2" in env.fake.last("sendMessage")["text"]
    assert len(sent_widgets(env)) == widgets_before, "collected files must not open file cards"

    await feed(env, u.callback(prompt["_mid"], "c:go"))
    await wait_tasks(env)
    name, content = env.fake.sent_documents[-1]
    assert name == "doc_mg.pdf"
    with pymupdf.open(stream=content, filetype="pdf") as merged:
        assert merged.page_count == 4 and merged[3].get_text().strip() == "Second file"


async def test_pdf_compress_and_convert_to_docx(env, samples):
    from docx import Document

    u = Updates()
    await feed(env, u.text("/start"))
    card = await upload(env, u, samples["pdf"], "P1", "doc.pdf")
    await feed(env, u.widget(card["_mid"], "cv"))
    convert = widget_of_type(env, "Конвертация")
    assert json.loads(convert["chat_data"])["o"] == ["docx", "txt", "png", "jpg"]
    await feed(env, u.widget(convert["_mid"], "go:docx"))
    await wait_tasks(env)
    name, content = env.fake.sent_documents[-1]
    assert name == "doc.docx"
    assert "FormatBot test page 2" in " ".join(p.text for p in Document(io.BytesIO(content)).paragraphs)

    await feed(env, u.widget(convert["_mid"], "go:png"))
    await wait_tasks(env)
    name, content = env.fake.sent_documents[-1]
    assert name == "doc.zip"
    import zipfile
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.namelist() == ["doc_p1.png", "doc_p2.png", "doc_p3.png"]


async def test_text_document_card(env, samples):
    u = Updates()
    await feed(env, u.text("/start"))
    card = await upload(env, u, samples["txt"], "T1", "notes.txt")
    state = json.loads(card["chat_data"])
    assert state["k"] == "document" and state["a"] == ["cv"]
    await feed(env, u.widget(card["_mid"], "cv"))
    convert = widget_of_type(env, "Конвертация")
    await feed(env, u.widget(convert["_mid"], "go:pdf"))
    await wait_tasks(env)
    import pymupdf
    name, content = env.fake.sent_documents[-1]
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        assert name == "notes.pdf" and "Привет, FormatBot!" in doc[0].get_text()


async def test_docx_to_pdf_with_libreoffice(env, samples):
    import pymupdf
    import pytest

    from tests.conftest import SOFFICE

    if SOFFICE is None:
        pytest.skip("LibreOffice is not installed")
    u = Updates()
    await feed(env, u.text("/start"))
    card = await upload(env, u, samples["docx"], "D1", "report.docx")
    assert json.loads(card["chat_data"])["a"] == ["cv", "cz"]
    await feed(env, u.widget(card["_mid"], "cv"))
    convert = widget_of_type(env, "Конвертация")
    assert "pdf" in json.loads(convert["chat_data"])["o"]
    await feed(env, u.widget(convert["_mid"], "go:pdf"))
    await wait_tasks(env, timeout=200)
    name, content = env.fake.sent_documents[-1]
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        assert name == "report.pdf" and "FormatBot DOCX sample" in doc[0].get_text()
    assert not list(env.settings.temp_dir.glob("task_*")), "LibreOffice profile and files must be removed"
