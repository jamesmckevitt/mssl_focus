import math

import numpy as np
import pytest

from src import geometry as geo
from src.imaging import Pyramid
from src.pair import BACKLIT, FRONTLIT, ImagePair
from tests.helpers import make_filter_image


def test_about_keeps_centre_fixed_and_turns_clockwise():
    m = geo.about((100, 50), 2.0, 90)
    assert geo.apply(m, 100, 50) == pytest.approx((100, 50))
    # One unit to the right of the centre ends up two units below it (y points down).
    assert geo.apply(m, 101, 50) == pytest.approx((100, 52))


def test_invert_round_trips():
    m = geo.translation(12, -7) @ geo.about((300, 200), 1.3, 17.5)
    x, y = geo.apply(geo.invert(m), *geo.apply(m, 41.5, 99.25))
    assert (x, y) == pytest.approx((41.5, 99.25))


@pytest.mark.parametrize("allow_scale", [True, False])
def test_fit_similarity_recovers_a_known_transform(allow_scale):
    scale = 1.07 if allow_scale else 1.0
    truth = geo.translation(35, -12) @ geo.about((500, 400), scale, -3.2)
    src = np.array([(100, 120), (900, 150), (480, 700), (200, 640)], dtype=float)
    fitted, rms = geo.fit_similarity(src, geo.apply_many(truth, src), allow_scale=allow_scale)
    assert np.allclose(fitted, truth, atol=1e-9)
    assert rms < 1e-9


def test_fit_similarity_reports_residual_for_inconsistent_points():
    src = [(0, 0), (100, 0), (0, 100)]
    dst = [(0, 0), (100, 0), (0, 110)]
    _matrix, rms = geo.fit_similarity(src, dst, allow_scale=False)
    assert rms > 1.0


def test_fit_similarity_rejects_degenerate_input():
    with pytest.raises(ValueError):
        geo.fit_similarity([(1, 1), (1, 1)], [(0, 0), (5, 5)])
    with pytest.raises(ValueError):
        geo.fit_similarity([(1, 1)], [(0, 0)])


def test_decompose_about_matches_about():
    centre = (640, 480)
    m = geo.translation(-20, 33) @ geo.about(centre, 0.97, 12.0)
    scale, deg, tx, ty = geo.decompose_about(m, centre)
    assert (scale, deg, tx, ty) == pytest.approx((0.97, 12.0, -20, 33))


def _pair(size_back=(1200, 800), size_front=(1210, 790)):
    pair = ImagePair()
    pair.set_image(BACKLIT, "back", None, Pyramid(make_filter_image(size_back, mesh=False)))
    pair.set_image(FRONTLIT, "front", None, Pyramid(make_filter_image(size_front, mesh=False)))
    return pair


def test_frontlit_matrix_matches_the_session_file_convention():
    """Offset, rotation and scale keep the meaning they have in saved sessions:
    rotate and scale about the frontlit image centre, then shift."""
    pair = _pair()
    pair.off_x, pair.off_y, pair.rot, pair.scale, pair.glob_rot = 118.0, 13.0, -0.38, 0.996, 0.96
    cx, cy = pair.centre(FRONTLIT)
    theta = math.radians(pair.glob_rot + pair.rot)
    x, y = 200.0, 300.0
    dx, dy = (x - cx) * pair.scale, (y - cy) * pair.scale
    expected = (cx + dx * math.cos(theta) - dy * math.sin(theta) + pair.off_x,
                cy + dx * math.sin(theta) + dy * math.cos(theta) + pair.off_y)
    assert geo.apply(pair.matrix(FRONTLIT), x, y) == pytest.approx(expected)


def test_set_frontlit_matrix_round_trips():
    pair = _pair()
    pair.glob_rot = 1.5
    target = geo.translation(40, -25) @ geo.about(pair.centre(FRONTLIT), 1.02, 4.0)
    pair.set_frontlit_matrix(target)
    assert np.allclose(pair.matrix(FRONTLIT), target, atol=1e-9)
    assert pair.rot == pytest.approx(2.5)


def test_global_rotation_turns_both_images_rigidly():
    """After aligning, rotating 'both images' must not pull them apart."""
    pair = _pair()
    pair.off_x, pair.off_y, pair.rot, pair.scale = 60.0, -35.0, 2.0, 1.01
    feature_on_front = (333.0, 444.0)
    on_back_before = geo.apply(geo.invert(pair.matrix(BACKLIT)) @ pair.matrix(FRONTLIT), *feature_on_front)
    pair.set_global_rotation(7.5)
    on_back_after = geo.apply(geo.invert(pair.matrix(BACKLIT)) @ pair.matrix(FRONTLIT), *feature_on_front)
    assert pair.glob_rot == 7.5
    assert on_back_after == pytest.approx(on_back_before, abs=1e-6)


def test_label_numbering_follows_existing_labels():
    pair = ImagePair()
    pair.annotations = [
        {"img1_x": 0, "img1_y": 0, "radius": 20, "colour": "#00cc44", "label": "I1"},
        {"img1_x": 0, "img1_y": 0, "radius": 20, "colour": "#00cc44", "label": "I36"},
        {"img1_x": 0, "img1_y": 0, "radius": 20, "colour": "#ff0000", "label": "S4"},
    ]
    assert pair.next_label("#00cc44") == "I37"
    assert pair.next_label("#ff0000") == "S5"
    assert pair.prefix_for("#0000ff") is None
    pair.label_prefixes["#0000ff"] = ""
    assert pair.next_label("#0000ff") == ""
