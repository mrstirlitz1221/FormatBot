"""Widget templates against the official limits and profile of https://core.telegram.org/bots/widgets."""
from __future__ import annotations

import json
import re
import zlib

import pytest

from api.widget_api import (
    AnswerWidgetQuery,
    EditMessageWidgetData,
    SendWidget,
    WidgetLimitError,
    WidgetQuery,
    WidgetQueryMiddleware,
    measure_widget_html,
    validate_widget_data,
    validate_widget_html,
)
from services.operations import CompressMode, CompressSpec, FileContext, ToolSpec
from utils.i18n import all_keys
from widgets import widget_state as ws
from widgets.widget_templates import TEMPLATE_DIR, WIDGET_TYPES, get_widget_html, render_template, widget_sizes

LANGS = ("ru", "en")

# Things every Telegram app removes (widget profile 1, "Out" lists).
FORBIDDEN_PATTERNS = [
    r"<input", r"<select", r"<textarea", r"<form", r"<iframe", r"<video", r"<audio", r"<progress", r"<meter",
    r"<script\s+src", r"<link", r"<img\s+src=\"http", r"\d+vh\b", r":has\(", r":focus", r":checked",
    r"overflow:\s*(auto|scroll)", r"position:\s*sticky", r"oklch\(", r"color-mix\(", r"@import", r"@font-face",
    r"text-shadow", r"line-clamp", r"\bfetch\(", r"XMLHttpRequest", r"WebSocket", r"\balert\(", r"\bconfirm\(",
    r"navigator\.clipboard", r"TelegramWidget\.sendMessage", r"ontouch",
]


@pytest.mark.parametrize("lang", LANGS)
def test_all_widgets_fit_limits(lang):
    for name, size in widget_sizes(lang).items():
        assert size.raw <= 32768, name
        assert size.compressed <= 4096, f"{name}: {size.compressed} bytes compressed"


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("name", WIDGET_TYPES)
def test_widget_uses_only_supported_features(lang, name):
    html = render_template(name, lang, title="Tools")
    for pattern in FORBIDDEN_PATTERNS:
        assert not re.search(pattern, html, re.IGNORECASE), f"{name} uses {pattern}"
    assert "\x00" not in html
    assert "//" not in re.sub(r"https?://", "", html.split("<script>", 1)[-1]), "JS comments break minification"


def test_compressed_size_counted_like_the_server():
    html = get_widget_html("main", "ru")
    assert measure_widget_html(html).compressed == len(zlib.compress(html.encode(), 9))


def test_validate_widget_html_rejects_oversized():
    with pytest.raises(WidgetLimitError):
        validate_widget_html("a" * 32769)
    noisy = "".join(chr(0x4E00 + (i * 7919) % 20000) for i in range(6000))  # hard to compress
    with pytest.raises(WidgetLimitError):
        validate_widget_html(noisy)
    with pytest.raises(WidgetLimitError):
        validate_widget_html("<p>\x00</p>")


def test_widget_data_limit():
    validate_widget_data("x" * 1024)
    with pytest.raises(WidgetLimitError):
        validate_widget_data("я" * 513)  # 1026 bytes


def test_templates_use_existing_i18n_keys():
    keys = set()
    for path in TEMPLATE_DIR.iterdir():
        keys |= set(re.findall(r"\[\[(?:js:)?([a-z0-9_]+)\]\]", path.read_text(encoding="utf-8")))
    keys -= {"css", "js", "title"}
    for lang in LANGS:
        missing = keys - all_keys(lang)
        assert not missing, f"{lang}: {missing}"


def test_i18n_languages_have_same_keys():
    assert all_keys("ru") == all_keys("en")


# ----------------------------------------------------------------------------- state builders

FILE = FileContext(kind="image", extension="png", name="очень_длинное_имя_файла_" * 6 + ".png",
                   size=123456, meta={"width": 4000, "height": 3000, "frames": 1})


def test_state_builders_fit_1024_bytes():
    from services.image_processor import ImageProcessor

    processor = ImageProcessor()
    for lang in LANGS:
        states = [
            ws.file_state(FILE, ["cv", "cz", "tl"], "предупреждение " * 20),
            ws.convert_state(FILE, processor.convert_targets(FILE), processor.lossy_targets(), 85),
            ws.compress_state(FILE, processor.compress_spec(FILE, lang, 75, "bal")),
            ws.tools_state(FILE, processor.tools(FILE, lang)),
            ws.task_state("d", "PNG → WEBP", original=10, result=5, seconds=1.25, output_name=FILE.name,
                          is_compression=True, details="WEBP · качество 80"),
            ws.task_state("f", "PNG → WEBP", error="ошибка " * 100),
        ]
        for state in states:
            assert len(ws.dump(state).encode()) <= 1024


def test_answer_payload():
    assert json.loads(ws.ActionAnswer("ok").widget_data()) == {"m": "ok"}
    assert json.loads(ws.ActionAnswer("bad", error=True).widget_data()) == {"m": "bad", "e": 1}


def test_compress_and_tool_states_shape():
    spec = CompressSpec([CompressMode("bal", "Balanced", "q80")], "bal", True, 75, [("o", "Orig")])
    state = ws.compress_state(FILE, spec)
    assert state["m"] == [["bal", "Balanced", "q80"]] and state["r"] == [["o", "Orig"]]
    tools = ws.tools_state(FILE, [ToolSpec("ro", "Rotate", "ro", [("90", "90")])])
    assert tools["t"] == [["ro", "Rotate", "ro", [["90", "90"]]]]


# ----------------------------------------------------------------------------- API adapter


def test_methods_use_official_names_and_fields():
    method = SendWidget(chat_id=1, html="<p>x</p>", chat_data="{}", caption="c", allow_queries=True)
    assert method.__api_method__ == "sendWidget"
    dumped = method.model_dump(exclude_none=True)
    assert dumped == {"chat_id": 1, "html": "<p>x</p>", "chat_data": "{}", "caption": "c", "allow_queries": True}
    assert AnswerWidgetQuery(widget_query_id="1").__api_method__ == "answerWidgetQuery"
    assert EditMessageWidgetData(chat_id=1, message_id=2, chat_data="{}").__api_method__ == "editMessageWidgetData"


def test_widget_query_parsing():
    query = WidgetQuery.model_validate({
        "id": "8123", "from": {"id": 1, "is_bot": False, "first_name": "A"},
        "chat": {"id": 1, "type": "private"}, "message_id": 4242, "chat_instance": "9",
        "type": {"type": "data"}, "data": "refresh",
    })
    assert query.from_user.id == 1 and query.message_id == 4242 and query.query_type == "data"


async def test_middleware_routes_widget_updates_only():
    from aiogram.types import Update

    seen = []

    async def on_query(query, data):
        seen.append(query.data)

    async def next_handler(event, data):
        return "passed"

    middleware = WidgetQueryMiddleware(on_query)
    update = Update.model_validate({"update_id": 1, "widget_query": {
        "id": "1", "from": {"id": 1, "is_bot": False, "first_name": "A"}, "chat": {"id": 1, "type": "private"},
        "message_id": 5, "chat_instance": "1", "type": {"type": "data"}, "data": "cv"}})
    assert await middleware(next_handler, update, {}) is True
    assert seen == ["cv"]

    message_update = Update.model_validate({"update_id": 2, "message": {
        "message_id": 1, "date": 0, "chat": {"id": 1, "type": "private"}, "text": "hi"}})
    assert await middleware(next_handler, message_update, {}) == "passed"
