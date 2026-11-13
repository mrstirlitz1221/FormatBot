from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from utils.validators import (
    ValidationError,
    check_zip_container,
    normalize_extension,
    parse_page_ranges,
    safe_join,
    sanitize_filename,
)


@pytest.mark.parametrize("raw, expected", [
    ("photo.PNG", "photo.png"),
    ("../../etc/passwd", "passwd"),
    ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
    ("CON.txt", "_CON.txt"),
    ('a<b>c:"d|e?.jpg', "a_b_c_d_e_.jpg"),
    ("", "file"),
    ("...", "file"),
    ("отчёт 2024.docx", "отчёт 2024.docx"),
    ("name.weird-ext!", "name.weird-ext!"),
])
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_limits_length():
    name = sanitize_filename("a" * 500 + ".jpg")
    assert len(name) <= 120 and name.endswith(".jpg")


def test_normalize_extension():
    assert normalize_extension(".JPG") == "jpg"
    assert normalize_extension("../x") == ""
    assert normalize_extension("toolongextension") == ""


def test_safe_join_blocks_traversal(tmp_path: Path):
    assert safe_join(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()
    for evil in ("../x", "..\\x", "/etc/passwd", "a/../../x"):
        with pytest.raises(ValidationError):
            safe_join(tmp_path, evil)


def test_zip_bomb_detection(tmp_path: Path):
    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * 50_000_000)
    with pytest.raises(ValidationError):
        check_zip_container(bomb)

    traversal = tmp_path / "evil.docx"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../evil.txt", b"x")
    with pytest.raises(ValidationError):
        check_zip_container(traversal)

    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"PK\x03\x04garbage")
    with pytest.raises(ValidationError):
        check_zip_container(broken)


def test_normal_docx_passes(samples):
    check_zip_container(samples["docx"])


def test_page_ranges():
    assert parse_page_ranges("1-3, 5", 10) == [0, 1, 2, 4]
    assert parse_page_ranges("3-1", 5) == [2, 1, 0]
    for bad in ("", "0", "11", "1-x", "a", "1;2"):
        with pytest.raises(ValidationError):
            parse_page_ranges(bad, 10)
