"""Audio and video processing with FFmpeg / ffprobe.

Commands are built as argument lists; file paths always point inside the task workspace
(fixed names), so user-controlled text never reaches the command line.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from services.external_tools import ToolError, run_process_lines

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SEC = 30
FFMPEG_TIMEOUT_SEC = 1800
MAX_DURATION_SEC = 4 * 3600
GIF_MAX_SECONDS = 20
MAX_FRAMES = 100

AUDIO_FORMATS = ("mp3", "wav", "flac", "aac", "ogg", "m4a", "opus")
VIDEO_FORMATS = ("mp4", "mov", "mkv", "webm", "avi")
LOSSLESS_AUDIO = {"wav", "flac"}

# target audio format -> (codec args, uses bitrate)
_AUDIO_CODECS: dict[str, tuple[list[str], bool]] = {
    "mp3": (["-c:a", "libmp3lame"], True),
    "aac": (["-c:a", "aac", "-f", "adts"], True),
    "m4a": (["-c:a", "aac", "-movflags", "+faststart"], True),
    "ogg": (["-c:a", "libvorbis"], True),
    "opus": (["-c:a", "libopus", "-vbr", "on"], True),
    "wav": (["-c:a", "pcm_s16le"], False),
    "flac": (["-c:a", "flac", "-compression_level", "8"], False),
}

# container -> (video codec args, audio codec args)
_VIDEO_CODECS: dict[str, tuple[list[str], list[str]]] = {
    "mp4": (["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"], ["-c:a", "aac"]),
    "mov": (["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"], ["-c:a", "aac"]),
    "mkv": (["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"], ["-c:a", "aac"]),
    "avi": (["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"], ["-c:a", "libmp3lame"]),
    "webm": (["-c:v", "libvpx-vp9", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", "-pix_fmt", "yuv420p"],
             ["-c:a", "libopus"]),
}
# Codecs a container can hold as-is (stream copy instead of re-encoding).
_COPY_OK = {
    "mp4": ({"h264", "hevc"}, {"aac", "mp3"}),
    "mov": ({"h264", "hevc"}, {"aac", "mp3"}),
    "mkv": ({"h264", "hevc", "vp9", "vp8", "av1"}, {"aac", "mp3", "opus", "vorbis", "flac"}),
    "webm": ({"vp9", "vp8", "av1"}, {"opus", "vorbis"}),
}


class MediaError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


# ----------------------------------------------------------------------------- probing


@dataclass
class MediaInfo:
    duration: float
    format_names: set[str]
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    audio_bitrate: int = 0       # bits per second, 0 if unknown
    sample_rate: int = 0
    channels: int = 0
    bitrate: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def meta(self) -> dict[str, Any]:
        """Compact metadata stored with the uploaded file."""
        meta: dict[str, Any] = {"duration": round(self.duration, 2)}
        if self.has_video:
            meta.update(width=self.width, height=self.height, fps=round(self.fps, 2), vcodec=self.video_codec)
        if self.has_audio:
            meta.update(acodec=self.audio_codec, abitrate=self.audio_bitrate, sample_rate=self.sample_rate,
                        channels=self.channels)
        meta["has_audio"] = self.has_audio
        return meta


def _fps(rate: str) -> float:
    try:
        num, _, den = rate.partition("/")
        return float(num) / float(den or 1) if float(den or 1) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(ffprobe: str, path: Path) -> MediaInfo:
    """Synchronous ffprobe (used by the file detector in a worker thread)."""
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=PROBE_TIMEOUT_SEC, check=False, **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError("broken_file", "ffprobe timeout") from exc
    if result.returncode != 0:
        raise MediaError("broken_file", result.stderr.decode("utf-8", "replace")[-300:])
    data = json.loads(result.stdout or b"{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise MediaError("broken_file", "no audio or video streams")
    duration = float(fmt.get("duration") or (video or audio).get("duration") or 0)
    info = MediaInfo(
        duration=duration,
        format_names=set((fmt.get("format_name") or "").split(",")),
        has_video=video is not None,
        has_audio=audio is not None,
        bitrate=int(fmt.get("bit_rate") or 0),
    )
    if video:
        info.width, info.height = int(video.get("width") or 0), int(video.get("height") or 0)
        info.fps = _fps(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
        info.video_codec = video.get("codec_name", "")
    if audio:
        info.audio_codec = audio.get("codec_name", "")
        info.audio_bitrate = int(audio.get("bit_rate") or 0)
        info.sample_rate = int(audio.get("sample_rate") or 0)
        info.channels = int(audio.get("channels") or 0)
    return info


# ----------------------------------------------------------------------------- running ffmpeg

_TIME_RE = re.compile(r"^out_time_(?:us|ms)=(\d+)$")


async def run_ffmpeg(ffmpeg: str, args: list[str], duration: float,
                     progress: Callable[[int], None] | None = None) -> None:
    """Run ffmpeg with machine-readable progress; raises MediaError on failure."""
    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
               *args]
    last = -1

    def on_line(line: str) -> None:
        nonlocal last
        match = _TIME_RE.match(line)
        if match and duration > 0 and progress is not None:
            percent = min(99, int(int(match.group(1)) / 1_000_000 / duration * 100))
            if percent != last:
                last = percent
                progress(percent)

    try:
        result = await run_process_lines(command, timeout=FFMPEG_TIMEOUT_SEC, on_line=on_line)
    except ToolError as exc:
        raise MediaError(exc.code) from exc
    if result.returncode != 0:
        logger.warning("ffmpeg failed: %s", result.stderr.decode("utf-8", "replace")[-500:])
        raise MediaError("convert_failed")


def _check(out: Path) -> Path:
    if not out.exists() or out.stat().st_size == 0:
        raise MediaError("convert_failed", "empty output")
    return out


# ----------------------------------------------------------------------------- audio


@dataclass(frozen=True)
class AudioOptions:
    bitrate_k: int | None = None    # lossy formats
    sample_rate: int | None = None  # None = keep
    channels: int | None = None     # None = keep
    start: float | None = None      # trim
    end: float | None = None


def default_bitrate(target: str) -> int:
    return 128 if target == "opus" else 192


async def convert_audio(ffmpeg: str, src: Path, dst: Path, target: str, duration: float,
                        options: AudioOptions = AudioOptions(), progress=None) -> Path:  # noqa: ANN001
    if target not in _AUDIO_CODECS:
        raise MediaError("unsupported_target")
    codec, uses_bitrate = _AUDIO_CODECS[target]
    args: list[str] = []
    if options.start is not None:
        args += ["-ss", f"{options.start:.3f}"]
    args += ["-i", str(src)]
    if options.end is not None:
        args += ["-t", f"{options.end - (options.start or 0):.3f}"]
    args += ["-vn", "-map_metadata", "-1", *codec]
    if uses_bitrate:
        args += ["-b:a", f"{options.bitrate_k or default_bitrate(target)}k"]
    sample_rate = options.sample_rate or (48000 if target == "opus" else None)
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    if options.channels:
        args += ["-ac", str(options.channels)]
    span = (options.end or duration) - (options.start or 0)
    await run_ffmpeg(ffmpeg, [*args, str(dst)], span, progress)
    return _check(dst)


# ----------------------------------------------------------------------------- video


def _scale_filter(max_short_side: int | None) -> str:
    """Limit the shorter side (so 720p works for landscape and portrait), never upscale,
    and keep both dimensions even (required by yuv420p encoders)."""
    parts = []
    if max_short_side:
        s = max_short_side
        parts.append(f"scale='if(gt(iw,ih),-2,min({s},iw))':'if(gt(iw,ih),min({s},ih),-2)'")
    parts.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    return ",".join(parts)


@dataclass(frozen=True)
class VideoOptions:
    crf: int = 23
    max_short_side: int | None = None
    fps: float | None = None
    audio_bitrate_k: int = 128
    max_bitrate_k: int | None = None
    start: float | None = None
    end: float | None = None


def can_copy(info: dict[str, Any], target: str) -> bool:
    allowed = _COPY_OK.get(target)
    if not allowed:
        return False
    video_ok = info.get("vcodec") in allowed[0]
    audio_ok = not info.get("has_audio") or info.get("acodec") in allowed[1]
    return video_ok and audio_ok


async def convert_video(ffmpeg: str, src: Path, dst: Path, target: str, meta: dict[str, Any],
                        options: VideoOptions | None = None, progress=None) -> tuple[Path, bool]:  # noqa: ANN001
    """Returns (output, stream_copied). Without options the streams are copied when possible."""
    if target not in _VIDEO_CODECS:
        raise MediaError("unsupported_target")
    duration = float(meta.get("duration") or 0)
    if options is None and can_copy(meta, target):
        args = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-map_metadata", "-1"]
        if target in {"mp4", "mov"}:
            args += ["-movflags", "+faststart"]
        await run_ffmpeg(ffmpeg, [*args, str(dst)], duration, progress)
        return _check(dst), True

    options = options or VideoOptions()
    video_codec, audio_codec = _VIDEO_CODECS[target]
    args: list[str] = []
    if options.start is not None:
        args += ["-ss", f"{options.start:.3f}"]
    args += ["-i", str(src)]
    if options.end is not None:
        args += ["-t", f"{options.end - (options.start or 0):.3f}"]
    filters = [_scale_filter(options.max_short_side)]
    if options.fps:
        filters.insert(0, f"fps={options.fps:g}")
    args += ["-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-vf", ",".join(filters), *video_codec]
    if target == "webm":
        args += ["-crf", str(options.crf + 8), "-b:v", "0"]
    else:
        args += ["-crf", str(options.crf)]
    if options.max_bitrate_k:
        args += ["-maxrate", f"{options.max_bitrate_k}k", "-bufsize", f"{options.max_bitrate_k * 2}k"]
    args += [*audio_codec, "-b:a", f"{options.audio_bitrate_k}k"]
    if target in {"mp4", "mov"}:
        args += ["-movflags", "+faststart"]
    span = (options.end or duration) - (options.start or 0)
    await run_ffmpeg(ffmpeg, [*args, str(dst)], span, progress)
    return _check(dst), False


async def video_to_gif(ffmpeg: str, src: Path, dst: Path, duration: float, fps: int = 12, width: int = 480,
                       progress=None) -> Path:  # noqa: ANN001
    """Two-pass palette GIF (good colours, small size) of at most GIF_MAX_SECONDS."""
    span = min(duration or GIF_MAX_SECONDS, GIF_MAX_SECONDS)
    graph = (f"fps={fps},scale='min({width},iw)':-2:flags=lanczos,split[a][b];"
             f"[a]palettegen=max_colors=192:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
    await run_ffmpeg(ffmpeg, ["-t", f"{span:.3f}", "-i", str(src), "-filter_complex", graph, "-loop", "0",
                              str(dst)], span, progress)
    return _check(dst)


async def gif_to_video(ffmpeg: str, src: Path, dst: Path, target: str, progress=None) -> Path:  # noqa: ANN001
    video_codec, _ = _VIDEO_CODECS[target]
    await run_ffmpeg(ffmpeg, ["-i", str(src), "-an", "-vf", _scale_filter(None), *video_codec,
                              "-crf", "23" if target != "webm" else "32", *(["-b:v", "0"] if target == "webm" else []),
                              *(["-movflags", "+faststart"] if target == "mp4" else []), str(dst)], 0, progress)
    return _check(dst)


async def extract_audio(ffmpeg: str, src: Path, dst: Path, target: str, meta: dict[str, Any],
                        progress=None) -> Path:  # noqa: ANN001
    if not meta.get("has_audio"):
        raise MediaError("no_audio")
    return await convert_audio(ffmpeg, src, dst, target, float(meta.get("duration") or 0),
                               AudioOptions(bitrate_k=192 if target != "wav" else None), progress)


async def extract_frames(ffmpeg: str, src: Path, out_dir: Path, stem: str, every_sec: float | None,
                         count: int | None, duration: float, progress=None) -> list[Path]:  # noqa: ANN001
    """Either one frame every ``every_sec`` seconds or ``count`` evenly spaced frames (max MAX_FRAMES)."""
    if duration <= 0:
        raise MediaError("bad_params")
    if count:
        every_sec = max(duration / count, 0.04)
    assert every_sec
    limit = min(MAX_FRAMES, max(1, int(duration / every_sec) + 1))
    pattern = out_dir / f"{stem}_%03d.jpg"
    await run_ffmpeg(ffmpeg, ["-i", str(src), "-vf", f"fps=1/{every_sec:g},{_scale_filter(None)}",
                              "-frames:v", str(limit), "-q:v", "3", str(pattern)], duration, progress)
    frames = sorted(out_dir.glob(f"{stem}_*.jpg"))
    if not frames:
        raise MediaError("convert_failed")
    return frames


# ----------------------------------------------------------------------------- time ranges

_TIME = r"(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,5}(?:[.,]\d+)?)"
_RANGE_RE = re.compile(rf"^\s*{_TIME}\s*[-–—]\s*{_TIME}\s*$")


def _seconds(h: str | None, m: str | None, s: str) -> float:
    parts = [p for p in (h, m) if p is not None]
    value = float(s.replace(",", "."))
    for index, part in enumerate(reversed(parts)):
        value += int(part) * (60 if index == 0 else 3600)
    return value


def parse_time_range(text: str, duration: float) -> tuple[float, float]:
    """'0:10-0:45', '10-45', '1:02:03-1:05:00' -> (start, end) in seconds, within the duration."""
    match = _RANGE_RE.match(text or "")
    if not match:
        raise MediaError("bad_params")
    start = _seconds(*match.groups()[0:3])
    end = _seconds(*match.groups()[3:6])
    if not 0 <= start < end or end - start < 0.1:
        raise MediaError("bad_params")
    if duration and start >= duration:
        raise MediaError("range_outside")
    return start, min(end, duration) if duration else end
