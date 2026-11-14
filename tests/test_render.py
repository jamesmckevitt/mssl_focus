"""Drawing an export: marker labels kept readable where markers crowd together."""

import numpy as np
from PIL import Image, ImageDraw

from src import render


def _layout(items, size=(1200, 900), stroke=2):
    font = render._font(22)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return render.label_layout(items, font, measure, size[0], size[1], stroke)


def _box(place):
    return (place["x"], place["y"] - place["h"] / 2, place["x"] + place["w"], place["y"] + place["h"] / 2)


def test_an_uncrowded_label_stays_beside_its_marker():
    lone = _layout([(100, 100, 10, "I1")])
    assert lone[0]["leader"] is False and lone[0]["y"] == 100 and lone[0]["x"] > 110


def test_crowded_labels_never_overlap_each_other_or_other_markers():
    rng = np.random.default_rng(3)
    centres = rng.normal((600, 450), 45, (40, 2))
    items = [(float(x), float(y), 10.0, f"I{n + 1}") for n, (x, y) in enumerate(centres)]
    places = _layout(items)
    boxes = [_box(p) for p in places]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], "two labels overlap"
        for j, (cx, cy, r, _t) in enumerate(items):
            if j == i:
                continue
            nx, ny = min(max(cx, a[0]), a[2]), min(max(cy, a[1]), a[3])
            assert np.hypot(cx - nx, cy - ny) >= r, "a label covers another marker"
    assert any(p["leader"] for p in places), "moved labels are joined to their markers"
    for p in places:
        assert 0 <= p["x"] and p["x"] + p["w"] <= 1200


def _covers(ring_r, gaps, centre, point, band, spot):
    """Whether a circle drawn as laid out runs over a spot of radius ``spot`` at ``point``."""
    import math
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    for step in range(720):
        a = step / 2.0
        if any((a - s) % 360.0 <= (e - s) for s, e in render.ring_arcs(gaps)):
            x = centre[0] + ring_r * math.cos(math.radians(a))
            y = centre[1] + ring_r * math.sin(math.radians(a))
            if math.hypot(x - point[0], y - point[1]) < band + spot - 0.5:
                return True
    return False


def test_circles_never_cover_another_markers_pinhole():
    stroke, halo = 7, 4
    band = stroke / 2 + halo
    # A tight triple, a pair, and one on its own.
    markers = [(100, 100, 20), (118, 112, 20), (134, 126, 22), (300, 100, 20), (327, 104, 21), (500, 300, 20)]
    layout = render.ring_layout(markers, stroke, halo)
    for i, ((cx, cy, _r), (ring_r, gaps)) in enumerate(zip(markers, layout)):
        assert ring_r - band > render.RING_SPOT * markers[i][2], "its own spot stays clear inside it"
        for j, (px, py, pr) in enumerate(markers):
            if j != i:
                assert not _covers(ring_r, gaps, (cx, cy), (px, py), band, render.RING_SPOT * pr)
    # Away from the crowd a circle is drawn whole, at its usual size.
    assert layout[-1] == (20 - stroke / 2, [])


def test_a_ring_with_gaps_is_drawn_as_the_arcs_between_them():
    assert render.ring_arcs([]) == [(0.0, 360.0)]
    assert render.ring_arcs([(-20, 20)]) == [(20.0, 340.0)]
    arcs = render.ring_arcs([(80, 100), (90, 130), (250, 270)])
    assert arcs == [(130.0, 250.0), (270.0, 440.0)]
