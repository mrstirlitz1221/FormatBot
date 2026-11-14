"""Operation registry: what can be done with each kind of file, and how requests are parsed.

The same short action strings are used by widget requests (TelegramWidget.request, <=64 bytes)
and by fallback inline keyboards (callback_data, <=64 bytes):

  convert   go:<fmt>[:<quality>]
  compress  go:<mode>  |  go:cus:<quality>:<resolution>
  tools     t:<tool>[:<option>]

Every value is validated against the processor's own lists, never trusted.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from utils.file_manager import TaskWorkspace

CATEGORY_CONVERT = "convert"
CATEGORY_COMPRESS = "compress"
CATEGORY_TOOL = "tool"


class OperationError(Exception):
    """A user-facing failure; ``code`` maps to the i18n key ``err_<code>``."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class OperationRequest:
    category: str
    name: str                                  # target format / compress mode / tool id
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def history_type(self) -> str:
        return self.category if self.category != CATEGORY_TOOL else f"tool:{self.name}"


@dataclass(frozen=True)
class ToolSpec:
    id: str
    label: str
    icon: str
    options: list[tuple[str, str]] = field(default_factory=list)  # (option id, label)
    input_options: frozenset[str] = frozenset()    # options that ask for text in the chat
    collect_options: frozenset[str] = frozenset()  # options that collect more files in the chat
    collect: bool = False                          # the tool itself (no options) collects files
    input: bool = False                            # the tool itself (no options) asks for text


@dataclass(frozen=True)
class CompressMode:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class CompressSpec:
    modes: list[CompressMode]
    default_mode: str
    custom: bool
    default_quality: int
    resolutions: list[tuple[str, str]]   # (id, label)


@dataclass(frozen=True)
class FileContext:
    """What processors know about the uploaded file (from the database record)."""

    kind: str
    extension: str
    name: str
    size: int
    meta: dict[str, Any]


@dataclass
class OperationResult:
    path: Path
    extension: str
    details: str = ""       # short line for the result card, e.g. "JPEG · quality 80"


ProgressCallback = Callable[[int], None]


class Processor(ABC):
    """Operations for one kind of file."""

    kind: str
    tools_title_key: str = ""

    @abstractmethod
    def convert_targets(self, file: FileContext) -> list[str]: ...

    def lossy_targets(self) -> set[str]:
        return set()

    @abstractmethod
    def compress_spec(self, file: FileContext, lang: str, default_quality: int, default_mode: str) -> CompressSpec | None: ...

    @abstractmethod
    def tools(self, file: FileContext, lang: str) -> list[ToolSpec]: ...

    @abstractmethod
    def operation_label(self, file: FileContext, request: OperationRequest, lang: str) -> str: ...

    @abstractmethod
    async def run(self, file: FileContext, request: OperationRequest, source: Path,
                  workspace: TaskWorkspace, progress: ProgressCallback, lang: str,
                  extra_sources: list[Path]) -> OperationResult: ...

    # -------------------------------------------------------------- chat input (optional)

    def input_prompt(self, file: FileContext, tool: str, lang: str) -> str | None:
        """Text asking for parameters of a tool option that needs typed input."""
        return None

    def parse_text_input(self, file: FileContext, tool: str, text: str) -> dict[str, Any]:
        """Validate typed parameters; returns request params. Raises OperationError."""
        raise OperationError("bad_params")

    def operation_warning(self, file: FileContext, request: OperationRequest, lang: str) -> str | None:
        """An honest note shown when the task starts (e.g. quality loss)."""
        return None

    def collect_kind(self, tool: str) -> str | None:
        """Kind of files a collecting tool accepts (e.g. 'pdf' for merge)."""
        return None

    # -------------------------------------------------------------- parsing (shared)

    def parse_convert(self, file: FileContext, data: str, default_quality: int) -> OperationRequest:
        parts = data.split(":")
        if len(parts) not in (2, 3) or parts[0] != "go":
            raise OperationError("bad_params")
        target = parts[1]
        if target not in self.convert_targets(file):
            raise OperationError("unsupported_target")
        quality = None
        if target in self.lossy_targets():
            quality = default_quality
            if len(parts) == 3:
                quality = _int_in(parts[2], 10, 100)
        elif len(parts) == 3:
            raise OperationError("bad_params")
        return OperationRequest(CATEGORY_CONVERT, target, {"quality": quality})

    def parse_compress(self, file: FileContext, data: str, lang: str) -> OperationRequest:
        spec = self.compress_spec(file, lang, 75, "bal")
        if spec is None:
            raise OperationError("bad_params")
        parts = data.split(":")
        if len(parts) < 2 or parts[0] != "go":
            raise OperationError("bad_params")
        mode = parts[1]
        if mode == "cus":
            if not spec.custom or len(parts) != 4:
                raise OperationError("bad_params")
            quality = _int_in(parts[2], 10, 100)
            resolution = parts[3]
            if resolution not in {r for r, _ in spec.resolutions}:
                raise OperationError("bad_params")
            return OperationRequest(CATEGORY_COMPRESS, "cus", {"quality": quality, "resolution": resolution})
        if len(parts) != 2 or mode not in {m.id for m in spec.modes}:
            raise OperationError("bad_params")
        return OperationRequest(CATEGORY_COMPRESS, mode, {})

    def parse_tool(self, file: FileContext, data: str, lang: str) -> tuple[OperationRequest, str | None]:
        """Returns (request, interaction): interaction is None, 'input' or 'collect'."""
        parts = data.split(":")
        if len(parts) not in (2, 3) or parts[0] != "t":
            raise OperationError("bad_params")
        tools = {tool.id: tool for tool in self.tools(file, lang)}
        tool = tools.get(parts[1])
        if tool is None:
            raise OperationError("bad_params")
        option = parts[2] if len(parts) == 3 else None
        valid_options = {o for o, _ in tool.options}
        if tool.options and option not in valid_options:
            raise OperationError("bad_params")
        if not tool.options and option is not None:
            raise OperationError("bad_params")
        request = OperationRequest(CATEGORY_TOOL, tool.id, {"option": option})
        if option in tool.input_options or (tool.input and option is None):
            return request, "input"
        if option in tool.collect_options or (tool.collect and option is None):
            return request, "collect"
        return request, None


def _int_in(raw: str, lo: int, hi: int) -> int:
    if not raw.isdigit():
        raise OperationError("bad_params")
    value = int(raw)
    if not lo <= value <= hi:
        raise OperationError("bad_params")
    return value


# ----------------------------------------------------------------------------- registry

_PROCESSORS: dict[str, Processor] = {}


def register(processor: Processor) -> None:
    _PROCESSORS[processor.kind] = processor


def get_processor(kind: str) -> Processor | None:
    return _PROCESSORS.get(kind)


def available_actions(file: FileContext, lang: str) -> list[str]:
    """Top-level actions for the file widget: only what really works for this file."""
    processor = get_processor(file.kind)
    if processor is None:
        return []
    actions = []
    if processor.convert_targets(file):
        actions.append("cv")
    if processor.compress_spec(file, lang, 75, "bal") is not None:
        actions.append("cz")
    if processor.tools(file, lang):
        actions.append("tl")
    return actions
