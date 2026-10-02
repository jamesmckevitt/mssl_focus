import numpy as np
from PIL import Image

from src import geometry as geo
from src.detect import (
    find_pinholes,
    flag_present_in,
    markers_without_a_spot,
    point_in_polygon,
    split_by_markers,
)
from tests.helpers import make_filter_image

DOTS = [(260, 210), (930, 190), (610, 420), (300, 620), (980, 610)]


def noisy(img, sigma=3.0, seed=1):
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.float32) + rng.normal(0, sigma, (img.height, img.width, 1))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def test_finds_the_spots_and_nothing_else():
    image = noisy(make_filter_image((1200, 800), DOTS))
    found, _total = find_pinholes(image)
    sure = [c for c in found if c["tier"] != "faint"]
    assert len(sure) == len(DOTS)
    assert {c["tier"] for c in sure} == {"clear"}
    for x, y in DOTS:
        nearest = min(np.hypot(c["x"] - (x + 0.5), c["y"] - (y + 0.5)) for c in found)
        assert nearest < 1.0


def test_ignores_lines_large_patches_and_single_hot_pixels():
    arr = np.full((600, 800, 3), 8, dtype=np.uint8)
    arr[100:103, 50:700] = 200          # a scratch
    arr[300:420, 300:460] = 220         # a large bright patch
    arr[500, 100] = 255                 # one hot pixel
    arr[200:204, 600:604] = 240         # a genuine small spot
    found, total = find_pinholes(Image.fromarray(arr))
    sure = [c for c in found if c["tier"] != "faint"]
    assert len(sure) == 1
    assert abs(sure[0]["x"] - 602) < 1.5 and abs(sure[0]["y"] - 202) < 1.5
    # The scratch and the patch are never offered; the lone hot pixel only as "faint".
    assert total <= 2
    assert all(abs(c["x"] - 100.5) < 1.5 and abs(c["y"] - 500.5) < 1.5 for c in found if c["tier"] == "faint")


def test_spots_are_graded_by_how_sure_the_search_is():
    arr = np.full((400, 600), 5, dtype=np.uint8)
    arr[100:104, 100:104] = 250         # unmistakable
    arr[200:204, 300:304] = 48          # modest
    arr[300:304, 500:504] = 27          # barely there
    found, total = find_pinholes(Image.fromarray(arr))
    assert total == 3
    assert [c["tier"] for c in found] == ["clear", "likely", "faint"], "surest first"
    assert [round(c["x"]) for c in found] == [102, 302, 502]


def test_a_mask_limits_the_search_to_the_filter():
    image = make_filter_image((1200, 800), DOTS, mesh=False)
    mask = np.zeros((800, 1200), dtype=np.uint8)
    mask[:, :700] = 255
    found, total = find_pinholes(image, mask=mask)
    assert sorted(round(c["x"]) for c in found) == [260, 300, 610]
    assert total == 3


def test_candidates_with_markers_are_set_aside():
    candidates = [{"x": 100.0, "y": 100.0}, {"x": 400.0, "y": 300.0}]
    fresh, marked = split_by_markers(candidates, [(104.0, 97.0, 20.0)])
    assert [c["x"] for c in fresh] == [400.0]
    assert [c["x"] for c in marked] == [100.0]
    assert markers_without_a_spot([(104.0, 97.0, 20.0), (900.0, 900.0, 20.0)], candidates) == [1]


def test_new_spots_are_told_apart_from_ones_seen_before():
    candidates = [{"x": 100.0, "y": 100.0}, {"x": 400.0, "y": 300.0}]
    flag_present_in(candidates, [(103.0, 101.0)])
    assert [c["in_reference"] for c in candidates] == [True, False]
    flag_present_in(candidates, [])
    assert [c["in_reference"] for c in candidates] == [False, False]


def test_rounded_rectangle_follows_the_corners():
    outline = geo.rounded_rectangle(100, 100, 500, 400, 80)
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    assert (min(xs), max(xs), min(ys), max(ys)) == (100, 500, 100, 400)
    assert point_in_polygon(300, 250, outline)
    assert point_in_polygon(300, 105, outline)          # middle of the top edge
    assert not point_in_polygon(104, 104, outline)      # the square corner is cut off
    assert point_in_polygon(104, 104, geo.rounded_rectangle(100, 100, 500, 400, 0))
    import pytest
    assert geo.rounded_rectangle(0, 0, 10, 10, 999)[0] == pytest.approx((0.0, 5.0)), "radius limited to half the side"
