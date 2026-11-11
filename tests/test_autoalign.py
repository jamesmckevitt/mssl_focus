"""Automatic alignment from the filter's frame: the opening, the tilt, and the
frontlit photograph placed on the backlit one."""

import numpy as np
import pytest

from src import autoalign
from src import geometry as geo
from tests.helpers import OPENING, framed_position, make_framed_filter

PINHOLES = [(480, 260), (560, 700), (640, 420), (760, 300), (820, 560), (900, 720), (990, 380)]


@pytest.mark.parametrize("tilt, shift", [(0.0, (0, 0)), (1.3, (25, -15)), (-2.0, (-40, 30))])
def test_the_opening_is_found_in_the_frontlit_image(tilt, shift):
    image = make_framed_filter("front", PINHOLES, tilt, shift)
    found = autoalign.find_aperture(image)
    cx, cy = framed_position(OPENING[:2], tilt, shift)
    assert (found.cx, found.cy) == pytest.approx((cx, cy), abs=1.5)
    assert (found.width, found.height) == pytest.approx(OPENING[2:4], abs=3.0)
    assert found.tilt == pytest.approx(tilt, abs=0.05)
    assert found.radius == pytest.approx(OPENING[4], abs=15)


def test_the_opening_is_found_whichever_side_is_darker():
    bright = autoalign.find_aperture(make_framed_filter("front", PINHOLES, membrane=210))
    assert (bright.width, bright.height) == pytest.approx(OPENING[2:4], abs=3.0)
    assert bright.polarity == -1


def test_a_known_size_keeps_a_reflection_from_passing_for_the_opening():
    image = make_framed_filter("front", PINHOLES, inner_box=(560, 330, 940, 660))
    hinted = autoalign.find_aperture(image, expect=OPENING[2:4])
    assert (hinted.width, hinted.height) == pytest.approx(OPENING[2:4], abs=3.0)


def test_the_outline_is_a_closed_rounded_rectangle_in_image_pixels():
    found = autoalign.find_aperture(make_framed_filter("front", PINHOLES, 1.0))
    points = np.array(found.points())
    upright = geo.apply_many(found.upright(), points)
    assert upright[:, 0].max() - upright[:, 0].min() == pytest.approx(found.width, abs=0.01)
    assert upright[:, 1].max() - upright[:, 1].min() == pytest.approx(found.height, abs=0.01)


def test_frontlit_taken_without_moving_the_camera_is_left_where_it_is():
    back = make_framed_filter("back", PINHOLES, 0.7, (10, 5))
    front = make_framed_filter("front", PINHOLES, 0.7, (10, 5))
    matrix, quality = autoalign.register_frontlit(back, front)
    assert np.allclose(matrix, np.eye(3))
    assert quality > 0.3


def test_a_moved_frontlit_photograph_is_put_back_on_the_backlit_one():
    back = make_framed_filter("back", PINHOLES)
    front = make_framed_filter("front", PINHOLES, 0.6, (35, -22))
    matrix, _quality = autoalign.register_frontlit(back, front)
    for point in [OPENING[:2], (400, 150), (1100, 850)]:
        x, y = geo.apply(matrix, *framed_position(point, 0.6, (35, -22)))
        assert (x, y) == pytest.approx(point, abs=1.5)
