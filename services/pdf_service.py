"""PDF operations with PyMuPDF (and python-docx for PDF -> DOCX). Synchronous: run in a thread."""
from __future__ import annotations

import io
import logging
import zipfile
from collections import Counter
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

MAX_PAGES = 1000           # pages accepted for any operation
MAX_RENDER_PAGES = 100     # pages rendered to images / split into files
MAX_MERGE_FILES = 20


class PdfError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def open_pdf(path: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several types for broken files
        raise PdfError("broken_file", str(exc)) from exc
    if not doc.is_pdf:
        doc.close()
        raise PdfError("broken_file")
    if doc.needs_pass:
        doc.close()
        raise PdfError("encrypted_pdf")
    if doc.page_count == 0:
        doc.close()
        raise PdfError("broken_file", "no pages")
    if doc.page_count > MAX_PAGES:
        doc.close()
        raise PdfError("too_many_pages")
    return doc


def page_count(path: Path) -> int:
    with open_pdf(path) as doc:
        return doc.page_count


def zip_files(paths: list[Path], dst: Path) -> Path:
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
    return dst


def _save(doc: pymupdf.Document, dst: Path) -> Path:
    doc.save(dst, garbage=4, deflate=True, clean=True)
    return dst


# ----------------------------------------------------------------------------- tools


def merge_pdfs(sources: list[Path], dst: Path) -> Path:
    if not 2 <= len(sources) <= MAX_MERGE_FILES:
        raise PdfError("bad_params")
    result = pymupdf.open()
    try:
        for source in sources:
            with open_pdf(source) as doc:
                result.insert_pdf(doc)
            if result.page_count > MAX_PAGES:
                raise PdfError("too_many_pages")
        return _save(result, dst)
    finally:
        result.close()


def split_pdf(src: Path, out_dir: Path, stem: str) -> list[Path]:
    """One PDF per page."""
    outputs = []
    with open_pdf(src) as doc:
        if doc.page_count > MAX_RENDER_PAGES:
            raise PdfError("too_many_pages")
        width = len(str(doc.page_count))
        for number in range(doc.page_count):
            part = pymupdf.open()
            part.insert_pdf(doc, from_page=number, to_page=number)
            path = out_dir / f"{stem}_p{number + 1:0{width}d}.pdf"
            _save(part, path)
            part.close()
            outputs.append(path)
    return outputs


def pdf_to_images(src: Path, out_dir: Path, stem: str, fmt: str = "png", dpi: int = 150) -> list[Path]:
    if fmt not in {"png", "jpg"}:
        raise PdfError("bad_params")
    outputs = []
    with open_pdf(src) as doc:
        if doc.page_count > MAX_RENDER_PAGES:
            raise PdfError("too_many_pages")
        width = len(str(doc.page_count))
        for number, page in enumerate(doc):
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            path = out_dir / f"{stem}_p{number + 1:0{width}d}.{fmt}"
            if fmt == "jpg":
                pixmap.save(path, jpg_quality=90)
            else:
                pixmap.save(path)
            outputs.append(path)
    return outputs


def extract_text(src: Path, dst: Path) -> Path:
    with open_pdf(src) as doc:
        pages = [page.get_text("text", sort=True).strip() for page in doc]
    if not any(pages):
        raise PdfError("no_text")
    text = "\n\n".join(f"--- {number} ---\n{content}" if len(pages) > 1 else content
                       for number, content in enumerate(pages, 1))
    dst.write_text(text + "\n", encoding="utf-8")
    return dst


def rotate_pdf(src: Path, dst: Path, angle: int) -> Path:
    if angle not in (90, 180, 270):
        raise PdfError("bad_params")
    with open_pdf(src) as doc:
        for page in doc:
            page.set_rotation((page.rotation + angle) % 360)
        return _save(doc, dst)


def select_pages(src: Path, dst: Path, indexes: list[int]) -> Path:
    """Keep the given zero-based pages in the given order (delete / extract / reorder)."""
    with open_pdf(src) as doc:
        if not indexes or any(not 0 <= i < doc.page_count for i in indexes):
            raise PdfError("bad_params")
        doc.select(indexes)
        return _save(doc, dst)


# ----------------------------------------------------------------------------- compression

COMPRESS_LEVELS = ("lt", "md", "st")
_IMAGE_SETTINGS = {  # dpi_threshold, dpi_target, jpeg quality
    "md": (200, 150, 75),
    "st": (120, 96, 55),
}


def compress_pdf(src: Path, dst: Path, level: str) -> Path:
    """lt: structure only (lossless). md/st: also downsample and re-encode images."""
    if level not in COMPRESS_LEVELS:
        raise PdfError("bad_params")
    with open_pdf(src) as doc:
        if level in _IMAGE_SETTINGS:
            threshold, target, quality = _IMAGE_SETTINGS[level]
            try:
                doc.rewrite_images(dpi_threshold=threshold, dpi_target=target, quality=quality)
            except Exception as exc:  # noqa: BLE001 - keep going with structural optimisation
                logger.info("rewrite_images skipped: %s", exc)
        doc.set_metadata({})
        doc.del_xml_metadata()
        doc.save(dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True,
                 use_objstms=1, compression_effort=100)
    return dst


# ----------------------------------------------------------------------------- PDF -> DOCX


def pdf_to_docx(src: Path, dst: Path) -> Path:
    """Rebuild the document in Word: paragraphs with size/bold/italic, headings, tables and images.
    Layout (columns, exact positions, fonts) is approximated, not reproduced."""
    from docx import Document
    from docx.shared import Inches, Pt

    word = Document()
    with open_pdf(src) as doc:
        if doc.page_count > MAX_RENDER_PAGES * 3:
            raise PdfError("too_many_pages")
        body_size = _body_font_size(doc)
        found_content = False
        for number, page in enumerate(doc):
            if number:
                word.add_page_break()
            items = _page_items(page)
            for _y, kind, payload in items:
                found_content = True
                if kind == "table":
                    _add_table(word, payload)
                elif kind == "image":
                    _add_image(word, doc, payload, Inches)
                else:
                    _add_text_block(word, payload, body_size, Pt)
        if not found_content:
            raise PdfError("no_text")
    word.save(dst)
    return dst


def _body_font_size(doc: pymupdf.Document) -> float:
    sizes: Counter[float] = Counter()
    for page in doc.pages(0, min(doc.page_count, 20)):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    sizes[round(span["size"], 1)] += len(span["text"].strip())
    return sizes.most_common(1)[0][0] if sizes else 11.0


def _page_items(page: pymupdf.Page) -> list[tuple[float, str, object]]:
    items: list[tuple[float, str, object]] = []
    table_rects: list[pymupdf.Rect] = []
    try:
        for table in page.find_tables().tables:
            rows = table.extract()
            if rows and len(rows[0]) > 1:
                table_rects.append(pymupdf.Rect(table.bbox))
                items.append((table.bbox[1], "table", rows))
    except Exception as exc:  # noqa: BLE001 - table detection is best effort
        logger.debug("find_tables failed: %s", exc)

    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        rect = pymupdf.Rect(block["bbox"])
        if any(rect.intersects(t) for t in table_rects):
            continue
        if any(span["text"].strip() for line in block["lines"] for span in line["spans"]):
            items.append((rect.y0, "text", block))

    seen = set()
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref")
        bbox = pymupdf.Rect(info["bbox"])
        if not xref or xref in seen or bbox.width < 12 or bbox.height < 12:
            continue
        seen.add(xref)
        items.append((bbox.y0, "image", (xref, bbox)))
    items.sort(key=lambda item: item[0])
    return items


def _add_text_block(word, block: dict, body_size: float, Pt) -> None:  # noqa: ANN001, N803
    spans = [span for line in block["lines"] for span in line["spans"] if span["text"]]
    if not spans:
        return
    max_size = max(span["size"] for span in spans)
    all_bold = all(span["flags"] & 16 for span in spans if span["text"].strip())
    text_len = sum(len(span["text"]) for span in spans)
    if max_size >= body_size * 1.5 and text_len < 200:
        word.add_heading(_block_text(block), level=1)
        return
    if max_size >= body_size * 1.2 and text_len < 200 or (all_bold and text_len < 120 and max_size > body_size):
        word.add_heading(_block_text(block), level=2)
        return
    paragraph = word.add_paragraph()
    lines = block["lines"]
    for line_index, line in enumerate(lines):
        for span in line["spans"]:
            run = paragraph.add_run(span["text"])
            run.bold = bool(span["flags"] & 16)
            run.italic = bool(span["flags"] & 2)
            run.font.size = Pt(round(span["size"] * 2) / 2)
        if line_index < len(lines) - 1:
            last = line["spans"][-1]["text"] if line["spans"] else ""
            if last.endswith("-"):
                continue  # hyphenated word: join without a space
            paragraph.add_run(" ")


def _block_text(block: dict) -> str:
    lines = ["".join(span["text"] for span in line["spans"]).strip() for line in block["lines"]]
    return " ".join(line for line in lines if line)


def _add_table(word, rows: list[list]) -> None:  # noqa: ANN001
    columns = max(len(row) for row in rows)
    table = word.add_table(rows=len(rows), cols=columns)
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = (value or "").strip()


def _add_image(word, doc: pymupdf.Document, payload, Inches) -> None:  # noqa: ANN001, N803
    xref, bbox = payload
    try:
        pixmap = pymupdf.Pixmap(doc, xref)
        if pixmap.n - pixmap.alpha >= 4 or pixmap.colorspace is None or pixmap.colorspace.n not in (1, 3):
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        data = pixmap.tobytes("png")
    except Exception as exc:  # noqa: BLE001 - skip images PyMuPDF cannot decode
        logger.debug("image %s skipped: %s", xref, exc)
        return
    width = min(bbox.width / 72, 6.5)
    word.add_picture(io.BytesIO(data), width=Inches(max(width, 0.3)))
