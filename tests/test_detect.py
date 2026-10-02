import numpy as np
from PIL import Image

from src.detect import find_pinholes, flag_present_in, split_by_markers
from tests.helpers import make_filter_image

DOTS = [(260, 210), (930, 190), (610, 420), (300, 620), (980, 610)]


def noisy(img, sigma=3.0, seed=1):
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.float32) + rng.normal(0, sigma, (img.height, img.width, 1))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def test_finds_the_spots_and_nothing_else():
    image = noisy(make_filter_image((1200, 800), DOTS))
    found, total = find_pinholes(image, "normal")
    assert total == len(DOTS)
    for x, y in DOTS:
        nearest = min(np.hypot(c["x"] - (x + 0.5), c["y"] - (y + 0.5)) for c in found)
        assert nearest < 1.0
    assert all(c["snr"] > 10 for c in found)


def test_ignores_lines_large_patches_and_single_hot_pixels():
    arr = np.full((600, 800, 3), 8, dtype=np.uint8)
    arr[100:103, 50:700] = 200          # a scratch
    arr[300:420, 300:460] = 220         # a large bright patch
    arr[500, 100] = 255                 # one hot pixel
    arr[200:204, 600:604] = 240         # a genuine small spot
    found, total = find_pinholes(Image.fromarray(arr), "normal")
    assert total == 1
    assert abs(found[0]["x"] - 602) < 1.5 and abs(found[0]["y"] - 202) < 1.5


def test_sensitivity_controls_how_faint_a_spot_may_be():
    arr = np.full((400, 400), 5, dtype=np.uint8)
    arr[100:104, 100:104] = 250
    arr[300:304, 300:304] = 38          # faint
    image = Image.fromarray(arr)
    assert find_pinholes(image, "low")[1] == 1
    assert find_pinholes(image, "high")[1] == 2


def test_candidates_with_markers_are_set_aside():
    candidates = [{"x": 100.0, "y": 100.0}, {"x": 400.0, "y": 300.0}]
    fresh, marked = split_by_markers(candidates, [(104.0, 97.0, 20.0)])
    assert [c["x"] for c in fresh] == [400.0]
    assert [c["x"] for c in marked] == [100.0]


def test_new_spots_are_told_apart_from_ones_seen_before():
    candidates = [{"x": 100.0, "y": 100.0}, {"x": 400.0, "y": 300.0}]
    flag_present_in(candidates, [(103.0, 101.0)])
    assert [c["in_reference"] for c in candidates] == [True, False]
    flag_present_in(candidates, [])
    assert [c["in_reference"] for c in candidates] == [False, False]
