"""Input validation: file names, paths, archives and user-supplied parameters."""
from __future__ import annotations

import re
import unicodedata
import zipfile
from pathlib import Path

_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]+')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_EXT_RE = re.compile(r"^[a-z0-9]{1,8}$")


class ValidationError(ValueError):
    """User input is not acceptable. The message is safe to log, not to show (use i18n keys)."""


def sanitize_filename(name: str | None, default: str = "file", max_length: int = 120) -> str:
    """Make a display/output file name safe on every OS. Never used to build input paths."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]  # drop any directory part
    name = _UNSAFE_CHARS.sub("_", name).strip(" .")
    stem, dot, ext = name.rpartition(".")
    if not dot or not _EXT_RE.match(ext.lower()):
        stem, ext = name, ""
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    ext = ext.lower() if _EXT_RE.match(ext.lower()) else ""
    stem = stem[: max_length - len(ext) - 1].strip(" .") or default
    return f"{stem}.{ext}" if ext else stem


def file_stem(name: str) -> str:
    return Path(sanitize_filename(name)).stem


def normalize_extension(ext: str | None) -> str:
    ext = (ext or "").lower().lstrip(".")
    return ext if _EXT_RE.match(ext) else ""


def safe_join(base: Path, *parts: str) -> Path:
    """Join paths and make sure the result stays inside ``base`` (no path traversal)."""
    base = base.resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        raise ValidationError(f"path escapes the base directory: {parts!r}")
    return target


def check_zip_container(
    path: Path,
    max_entries: int = 5000,
    max_total_uncompressed: int = 500 * 1024 * 1024,
    max_ratio: float = 200.0,
) -> None:
    """Reject ZIP bombs and broken archives (DOCX/XLSX/PPTX/ODT are ZIP containers)."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > max_entries:
                raise ValidationError("too many entries in the archive")
            total = 0
            for info in infos:
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise ValidationError("unsafe path inside the archive")
                total += info.file_size
                if info.compress_size > 0 and info.file_size / info.compress_size > max_ratio:
                    raise ValidationError("suspicious compression ratio")
            if total > max_total_uncompressed:
                raise ValidationError("archive unpacks to too much data")
    except zipfile.BadZipFile as exc:
        raise ValidationError("broken archive") from exc


def clamp_int(value: str | int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"not an integer: {value!r}") from exc
    if not lo <= number <= hi:
        raise ValidationError(f"{number} is outside {lo}..{hi}")
    return number


def parse_page_ranges(text: str, page_count: int, max_items: int = 1000) -> list[int]:
    """Parse '1-3, 5, 8-6' into zero-based page indexes (order kept, ranges may go down)."""
    text = (text or "").replace(" ", "")
    if not text or not re.fullmatch(r"[0-9,\-]+", text):
        raise ValidationError("bad page list")
    pages: list[int] = []
    for chunk in text.split(","):
        if not chunk:
            continue
        if "-" in chunk:
            start_s, _, end_s = chunk.partition("-")
            start, end = clamp_int(start_s, 1, page_count), clamp_int(end_s, 1, page_count)
            step = 1 if end >= start else -1
            pages.extend(range(start - 1, end - 1 + step, step))
        else:
            pages.append(clamp_int(chunk, 1, page_count) - 1)
        if len(pages) > max_items:
            raise ValidationError("too many pages")
    if not pages:
        raise ValidationError("empty page list")
    return pages
