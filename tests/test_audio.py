"""Audio: detection, conversion, compression, tools. Outputs are re-probed with ffprobe."""
from __future__ import annotations

from pathlib import Path

import pytest

from services import media_service as m
from services.file_detector import detect_file
from services.media_processor import AudioProcessor, quality_to_bitrate
from services.operations import CATEGORY_COMPRESS, CATEGORY_CONVERT, FileContext, OperationError, OperationRequest
from tests.conftest import FFMPEG, FFPROBE, needs_ffmpeg
from utils.file_manager import TaskWorkspace

pytestmark = needs_ffmpeg


def _probe(path: Path) -> m.MediaInfo:
    return m.probe(FFPROBE, path)


def _ctx(path: Path) -> FileContext:
    info = detect_file(path, path.name)
    assert info.error is None
    return FileContext(info.kind, info.extension, path.name, info.size, info.meta)


def test_detection_uses_real_streams(media):
    wav = detect_file(media["wav"], "tone.wav")
    assert (wav.kind, wav.extension, round(wav.meta["duration"])) == ("audio", "wav", 5)
    assert wav.meta["channels"] == 2 and wav.meta["sample_rate"] == 44100
    # an .mp4 with only sound is audio, not video
    voice = detect_file(media["audio_mp4"], "voice.mp4")
    assert (voice.kind, voice.extension) == ("audio", "m4a")


@pytest.mark.parametrize("target", m.AUDIO_FORMATS)
async def test_convert_wav_to_every_format(media, tmp_path, target):
    out = await m.convert_audio(FFMPEG, media["wav"], tmp_path / f"o.{target}", target, 5,
                                m.AudioOptions(bitrate_k=128))
    info = _probe(out)
    assert info.has_audio and not info.has_video
    assert abs(info.duration - 5) < 0.2
    assert detect_file(out, out.name).kind == "audio"


async def test_bitrate_samplerate_channels(media, tmp_path):
    out = await m.convert_audio(FFMPEG, media["wav"], tmp_path / "o.mp3", "mp3", 5,
                                m.AudioOptions(bitrate_k=96, sample_rate=22050, channels=1))
    info = _probe(out)
    assert (info.sample_rate, info.channels) == (22050, 1)
    assert 80_000 <= info.audio_bitrate <= 112_000


async def test_trim(media, tmp_path):
    out = await m.convert_audio(FFMPEG, media["wav"], tmp_path / "t.wav", "wav", 5,
                                m.AudioOptions(start=1.0, end=3.5))
    assert abs(_probe(out).duration - 2.5) < 0.1


def test_time_range_parsing():
    assert m.parse_time_range("0:10-0:45", 100) == (10.0, 45.0)
    assert m.parse_time_range("10 - 45,5", 100) == (10.0, 45.5)
    assert m.parse_time_range("1:00:00-1:00:30", 4000) == (3600.0, 3630.0)
    assert m.parse_time_range("0:10-9:00", 60) == (10.0, 60.0)  # end clamped to the duration
    for bad in ("", "abc", "0:45-0:10", "5-5", "1:2:3:4-5"):
        with pytest.raises(m.MediaError):
            m.parse_time_range(bad, 100)
    with pytest.raises(m.MediaError) as error:
        m.parse_time_range("2:00-3:00", 60)
    assert error.value.code == "range_outside"


def test_quality_chips_map_to_bitrates():
    assert [quality_to_bitrate(q) for q in (95, 85, 70, 50)] == [320, 192, 128, 96]


def test_compress_spec_is_honest(media):
    processor = AudioProcessor()
    mp3 = _ctx(media["mp3"])                     # 256 kbps source
    modes = [mode.id for mode in processor.compress_spec(mp3, "ru", 75, "bal").modes]
    assert modes == ["192", "128", "96"]         # never "compress" to a higher bitrate
    wav = _ctx(media["wav"])
    spec = processor.compress_spec(wav, "ru", 75, "bal")
    assert [mode.id for mode in spec.modes] == ["320", "192", "128", "96"]
    assert "с потерями" in spec.modes[0].description
    low = FileContext("audio", "mp3", "low.mp3", 1000, {"abitrate": 96000, "duration": 1})
    assert processor.compress_spec(low, "ru", 75, "bal") is None


def test_warnings(media):
    processor = AudioProcessor()
    wav, mp3 = _ctx(media["wav"]), _ctx(media["mp3"])
    assert "потерями" in processor.operation_warning(wav, OperationRequest(CATEGORY_CONVERT, "mp3"), "ru")
    assert "не вернёт качество" in processor.operation_warning(mp3, OperationRequest(CATEGORY_CONVERT, "wav"), "ru")
    assert processor.operation_warning(mp3, OperationRequest(CATEGORY_CONVERT, "ogg"), "ru") is None


async def test_processor_compress_reduces_size(media, tmp_path):
    processor = AudioProcessor()
    ctx = _ctx(media["mp3"])
    request = processor.parse_compress(ctx, "go:96", "ru")
    assert request == OperationRequest(CATEGORY_COMPRESS, "96", {})
    with TaskWorkspace(tmp_path) as workspace:
        result = await processor.run(ctx, request, media["mp3"], workspace, lambda p: None, "ru", [])
        assert result.extension == "mp3" and result.path.stat().st_size < media["mp3"].stat().st_size


def test_tool_parsing(media):
    processor = AudioProcessor()
    ctx = _ctx(media["wav"])
    ids = [tool.id for tool in processor.tools(ctx, "ru")]
    assert ids == ["tr", "sr", "ch"]
    assert processor.parse_tool(ctx, "t:tr", "ru")[1] == "input"
    assert processor.parse_tool(ctx, "t:ch:1", "ru")[1] is None
    with pytest.raises(OperationError):
        processor.parse_tool(ctx, "t:ch:2", "ru")   # already stereo: option not offered
    assert processor.parse_text_input(ctx, "tr", "0:01-0:02") == {"start": 1.0, "end": 2.0}


def test_corrupted_audio_rejected(tmp_path):
    fake = tmp_path / "broken.mp3"
    fake.write_bytes(b"ID3" + b"\x00" * 7 + b"\xff\xfb" + b"garbage" * 50)
    assert detect_file(fake, "broken.mp3").error == "broken_file"
