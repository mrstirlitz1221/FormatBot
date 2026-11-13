"""Loads widget templates, injects shared CSS/JS, localizes strings and minifies.

Template syntax:
  [[key]]      i18n string, HTML-escaped
  [[js:key]]   i18n string escaped for a JavaScript string literal
  [[=name]]    a value passed by the caller, HTML-escaped
  [[@css]] / [[@js]]   shared _base.css / _base.js

JavaScript in templates must not rely on newlines (statements end with ';', no // comments),
because minification joins lines.
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path

from api.widget_api import WidgetSize, measure_widget_html, validate_widget_html
from utils.i18n import t

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
WIDGET_TYPES = ("main", "file", "convert", "compress", "tools", "task")

_PLACEHOLDER = re.compile(r"\[\[(js:|=|@)?([a-z0-9_]+)\]\]")


def _js_escape(value: str) -> str:
    # json.dumps gives a valid JS string; strip the quotes, escape ' and < for safety in <script>.
    return json.dumps(value, ensure_ascii=False)[1:-1].replace("'", "\\'").replace("<", "\\u003c")


def _minify(source: str) -> str:
    lines = (line.strip() for line in source.splitlines())
    return "".join(line for line in lines if line)


def _read(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def render_template(name: str, lang: str, **values: str) -> str:
    if name not in WIDGET_TYPES:
        raise KeyError(f"unknown widget template {name!r}")
    source = _read(f"{name}.html")
    source = source.replace("[[@css]]", _read("_base.css")).replace("[[@js]]", _read("_base.js"))

    def substitute(match: re.Match[str]) -> str:
        prefix, key = match.group(1), match.group(2)
        if prefix == "=":
            return html.escape(values[key], quote=True)
        text = t(lang, key)
        return _js_escape(text) if prefix == "js:" else html.escape(text, quote=False)

    rendered = _minify(_PLACEHOLDER.sub(substitute, source))
    if _PLACEHOLDER.search(rendered):
        raise ValueError(f"unresolved placeholder in {name}.html")
    return rendered


@lru_cache(maxsize=64)
def get_widget_html(name: str, lang: str, title: str = "") -> str:
    """Rendered and validated HTML (cached: templates do not change at runtime)."""
    values = {"title": title} if title else {}
    rendered = render_template(name, lang, **values)
    validate_widget_html(rendered)
    return rendered


def widget_sizes(lang: str) -> dict[str, WidgetSize]:
    sizes = {}
    for name in WIDGET_TYPES:
        values = {"title": t(lang, "tl_image")} if name == "tools" else {}
        sizes[name] = measure_widget_html(render_template(name, lang, **values))
    return sizes
