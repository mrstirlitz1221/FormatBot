"""Detects the real type of a file from its content (magic bytes / container structure),
compares it with the claimed extension and collects basic metadata."""
from __future__ import annotations

import logging
import mimetypes
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import filetype

from services import image_service
from utils.validators import normalize_extension

logger = logging.getLogger(__name__)

KIND_IMAGE = "image"
KIND_PDF = "pdf"
KIND_DOCUMENT = "document"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"
KIND_OTHER = "other"

IMAGE_EXTS = {"jpg", "png", "webp", "bmp", "gif", "tiff", "ico", "heic", "heif", "avif"}
DOCUMENT_EXTS = {"doc", "docx", "txt", "rtf", "odt", "xls", "xlsx", "csv", "ppt", "pptx", "odp", "ods", "html"}
AUDIO_EXTS = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "opus"}
VIDEO_EXTS = {"mp4", "avi", "mov", "mkv", "webm"}

# filetype's extension names -> ours
_EXT_ALIASES = {"jpeg": "jpg", "jpe": "jpg", "tif": "tiff", "htm": "html", "oga": "ogg", "qt": "mov", "m4v": "mp4"}

_MIME_BY_EXT = {
    "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "bmp": "image/bmp", "gif": "image/gif",
    "tiff": "image/tiff", "ico": "image/x-icon", "heic": "image/heic", "heif": "image/heif", "avif": "image/avif",
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "rtf": "application/rtf", "txt": "text/plain", "csv": "text/csv", "html": "text/html",
    "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "aac": "audio/aac", "ogg": "audio/ogg",
    "m4a": "audio/mp4", "opus": "audio/opus",
    "mp4": "video/mp4", "avi": "video/x-msvideo", "mov": "video/quicktime", "mkv": "video/x-matroska",
    "webm": "video/webm",
}

_ODF_MIMES = {
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
}


@dataclass
class FileInfo:
    kind: str
    extension: str
    mime_type: str
    size: int
    claimed_extension: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None  # set when the file is broken/unsupported

    @property
    def extension_mismatch(self) -> bool:
        return bool(self.claimed_extension) and self.claimed_extension != self.extension and not (
            {self.claimed_extension, self.extension} <= {"heic", "heif"}
        )

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.kind != KIND_OTHER


def kind_of_extension(ext: str) -> str:
    if ext in IMAGE_EXTS:
        return KIND_IMAGE
    if ext == "pdf":
        return KIND_PDF
    if ext in DOCUMENT_EXTS:
        return KIND_DOCUMENT
    if ext in AUDIO_EXTS:
        return KIND_AUDIO
    if ext in VIDEO_EXTS:
        return KIND_VIDEO
    return KIND_OTHER


def _alias(ext: str) -> str:
    return _EXT_ALIASES.get(ext, ext)


def _zip_office_type(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "mimetype" in names:
                mime = archive.read("mimetype")[:100].decode("ascii", "ignore").strip()
                return _ODF_MIMES.get(mime)
            if "word/document.xml" in names:
                return "docx"
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
            if any(n.startswith("ppt/") for n in names):
                return "pptx"
    except (zipfile.BadZipFile, OSError):
        return None
    return None


def _sniff_text(head: bytes, claimed: str) -> str | None:
    if b"\x00" in head:
        return None
    text = None
    for encoding in ("utf-8", "cp1251"):
        try:
            text = head.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        # A multi-byte UTF-8 character may be cut at the end of the sample.
        try:
            text = head[:-4].decode("utf-8")
        except UnicodeDecodeError:
            return None
    stripped = text.lstrip("﻿ \t\r\n").lower()
    if stripped.startswith("{\\rtf"):
        return "rtf"
    if stripped.startswith(("<!doctype html", "<html")) or "<html" in stripped[:2048]:
        return "html"
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
    if text and printable / len(text) < 0.95:
        return None
    if claimed in {"csv", "html"}:
        return claimed
    return "txt"


def detect_file(path: Path, claimed_name: str | None = None) -> FileInfo:
    """Detect a file by content. ``claimed_name`` is only used to report mismatches and to
    choose between formats that share a container (e.g. OLE .doc/.xls/.ppt, CSV vs TXT)."""
    size = path.stat().st_size
    claimed = _alias(normalize_extension(Path(claimed_name or "").suffix))

    with path.open("rb") as fh:
        head = fh.read(8192)

    ext: str | None = None
    kind_guess = filetype.guess(head)
    if kind_guess is not None:
        ext = _alias(kind_guess.extension)
        if ext in {"zip", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub"}:
            ext = _zip_office_type(path) or ("zip" if ext in {"zip", "epub"} else ext)
        elif ext in {"doc", "xls", "ppt"} or head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            ext = claimed if claimed in {"doc", "xls", "ppt"} else "doc"
        elif ext == "mp4" and claimed == "m4a":
            ext = "m4a"
        elif ext == "ogg" and claimed == "opus":
            ext = "opus"
        elif ext == "mkv" and claimed == "webm":
            ext = "webm"
    elif head.startswith(b"%PDF"):
        ext = "pdf"
    elif head[:2] in (b"\xff\xf1", b"\xff\xf9"):  # ADTS AAC
        ext = "aac"
    elif head[:4] == b"\x00\x00\x01\x00":  # ICO
        ext = "ico"
    else:
        ext = _sniff_text(head, claimed)

    if not ext:
        return FileInfo(KIND_OTHER, claimed or "", "application/octet-stream", size, claimed,
                        error="unknown_type")

    kind = kind_of_extension(ext)
    mime = _MIME_BY_EXT.get(ext) or (kind_guess.mime if kind_guess else None) \
        or mimetypes.types_map.get("." + ext, "application/octet-stream")
    info = FileInfo(kind=kind, extension=ext, mime_type=mime, size=size, claimed_extension=claimed)

    if kind == KIND_IMAGE:
        try:
            info.meta = image_service.probe_image(path)
        except image_service.ImageError as exc:
            info.error = exc.code
    elif kind == KIND_PDF:
        info.meta, info.error = _probe_pdf(path)
    elif kind == KIND_OTHER:
        info.error = "unsupported_type"
    return info


def _probe_pdf(path: Path) -> tuple[dict[str, Any], str | None]:
    import pymupdf

    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                return {"pages": doc.page_count, "encrypted": True}, "encrypted_pdf"
            return {"pages": doc.page_count}, None
    except Exception:  # noqa: BLE001 - PyMuPDF raises several error types for broken files
        logger.info("Broken PDF rejected")
        return {}, "broken_file"
