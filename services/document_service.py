"""Office documents: LibreOffice conversions, built-in fallbacks and ZIP-container optimisation."""
from __future__ import annotations

import csv
import html
import io
import logging
import zipfile
from pathlib import Path

import pymupdf
from PIL import Image

from services.external_tools import ToolError, run_process
from utils.validators import ValidationError, check_zip_container

logger = logging.getLogger(__name__)

LIBREOFFICE_TIMEOUT_SEC = 180
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 5000

TEXT_FORMATS = ("doc", "docx", "odt", "rtf", "txt", "html")
SHEET_FORMATS = ("xls", "xlsx", "ods", "csv")
SLIDE_FORMATS = ("ppt", "pptx", "odp")
ZIP_CONTAINERS = ("docx", "xlsx", "pptx", "odt", "ods", "odp")

# LibreOffice --convert-to filters (explicit, so output does not depend on the input type guess).
_LO_FILTERS = {
    "pdf": "pdf",
    "docx": 'docx:MS Word 2007 XML',
    "odt": "odt",
    "rtf": "rtf",
    "txt": "txt:Text (encoded):UTF8",
    "html": "html:XHTML Writer File:UTF8",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "ods": "ods",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "odp": "odp",
}


def libreoffice_targets(source_ext: str) -> list[str]:
    if source_ext in TEXT_FORMATS:
        targets = ["pdf", "docx", "odt", "rtf", "txt", "html"]
    elif source_ext in SHEET_FORMATS:
        targets = ["pdf", "xlsx", "ods", "csv"]
    elif source_ext in SLIDE_FORMATS:
        targets = ["pdf", "pptx", "odp"]
    else:
        return []
    return [t for t in targets if t != source_ext]


async def libreoffice_convert(soffice: str, src: Path, out_dir: Path, target: str, profile_dir: Path) -> Path:
    """Convert with LibreOffice in headless mode. A separate profile per task allows parallel runs."""
    if target not in _LO_FILTERS:
        raise ToolError("unsupported_target")
    if src.suffix.lstrip(".") in ZIP_CONTAINERS:
        try:
            check_zip_container(src)
        except ValidationError as exc:
            raise ToolError("unsafe_archive", str(exc)) from exc
    out_dir.mkdir(exist_ok=True)
    args = [
        soffice,
        f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
        "--headless", "--invisible", "--nologo", "--nodefault", "--norestore", "--nolockcheck",
        "--convert-to", _LO_FILTERS[target],
        "--outdir", str(out_dir),
        str(src),
    ]
    result = await run_process(args, timeout=LIBREOFFICE_TIMEOUT_SEC, cwd=out_dir)
    expected = out_dir / f"{src.stem}.{target}"
    if result.returncode != 0 or not expected.exists() or expected.stat().st_size == 0:
        logger.warning("LibreOffice failed (code %s): %s", result.returncode,
                       result.stderr.decode("utf-8", "replace")[-500:])
        raise ToolError("convert_failed")
    return expected


# ----------------------------------------------------------------------------- built-in conversions


def read_text(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > MAX_TEXT_BYTES:
        raise ToolError("file_too_big")
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _story_to_pdf(html_text: str, dst: Path, css: str = "") -> Path:
    story = pymupdf.Story(html=html_text, user_css=css)
    writer = pymupdf.DocumentWriter(str(dst))
    page = pymupdf.paper_rect("a4")
    area = page + (48, 48, -48, -48)
    more = True
    pages = 0
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
        pages += 1
        if pages > 2000:
            break
    writer.close()
    return dst


def text_to_pdf(src: Path, dst: Path) -> Path:
    text = read_text(src)
    paragraphs = "".join(f"<p>{html.escape(line) or '&nbsp;'}</p>" for line in text.splitlines())
    return _story_to_pdf(f"<body>{paragraphs}</body>", dst,
                         css="body{font-family:sans-serif;font-size:11pt} p{margin:0 0 2pt 0}")


def html_to_pdf(src: Path, dst: Path) -> Path:
    """Render HTML with PyMuPDF's Story (no network access, scripts are ignored)."""
    return _story_to_pdf(read_text(src), dst, css="body{font-family:sans-serif;font-size:11pt}")


def csv_to_pdf(src: Path, dst: Path) -> Path:
    text = read_text(src)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for index, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if index >= MAX_CSV_ROWS:
            break
        rows.append(row)
    if not rows:
        raise ToolError("empty_file")
    header = "".join(f"<th>{html.escape(c)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in rows[1:])
    return _story_to_pdf(f"<table><tr>{header}</tr>{body}</table>", dst,
                         css="body{font-family:sans-serif;font-size:9pt} table{border-collapse:collapse} "
                             "td,th{border:1px solid #999;padding:2px 4px} th{background:#eee}")


def docx_to_txt(src: Path, dst: Path) -> Path:
    from docx import Document

    try:
        check_zip_container(src)
        document = Document(str(src))
    except (ValidationError, Exception) as exc:  # noqa: BLE001 - python-docx raises various errors
        raise ToolError("broken_file", str(exc)) from exc
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    dst.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
    return dst


def text_to_docx(src: Path, dst: Path) -> Path:
    from docx import Document

    document = Document()
    for line in read_text(src).splitlines():
        document.add_paragraph(line)
    document.save(str(dst))
    return dst


# ----------------------------------------------------------------------------- container optimisation

OFFICE_COMPRESS_LEVELS = ("lt", "md", "st")
_LEVEL_IMAGES = {  # max side, jpeg quality, png palette
    "lt": (None, None, False),
    "md": (1920, 75, False),
    "st": (1280, 55, True),
}
_MEDIA_DIRS = ("word/media/", "xl/media/", "ppt/media/", "Pictures/")


def _optimize_image(data: bytes, name: str, level: str) -> bytes:
    max_side, quality, palette = _LEVEL_IMAGES[level]
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            if fmt not in ("JPEG", "PNG"):
                return data
            img.load()
            if max_side and max(img.size) > max_side:
                img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            if fmt == "JPEG":
                img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
                img.save(out, "JPEG", quality=quality or 90, optimize=True, progressive=True)
            else:
                if palette and img.mode != "P":
                    img = img.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE)
                img.save(out, "PNG", optimize=True)
            result = out.getvalue()
    except Exception as exc:  # noqa: BLE001 - leave an image we cannot read untouched
        logger.debug("image %s kept: %s", name, exc)
        return data
    return result if len(result) < len(data) else data


def compress_office(src: Path, dst: Path, level: str) -> Path:
    """Re-pack an OOXML/ODF container: maximum deflate and optimised embedded images.
    Entry names, order and the ODF 'mimetype' rule (first, stored) are preserved."""
    if level not in OFFICE_COMPRESS_LEVELS:
        raise ToolError("bad_params")
    try:
        check_zip_container(src)
    except ValidationError as exc:
        raise ToolError("unsafe_archive", str(exc)) from exc
    with zipfile.ZipFile(src) as source, zipfile.ZipFile(dst, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "mimetype":
                target.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename.startswith(_MEDIA_DIRS):
                data = _optimize_image(data, info.filename, level)
            entry = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            entry.external_attr = info.external_attr
            target.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(dst) as check:
        if check.testzip() is not None:
            raise ToolError("convert_failed")
    return dst
