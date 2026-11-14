"""Audio and video operations exposed to the bot (FFmpeg)."""
from __future__ import annotations

from pathlib import Path

from services import media_service as media
from services import pdf_service
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
from utils.size_formatter import format_duration
from utils.validators import file_stem

LOSSY_AUDIO = {"mp3", "aac", "m4a", "ogg", "opus"}
AUDIO_BITRATES = (320, 192, 128, 96)


def _ffmpeg() -> str:
    path = ffmpeg_path()
    if not path:
        raise OperationError("unsupported_target")
    return path


def quality_to_bitrate(quality: int | None) -> int:
    """The convert widget offers quality 95/85/70/50; for audio these mean 320/192/128/96 kbps."""
    quality = quality or 85
    if quality >= 95:
        return 320
    if quality >= 85:
        return 192
    if quality >= 70:
        return 128
    return 96


def _duration(file: FileContext) -> float:
    return float(file.meta.get("duration") or 0)


def _trim_prompt(file: FileContext, lang: str) -> str:
    return t(lang, "in_trim", d=format_duration(_duration(file)) or "?")


def _parse_trim(file: FileContext, text: str) -> dict:
    try:
        start, end = media.parse_time_range(text, _duration(file))
    except media.MediaError as exc:
        raise OperationError(exc.code) from exc
    return {"start": start, "end": end}


async def _run_media(coro):  # noqa: ANN001, ANN202
    try:
        return await coro
    except media.MediaError as exc:
        raise OperationError(exc.code, str(exc)) from exc


# ============================================================================= audio


class AudioProcessor(Processor):
    kind = "audio"
    tools_title_key = "tl_media"

    @staticmethod
    def _source_format(file: FileContext) -> str:
        return file.extension if file.extension in media.AUDIO_FORMATS else "mp3"

    def convert_targets(self, file: FileContext) -> list[str]:
        if not ffmpeg_path():
            return []
        return [fmt for fmt in media.AUDIO_FORMATS if fmt != file.extension]

    def lossy_targets(self) -> set[str]:
        return set(LOSSY_AUDIO)

    def _compress_format(self, file: FileContext) -> str:
        """Lossy sources keep their format; lossless ones become MP3 (with a warning)."""
        return file.extension if file.extension in LOSSY_AUDIO else "mp3"

    def _available_bitrates(self, file: FileContext) -> list[int]:
        source_k = int(file.meta.get("abitrate") or 0) // 1000
        if file.extension in LOSSY_AUDIO and source_k:
            return [b for b in AUDIO_BITRATES if b < source_k * 0.9]
        return list(AUDIO_BITRATES)

    def compress_spec(self, file: FileContext, lang: str, default_quality: int, default_mode: str) -> CompressSpec | None:
        if not ffmpeg_path():
            return None
        bitrates = self._available_bitrates(file)
        if not bitrates:
            return None
        fmt = self._compress_format(file).upper()
        lossy_note = "" if file.extension in LOSSY_AUDIO else " · " + t(lang, "a_lossy")
        modes = [CompressMode(str(b), f"{b} kbps", f"{fmt} · {b} kbps{lossy_note}") for b in bitrates]
        preferred = {"mq": bitrates[0], "bal": 192 if 192 in bitrates else bitrates[len(bitrates) // 2],
                     "max": bitrates[-1]}.get(default_mode, bitrates[0])
        return CompressSpec(modes, str(preferred), False, default_quality, [])

    def tools(self, file: FileContext, lang: str) -> list[ToolSpec]:
        if not ffmpeg_path():
            return []
        rate = int(file.meta.get("sample_rate") or 0)
        channels = int(file.meta.get("channels") or 0)
        tools = [ToolSpec("tr", t(lang, "t_tr"), "tm", input=True)]
        rates = [(str(r), f"{r / 1000:g} kHz") for r in (48000, 44100, 22050, 16000) if r != rate]
        tools.append(ToolSpec("sr", t(lang, "t_sr"), "au", rates))
        layouts = [(c, t(lang, label)) for c, label in (("1", "o_mono"), ("2", "o_stereo")) if int(c) != channels]
        if layouts:
            tools.append(ToolSpec("ch", t(lang, "t_ch"), "au", layouts))
        return tools

    def input_prompt(self, file: FileContext, tool: str, lang: str) -> str | None:
        return _trim_prompt(file, lang) if tool == "tr" else None

    def parse_text_input(self, file: FileContext, tool: str, text: str) -> dict:
        if tool != "tr":
            raise OperationError("bad_params")
        return _parse_trim(file, text)

    def operation_label(self, file: FileContext, request: OperationRequest, lang: str) -> str:
        src = file.extension.upper()
        if request.category == CATEGORY_CONVERT:
            return f"{src} → {request.name.upper()}"
        if request.category == CATEGORY_COMPRESS:
            return f"{t(lang, 'cz_t')} · {request.name} kbps"
        tool = next((x for x in self.tools(file, lang) if x.id == request.name), None)
        label = tool.label if tool else request.name
        option = request.params.get("option")
        if tool and option:
            label += " · " + dict(tool.options).get(option, option)
        return label

    def operation_warning(self, file: FileContext, request: OperationRequest, lang: str) -> str | None:
        target = request.name if request.category == CATEGORY_CONVERT else (
            self._compress_format(file) if request.category == CATEGORY_COMPRESS else None)
        if target is None:
            return None
        if file.extension not in LOSSY_AUDIO and target in LOSSY_AUDIO:
            return t(lang, "warn_lossy")
        if file.extension in LOSSY_AUDIO and target in media.LOSSLESS_AUDIO:
            return t(lang, "warn_no_gain")
        return None

    async def run(self, file: FileContext, request: OperationRequest, source: Path, workspace: TaskWorkspace,
                  progress: ProgressCallback, lang: str, extra_sources: list[Path]) -> OperationResult:
        ffmpeg = _ffmpeg()
        duration = _duration(file)
        name, params = request.name, request.params

        if request.category == CATEGORY_CONVERT:
            if name not in self.convert_targets(file):
                raise OperationError("unsupported_target")
            bitrate = quality_to_bitrate(params.get("quality")) if name in LOSSY_AUDIO else None
            out = workspace.output_path(name)
            await _run_media(media.convert_audio(ffmpeg, source, out, name, duration,
                                                 media.AudioOptions(bitrate_k=bitrate), progress))
            return OperationResult(out, name, f"{name.upper()}" + (f" · {bitrate} kbps" if bitrate else ""))

        if request.category == CATEGORY_COMPRESS:
            bitrate = int(name)
            fmt = self._compress_format(file)
            out = workspace.output_path(fmt)
            await _run_media(media.convert_audio(ffmpeg, source, out, fmt, duration,
                                                 media.AudioOptions(bitrate_k=bitrate), progress))
            return OperationResult(out, fmt, f"{fmt.upper()} · {bitrate} kbps")

        if request.category == CATEGORY_TOOL:
            fmt = self._source_format(file)
            keep_k = min(320, max(96, int(file.meta.get("abitrate") or 192000) // 1000))
            bitrate = keep_k if fmt in LOSSY_AUDIO else None
            out = workspace.output_path(fmt)
            if name == "tr" and "start" in params:
                options = media.AudioOptions(bitrate_k=bitrate, start=params["start"], end=params["end"])
                details = f"{format_duration(params['start'])}–{format_duration(params['end'])}"
            elif name == "sr":
                options = media.AudioOptions(bitrate_k=bitrate, sample_rate=int(params["option"]))
                details = f"{int(params['option']) / 1000:g} kHz"
            elif name == "ch":
                options = media.AudioOptions(bitrate_k=bitrate, channels=int(params["option"]))
                details = t(lang, "o_mono" if params["option"] == "1" else "o_stereo")
            else:
                raise OperationError("bad_params")
            await _run_media(media.convert_audio(ffmpeg, source, out, fmt, duration, options, progress))
            return OperationResult(out, fmt, details)
        raise OperationError("bad_params")


# ============================================================================= video

# mode -> (max short side, crf, max bitrate kbit/s, audio kbit/s)
VIDEO_PRESETS = {
    "sm": (480, 30, 1000, 96),
    "bal": (720, 26, 2500, 128),
    "hq": (1080, 22, 6000, 160),
}
VIDEO_RESOLUTIONS = (1080, 720, 480, 360)


def quality_to_crf(quality: int) -> int:
    """Custom quality 10..100 -> x264 CRF 38..18 (lower CRF = better quality, bigger file)."""
    return round(40 - quality * 0.22)


class VideoProcessor(Processor):
    kind = "video"
    tools_title_key = "tl_media"

    @staticmethod
    def _short_side(file: FileContext) -> int:
        width, height = int(file.meta.get("width") or 0), int(file.meta.get("height") or 0)
        return min(width, height) if width and height else 0

    @staticmethod
    def _container(file: FileContext) -> str:
        return file.extension if file.extension in media.VIDEO_FORMATS else "mp4"

    def convert_targets(self, file: FileContext) -> list[str]:
        if not ffmpeg_path():
            return []
        return [fmt for fmt in (*media.VIDEO_FORMATS, "gif") if fmt != file.extension]

    def _compress_container(self, file: FileContext) -> str:
        return "webm" if file.extension == "webm" else "mp4"

    def compress_spec(self, file: FileContext, lang: str, default_quality: int, default_mode: str) -> CompressSpec | None:
        if not ffmpeg_path():
            return None
        short = self._short_side(file)
        container = self._compress_container(file).upper()
        modes = []
        for mode, (side, crf, maxrate, audio) in VIDEO_PRESETS.items():
            size = f"≤{side}p" if not short or side < short else t(lang, "plan_keep")
            modes.append(CompressMode(mode, t(lang, f"cz_v{mode}"),
                                      f"{container} · {size} · CRF {crf} · ≤{maxrate / 1000:g} Mbit/s · {audio}k"))
        modes.append(CompressMode("cus", t(lang, "cz_cus"), t(lang, "cz_cus_d")))
        resolutions = [("o", t(lang, "cz_orig"))] + [
            (str(r), f"{r}p") for r in VIDEO_RESOLUTIONS if not short or r < short]
        default = {"mq": "hq", "bal": "bal", "max": "sm"}.get(default_mode, "bal")
        return CompressSpec(modes, default, True, default_quality, resolutions[:4])

    def tools(self, file: FileContext, lang: str) -> list[ToolSpec]:
        if not ffmpeg_path():
            return []
        tools = []
        if file.meta.get("has_audio", True):
            tools.append(ToolSpec("ea", t(lang, "t_ea"), "au", [("mp3", "MP3"), ("m4a", "M4A"), ("wav", "WAV")]))
        tools += [
            ToolSpec("fr", t(lang, "t_fr"), "fr",
                     [("1", t(lang, "o_fr_1")), ("5", t(lang, "o_fr_5")), ("n10", t(lang, "o_fr_10"))]),
            ToolSpec("tr", t(lang, "t_tr"), "tm", input=True),
            ToolSpec("gf", t(lang, "t_gf"), "gf"),
        ]
        short = self._short_side(file)
        resolutions = [(str(r), f"{r}p") for r in VIDEO_RESOLUTIONS if short and r < short]
        if resolutions:
            tools.append(ToolSpec("re", t(lang, "t_re"), "rs", resolutions))
        fps = float(file.meta.get("fps") or 0)
        rates = [(str(r), f"{r} fps") for r in (30, 24, 15) if fps and r < fps - 0.5]
        if rates:
            tools.append(ToolSpec("fp", t(lang, "t_fp"), "fr", rates))
        return tools

    def input_prompt(self, file: FileContext, tool: str, lang: str) -> str | None:
        return _trim_prompt(file, lang) if tool == "tr" else None

    def parse_text_input(self, file: FileContext, tool: str, text: str) -> dict:
        if tool != "tr":
            raise OperationError("bad_params")
        return _parse_trim(file, text)

    def operation_label(self, file: FileContext, request: OperationRequest, lang: str) -> str:
        if request.category == CATEGORY_CONVERT:
            return f"{file.extension.upper()} → {request.name.upper()}"
        if request.category == CATEGORY_COMPRESS:
            mode = t(lang, "cz_cus") if request.name == "cus" else t(lang, f"cz_v{request.name}")
            return f"{t(lang, 'cz_t')} · {mode}"
        tool = next((x for x in self.tools(file, lang) if x.id == request.name), None)
        label = tool.label if tool else request.name
        option = request.params.get("option")
        if tool and option:
            label += " · " + dict(tool.options).get(option, option)
        return label

    async def run(self, file: FileContext, request: OperationRequest, source: Path, workspace: TaskWorkspace,
                  progress: ProgressCallback, lang: str, extra_sources: list[Path]) -> OperationResult:
        ffmpeg = _ffmpeg()
        meta, duration = file.meta, _duration(file)
        name, params = request.name, request.params
        stem = file_stem(file.name)

        if request.category == CATEGORY_CONVERT:
            if name not in self.convert_targets(file):
                raise OperationError("unsupported_target")
            out = workspace.output_path(name)
            if name == "gif":
                await _run_media(media.video_to_gif(ffmpeg, source, out, duration, progress=progress))
                return OperationResult(out, "gif", self._gif_details(duration, lang))
            _, copied = await _run_media(media.convert_video(ffmpeg, source, out, name, meta, None, progress))
            return OperationResult(out, name, f"{name.upper()} · " + (t(lang, "d_copy") if copied else "H.264/VP9"))

        if request.category == CATEGORY_COMPRESS:
            container = self._compress_container(file)
            if name == "cus":
                resolution = params.get("resolution", "o")
                options = media.VideoOptions(crf=quality_to_crf(int(params["quality"])),
                                             max_short_side=None if resolution == "o" else int(resolution))
                details = f"CRF {options.crf}" + (f" · ≤{resolution}p" if resolution != "o" else "")
            else:
                side, crf, maxrate, audio = VIDEO_PRESETS[name]
                options = media.VideoOptions(crf=crf, max_short_side=side, max_bitrate_k=maxrate,
                                             audio_bitrate_k=audio)
                details = f"CRF {crf} · ≤{side}p · {audio}k"
            out = workspace.output_path(container)
            await _run_media(media.convert_video(ffmpeg, source, out, container, meta, options, progress))
            return OperationResult(out, container, details)

        if request.category == CATEGORY_TOOL:
            option = params.get("option")
            container = self._container(file)
            if name == "ea":
                out = workspace.output_path(option)
                await _run_media(media.extract_audio(ffmpeg, source, out, option, meta, progress))
                return OperationResult(out, option, option.upper())
            if name == "fr":
                every, count = (None, 10) if option == "n10" else (float(option), None)
                frames = await _run_media(media.extract_frames(
                    ffmpeg, source, workspace.subdir("frames"), stem, every, count, duration, progress))
                if len(frames) == 1:
                    return OperationResult(frames[0], "jpg", "JPG")
                archive = pdf_service.zip_files(frames, workspace.output_path("zip", f"{stem}_frames"))
                return OperationResult(archive, "zip", t(lang, "d_frames", n=len(frames)))
            if name == "gf":
                out = workspace.output_path("gif")
                await _run_media(media.video_to_gif(ffmpeg, source, out, duration, progress=progress))
                return OperationResult(out, "gif", self._gif_details(duration, lang))
            out = workspace.output_path(container)
            if name == "tr" and "start" in params:
                options = media.VideoOptions(crf=20, start=params["start"], end=params["end"], audio_bitrate_k=160)
                details = f"{format_duration(params['start'])}–{format_duration(params['end'])}"
            elif name == "re":
                options = media.VideoOptions(crf=21, max_short_side=int(option), audio_bitrate_k=160)
                details = f"{option}p"
            elif name == "fp":
                options = media.VideoOptions(crf=21, fps=float(option), audio_bitrate_k=160)
                details = f"{option} fps"
            else:
                raise OperationError("bad_params")
            await _run_media(media.convert_video(ffmpeg, source, out, container, meta, options, progress))
            return OperationResult(out, container, details)
        raise OperationError("bad_params")

    @staticmethod
    def _gif_details(duration: float, lang: str) -> str:
        if duration > media.GIF_MAX_SECONDS:
            return t(lang, "d_gif_cut", s=media.GIF_MAX_SECONDS)
        return "GIF · 12 fps · ≤480px"


register(AudioProcessor())
register(VideoProcessor())
