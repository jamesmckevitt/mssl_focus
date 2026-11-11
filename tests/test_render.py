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
