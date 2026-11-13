"""Image conversion and tools: outputs are reopened and checked, not just 'no exception'."""
from __future__ import annotations

import pytest
from PIL import Image

from services import image_service as img
from services.file_detector import detect_file
from services.image_processor import ImageProcessor
from services.operations import OperationError


def _open(path):
    image = Image.open(path)
    image.load()
    return image


def test_png_to_jpg(samples, tmp_path):
    out = img.convert_image(samples["png"], tmp_path / "o.jpg", "jpg", 85)
    with _open(out) as result:
        assert result.format == "JPEG" and result.mode == "RGB" and result.size == (400, 300)
        # transparent corner flattened onto white
        assert result.getpixel((2, 2)) == pytest.approx((255, 255, 255), abs=3)


def test_jpg_to_webp(samples, tmp_path):
    out = img.convert_image(samples["jpg"], tmp_path / "o.webp", "webp", 80)
    with _open(out) as result:
        assert result.format == "WEBP" and result.size == (1200, 900)
    assert detect_file(out).extension == "webp"


@pytest.mark.parametrize("target", img.convert_targets("png"))
def test_every_target_opens(samples, tmp_path, target):
    out = img.convert_image(samples["png"], tmp_path / f"o.{target}", target, 80)
    info = detect_file(out)
    assert info.error is None
    assert info.extension == target
    if target in img.ALPHA_FORMATS and target != "ico":
        assert info.meta.get("alpha"), f"{target} lost transparency"


def test_png_to_pdf_is_valid(samples, tmp_path):
    import pymupdf

    out = img.convert_image(samples["png"], tmp_path / "o.pdf", "pdf")
    with pymupdf.open(out) as doc:
        assert doc.page_count == 1


def test_animated_gif_to_webp_keeps_frames(samples, tmp_path):
    out = img.convert_image(samples["gif"], tmp_path / "o.webp", "webp", 80)
    with Image.open(out) as result:
        assert result.n_frames == 4


def test_heic_roundtrip(samples, tmp_path):
    if not img.HEIF_SUPPORTED:
        pytest.skip("pillow-heif not installed")
    heic = img.convert_image(samples["jpg"], tmp_path / "o.heic", "heic", 80)
    back = img.convert_image(heic, tmp_path / "back.png", "png")
    with _open(back) as result:
        assert result.size == (1200, 900)


def test_resize_presets_and_no_upscale(samples, tmp_path):
    with _open(img.resize_image(samples["jpg"], tmp_path / "a.jpg", "jpg", "p50")) as r:
        assert r.size == (600, 450)
    with _open(img.resize_image(samples["jpg"], tmp_path / "b.jpg", "jpg", "s1920")) as r:
        assert r.size == (1200, 900)  # already smaller: not upscaled
    with _open(img.resize_image(samples["jpg"], tmp_path / "c.jpg", "jpg", size=(100, 50))) as r:
        assert r.size == (100, 50)


def test_crop_rotate_grayscale(samples, tmp_path):
    with _open(img.crop_image(samples["jpg"], tmp_path / "c.jpg", "jpg", "1x1")) as r:
        assert r.size == (900, 900)
    with _open(img.crop_image(samples["jpg"], tmp_path / "d.jpg", "jpg", box=(10, 20, 100, 50))) as r:
        assert r.size == (100, 50)
    with pytest.raises(img.ImageError):
        img.crop_image(samples["jpg"], tmp_path / "e.jpg", "jpg", box=(1150, 0, 100, 100))
    with _open(img.rotate_image(samples["png"], tmp_path / "r.png", "png", "90")) as r:
        assert r.size == (300, 400)
    with _open(img.grayscale_image(samples["png"], tmp_path / "g.png", "png")) as r:
        assert r.mode == "LA"


def test_strip_metadata(samples, tmp_path):
    assert img.has_metadata(samples["jpg"])
    out = img.strip_metadata(samples["jpg"], tmp_path / "clean.jpg", "jpg")
    assert not img.has_metadata(out)


def test_images_to_pdf(samples, tmp_path):
    import pymupdf

    out = img.images_to_pdf([samples["jpg"], samples["png"], samples["gif"]], tmp_path / "all.pdf")
    with pymupdf.open(out) as doc:
        assert doc.page_count == 3


def test_broken_image_raises(samples, tmp_path):
    with pytest.raises(img.ImageError) as error:
        img.convert_image(samples["broken_png"], tmp_path / "x.jpg", "jpg")
    assert error.value.code == "broken_file"


def test_size_and_crop_input_parsing():
    assert ImageProcessor.parse_size_input("1280x720", 4000, 3000) == (1280, 720)
    assert ImageProcessor.parse_size_input("800x", 4000, 3000) == (800, 600)
    assert ImageProcessor.parse_size_input("x300", 4000, 3000) == (400, 300)
    assert ImageProcessor.parse_crop_input("100x50+10+20", 4000, 3000) == (10, 20, 100, 50)
    for bad in ("", "x", "abc", "0x0", "99999x1"):
        with pytest.raises(OperationError):
            ImageProcessor.parse_size_input(bad, 4000, 3000)
    with pytest.raises(OperationError):
        ImageProcessor.parse_crop_input("5000x10+0+0", 4000, 3000)
