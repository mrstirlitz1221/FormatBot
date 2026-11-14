"""PDF tools, PDF compression, document conversions. Outputs are reopened and inspected."""
from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from services import document_service as docs
from services import pdf_service as pdf
from services.document_processor import DocumentProcessor, PdfProcessor
from services.external_tools import ToolError, run_process
from services.operations import FileContext, OperationError
from tests.conftest import SOFFICE

needs_soffice = pytest.mark.skipif(SOFFICE is None, reason="LibreOffice is not installed")


def _pages_text(path: Path) -> list[str]:
    with pymupdf.open(path) as doc:
        return [page.get_text().strip() for page in doc]


@pytest.fixture
def photo_pdf(tmp_path: Path) -> Path:
    """A PDF with a large, noisy photo-like image (compressible) and text."""
    image = Image.effect_noise((2400, 1800), 60).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Report with a photo")
    page.insert_image(pymupdf.Rect(72, 80, 520, 416), stream=buffer.getvalue())
    path = tmp_path / "photo.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def rich_pdf(tmp_path: Path) -> Path:
    """Heading, body text in Russian, a table and an image."""
    html = (
        "<h1>Квартальный отчёт</h1>"
        "<p>Выручка выросла на 12 процентов. Это обычный абзац текста для проверки.</p>"
        "<table border='1'><tr><th>Месяц</th><th>Сумма</th></tr>"
        "<tr><td>Январь</td><td>100</td></tr><tr><td>Февраль</td><td>120</td></tr></table>"
    )
    path = tmp_path / "rich.pdf"
    story = pymupdf.Story(html=html, user_css="table{border-collapse:collapse} td,th{border:1px solid black}")
    writer = pymupdf.DocumentWriter(str(path))
    device = writer.begin_page(pymupdf.paper_rect("a4"))
    story.place(pymupdf.Rect(50, 50, 545, 792))
    story.draw(device)
    writer.end_page()
    writer.close()
    return path


# ----------------------------------------------------------------------------- PDF tools


def test_merge_and_split(samples, tmp_path):
    merged = pdf.merge_pdfs([samples["pdf"], samples["pdf"]], tmp_path / "m.pdf")
    texts = _pages_text(merged)
    assert len(texts) == 6 and texts[3] == "FormatBot test page 1"

    parts = pdf.split_pdf(samples["pdf"], tmp_path, "doc")
    assert [p.name for p in parts] == ["doc_p1.pdf", "doc_p2.pdf", "doc_p3.pdf"]
    assert _pages_text(parts[1]) == ["FormatBot test page 2"]
    with pytest.raises(pdf.PdfError):
        pdf.merge_pdfs([samples["pdf"]], tmp_path / "x.pdf")


def test_pdf_to_images(samples, tmp_path):
    pages = pdf.pdf_to_images(samples["pdf"], tmp_path, "doc", "jpg", dpi=72)
    assert len(pages) == 3
    with Image.open(pages[0]) as page:
        assert page.format == "JPEG" and page.size == (595, 842)  # A4 at 72 dpi


def test_extract_text_and_scans(samples, photo_pdf, tmp_path):
    out = pdf.extract_text(samples["pdf"], tmp_path / "t.txt")
    text = out.read_text(encoding="utf-8")
    assert "FormatBot test page 3" in text and "--- 2 ---" in text

    scan = pymupdf.open()
    scan.new_page().insert_image(pymupdf.Rect(0, 0, 100, 100), filename=str(samples["png"]))
    scan_path = tmp_path / "scan.pdf"
    scan.save(scan_path)
    with pytest.raises(pdf.PdfError) as error:
        pdf.extract_text(scan_path, tmp_path / "s.txt")
    assert error.value.code == "no_text"


def test_rotate_and_select(samples, tmp_path):
    rotated = pdf.rotate_pdf(samples["pdf"], tmp_path / "r.pdf", 90)
    with pymupdf.open(rotated) as doc:
        assert [p.rotation for p in doc] == [90, 90, 90]
    selected = pdf.select_pages(samples["pdf"], tmp_path / "s.pdf", [2, 0])
    assert _pages_text(selected) == ["FormatBot test page 3", "FormatBot test page 1"]


def test_broken_and_encrypted_pdf(tmp_path):
    broken = tmp_path / "b.pdf"
    broken.write_bytes(b"%PDF-1.4 nonsense")
    with pytest.raises(pdf.PdfError):
        pdf.page_count(broken)
    doc = pymupdf.open()
    doc.new_page()
    secret = tmp_path / "s.pdf"
    doc.save(secret, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1", owner_pw="2")
    with pytest.raises(pdf.PdfError) as error:
        pdf.page_count(secret)
    assert error.value.code == "encrypted_pdf"


def test_pdf_compression_levels(photo_pdf, tmp_path):
    original = photo_pdf.stat().st_size
    sizes = {}
    for level in pdf.COMPRESS_LEVELS:
        out = pdf.compress_pdf(photo_pdf, tmp_path / f"{level}.pdf", level)
        sizes[level] = out.stat().st_size
        assert _pages_text(out)[0] == "Report with a photo"   # still readable
    assert sizes["md"] < original and sizes["st"] < sizes["md"]


def test_pdf_to_docx(rich_pdf, tmp_path):
    from docx import Document

    out = pdf.pdf_to_docx(rich_pdf, tmp_path / "r.docx")
    document = Document(str(out))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    body = " ".join(p.text for p in document.paragraphs)
    assert "Квартальный отчёт" in headings
    assert "Выручка выросла на 12 процентов" in body
    assert document.tables, "the table must become a Word table"
    cells = [[c.text for c in row.cells] for row in document.tables[0].rows]
    assert ["Январь", "100"] in cells


# ----------------------------------------------------------------------------- built-in document conversions


def test_text_to_pdf_keeps_cyrillic(samples, tmp_path):
    out = docs.text_to_pdf(samples["txt"], tmp_path / "t.pdf")
    assert "Привет, FormatBot!" in _pages_text(out)[0]


def test_csv_and_html_to_pdf(samples, tmp_path):
    assert "1" in _pages_text(docs.csv_to_pdf(samples["csv"], tmp_path / "c.pdf"))[0]
    assert _pages_text(docs.html_to_pdf(samples["html"], tmp_path / "h.pdf"))[0] == "Hi"


def test_docx_txt_roundtrip(samples, tmp_path):
    from docx import Document

    txt = docs.docx_to_txt(samples["docx"], tmp_path / "d.txt")
    assert txt.read_text(encoding="utf-8").strip() == "FormatBot DOCX sample"
    back = docs.text_to_docx(samples["txt"], tmp_path / "t.docx")
    assert Document(str(back)).paragraphs[0].text == "Привет, FormatBot!"


def _docx_with_photo(path: Path) -> Path:
    from docx import Document
    from docx.shared import Inches

    image = Image.effect_noise((2600, 1900), 50).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=98)
    buffer.seek(0)
    document = Document()
    document.add_paragraph("Photo report")
    document.add_picture(buffer, width=Inches(5))
    document.save(str(path))
    return path


def test_office_compression_keeps_structure(tmp_path):
    from docx import Document

    source = _docx_with_photo(tmp_path / "photo.docx")
    with zipfile.ZipFile(source) as archive:
        names_before = archive.namelist()
    for level in docs.OFFICE_COMPRESS_LEVELS:
        out = docs.compress_office(source, tmp_path / f"{level}.docx", level)
        with zipfile.ZipFile(out) as archive:
            assert archive.namelist() == names_before
        assert Document(str(out)).paragraphs[0].text == "Photo report"
        if level != "lt":
            assert out.stat().st_size < source.stat().st_size * 0.7


def test_odf_mimetype_stays_first_and_stored(tmp_path):
    odt = tmp_path / "a.odt"
    with zipfile.ZipFile(odt, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        archive.writestr("content.xml", "<x/>" * 1000, compress_type=zipfile.ZIP_STORED)
    out = docs.compress_office(odt, tmp_path / "b.odt", "lt")
    with zipfile.ZipFile(out) as archive:
        first = archive.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert out.stat().st_size < odt.stat().st_size


# ----------------------------------------------------------------------------- LibreOffice


@needs_soffice
async def test_libreoffice_docx_to_pdf(samples, tmp_path):
    out = await docs.libreoffice_convert(SOFFICE, samples["docx"], tmp_path / "out", "pdf", tmp_path / "profile")
    assert "FormatBot DOCX sample" in _pages_text(out)[0]


@needs_soffice
async def test_libreoffice_spreadsheet_chain(samples, tmp_path):
    xlsx = await docs.libreoffice_convert(SOFFICE, samples["csv"], tmp_path / "o1", "xlsx", tmp_path / "p1")
    assert zipfile.is_zipfile(xlsx)
    out = await docs.libreoffice_convert(SOFFICE, xlsx, tmp_path / "o2", "pdf", tmp_path / "p2")
    assert "2" in _pages_text(out)[0]


@needs_soffice
async def test_libreoffice_rejects_zip_bomb(tmp_path):
    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * 50_000_000)
    with pytest.raises(ToolError) as error:
        await docs.libreoffice_convert(SOFFICE, bomb, tmp_path / "o", "pdf", tmp_path / "p")
    assert error.value.code == "unsafe_archive"


# ----------------------------------------------------------------------------- external processes


async def test_run_process_timeout_kills():
    args = [sys.executable, "-c", "import time; time.sleep(30)"]
    started = asyncio.get_running_loop().time()
    with pytest.raises(ToolError) as error:
        await run_process(args, timeout=0.5)
    assert error.value.code == "timeout"
    assert asyncio.get_running_loop().time() - started < 10


async def test_run_process_requires_argument_list():
    with pytest.raises(ValueError):
        await run_process("echo hi", timeout=1)  # type: ignore[arg-type]
    result = await run_process([sys.executable, "-c", "print('ok; rm -rf /')"], timeout=10)
    assert result.returncode == 0 and b"ok; rm -rf /" in result.stdout


# ----------------------------------------------------------------------------- processors


PDF_FILE = FileContext("pdf", "pdf", "doc.pdf", 1000, {"pages": 5})


def test_pdf_page_inputs():
    processor = PdfProcessor()
    assert processor.parse_text_input(PDF_FILE, "dl", "2, 4-5") == {"pages": [0, 2], "removed": 3}
    assert processor.parse_text_input(PDF_FILE, "ex", "5,1") == {"pages": [4, 0]}
    assert processor.parse_text_input(PDF_FILE, "rd", "5-1") == {"pages": [4, 3, 2, 1, 0]}
    for tool, text, code in [("dl", "1-5", "delete_all"), ("rd", "1,2", "bad_reorder"), ("ex", "9", "bad_params")]:
        with pytest.raises(OperationError) as error:
            processor.parse_text_input(PDF_FILE, tool, text)
        assert error.value.code == code


def test_pdf_tool_parsing():
    processor = PdfProcessor()
    assert processor.parse_tool(PDF_FILE, "t:mg", "ru")[1] == "collect"
    assert processor.parse_tool(PDF_FILE, "t:dl", "ru")[1] == "input"
    assert processor.parse_tool(PDF_FILE, "t:im:png", "ru")[1] is None
    for bad in ("t:im:gif", "t:sp:1", "t:zz"):
        with pytest.raises(OperationError):
            processor.parse_tool(PDF_FILE, bad, "ru")
    single = FileContext("pdf", "pdf", "one.pdf", 10, {"pages": 1})
    assert {tool.id for tool in processor.tools(single, "ru")} == {"mg", "im", "tx", "ro"}


def test_document_targets_depend_on_libreoffice():
    from config import ExternalTools
    from services.external_tools import set_tools

    processor = DocumentProcessor()
    docx = FileContext("document", "docx", "a.docx", 10, {})
    txt = FileContext("document", "txt", "a.txt", 10, {})
    set_tools(ExternalTools(None, None, None, None))
    assert processor.convert_targets(docx) == ["txt"]
    assert processor.convert_targets(txt) == ["pdf", "docx"]
    assert processor.compress_spec(txt, "ru", 75, "bal") is None
    assert [m.id for m in processor.compress_spec(docx, "ru", 75, "bal").modes] == ["lt", "md", "st"]
    set_tools(ExternalTools(None, None, "soffice", None))
    assert processor.convert_targets(docx) == ["pdf", "odt", "rtf", "txt", "html"]
