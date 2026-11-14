"""PDF and office document operations exposed to the bot."""
from __future__ import annotations

import asyncio
from pathlib import Path

from services import document_service as docs
from services import pdf_service as pdf
from services.external_tools import ToolError, soffice_path
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
from utils.validators import ValidationError, file_stem, parse_page_ranges

# User's default compression mode (image terms) -> document levels.
_MODE_TO_LEVEL = {"mq": "lt", "bal": "md", "max": "st"}


def _upper(ext: str) -> str:
    return ext.upper()


def _many_or_one(paths: list[Path], workspace: TaskWorkspace, stem: str, details: str) -> OperationResult:
    """A single output file is sent as is; several are packed into one ZIP."""
    if len(paths) == 1:
        return OperationResult(paths[0], paths[0].suffix.lstrip("."), details)
    archive = pdf.zip_files(paths, workspace.output_path("zip", stem))
    return OperationResult(archive, "zip", f"{details} · {len(paths)}")


# ============================================================================= PDF


class PdfProcessor(Processor):
    kind = "pdf"
    tools_title_key = "tl_pdf"

    def convert_targets(self, file: FileContext) -> list[str]:
        return ["docx", "txt", "png", "jpg"]

    def compress_spec(self, file: FileContext, lang: str, default_quality: int, default_mode: str) -> CompressSpec:
        modes = [CompressMode(level, t(lang, f"cz_{level}"), t(lang, f"pdf_{level}_d"))
                 for level in pdf.COMPRESS_LEVELS]
        return CompressSpec(modes, _MODE_TO_LEVEL.get(default_mode, "md"), False, default_quality, [])

    def tools(self, file: FileContext, lang: str) -> list[ToolSpec]:
        pages = int(file.meta.get("pages", 0))
        tools = [ToolSpec("mg", t(lang, "t_mg"), "mg", collect=True)]
        if pages > 1:
            tools.append(ToolSpec("sp", t(lang, "t_sp"), "sp"))
        tools += [
            ToolSpec("im", t(lang, "t_im"), "im", [("png", "PNG"), ("jpg", "JPG")]),
            ToolSpec("tx", t(lang, "t_tx"), "tx"),
            ToolSpec("ro", t(lang, "t_ro"), "ro",
                     [("90", t(lang, "o_90")), ("180", t(lang, "o_180")), ("270", t(lang, "o_270"))]),
        ]
        if pages > 1:
            tools += [
                ToolSpec("dl", t(lang, "t_dl"), "dl", input=True),
                ToolSpec("ex", t(lang, "t_ex"), "ex", input=True),
                ToolSpec("rd", t(lang, "t_rd"), "rd", input=True),
            ]
        return tools

    def collect_kind(self, tool: str) -> str | None:
        return "pdf" if tool == "mg" else None

    def input_prompt(self, file: FileContext, tool: str, lang: str) -> str | None:
        key = {"dl": "in_pages_dl", "ex": "in_pages_ex", "rd": "in_pages_rd"}.get(tool)
        return t(lang, key, n=file.meta.get("pages", 0)) if key else None

    def parse_text_input(self, file: FileContext, tool: str, text: str) -> dict:
        count = int(file.meta.get("pages", 0))
        try:
            pages = parse_page_ranges(text, count)
        except ValidationError as exc:
            raise OperationError("bad_params") from exc
        if tool == "dl":
            removed = set(pages)
            keep = [i for i in range(count) if i not in removed]
            if not keep:
                raise OperationError("delete_all")
            return {"pages": keep, "removed": len(removed)}
        if tool == "ex":
            return {"pages": pages}
        if tool == "rd":
            if sorted(pages) != list(range(count)):
                raise OperationError("bad_reorder")
            return {"pages": pages}
        raise OperationError("bad_params")

    def operation_label(self, file: FileContext, request: OperationRequest, lang: str) -> str:
        if request.category == CATEGORY_CONVERT:
            return f"PDF → {_upper(request.name)}"
        if request.category == CATEGORY_COMPRESS:
            return f"{t(lang, 'cz_t')} · {t(lang, 'cz_' + request.name)}"
        tool = next((x for x in self.tools(file, lang) if x.id == request.name), None)
        label = tool.label if tool else request.name
        option = request.params.get("option")
        if tool and option:
            label += " · " + dict(tool.options).get(option, option)
        return label

    async def run(self, file: FileContext, request: OperationRequest, source: Path, workspace: TaskWorkspace,
                  progress: ProgressCallback, lang: str, extra_sources: list[Path]) -> OperationResult:
        try:
            return await asyncio.to_thread(self._run_sync, file, request, source, workspace, lang, extra_sources)
        except pdf.PdfError as exc:
            raise OperationError(exc.code, str(exc)) from exc

    def _run_sync(self, file: FileContext, request: OperationRequest, source: Path, workspace: TaskWorkspace,
                  lang: str, extra_sources: list[Path]) -> OperationResult:
        stem = file_stem(file.name)
        name, params = request.name, request.params

        if request.category == CATEGORY_CONVERT:
            if name == "docx":
                return OperationResult(pdf.pdf_to_docx(source, workspace.output_path("docx")), "docx", "DOCX")
            if name == "txt":
                return OperationResult(pdf.extract_text(source, workspace.output_path("txt")), "txt", "TXT · UTF-8")
            if name in {"png", "jpg"}:
                pages = pdf.pdf_to_images(source, workspace.subdir("pages"), stem, name)
                return _many_or_one(pages, workspace, stem, f"{_upper(name)} · 150 dpi")
            raise OperationError("unsupported_target")

        if request.category == CATEGORY_COMPRESS:
            out = pdf.compress_pdf(source, workspace.output_path("pdf"), name)
            return OperationResult(out, "pdf", t(lang, f"pdf_{name}_d"))

        if request.category == CATEGORY_TOOL:
            out = workspace.output_path("pdf")
            if name == "mg":
                pdf.merge_pdfs([source, *extra_sources], out)
                return OperationResult(out, "pdf", t(lang, "d_merged", n=1 + len(extra_sources)))
            if name == "sp":
                parts = pdf.split_pdf(source, workspace.subdir("parts"), stem)
                return _many_or_one(parts, workspace, f"{stem}_pages", "PDF")
            if name == "im":
                pages = pdf.pdf_to_images(source, workspace.subdir("pages"), stem, params["option"])
                return _many_or_one(pages, workspace, f"{stem}_images", _upper(params["option"]))
            if name == "tx":
                return OperationResult(pdf.extract_text(source, workspace.output_path("txt")), "txt", "TXT · UTF-8")
            if name == "ro":
                pdf.rotate_pdf(source, out, int(params["option"]))
                return OperationResult(out, "pdf", f"{params['option']}°")
            if name in {"dl", "ex", "rd"} and params.get("pages"):
                pdf.select_pages(source, out, params["pages"])
                return OperationResult(out, "pdf", t(lang, "d_pages", n=len(params["pages"])))
        raise OperationError("bad_params")


# ============================================================================= office documents

# Conversions done without LibreOffice (always available).
_BUILTIN = {
    ("txt", "pdf"): docs.text_to_pdf,
    ("txt", "docx"): docs.text_to_docx,
    ("csv", "pdf"): docs.csv_to_pdf,
    ("docx", "txt"): docs.docx_to_txt,
}
_BUILTIN_FALLBACK = {("html", "pdf"): docs.html_to_pdf}  # used only when LibreOffice is missing


class DocumentProcessor(Processor):
    kind = "document"
    tools_title_key = ""

    def convert_targets(self, file: FileContext) -> list[str]:
        ext = file.extension
        targets = docs.libreoffice_targets(ext) if soffice_path() else []
        for (src, dst) in (*_BUILTIN, *_BUILTIN_FALLBACK):
            if src == ext and dst not in targets:
                targets.append(dst)
        return targets

    def compress_spec(self, file: FileContext, lang: str, default_quality: int, default_mode: str) -> CompressSpec | None:
        if file.extension not in docs.ZIP_CONTAINERS:
            return None
        modes = [CompressMode(level, t(lang, f"cz_{level}"), t(lang, f"office_{level}_d"))
                 for level in docs.OFFICE_COMPRESS_LEVELS]
        return CompressSpec(modes, _MODE_TO_LEVEL.get(default_mode, "md"), False, default_quality, [])

    def tools(self, file: FileContext, lang: str) -> list[ToolSpec]:
        return []

    def operation_label(self, file: FileContext, request: OperationRequest, lang: str) -> str:
        if request.category == CATEGORY_CONVERT:
            return f"{_upper(file.extension)} → {_upper(request.name)}"
        return f"{t(lang, 'cz_t')} · {t(lang, 'cz_' + request.name)}"

    async def run(self, file: FileContext, request: OperationRequest, source: Path, workspace: TaskWorkspace,
                  progress: ProgressCallback, lang: str, extra_sources: list[Path]) -> OperationResult:
        try:
            if request.category == CATEGORY_CONVERT:
                return await self._convert(file, request.name, source, workspace)
            if request.category == CATEGORY_COMPRESS:
                out = workspace.output_path(file.extension)
                await asyncio.to_thread(docs.compress_office, source, out, request.name)
                return OperationResult(out, file.extension, t(lang, f"office_{request.name}_d"))
        except ToolError as exc:
            raise OperationError(exc.code, str(exc)) from exc
        raise OperationError("bad_params")

    async def _convert(self, file: FileContext, target: str, source: Path, workspace: TaskWorkspace) -> OperationResult:
        ext = file.extension
        if target not in self.convert_targets(file):
            raise OperationError("unsupported_target")
        key = (ext, target)
        builtin = _BUILTIN.get(key) or (None if soffice_path() else _BUILTIN_FALLBACK.get(key))
        if builtin is not None:
            out = await asyncio.to_thread(builtin, source, workspace.output_path(target))
            return OperationResult(out, target, _upper(target))
        soffice = soffice_path()
        if not soffice:
            raise OperationError("unsupported_target")
        out = await docs.libreoffice_convert(soffice, source, workspace.subdir("out"), target,
                                             workspace.subdir("lo_profile"))
        if target == "pdf":
            pdf.page_count(out)  # make sure the result opens
        return OperationResult(out, target, f"{_upper(target)} · LibreOffice")


register(PdfProcessor())
register(DocumentProcessor())
