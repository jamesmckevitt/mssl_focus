"""Shared test helpers: synthetic filter images and a driver for the Tk app."""

import json
import math
import time

import numpy as np
from PIL import Image, ImageDraw


def make_filter_image(size=(1200, 800), dots=(), rotation=0.0, shift=(0, 0), scale=1.0,
                      background=12, mesh=True, dot_value=255):
    """A dark frame with a faint mesh and bright dots, optionally transformed.

    ``dots`` are (x, y) positions in the untransformed frame; the returned
    image shows them rotated by ``rotation`` degrees (clockwise) and scaled
    about the centre, then shifted.
    """
    width, height = size
    img = Image.new("RGB", size, (background,) * 3)
    draw = ImageDraw.Draw(img)
    cx, cy = width / 2.0, height / 2.0
    theta = math.radians(rotation)

    def place(x, y):
        dx, dy = (x - cx) * scale, (y - cy) * scale
        return (cx + dx * math.cos(theta) - dy * math.sin(theta) + shift[0],
                cy + dx * math.sin(theta) + dy * math.cos(theta) + shift[1])

    if mesh:
        for gx in range(100, width, 100):
            draw.line([place(gx, 40), place(gx, height - 40)], fill=(26, 26, 30), width=2)
        for gy in range(100, height, 100):
            draw.line([place(40, gy), place(width - 40, gy)], fill=(26, 26, 30), width=2)
    for x, y in dots:
        px, py = place(x, y)
        draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(dot_value,) * 3)
    return img


FRAMED_SIZE = (1500, 1000)
OPENING = (750.0, 500.0, 660.0, 600.0, 60.0)      # centre x, y, width, height, corner radius
PLATE = (860.0, 800.0)                            # the frame plate around the opening


def make_framed_filter(lit="back", pinholes=(), tilt=0.0, shift=(0.0, 0.0), turned=False,
                       size=FRAMED_SIZE, membrane=None, inner_box=None, seed=0):
    """A filter in its frame as the camera sees it, lit from behind or in front.

    The frame plate (with a screw in each corner) holds a rounded-rectangle
    opening; behind it, a mount brighter than the plate.  ``pinholes`` are
    ``(x, y)`` in the upright, unshifted picture; they show as bright dots when
    backlit only.  The whole picture is then turned by ``tilt`` degrees
    (clockwise) about its centre, half a turn more if ``turned``, and moved by
    ``shift``; see ``framed_position``.  ``inner_box`` draws a rectangle inside the
    opening (a reflection with straight edges).
    """
    width, height = size
    cx, cy, ow, oh, radius = OPENING
    pw, ph = PLATE
    rng = np.random.default_rng(seed)
    if lit == "back":
        outside, plate, inside, screw = 70, 8, 14, 45
    else:
        outside, plate, inside, screw = 225, 95, 35, 190
    if membrane is not None:
        inside = membrane
    img = Image.new("L", size, outside)
    draw = ImageDraw.Draw(img)
    draw.rectangle([cx - pw / 2, cy - ph / 2, cx + pw / 2, cy + ph / 2], fill=plate)
    draw.rounded_rectangle([cx - ow / 2, cy - oh / 2, cx + ow / 2, cy + oh / 2], radius=radius, fill=inside)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = cx + sx * (pw / 2 - 35), cy + sy * (ph / 2 - 35)
            draw.ellipse([x - 22, y - 22, x + 22, y + 22], fill=screw)
            draw.ellipse([x - 9, y - 9, x + 9, y + 9], fill=plate)
    if inner_box is not None:
        draw.rectangle(inner_box, fill=inside + (60 if inside < 128 else -60))
    if lit == "back":
        for x, y in pinholes:
            draw.ellipse([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=255)
    else:
        for _ in range(40):     # dust on the membrane, seen only from the front
            x = cx + rng.uniform(-ow / 2 + 20, ow / 2 - 20)
            y = cy + rng.uniform(-oh / 2 + 20, oh / 2 - 20)
            draw.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=200)
    angle = tilt + (180.0 if turned else 0.0)
    img = img.rotate(-angle, resample=Image.BICUBIC, center=(width / 2, height / 2),
                     translate=tuple(shift), fillcolor=outside)
    arr = np.asarray(img, dtype=np.float32) + rng.normal(0, 1.5, (height, width))
    grey = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([grey] * 3))


def framed_position(point, tilt=0.0, shift=(0.0, 0.0), turned=False, size=FRAMED_SIZE):
    """Where ``make_framed_filter`` draws an upright point given the same placement."""
    angle = math.radians(tilt + (180.0 if turned else 0.0))
    cx, cy = size[0] / 2, size[1] / 2
    dx, dy = point[0] - cx, point[1] - cy
    return (cx + dx * math.cos(angle) - dy * math.sin(angle) + shift[0],
            cy + dx * math.sin(angle) + dy * math.cos(angle) + shift[1])


def dot_centroid(img, near, window=12):
    """Centre of brightness near an expected position, in pixels."""
    arr = np.asarray(img.convert("L"), dtype=float)
    x0, y0 = int(round(near[0])) - window, int(round(near[1])) - window
    x0, y0 = max(0, x0), max(0, y0)
    patch = arr[y0:y0 + 2 * window, x0:x0 + 2 * window]
    patch = np.clip(patch - patch.min() - 0.5 * (patch.max() - patch.min()), 0, None)
    total = patch.sum()
    if total <= 0:
        return None
    ys, xs = np.mgrid[0:patch.shape[0], 0:patch.shape[1]]
    return (x0 + (xs * patch).sum() / total + 0.5, y0 + (ys * patch).sum() / total + 0.5)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def pump(app, seconds=0.05):
    """Let Tk process events for a moment."""
    end = time.time() + seconds
    while True:
        app.root.update()
        if time.time() >= end:
            break
        time.sleep(0.005)


def wait_idle(app, timeout=60):
    """Run the event loop until background work and pending renders have finished."""
    end = time.time() + timeout
    pump(app, 0.05)
    while app._busy or app._render_job is not None or app._quality_job is not None:
        if time.time() > end:
            raise TimeoutError("the app did not become idle")
        pump(app, 0.02)
    pump(app, 0.05)


class Click:
    """A stand-in for a Tk mouse event."""

    def __init__(self, widget, x, y):
        self.widget = widget
        self.x = x
        self.y = y
        self.x_root = widget.winfo_rootx() + int(x)
        self.y_root = widget.winfo_rooty() + int(y)
        self.state = 0
        self.delta = 0
        self.num = 1


def click(app, pane, x, y):
    canvas = pane.canvas
    app._on_press(Click(canvas, x, y))
    app._on_release(Click(canvas, x, y))


def drag(app, pane, start, end, steps=4):
    canvas = pane.canvas
    app._on_press(Click(canvas, *start))
    for i in range(1, steps + 1):
        t = i / steps
        app._on_drag(Click(canvas, start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t))
    app._on_release(Click(canvas, *end))
