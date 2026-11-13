"""Image processing with Pillow (+ pillow-heif for HEIC/HEIF).

All functions are synchronous and CPU-bound: call them through ``asyncio.to_thread``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError, features

logger = logging.getLogger(__name__)

try:  # HEIC/HEIF support is optional
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:  # pragma: no cover - depends on the environment
    HEIF_SUPPORTED = False

AVIF_SUPPORTED = bool(features.check("avif")) if hasattr(features, "check") else False

# Hard cap against decompression bombs (~ 90 megapixels, e.g. 12000 x 7500).
MAX_PIXELS = 90_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

PIL_FORMAT = {
    "jpg": "JPEG", "png": "PNG", "webp": "WEBP", "bmp": "BMP", "gif": "GIF", "tiff": "TIFF",
    "ico": "ICO", "heic": "HEIF", "heif": "HEIF", "avif": "AVIF", "pdf": "PDF",
}
LOSSY_FORMATS = {"jpg", "webp", "heic", "heif", "avif"}
ALPHA_FORMATS = {"png", "webp", "gif", "tiff", "ico", "heic", "heif", "avif"}
ANIMATED_FORMATS = {"gif", "webp"}

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


class ImageError(Exception):
    """Processing failed; ``code`` is an i18n key suffix shown to the user."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def readable_formats() -> set[str]:
    formats = {"jpg", "png", "webp", "bmp", "gif", "tiff", "ico"}
    if HEIF_SUPPORTED:
        formats |= {"heic", "heif"}
    if AVIF_SUPPORTED:
        formats.add("avif")
    return formats


def convert_targets(source_ext: str) -> list[str]:
    """Formats an image can be converted to (the source format itself is excluded)."""
    targets = ["jpg", "png", "webp", "bmp", "gif", "tiff", "ico", "pdf"]
    if HEIF_SUPPORTED:
        targets.append("heic")
    if AVIF_SUPPORTED:
        targets.append("avif")
    same = {"heif": "heic"}.get(source_ext, source_ext)
    return [t for t in targets if t != same]


# ----------------------------------------------------------------------------- open / probe


def probe_image(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as img:
            width, height = img.size
            if width * height > MAX_PIXELS:
                raise ImageError("image_too_large")
            frames = int(getattr(img, "n_frames", 1) or 1)
            has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
            mode = img.mode
            img.verify()
    except ImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageError("image_too_large") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageError("broken_file", str(exc)) from exc
    return {"width": width, "height": height, "frames": frames, "alpha": has_alpha, "mode": mode}


def open_image(path: Path) -> Image.Image:
    """Open and fully decode an image, applying the EXIF orientation."""
    try:
        img = Image.open(path)
        if img.size[0] * img.size[1] > MAX_PIXELS:
            raise ImageError("image_too_large")
        if getattr(img, "n_frames", 1) > 1:
            return img  # animated: keep frames; orientation tags are not used for animations
        img.load()
        return ImageOps.exif_transpose(img)
    except ImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageError("image_too_large") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageError("broken_file", str(exc)) from exc


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _flatten(img: Image.Image, background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Drop transparency onto a white background (for formats without alpha)."""
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, background)
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return img.convert("RGB") if img.mode not in ("RGB", "L") else img


def _for_alpha_format(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "RGBA", "L", "LA"):
        return img
    return img.convert("RGBA" if _has_alpha(img) else "RGB")


def _to_gif_palette(img: Image.Image, colors: int) -> Image.Image:
    """Palette image for GIF; fully transparent pixels get a reserved transparent index."""
    if not _has_alpha(img):
        return img.convert("RGB").quantize(colors=min(colors, 256), method=Image.Quantize.MEDIANCUT)
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    paletted = rgba.convert("RGB").quantize(colors=min(colors, 255), method=Image.Quantize.MEDIANCUT)
    transparent_index = 255
    mask = alpha.point(lambda a: 255 if a < 128 else 0)
    paletted.paste(transparent_index, mask=mask)
    paletted.info["transparency"] = transparent_index
    return paletted


def _square_canvas(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    side = max(rgba.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
    return canvas


# ----------------------------------------------------------------------------- saving


@dataclass(frozen=True)
class SaveOptions:
    quality: int | None = None          # 10..100 for lossy formats
    keep_metadata: bool = True          # EXIF/XMP (ICC colour profile is kept unless strip_icc)
    strip_icc: bool = False
    palette_colors: int | None = None   # PNG/GIF palette quantization
    lossless: bool = False              # WEBP lossless


def save_image(img: Image.Image, dst: Path, fmt: str, options: SaveOptions = SaveOptions()) -> Path:
    """Save ``img`` (possibly animated) as ``fmt`` with format-appropriate settings."""
    fmt = {"jpeg": "jpg", "tif": "tiff"}.get(fmt, fmt)
    if fmt not in PIL_FORMAT:
        raise ImageError("unsupported_target")
    if fmt in {"heic", "heif"} and not HEIF_SUPPORTED:
        raise ImageError("unsupported_target")
    if fmt == "avif" and not AVIF_SUPPORTED:
        raise ImageError("unsupported_target")

    params: dict[str, Any] = {}
    icc = None if options.strip_icc else img.info.get("icc_profile")
    if icc:
        params["icc_profile"] = icc
    if options.keep_metadata:
        if fmt in {"jpg", "webp", "png", "tiff", "heic", "heif", "avif"}:
            exif_obj = img.getexif()
            if len(exif_obj):
                exif_obj.pop(0x0112, None)  # orientation is already applied to the pixels
                params["exif"] = exif_obj.tobytes()
    else:
        # Encoders may fall back to img.info for EXIF/XMP: keep only what affects rendering.
        img.info = {k: v for k, v in img.info.items()
                    if k in {"icc_profile", "transparency", "duration", "loop", "background"}}

    quality = options.quality
    animated = getattr(img, "n_frames", 1) > 1 and getattr(img, "is_animated", False)

    if animated and fmt in ANIMATED_FORMATS:
        frames = []
        durations = []
        for index in range(img.n_frames):
            img.seek(index)
            frame = img.convert("RGBA")
            if options.palette_colors and fmt == "gif":
                frame = frame.quantize(colors=options.palette_colors, method=Image.Quantize.FASTOCTREE)
            frames.append(frame)
            durations.append(img.info.get("duration", 100))
        extra = {"save_all": True, "append_images": frames[1:], "duration": durations,
                 "loop": img.info.get("loop", 0)}
        if fmt == "webp":
            extra.update(quality=quality or 80, method=4, lossless=options.lossless)
        else:
            extra.update(optimize=True, disposal=2)
        frames[0].save(dst, PIL_FORMAT[fmt], **extra)
        return dst

    if animated:
        img.seek(0)
        img = img.convert("RGBA")

    if fmt == "jpg":
        out = _flatten(img)
        q = quality or 85
        params.update(quality=q, optimize=True, progressive=True, subsampling=0 if q >= 90 else 2)
        out.save(dst, "JPEG", **params)
    elif fmt == "png":
        out = _for_alpha_format(img) if img.mode not in ("P", "PA") else img
        if options.palette_colors:
            out = out.convert("RGBA").quantize(colors=options.palette_colors, method=Image.Quantize.FASTOCTREE)
        out.save(dst, "PNG", optimize=True, **params)
    elif fmt == "webp":
        out = _for_alpha_format(img)
        if out.mode in ("L", "LA"):
            out = out.convert("RGBA" if out.mode == "LA" else "RGB")
        out.save(dst, "WEBP", quality=quality or 80, method=6, lossless=options.lossless, **params)
    elif fmt == "bmp":
        _flatten(img).save(dst, "BMP")
    elif fmt == "gif":
        _to_gif_palette(img, options.palette_colors or 256).save(dst, "GIF", optimize=True)
    elif fmt == "tiff":
        out = _for_alpha_format(img)
        out.save(dst, "TIFF", compression="tiff_adobe_deflate", **params)
    elif fmt == "ico":
        out = _square_canvas(img)
        sizes = [s for s in ICO_SIZES if s[0] <= out.width] or [ICO_SIZES[0]]
        out.save(dst, "ICO", sizes=sizes)
    elif fmt in {"heic", "heif"}:
        out = _for_alpha_format(img)
        if out.mode in ("L", "LA"):
            out = out.convert("RGB")
        out.save(dst, "HEIF", quality=quality or 80, **params)
    elif fmt == "avif":
        out = _for_alpha_format(img)
        out.save(dst, "AVIF", quality=quality or 70, **params)
    elif fmt == "pdf":
        _flatten(img).save(dst, "PDF", resolution=150.0)
    return dst


# ----------------------------------------------------------------------------- operations


def convert_image(src: Path, dst: Path, target: str, quality: int | None = None) -> Path:
    img = open_image(src)
    try:
        return save_image(img, dst, target, SaveOptions(quality=quality if target in LOSSY_FORMATS else None))
    finally:
        img.close()


def images_to_pdf(sources: list[Path], dst: Path) -> Path:
    """Combine several images into one PDF, one image per page, in the given order."""
    if not sources:
        raise ImageError("no_input")
    pages = []
    try:
        for src in sources:
            img = open_image(src)
            if getattr(img, "n_frames", 1) > 1:
                img.seek(0)
            pages.append(_flatten(img.convert("RGBA") if img.mode == "P" else img))
        pages[0].save(dst, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    finally:
        for page in pages:
            page.close()
    return dst


# Compression plans --------------------------------------------------------------

COMPRESS_MODES = ("mq", "bal", "max", "cus")
RESOLUTION_PRESETS = {"o": None, "2560": 2560, "1920": 1920, "1280": 1280, "1080": 1080, "720": 720}

# Output format when compressing: formats without a useful compressed form are mapped.
_COMPRESS_FORMAT = {"bmp": "png", "heif": "heic"}


@dataclass(frozen=True)
class CompressPlan:
    fmt: str
    quality: int | None
    max_side: int | None
    palette_colors: int | None
    lossless: bool

    def describe(self) -> dict[str, Any]:
        return {
            "fmt": self.fmt, "q": self.quality, "side": self.max_side,
            "colors": self.palette_colors, "lossless": self.lossless,
        }


def plan_compression(source_ext: str, mode: str, quality: int | None = None,
                     resolution: str | None = None) -> CompressPlan:
    """Decide the exact settings for a compression mode. Used both to show the user
    what will happen and to do it, so the description always matches the result."""
    if mode not in COMPRESS_MODES:
        raise ImageError("bad_params")
    fmt = _COMPRESS_FORMAT.get(source_ext, source_ext)
    max_side = None
    if mode == "max":
        max_side = 1920
    elif mode == "cus":
        if resolution not in RESOLUTION_PRESETS:
            raise ImageError("bad_params")
        max_side = RESOLUTION_PRESETS[resolution]
        if quality is None or not 10 <= quality <= 100:
            raise ImageError("bad_params")

    if fmt in LOSSY_FORMATS:
        q = {"mq": 92, "bal": 80, "max": 60}.get(mode, quality)
        return CompressPlan(fmt, q, max_side, None, False)
    if fmt in {"png", "gif"}:
        colors = None
        if mode == "max":
            colors = 256 if fmt == "png" else 128
        elif mode == "cus" and quality is not None and quality < 90:
            colors = max(16, min(256, round(quality * 2.56)))
        elif fmt == "gif" and mode == "bal":
            colors = 256
        return CompressPlan(fmt, None, max_side, colors, colors is None)
    # tiff / ico: lossless re-encoding (+ optional downscale)
    return CompressPlan(fmt, None, max_side, None, True)


def compress_image(src: Path, dst_dir: Path, plan: CompressPlan, stem: str = "output") -> Path:
    img = open_image(src)
    try:
        if plan.max_side and getattr(img, "n_frames", 1) == 1:
            img = _downscale(img, plan.max_side)
        dst = dst_dir / f"{stem}.{plan.fmt}"
        save_image(img, dst, plan.fmt, SaveOptions(
            quality=plan.quality, keep_metadata=False, palette_colors=plan.palette_colors,
        ))
        return dst
    finally:
        img.close()


def _downscale(img: Image.Image, max_side: int) -> Image.Image:
    """Shrink so the longest side is at most ``max_side``. Never upscales."""
    if max(img.size) <= max_side:
        return img
    copy = img.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return copy


# Tools -------------------------------------------------------------------------

RESIZE_PRESETS = ("p75", "p50", "p25", "s1920", "s1280", "s1080", "s720")
CROP_PRESETS = {"1x1": (1, 1), "4x3": (4, 3), "3x4": (3, 4), "16x9": (16, 9), "9x16": (9, 16)}
ROTATE_PRESETS = ("90", "180", "270", "fh", "fv")


def tool_output_format(source_ext: str) -> str:
    return {"heif": "heic"}.get(source_ext, source_ext)


def _apply_frames(img: Image.Image, fn) -> Image.Image:  # noqa: ANN001
    """Apply ``fn`` to a still image, or to every frame of an animation."""
    if getattr(img, "n_frames", 1) <= 1:
        return fn(img)
    frames, durations = [], []
    for index in range(img.n_frames):
        img.seek(index)
        frames.append(fn(img.convert("RGBA")))
        durations.append(img.info.get("duration", 100))
    first = frames[0]
    first.info["duration"] = durations
    first.info["loop"] = img.info.get("loop", 0)
    first._fb_frames = frames  # type: ignore[attr-defined]
    return first


def _save_tool_result(result: Image.Image, dst: Path, fmt: str, keep_metadata: bool = True) -> Path:
    frames = getattr(result, "_fb_frames", None)
    if frames and fmt in ANIMATED_FORMATS:
        extra = {"save_all": True, "append_images": frames[1:], "duration": result.info.get("duration", 100),
                 "loop": result.info.get("loop", 0)}
        if fmt == "webp":
            extra.update(quality=90, method=4)
        frames[0].save(dst, PIL_FORMAT[fmt], **extra)
        return dst
    return save_image(result, dst, fmt, SaveOptions(quality=92 if fmt in LOSSY_FORMATS else None,
                                                    keep_metadata=keep_metadata))


def resize_image(src: Path, dst: Path, fmt: str, preset: str | None = None,
                 size: tuple[int, int] | None = None) -> Path:
    img = open_image(src)
    width, height = img.size

    if size is not None:
        target = size
    elif preset in RESIZE_PRESETS and preset.startswith("p"):
        factor = int(preset[1:]) / 100
        target = (max(1, round(width * factor)), max(1, round(height * factor)))
    elif preset in RESIZE_PRESETS:
        side = int(preset[1:])
        scale = min(1.0, side / max(width, height))
        target = (max(1, round(width * scale)), max(1, round(height * scale)))
    else:
        raise ImageError("bad_params")
    if not (1 <= target[0] <= 10000 and 1 <= target[1] <= 10000):
        raise ImageError("bad_params")

    result = _apply_frames(img, lambda frame: frame.resize(target, Image.Resampling.LANCZOS))
    return _save_tool_result(result, dst, fmt)


def crop_image(src: Path, dst: Path, fmt: str, preset: str | None = None,
               box: tuple[int, int, int, int] | None = None) -> Path:
    """Crop to a centred aspect ratio (preset) or to an explicit box (x, y, w, h)."""
    img = open_image(src)
    width, height = img.size
    if box is not None:
        x, y, w, h = box
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
            raise ImageError("crop_outside")
        rect = (x, y, x + w, y + h)
    elif preset in CROP_PRESETS:
        rw, rh = CROP_PRESETS[preset]
        if width / height > rw / rh:
            new_w, new_h = round(height * rw / rh), height
        else:
            new_w, new_h = width, round(width * rh / rw)
        left, top = (width - new_w) // 2, (height - new_h) // 2
        rect = (left, top, left + new_w, top + new_h)
    else:
        raise ImageError("bad_params")
    result = _apply_frames(img, lambda frame: frame.crop(rect))
    return _save_tool_result(result, dst, fmt)


def rotate_image(src: Path, dst: Path, fmt: str, preset: str) -> Path:
    ops = {
        "90": Image.Transpose.ROTATE_270,   # Pillow rotates counter-clockwise; 90 = clockwise
        "180": Image.Transpose.ROTATE_180,
        "270": Image.Transpose.ROTATE_90,
        "fh": Image.Transpose.FLIP_LEFT_RIGHT,
        "fv": Image.Transpose.FLIP_TOP_BOTTOM,
    }
    if preset not in ops:
        raise ImageError("bad_params")
    img = open_image(src)
    result = _apply_frames(img, lambda frame: frame.transpose(ops[preset]))
    return _save_tool_result(result, dst, fmt)


def grayscale_image(src: Path, dst: Path, fmt: str) -> Path:
    img = open_image(src)

    def to_gray(frame: Image.Image) -> Image.Image:
        if _has_alpha(frame):
            rgba = frame.convert("RGBA")
            gray = ImageOps.grayscale(rgba).convert("LA")
            gray.putalpha(rgba.getchannel("A"))
            return gray
        return ImageOps.grayscale(frame.convert("RGB"))

    result = _apply_frames(img, to_gray)
    if fmt == "jpg" and result.mode == "LA":
        result = result.convert("L")
    return _save_tool_result(result, dst, fmt)


def strip_metadata(src: Path, dst: Path, fmt: str) -> Path:
    """Re-save without EXIF/XMP/GPS. The ICC colour profile is kept so colours do not shift."""
    img = open_image(src)
    try:
        return save_image(img, dst, fmt, SaveOptions(quality=95 if fmt in LOSSY_FORMATS else None,
                                                     keep_metadata=False))
    finally:
        img.close()


def has_metadata(path: Path) -> bool:
    with Image.open(path) as img:
        return bool(len(img.getexif())) or any(k in img.info for k in ("exif", "xmp", "XML:com.adobe.xmp"))
