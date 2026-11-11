"""Render an export image: panels, markers, legend and watermark.

This is the drawing half of an export, with no user-interface dependency, so the
same code produces the picture whether it was asked for from the window (see
``export.py``) or from the command line (see ``cli.py``).

Everything the drawing needs is gathered in a :class:`Scene`; the Tk application
builds one from its widgets, the command line builds one from a session file.
"""

import datetime
import math

import numpy as np

from PIL import Image, ImageDraw, ImageFont

from . import geometry as geo
from .imaging import blank_frame
from .metadata import APP_VERSION
from .pair import BACKLIT, FRONTLIT, marker_text

MAX_EXPORT_PIXELS = 160e6
GAP = 4

# Row indices, matching viewer.py.  Defined here so this module stays free of
# anything that imports tkinter.
CURRENT, REFERENCE = 0, 1


def _font(size):
    try:
        return ImageFont.load_default(size=max(6, int(size)))
    except TypeError:  # Pillow without a scalable default font
        return ImageFont.load_default()


class Scene:
    """Everything needed to draw an export, independent of where it came from."""

    def __init__(self, pairs, zoom=1.0, pan_x=0.0, pan_y=0.0, mode="sidebyside",
                 opacity=0.5, crop_pad=20, label_size=12, legend_size=10,
                 line_width=2.0, px_per_point=96.0 / 72.0, row_matrix=None):
        self.pairs = pairs
        self.zoom = float(zoom)
        self.pan_x = float(pan_x)
        self.pan_y = float(pan_y)
        self.mode = mode
        self.opacity = float(opacity)
        self.crop_pad = int(crop_pad)
        self.label_size = label_size
        self.legend_size = legend_size
        self.line_width = line_width
        self.px_per_point = float(px_per_point)
        self._row_matrix = row_matrix

    def pair_to_world(self, row):
        if row == REFERENCE and self._row_matrix is not None:
            return self._row_matrix
        return geo.identity()

    def world_matrix(self, row, idx):
        return self.pair_to_world(row) @ self.pairs[row].matrix(idx)

    # -- the two helpers the viewer also has, in their pure form --------- #

    def render_frame(self, row, idx, size, view, quality=True):
        pair = self.pairs[row]
        pyramid = pair.pyramids[idx]
        if pyramid is None:
            return None
        matrix = view @ self.world_matrix(row, idx)
        return pyramid.render(matrix, size, quality=quality, lut=pair.lut(idx))

    def compose_pane(self, row, idx, size, view, quality=True):
        if self.mode != "overlay":
            return self.render_frame(row, idx, size, view, quality)
        back = self.render_frame(row, BACKLIT, size, view, quality)
        front = self.render_frame(row, FRONTLIT, size, view, quality)
        if back is not None and front is not None:
            return Image.blend(back, front, self.opacity)
        return back if back is not None else front


# Labels keep this much clear space around them, as a fraction of text height,
# so that separated labels have a visible gap rather than merely not touching.
LABEL_GAP = 0.30
LABEL_RINGS = 16          # how far out a crowded label may go, in steps of about a text height
LABEL_DIRECTIONS = 16     # directions tried at each step
SHELF = 0.14              # the line under a moved label, below the text, as a fraction of text height

# What a placement costs if it breaks a rule, worst first.  A spot that breaks
# none is always taken in preference to any that breaks one.
_OUTSIDE, _ON_LABEL, _ON_MARKER, _LEADER_ON_LABEL, _LEADER_ON_MARKER, _LEADERS_CROSS = (
    1e9, 1e8, 1e7, 1e6, 1e5, 1e4)


def _boxes_hit(boxes, box):
    """Which of ``boxes`` (n x 4: x0, y0, x1, y1) overlap ``box``."""
    if not len(boxes):
        return np.zeros(0, dtype=bool)
    return ((boxes[:, 0] < box[2]) & (boxes[:, 2] > box[0])
            & (boxes[:, 1] < box[3]) & (boxes[:, 3] > box[1]))


def _circles_hit_box(circles, box):
    """Which circles (n x 3: cx, cy, r) a box overlaps."""
    if not len(circles):
        return np.zeros(0, dtype=bool)
    nx = np.clip(circles[:, 0], box[0], box[2])
    ny = np.clip(circles[:, 1], box[1], box[3])
    return np.hypot(circles[:, 0] - nx, circles[:, 1] - ny) < circles[:, 2]


def _segment_points(p, q, count=16):
    t = np.linspace(0.0, 1.0, count)[:, None]
    p = np.asarray(p, dtype=float)
    return p + t * (np.asarray(q, dtype=float) - p)


def _points_in_boxes(points, boxes):
    """Which boxes any of ``points`` falls inside."""
    if not len(boxes):
        return np.zeros(0, dtype=bool)
    xs, ys = points[:, 0][:, None], points[:, 1][:, None]
    inside = (xs > boxes[:, 0]) & (xs < boxes[:, 2]) & (ys > boxes[:, 1]) & (ys < boxes[:, 3])
    return inside.any(axis=0)


def _segment_hits_circles(p, q, circles):
    """Which circles the segment ``p``-``q`` passes through."""
    if not len(circles):
        return np.zeros(0, dtype=bool)
    p, q = np.asarray(p, dtype=float), np.asarray(q, dtype=float)
    d = q - p
    length2 = float(d @ d) or 1e-9
    t = np.clip(((circles[:, :2] - p) @ d) / length2, 0.0, 1.0)
    nearest = p + t[:, None] * d
    return np.hypot(*(circles[:, :2] - nearest).T) < circles[:, 2]


def _segments_cross(p, q, segments):
    """Which of ``segments`` (n x 4) the segment ``p``-``q`` properly crosses."""
    if not len(segments):
        return np.zeros(0, dtype=bool)
    a, b = segments[:, :2], segments[:, 2:]
    p = np.broadcast_to(np.asarray(p, dtype=float), a.shape)
    q = np.broadcast_to(np.asarray(q, dtype=float), a.shape)

    def side(o, u, v):
        return (u[:, 0] - o[:, 0]) * (v[:, 1] - o[:, 1]) - (u[:, 1] - o[:, 1]) * (v[:, 0] - o[:, 0])

    return (side(p, q, a) * side(p, q, b) < 0) & (side(a, b, p) * side(a, b, q) < 0)


def _candidates(cx, cy, radius, w, h, pad):
    """Places a label might go, nearest first: ``(cost, x, centre_y, ring)``.
    Ring 0 is beside the marker (no leader); further rings need one."""
    out = [(0.0, cx + radius + pad, cy, 0), (1.0, cx - radius - pad - w, cy, 0)]
    step = 0.9 * h
    for ring in range(1, LABEL_RINGS + 1):
        reach = radius + pad + ring * step
        for k in range(LABEL_DIRECTIONS):
            angle = 2.0 * math.pi * k / LABEL_DIRECTIONS
            ux, uy = math.cos(angle), math.sin(angle)
            if abs(ux) > 0.3:          # beside: the near end of the text faces the marker
                x = cx + ux * reach if ux > 0 else cx + ux * reach - w
                y = cy + uy * reach
            else:                      # above or below: centred over the direction
                x = cx + ux * reach - w / 2.0
                y = cy + uy * reach + (h / 2.0 if uy > 0 else -h / 2.0)
            # Prefer near, then to the side (as an uncrowded label sits), then right.
            cost = 10.0 * ring + 2.0 * abs(uy) + (0.5 if ux < 0 else 0.0)
            out.append((cost, x, y, ring))
    out.sort(key=lambda item: item[0])
    return out


def _leader(cx, cy, radius, stroke, x, y, w, h):
    """The leader of a moved label: from the rim of its marker to the near end of
    the shelf under the text."""
    left_side = x + w / 2.0 < cx
    near = (x + w if left_side else x, y + h / 2.0 + SHELF * h)
    dx, dy = near[0] - cx, near[1] - cy
    span = math.hypot(dx, dy) or 1.0
    return (cx + dx / span * (radius + stroke), cy + dy / span * (radius + stroke)), near, left_side


def label_layout(items, font, measure, width, height, stroke):
    """Choose where each marker label goes, so that labels stay readable.

    ``items`` is a sequence of ``(cx, cy, radius, text)`` in panel pixels.
    Returns one dict per item: ``x`` (left of the text), ``y`` (its middle),
    ``w``, ``h``, ``left`` (the text is left of its marker) and ``leader``
    (it was moved away from its marker and needs a line back to it).

    A label goes beside its marker if that is clear.  Otherwise it is moved out,
    step by step and in all directions, to the nearest place where it overlaps
    no other label and no marker, and where its leader line crosses no label,
    no marker and no other leader.  Crowded markers are placed first, while
    there is most room near them.  Only if nowhere in reach is clear is the
    least bad place taken.  An uncrowded map keeps every label beside its marker.
    """
    n = len(items)
    if not n:
        return []
    pad = stroke + 3
    sizes = []
    for _cx, _cy, _r, text in items:
        left, top, right, bottom = measure.textbbox((0, 0), text, font=font)
        sizes.append((right - left, bottom - top))
    text_h = max(h for _w, h in sizes)
    gap = LABEL_GAP * text_h
    circles = np.array([(cx, cy, r + stroke / 2.0 + gap / 2.0) for cx, cy, r, _t in items], dtype=float)

    # Most crowded first: they have the fewest good places.
    centres = circles[:, :2]
    crowd = (np.hypot(centres[:, None, 0] - centres[None, :, 0],
                      centres[:, None, 1] - centres[None, :, 1]) < 6.0 * text_h).sum(axis=1)
    order = sorted(range(n), key=lambda i: (-crowd[i], items[i][1], items[i][0]))

    placed = np.zeros((0, 4))
    leaders = np.zeros((0, 4))
    out = [None] * n
    for i in order:
        cx, cy, radius, _text = items[i]
        w, h = sizes[i]
        others = np.delete(circles, i, axis=0)
        best = None
        for base, x, y, ring in _candidates(cx, cy, radius, w, h, pad):
            top, bottom = y - h / 2.0, y + h / 2.0 + SHELF * h + 1.0
            box = (x - gap / 2.0, top - gap / 2.0, x + w + gap / 2.0, bottom + gap / 2.0)
            penalty = 0.0
            if x < 0 or top < 0 or x + w > width or bottom > height:
                penalty += _OUTSIDE
            penalty += _ON_LABEL * float(_boxes_hit(placed, box).sum())
            penalty += _ON_MARKER * float(_circles_hit_box(others, box).sum())
            if ring and penalty < _ON_MARKER:
                rim, near, _left = _leader(cx, cy, radius, stroke, x, y, w, h)
                penalty += _LEADER_ON_LABEL * float(_points_in_boxes(_segment_points(rim, near), placed).sum())
                penalty += _LEADER_ON_MARKER * float(_segment_hits_circles(rim, near, others).sum())
                penalty += _LEADERS_CROSS * float(_segments_cross(rim, near, leaders).sum())
            cost = penalty + base
            if best is None or cost < best[0]:
                best = (cost, x, y, ring, box)
                if penalty == 0.0:
                    break      # candidates come nearest first, so the first clear one is the best
        _cost, x, y, ring, box = best
        placed = np.vstack([placed, box])
        rim, near, left_side = _leader(cx, cy, radius, stroke, x, y, w, h)
        if ring:
            leaders = np.vstack([leaders, [rim[0], rim[1], near[0], near[1]]])
        out[i] = {"x": float(x), "y": float(y), "w": w, "h": h, "left": bool(left_side),
                  "leader": bool(ring)}
    return out


def export_geometry(scene, x0, y0, x1, y1, rows):
    """Output scale, padding and panel size for a canvas rectangle."""
    pad = max(0, int(scene.crop_pad))
    panels = len(rows) * (1 if scene.mode == "overlay" else 2)
    world_w = max(1.0, (x1 - x0) / scene.zoom)
    world_h = max(1.0, (y1 - y0) / scene.zoom)
    # Native resolution of the current backlit image, unless that would be enormous.
    scale = min(1.0, math.sqrt(MAX_EXPORT_PIXELS / (world_w * world_h * panels)))
    width = max(1, int(round(world_w * scale))) + 2 * pad
    height = max(1, int(round(world_h * scale))) + 2 * pad
    world_x0 = (x0 - scene.pan_x) / scene.zoom
    world_y0 = (y0 - scene.pan_y) / scene.zoom
    view = geo.translation(pad, pad) @ geo.scaling(scale) @ geo.translation(-world_x0, -world_y0)
    return view, scale, (width, height)


def export_images(scene, x0, y0, x1, y1, rows):
    """The image part of an export (slow); markers and text are added per preview."""
    view, scale, size = export_geometry(scene, x0, y0, x1, y1, rows)
    overlay = scene.mode == "overlay"
    rendered = []
    for row in rows:
        if overlay:
            frames = [scene.compose_pane(row, BACKLIT, size, view, True) or blank_frame(size)]
        else:
            frames = [scene.render_frame(row, idx, size, view, True) or blank_frame(size)
                      for idx in (BACKLIT, FRONTLIT)]
        rendered.append((row, frames))
    return {"view": view, "scale": scale, "size": size, "rows": rendered}


def compose_export(scene, images, label_size, legend_size, line_width):
    view, scale, (width, height) = images["view"], images["scale"], images["size"]
    rows = images["rows"]
    # Sizes are given as on screen; convert to output pixels.
    per_screen_px = scale / scene.zoom
    px_per_point = scene.px_per_point
    label_font = _font(label_size * px_per_point * per_screen_px)
    legend_font = _font(legend_size * px_per_point * per_screen_px)
    stroke = max(1, int(round(line_width * per_screen_px)))
    # Much finer than the lettering, so it guides the eye without competing.
    leader_width = max(1, int(round(label_font.size * 0.035)))
    with_titles = len(rows) > 1
    title_font = _font(max(14, height // 45))
    title_h = int(title_font.size * 2.0) if with_titles else 0

    panel_count = len(rows[0][1])
    total_w = width * panel_count + GAP * (panel_count - 1)
    total_h = (height + title_h) * len(rows) + GAP * (len(rows) - 1)
    result = Image.new("RGB", (total_w, total_h), (40, 40, 40))
    draw = ImageDraw.Draw(result)

    for n, (row, frames) in enumerate(rows):
        top = n * (height + title_h + GAP)
        pair = scene.pairs[row]
        if with_titles:
            name = ("Reference: " if row == REFERENCE else "Current: ") + (pair.label or "untitled")
            draw.text((title_font.size // 2, top + title_font.size // 2), name, fill="#dddddd",
                      font=title_font)
        to_output = view @ scene.world_matrix(row, BACKLIT)
        marker_scale = geo.scale_of(to_output)
        # Where every marker and its label go; the same in each panel, so work it
        # out once and keep crowded labels legible by moving them apart.
        visible = []
        for ann in pair.annotations:
            cx, cy = geo.apply(to_output, ann["img1_x"], ann["img1_y"])
            radius = max(2.0, ann["radius"] * marker_scale)
            if cx + radius < 0 or cy + radius < 0 or cx - radius > width or cy - radius > height:
                continue
            visible.append((cx, cy, radius, ann))
        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        labelled = [(cx, cy, r, marker_text(a)) for cx, cy, r, a in visible if marker_text(a)]
        layout = label_layout(labelled, label_font, measure, width, height, stroke)
        places = iter(layout)
        for col, frame in enumerate(frames):
            # Markers are drawn on the panel itself so they never spill into its neighbour.
            panel = frame.copy()
            panel_draw = ImageDraw.Draw(panel)
            places = iter(layout)
            for cx, cy, radius, ann in visible:
                panel_draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                                   outline=ann["colour"], width=stroke)
                text = marker_text(ann)
                if not text:
                    continue
                place = next(places)
                x, y = place["x"], place["y"]
                if place["leader"]:
                    # A moved label is joined to its marker by a thin line that
                    # runs from the rim of the circle to a shelf under the text,
                    # so it is unambiguous which spot the label belongs to and
                    # the line never crosses the writing.
                    shelf_y = y + place["h"] / 2 + max(1.0, place["h"] * SHELF)
                    near_x = x + place["w"] if place["left"] else x
                    far_x = x if place["left"] else x + place["w"]
                    dx, dy = near_x - cx, shelf_y - cy
                    span = math.hypot(dx, dy) or 1.0
                    panel_draw.line([cx + dx / span * (radius + stroke / 2),
                                     cy + dy / span * (radius + stroke / 2),
                                     near_x, shelf_y, far_x, shelf_y],
                                    fill=ann["colour"], width=leader_width, joint="curve")
                panel_draw.text((x, y), text, fill=ann["colour"], font=label_font, anchor="lm")
            result.paste(panel, (col * (width + GAP), top + title_h))

    draw_watermark(result)
    legends = [(scene.pairs[row].label if with_titles else None, scene.pairs[row].legend())
               for row, _frames in rows]
    return attach_legend(result, legends, legend_font)


def draw_watermark(img):
    size = max(10, min(img.width, img.height) // 80)
    font = _font(size)
    text = f"MSSL FOCUS v{APP_VERSION}  |  {datetime.date.today().isoformat()}"
    draw = ImageDraw.Draw(img)
    box = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = box[2] - box[0], box[3] - box[1]
    pad = max(4, size // 3)
    x = pad
    y = img.height - text_h - pad * 3
    draw.rectangle([x, y, x + text_w + pad * 2, y + text_h + pad * 2], fill="#1e1e1e", outline="#555555")
    draw.text((x + pad - box[0], y + pad - box[1]), text, fill="#cccccc", font=font)


def attach_legend(result, legends, font):
    legends = [(title, data) for title, data in legends if data]
    if not legends:
        return result
    line = int(font.size * 1.7)
    swatch = int(font.size * 0.9)
    pad = max(8, font.size // 2)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows = []  # (kind, colour, text)
    for title, data in legends:
        if title:
            rows.append(("title", "#dddddd", title))
        for colour, text in data:
            rows.append(("entry", colour, text))
        rows.append(("gap", None, ""))
    rows.pop()
    text_w = max(measure.textbbox((0, 0), text, font=font)[2] for _k, _c, text in rows)
    box_w = pad * 2 + swatch + 6 + text_w
    box_h = pad * 2 + sum(line // 2 if kind == "gap" else line for kind, _c, _t in rows)
    final = Image.new("RGB", (result.width + box_w + pad * 2, max(result.height, box_h + pad * 2)),
                      (30, 30, 30))
    final.paste(result, (0, 0))
    draw = ImageDraw.Draw(final)
    x0 = result.width + pad
    y = max(pad, (final.height - box_h) // 2)
    draw.rectangle([x0, y, x0 + box_w, y + box_h], fill="#1e1e1e", outline="#555555")
    y += pad
    for kind, colour, text in rows:
        if kind == "gap":
            y += line // 2
            continue
        middle = y + line // 2
        if kind == "title":
            draw.text((x0 + pad, middle), text, fill=colour, font=font, anchor="lm")
        else:
            draw.rectangle([x0 + pad, middle - swatch // 2, x0 + pad + swatch, middle + swatch // 2],
                           fill=colour)
            draw.text((x0 + pad + swatch + 6, middle), text, fill=colour, font=font, anchor="lm")
        y += line
    return final


def render_rect(scene, x0, y0, x1, y1, rows=None):
    """Draw the canvas rectangle ``(x0, y0, x1, y1)`` for the given rows."""
    rows = [CURRENT] if rows is None else rows
    images = export_images(scene, x0, y0, x1, y1, rows)
    return compose_export(scene, images, scene.label_size, scene.legend_size, scene.line_width)
