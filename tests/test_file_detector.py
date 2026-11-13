from __future__ import annotations

import pytest

from services.file_detector import detect_file


@pytest.mark.parametrize("key, kind, ext", [
    ("jpg", "image", "jpg"),
    ("png", "image", "png"),
    ("gif", "image", "gif"),
    ("bmp", "image", "bmp"),
    ("pdf", "pdf", "pdf"),
    ("docx", "document", "docx"),
    ("txt", "document", "txt"),
    ("html", "document", "html"),
    ("rtf", "document", "rtf"),
    ("csv", "document", "csv"),
])
def test_detects_by_content(samples, key, kind, ext):
    info = detect_file(samples[key], samples[key].name)
    assert (info.kind, info.extension, info.error) == (kind, ext, None)
    assert info.size == samples[key].stat().st_size


def test_ignores_wrong_extension(samples, tmp_path):
    renamed = tmp_path / "picture.pdf"
    renamed.write_bytes(samples["png"].read_bytes())
    info = detect_file(renamed, "picture.pdf")
    assert info.extension == "png" and info.mime_type == "image/png"
    assert info.extension_mismatch and info.claimed_extension == "pdf"


def test_image_metadata(samples):
    info = detect_file(samples["gif"], "anim.gif")
    assert info.meta["width"] == 120 and info.meta["frames"] == 4
    assert detect_file(samples["png"]).meta["alpha"] is True


def test_pdf_pages(samples):
    assert detect_file(samples["pdf"]).meta == {"pages": 3}


def test_broken_and_unknown(samples, tmp_path):
    assert detect_file(samples["broken_png"], "broken.png").error == "broken_file"
    assert detect_file(samples["random"], "data.bin").error == "unknown_type"
    broken_pdf = tmp_path / "x.pdf"
    broken_pdf.write_bytes(b"%PDF-1.7\n garbage without objects")
    assert detect_file(broken_pdf).error == "broken_file"


def test_encrypted_pdf(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "secret.pdf"
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1", owner_pw="2")
    doc.close()
    assert detect_file(path).error == "encrypted_pdf"


def test_decompression_bomb_rejected(tmp_path):
    from PIL import Image

    path = tmp_path / "huge.png"
    Image.new("1", (12000, 9000)).save(path)  # 108 MP, tiny file
    assert detect_file(path).error == "image_too_large"
