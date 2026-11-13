"""Compression plans, real size reduction and honest reporting."""
from __future__ import annotations

import pytest
from PIL import Image

from services import image_service as img
from services.image_processor import ImageProcessor
from services.operations import FileContext, OperationError
from utils.size_formatter import compare_sizes, format_size


@pytest.mark.parametrize("mode", ["mq", "bal", "max"])
def test_jpeg_compression_reduces_size(samples, tmp_path, mode):
    plan = img.plan_compression("jpg", mode)
    out = img.compress_image(samples["jpg"], tmp_path, plan, f"c_{mode}")
    assert out.stat().st_size < samples["jpg"].stat().st_size
    with Image.open(out) as result:
        assert result.format == "JPEG"
    assert not img.has_metadata(out)


def test_quality_ordering(samples, tmp_path):
    sizes = {}
    for mode in ("mq", "bal", "max"):
        out = img.compress_image(samples["jpg"], tmp_path, img.plan_compression("jpg", mode), f"o_{mode}")
        sizes[mode] = out.stat().st_size
    assert sizes["mq"] > sizes["bal"] > sizes["max"]


def test_custom_plan_validation():
    plan = img.plan_compression("webp", "cus", 55, "1280")
    assert (plan.fmt, plan.quality, plan.max_side) == ("webp", 55, 1280)
    with pytest.raises(img.ImageError):
        img.plan_compression("webp", "cus", 5, "o")
    with pytest.raises(img.ImageError):
        img.plan_compression("webp", "cus", 50, "999")
    with pytest.raises(img.ImageError):
        img.plan_compression("webp", "turbo")


def test_png_palette_keeps_transparency(samples, tmp_path):
    plan = img.plan_compression("png", "max")
    assert plan.palette_colors == 256 and plan.quality is None
    out = img.compress_image(samples["png"], tmp_path, plan)
    with Image.open(out) as result:
        assert result.mode == "P" and "transparency" in result.info
        assert result.convert("RGBA").getpixel((1, 1))[3] == 0


def test_png_balanced_is_lossless(samples, tmp_path):
    plan = img.plan_compression("png", "bal")
    assert plan.lossless
    out = img.compress_image(samples["png"], tmp_path, plan)
    with Image.open(samples["png"]) as a, Image.open(out) as b:
        assert list(a.convert("RGBA").getdata()) == list(b.convert("RGBA").getdata())


def test_bmp_compresses_to_lossless_png(samples, tmp_path):
    plan = img.plan_compression("bmp", "bal")
    out = img.compress_image(samples["bmp"], tmp_path, plan)
    assert out.suffix == ".png" and out.stat().st_size < samples["bmp"].stat().st_size


def test_max_mode_downscales_only_large_images(tmp_path):
    big = tmp_path / "big.jpg"
    Image.new("RGB", (4000, 2000), (120, 30, 200)).save(big, quality=95)
    out = img.compress_image(big, tmp_path, img.plan_compression("jpg", "max"), "small")
    with Image.open(out) as result:
        assert result.size == (1920, 960)


def test_reduction_math():
    comparison = compare_sizes(15_400_000, 4_200_000)
    assert comparison.saved == 11_200_000
    assert comparison.reduction_percent == 72.7
    assert compare_sizes(100, 120).saved == -20 and not compare_sizes(100, 120).is_smaller
    assert compare_sizes(0, 10).reduction_percent == 0.0
    with pytest.raises(ValueError):
        compare_sizes(-1, 1)
    assert format_size(15_400_000, "en") == "14.7 MB"
    assert format_size(512, "ru") == "512 Б"


def test_compress_spec_describes_real_plan():
    processor = ImageProcessor()
    file = FileContext("image", "jpg", "a.jpg", 1000, {"width": 3000, "height": 2000})
    spec = processor.compress_spec(file, "en", 75, "bal")
    descriptions = {m.id: m.description for m in spec.modes}
    assert descriptions["bal"] == "JPEG · quality 80 · original size"
    assert descriptions["max"] == "JPEG · quality 60 · up to 1920px"
    assert [r for r, _ in spec.resolutions] == ["o", "2560", "1920", "1280"]


def test_compress_request_parsing():
    processor = ImageProcessor()
    file = FileContext("image", "jpg", "a.jpg", 1000, {"width": 3000, "height": 2000})
    assert processor.parse_compress(file, "go:bal", "en").name == "bal"
    request = processor.parse_compress(file, "go:cus:40:1280", "en")
    assert request.params == {"quality": 40, "resolution": "1280"}
    for bad in ("go:cus:40:720", "go:cus:4:o", "go:zip", "go", "go:bal:1", "t:rs"):
        with pytest.raises(OperationError):
            processor.parse_compress(file, bad, "en")
