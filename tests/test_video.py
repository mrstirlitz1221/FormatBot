"""Video: conversion, compression, tools, cancellation. Outputs are re-probed with ffprobe."""
from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from services import media_service as m
from services.file_detector import detect_file
from services.media_processor import VideoProcessor, quality_to_crf
from services.operations import FileContext, OperationError
from tests.conftest import FFMPEG, FFPROBE, needs_ffmpeg
from utils.file_manager import TaskWorkspace

pytestmark = needs_ffmpeg


def _probe(path: Path) -> m.MediaInfo:
    return m.probe(FFPROBE, path)


def _ctx(path: Path) -> FileContext:
    info = detect_file(path, path.name)
    assert info.error is None
    return FileContext(info.kind, info.extension, path.name, info.size, info.meta)


async def _run(processor, ctx, data, source, tmp_path, kind="convert"):  # noqa: ANN001
    parse = {"convert": lambda: processor.parse_convert(ctx, data, 85),
             "compress": lambda: processor.parse_compress(ctx, data, "ru"),
             "tool": lambda: processor.parse_tool(ctx, data, "ru")[0]}[kind]
    progress: list[int] = []
    workspace = TaskWorkspace(tmp_path)
    result = await processor.run(ctx, parse(), source, workspace, progress.append, "ru", [])
    return result, progress


def test_detection(media):
    info = detect_file(media["mp4"], "clip.mp4")
    assert info.kind == "video"
    assert (info.meta["width"], info.meta["height"], round(info.meta["fps"])) == (1280, 720, 30)
    assert info.meta["has_audio"] and round(info.meta["duration"]) == 6
    assert detect_file(media["silent"], "silent.mp4").meta["has_audio"] is False


@pytest.mark.parametrize("target", ["mkv", "mov"])
async def test_remux_without_reencoding(media, tmp_path, target):
    result, _ = await _run(VideoProcessor(), _ctx(media["mp4"]), f"go:{target}", media["mp4"], tmp_path)
    info = _probe(result.path)
    assert info.video_codec == "h264" and info.audio_codec == "aac"
    assert "без перекодирования" in result.details


@pytest.mark.parametrize("target, vcodec", [("webm", "vp9"), ("avi", "h264")])
async def test_convert_reencodes(media, tmp_path, target, vcodec):
    result, progress = await _run(VideoProcessor(), _ctx(media["mp4"]), f"go:{target}", media["mp4"], tmp_path)
    info = _probe(result.path)
    assert info.video_codec == vcodec and abs(info.duration - 6) < 0.3
    assert progress and progress[-1] >= 50, "ffmpeg progress must reach the task card"


async def test_video_to_gif(media, tmp_path):
    result, _ = await _run(VideoProcessor(), _ctx(media["mp4"]), "go:gif", media["mp4"], tmp_path)
    with Image.open(result.path) as gif:
        assert gif.format == "GIF" and gif.n_frames > 50 and gif.width == 480


@pytest.mark.parametrize("mode, height", [("sm", 480), ("bal", 720), ("hq", 720)])
async def test_compress_presets_never_upscale(media, tmp_path, mode, height):
    result, _ = await _run(VideoProcessor(), _ctx(media["mp4"]), f"go:{mode}", media["mp4"], tmp_path, "compress")
    info = _probe(result.path)
    assert info.height == height and info.width % 2 == 0
    assert result.path.stat().st_size < media["mp4"].stat().st_size


async def test_compress_custom(media, tmp_path):
    result, _ = await _run(VideoProcessor(), _ctx(media["mp4"]), "go:cus:40:360", media["mp4"], tmp_path, "compress")
    assert _probe(result.path).height == 360
    assert quality_to_crf(100) == 18 and quality_to_crf(10) == 38


def test_compress_spec(media):
    spec = VideoProcessor().compress_spec(_ctx(media["mp4"]), "ru", 75, "max")
    assert [mode.id for mode in spec.modes] == ["sm", "bal", "hq", "cus"]
    assert spec.default_mode == "sm"
    assert [r for r, _ in spec.resolutions] == ["o", "480", "360"]  # only below 720p
    assert "исходный размер" in spec.modes[2].description          # 1080p preset on a 720p file


async def test_tools(media, tmp_path):
    processor, ctx = VideoProcessor(), _ctx(media["mp4"])
    assert [t.id for t in processor.tools(ctx, "ru")] == ["ea", "fr", "tr", "gf", "re", "fp"]

    audio, _ = await _run(processor, ctx, "t:ea:mp3", media["mp4"], tmp_path / "a", "tool")
    info = _probe(audio.path)
    assert audio.extension == "mp3" and info.has_audio and not info.has_video

    frames, _ = await _run(processor, ctx, "t:fr:n10", media["mp4"], tmp_path / "f", "tool")
    with zipfile.ZipFile(frames.path) as archive:
        assert len(archive.namelist()) == 10

    lower, _ = await _run(processor, ctx, "t:re:480", media["mp4"], tmp_path / "r", "tool")
    assert _probe(lower.path).height == 480

    slower, _ = await _run(processor, ctx, "t:fp:15", media["mp4"], tmp_path / "p", "tool")
    assert round(_probe(slower.path).fps) == 15

    params = processor.parse_text_input(ctx, "tr", "0:01-0:03")
    from services.operations import CATEGORY_TOOL, OperationRequest
    workspace = TaskWorkspace(tmp_path / "t")
    trimmed = await processor.run(ctx, OperationRequest(CATEGORY_TOOL, "tr", params), media["mp4"], workspace,
                                  lambda p: None, "ru", [])
    assert abs(_probe(trimmed.path).duration - 2) < 0.2


def test_silent_video_has_no_audio_tool(media):
    processor, ctx = VideoProcessor(), _ctx(media["silent"])
    assert "ea" not in [t.id for t in processor.tools(ctx, "ru")]
    with pytest.raises(OperationError):
        processor.parse_tool(ctx, "t:ea:mp3", "ru")


async def test_cancel_kills_ffmpeg(media, tmp_path):
    (tmp_path / "w").mkdir()
    slow = asyncio.create_task(m.convert_video(
        FFMPEG, media["mp4"], tmp_path / "w" / "o.webm", "webm", {"duration": 6},
        m.VideoOptions(crf=10)))
    await asyncio.sleep(0.5)
    slow.cancel()
    with pytest.raises(asyncio.CancelledError):
        await slow
    await asyncio.sleep(0.5)
    # the output file is no longer being written (process killed) and can be removed
    for path in (tmp_path / "w").iterdir():
        path.unlink()


async def test_corrupted_video_rejected(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
    assert detect_file(broken, "broken.mp4").error == "broken_file"
