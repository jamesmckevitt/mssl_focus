"""Drawing an export: marker labels kept readable where markers crowd together."""

import pytest
from PIL import Image, ImageDraw

from src import render


def test_crowded_labels_are_moved_apart_and_given_leaders():
    font = render._font(14)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lone = render.label_layout([(100, 100, 10, "I1")], font, measure, 800, 600, 2)
    assert lone[0]["leader"] is False and lone[0]["y"] == pytest.approx(100)
    crowd = [(300 + n * 3, 300 + n * 2, 10, f"I{n}") for n in range(6)]
    placed = render.label_layout(crowd, font, measure, 800, 600, 2)
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            apart_y = abs(a["y"] - b["y"]) >= (a["h"] + b["h"]) / 2
            apart_x = a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
            assert apart_x or apart_y
    assert any(p["leader"] for p in placed)
