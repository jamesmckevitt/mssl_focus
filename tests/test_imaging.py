import numpy as np
import pytest
from PIL import Image

from src import geometry as geo
from src.imaging import CANVAS_BACKGROUND, Pyramid, build_lut, match_tone, open_image
from tests.helpers import dot_centroid, make_filter_image


def test_render_puts_a_feature_where_the_matrix_says():
    """Drawing and click handling share one matrix, so a dot must land exactly
    where that matrix maps it -- including rotation, scale and offset."""
    dot = (700.0, 260.0)
    pyramid = Pyramid(make_filter_image((1200, 800), dots=[dot], mesh=False))
    centre = (dot[0] + 0.5, dot[1] + 0.5)   # pixel (700, 260) spans 700..701, 260..261
    for zoom, deg in ((1.0, 0.0), (0.4, 3.0), (2.5, -7.0), (0.13, 11.0)):
        placement = geo.scaling(zoom) @ geo.about((600, 400), 1.03, deg)
        x, y = geo.apply(placement, *centre)
        matrix = geo.translation(431.3 - x, 352.6 - y) @ placement   # keep the dot in frame
        frame = pyramid.render(matrix, (900, 700), quality=True)
        expected = geo.apply(matrix, *centre)
        found = dot_centroid(frame, expected)
        assert found is not None, f"dot not visible at zoom {zoom}"
        assert found == pytest.approx(expected, abs=1.0)


def test_zoomed_out_render_keeps_a_single_bright_pixel_visible():
    """A one-pixel pinhole must not vanish between samples when zoomed far out."""
    arr = np.zeros((2000, 3000), dtype=np.uint8)
    arr[1001, 1503] = 255
    pyramid = Pyramid(Image.fromarray(arr))
    matrix = geo.scaling(0.2)
    frame = np.asarray(pyramid.render(matrix, (600, 400), quality=False).convert("L")).astype(int)
    background = CANVAS_BACKGROUND[0]
    assert frame[190:210, 290:310].max() > frame[:50, :50].max()
    assert frame[:50, :50].max() <= background


def test_tone_curve_does_not_change_the_surround():
    pyramid = Pyramid(make_filter_image((400, 300), mesh=False, background=100))
    lut = build_lut(1.8, 1.0, 0.0, 255.0, pyramid.mean)
    frame = pyramid.render(geo.translation(200, 150), (800, 600), lut=lut)
    assert frame.getpixel((20, 20)) == CANVAS_BACKGROUND      # outside the image
    assert frame.getpixel((400, 300)) == (180, 180, 180)      # inside, brightened


def test_neutral_settings_need_no_tone_curve():
    assert build_lut(1.0, 1.0, 0.0, 255.0, 128.0) is None
    lut = build_lut(1.0, 1.0, 10.0, 245.0, 128.0)
    assert lut[10] == 0 and lut[245] == 255


def test_contrast_pivots_on_the_image_mean():
    lut = build_lut(1.0, 2.0, 0.0, 255.0, 100.0)
    assert lut[100] == 100
    assert lut[110] == 120


def test_open_image_rescales_16_bit_greyscale(tmp_path):
    arr = np.zeros((40, 60), dtype=np.uint16)
    arr[10:20, 10:20] = 65535
    arr[20:30, 20:30] = 32768
    path = tmp_path / "grey16.tif"
    Image.fromarray(arr).save(path)
    img = open_image(str(path))
    assert img.mode == "L"
    assert img.getpixel((15, 15)) == 255
    assert img.getpixel((25, 25)) == 128
    assert img.getpixel((35, 5)) == 0


def test_open_image_reports_unreadable_files(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    with pytest.raises(Exception):
        open_image(str(path))


@pytest.mark.parametrize("brightness, contrast", [(1.25, 1.0), (0.8, 1.3), (1.6, 0.7)])
def test_match_tone_recovers_the_settings_that_produced_the_other_image(brightness, contrast):
    rng = np.random.default_rng(3)
    target = np.clip(rng.normal(95, 22, 20000), 20, 150).astype(np.uint8).astype(np.float32)
    mean = float(target.mean())
    lut = np.asarray(build_lut(brightness, contrast, 0.0, 255.0, mean), dtype=np.float32)
    source = lut[target.astype(np.uint8)]
    found_brightness, found_contrast = match_tone(target, source, mean)
    assert found_brightness == pytest.approx(brightness, abs=0.03)
    assert found_contrast == pytest.approx(contrast, abs=0.04)


def test_match_tone_on_dark_frames_matches_the_bright_end_only():
    target = np.zeros(50000, dtype=np.float32)
    target[:200] = 80.0
    source = np.zeros(50000, dtype=np.float32)
    source[:200] = 160.0
    brightness, contrast = match_tone(target, source, pivot=0.3)
    assert brightness == pytest.approx(2.0, abs=0.01)
    assert contrast is None


def test_match_tone_declines_when_an_image_has_nothing_bright():
    assert match_tone(np.zeros(1000), np.full(1000, 2.0), pivot=0.0) == (None, None)


def test_match_tone_keeps_blown_highlights_white():
    """Two photographs with large clipped-white areas: the shadows are matched and
    white stays white, instead of being dragged down to grey."""
    rng = np.random.default_rng(4)
    target = np.concatenate([np.clip(rng.normal(90, 15, 6000), 40, 160), np.full(4000, 255.0)])
    source = np.concatenate([np.clip(rng.normal(120, 12, 6000), 80, 180), np.full(4000, 255.0)])
    pivot = float(target.mean())
    brightness, contrast = match_tone(target, source, pivot)
    lut = np.asarray(build_lut(brightness, contrast, 0.0, 255.0, pivot), dtype=np.float32)
    shown = lut[target.astype(np.uint8)]
    assert shown[-1] >= 250
    assert np.median(shown[:6000]) == pytest.approx(np.median(source[:6000]), abs=5)
