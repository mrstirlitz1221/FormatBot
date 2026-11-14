"""Image operations exposed to the bot: conversion, compression and image tools."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from services import image_service as img
from services import media_service as media
from services.external_tools import ffmpeg_path
from services.operations import (
    CATEGORY_COMPRESS,
    CATEGORY_CONVERT,
    CATEGORY_TOOL,
    CompressMode,
    CompressSpec,
    FileContext,
    OperationError,
    OperationRequest,
    OperationResult,
    ProgressCallback,
    Processor,
    ToolSpec,
    register,
)
from utils.file_manager import TaskWorkspace
from utils.i18n import t

_SIZE_RE = re.compile(r"^\s*(\d{1,5})?\s*[xх×*]\s*(\d{1,5})?\s*$", re.IGNORECASE)
_CROP_RE = re.compile(r"^\s*(\d{1,5})\s*[xх×*]\s*(\d{1,5})\s*\+\s*(\d{1,5})\s*\+\s*(\d{1,5})\s*$", re.IGNORECASE)


def _fmt_name(ext: str) -> str:
    return {"jpg": "JPEG"}.get(ext, ext.upper())


class ImageProcessor(Processor):
    kind = "image"
    tools_title_key = "tl_image"

    def convert_targets(self, file: FileContext) -> list[str]:
        if file.extension not in img.readable_formats():
            return []
        targets = img.convert_targets(file.extension)
        if file.extension == "gif" and file.meta.get("frames", 1) > 1 and ffmpeg_path():
            targets += ["mp4", "webm"]  # animated GIF -> video
        return targets

    def lossy_targets(self) -> set[str]:
        return set(img.LOSSY_FORMATS)

    # ------------------------------------------------------------------ compression

    def describe_plan(self, plan: img.CompressPlan, source_ext: str, lang: str) -> str:
        if source_ext == "bmp":
            base = t(lang, "plan_bmp")
        elif plan.quality is not None:
            base = t(lang, "plan_q", fmt=_fmt_name(plan.fmt), q=plan.quality)
        elif plan.palette_colors:
            base = t(lang, "plan_palette", fmt=_fmt_name(plan.fmt), colors=plan.palette_colors)
        else:
            base = t(lang, "plan_lossless", fmt=_fmt_name(plan.fmt))
        size = t(lang, "plan_side", side=plan.max_side) if plan.max_side else t(lang, "plan_keep")
        return f"{base} · {size}"

    def compress_spec(self, file: FileContext, lang: str, default_quality: int, default_mode: str) -> CompressSpec | None:
        if file.extension not in img.readable_formats():
            return None
        modes = []
        for mode in ("mq", "bal", "max"):
            plan = img.plan_compression(file.extension, mode)
            modes.append(CompressMode(mode, t(lang, f"cz_{mode}"), self.describe_plan(plan, file.extension, lang)))
        modes.append(CompressMode("cus", t(lang, "cz_cus"), t(lang, "cz_cus_d")))
        longest = max(file.meta.get("width", 0), file.meta.get("height", 0))
        resolutions = [("o", t(lang, "cz_orig"))] + [
            (key, f"≤{key}") for key in ("2560", "1920", "1280", "720") if int(key) < longest
        ]
        return CompressSpec(
            modes=modes,
            default_mode=default_mode if default_mode in {"mq", "bal", "max"} else "bal",
            custom=True,
            default_quality=default_quality,
            resolutions=resolutions[:4],
        )

    # ------------------------------------------------------------------ tools

    def tools(self, file: FileContext, lang: str) -> list[ToolSpec]:
        if file.extension not in img.readable_formats():
            return []
        custom = t(lang, "o_custom")
        longest = max(file.meta.get("width", 0), file.meta.get("height", 0))
        sizes = [(p, f"≤{p[1:]}") for p in ("s1920", "s1280", "s720") if int(p[1:]) < longest]
        return [
            ToolSpec("rs", t(lang, "t_rs"), "rs",
                     [("p75", "75%"), ("p50", "50%"), ("p25", "25%"), *sizes, ("in", custom)],
                     frozenset({"in"})),
            ToolSpec("cr", t(lang, "t_cr"), "cr",
                     [("1x1", "1:1"), ("4x3", "4:3"), ("3x4", "3:4"), ("16x9", "16:9"), ("9x16", "9:16"),
                      ("in", custom)],
                     frozenset({"in"})),
            ToolSpec("ro", t(lang, "t_ro"), "ro",
                     [("90", t(lang, "o_90")), ("180", t(lang, "o_180")), ("270", t(lang, "o_270")),
                      ("fh", t(lang, "o_fh")), ("fv", t(lang, "o_fv"))]),
            ToolSpec("gr", t(lang, "t_gr"), "gr"),
            ToolSpec("pd", t(lang, "t_pd"), "pd",
                     [("1", t(lang, "o_this")), ("mu", t(lang, "o_many"))], collect_options=frozenset({"mu"})),
            ToolSpec("mt", t(lang, "t_mt"), "mt"),
            ToolSpec("op", t(lang, "t_op"), "op"),
        ]

    @staticmethod
    def parse_size_input(text: str, width: int, height: int) -> tuple[int, int]:
        match = _SIZE_RE.match(text or "")
        if not match or not (match.group(1) or match.group(2)):
            raise OperationError("bad_params")
        new_w = int(match.group(1)) if match.group(1) else None
        new_h = int(match.group(2)) if match.group(2) else None
        if new_w is None:
            new_w = max(1, round(width * new_h / height))
        if new_h is None:
            new_h = max(1, round(height * new_w / width))
        if not (1 <= new_w <= 10000 and 1 <= new_h <= 10000):
            raise OperationError("bad_params")
        return new_w, new_h

    @staticmethod
    def parse_crop_input(text: str, width: int, height: int) -> tuple[int, int, int, int]:
        match = _CROP_RE.match(text or "")
        if not match:
            raise OperationError("bad_params")
        w, h, x, y = (int(g) for g in match.groups())
        if w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise OperationError("crop_outside")
        return x, y, w, h

    def input_prompt(self, file: FileContext, tool: str, lang: str) -> str | None:
        width, height = file.meta.get("width", 0), file.meta.get("height", 0)
        key = {"rs": "in_resize", "cr": "in_crop"}.get(tool)
        return t(lang, key, w=width, h=height) if key else None

    def parse_text_input(self, file: FileContext, tool: str, text: str) -> dict:
        width, height = file.meta.get("width", 0), file.meta.get("height", 0)
        if not width or not height:
            raise OperationError("bad_params")
        if tool == "rs":
            return {"option": "in", "size": self.parse_size_input(text, width, height)}
        if tool == "cr":
            return {"option": "in", "box": self.parse_crop_input(text, width, height)}
        raise OperationError("bad_params")

    def collect_kind(self, tool: str) -> str | None:
        return "image" if tool == "pd" else None

    # ------------------------------------------------------------------ labels

    def operation_label(self, file: FileContext, request: OperationRequest, lang: str) -> str:
        src = _fmt_name(file.extension)
        if request.category == CATEGORY_CONVERT:
            return f"{src} → {_fmt_name(request.name)}"
        if request.category == CATEGORY_COMPRESS:
            return f"{t(lang, 'cz_t')} · {t(lang, 'cz_' + request.name)}"
        tool = next((x for x in self.tools(file, lang) if x.id == request.name), None)
        label = tool.label if tool else request.name
        option = request.params.get("option")
        if tool and option and option not in {"in", "mu", "1"}:
            label += " · " + dict(tool.options).get(option, option)
        return label

    # ------------------------------------------------------------------ execution

    async def run(self, file: FileContext, request: OperationRequest, source: Path,
                  workspace: TaskWorkspace, progress: ProgressCallback, lang: str,
                  extra_sources: list[Path]) -> OperationResult:
        if request.category == CATEGORY_CONVERT and request.name in {"mp4", "webm"}:
            if request.name not in self.convert_targets(file):
                raise OperationError("unsupported_target")
            out = workspace.output_path(request.name)
            try:
                await media.gif_to_video(ffmpeg_path(), source, out, request.name, progress)
            except media.MediaError as exc:
                raise OperationError(exc.code, str(exc)) from exc
            return OperationResult(out, request.name, request.name.upper())
        try:
            return await asyncio.to_thread(self._run_sync, file, request, source, workspace, lang, extra_sources)
        except img.ImageError as exc:
            raise OperationError(exc.code, str(exc)) from exc

    def _run_sync(self, file: FileContext, request: OperationRequest, source: Path,
                  workspace: TaskWorkspace, lang: str, extra_sources: list[Path]) -> OperationResult:
        ext = file.extension
        if request.category == CATEGORY_CONVERT:
            target = request.name
            out = workspace.output_path(target)
            img.convert_image(source, out, target, request.params.get("quality"))
            quality = request.params.get("quality")
            return OperationResult(out, target, f"{_fmt_name(target)}" + (f" · q{quality}" if quality else ""))

        if request.category == CATEGORY_COMPRESS:
            plan = img.plan_compression(ext, request.name, request.params.get("quality"),
                                        request.params.get("resolution"))
            out = img.compress_image(source, workspace.path, plan)
            return OperationResult(out, plan.fmt, self.describe_plan(plan, ext, lang))

        if request.category == CATEGORY_TOOL:
            fmt = img.tool_output_format(ext)
            option = request.params.get("option")
            name = request.name
            if name == "pd":
                out = workspace.output_path("pdf")
                img.images_to_pdf([source, *extra_sources], out)
                return OperationResult(out, "pdf", f"PDF · {1 + len(extra_sources)}")
            out = workspace.output_path(fmt)
            if name == "rs":
                size = request.params.get("size")
                img.resize_image(source, out, fmt, preset=None if size else option, size=size)
            elif name == "cr":
                box = request.params.get("box")
                img.crop_image(source, out, fmt, preset=None if box else option, box=box)
            elif name == "ro":
                img.rotate_image(source, out, fmt, option)
            elif name == "gr":
                img.grayscale_image(source, out, fmt)
            elif name == "mt":
                img.strip_metadata(source, out, fmt)
            elif name == "op":
                plan = img.plan_compression(ext, "bal")
                out = img.compress_image(source, workspace.path, plan)
                return OperationResult(out, plan.fmt, self.describe_plan(plan, ext, lang))
            else:
                raise OperationError("bad_params")
            return OperationResult(out, fmt, _fmt_name(fmt))

        raise OperationError("bad_params")


register(ImageProcessor())
