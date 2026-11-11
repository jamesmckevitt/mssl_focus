"""Render an export image: panels, markers, legend and watermark.

This is the drawing half of an export, with no user-interface dependency, so the
same code produces the picture whether it was asked for from the window (see
``export.py``) or from the command line (see ``cli.py``).

Everything the drawing needs is gathered in a :class:`Scene`; the Tk application
builds one from its widgets, the command line builds one from a session file.
"""

import datetime
import math

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


def _overlap(a, b):
    """Area shared by two label boxes once their clear space is allowed for."""
    margin = (a["h"] + b["h"]) / 2 * LABEL_GAP
    gap_x = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]) + margin / 2
    gap_y = (min(a["y"] + a["h"] / 2, b["y"] + b["h"] / 2)
             - max(a["y"] - a["h"] / 2, b["y"] - b["h"] / 2)) + margin
    return gap_x * gap_y if gap_x > 0 and gap_y > 0 else 0.0


def _clear_of_markers(box, markers, own):
    """Push a label off any marker circle it is sitting on.  Markers cannot move,
    so only the label does.  Its own marker is skipped: the label is placed
    beside that one on purpose."""
    moved = False
    for n, (mx, my, mr) in enumerate(markers):
        if n == own:
            continue
        gap_x = min(box["x"] + box["w"], mx + mr) - max(box["x"], mx - mr)
        gap_y = min(box["y"] + box["h"] / 2, my + mr) - max(box["y"] - box["h"] / 2, my - mr)
        if gap_x <= 0 or gap_y <= 0:
            continue
        box["y"] += (gap_y + 1) if box["y"] >= my else -(gap_y + 1)
        moved = True
    return moved


def _relax(boxes, max_iter, markers=()):
    """Separate overlapping labels vertically, which costs least room, while a
    weak pull towards the marker stops a crowded group drifting away from it."""
    for _ in range(max_iter):
        moved = False
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                if not _overlap(a, b):
                    continue
                moved = True
                gap_y = (min(a["y"] + a["h"] / 2, b["y"] + b["h"] / 2)
                         - max(a["y"] - a["h"] / 2, b["y"] - b["h"] / 2)
                         + (a["h"] + b["h"]) / 2 * LABEL_GAP)
                push = gap_y / 2 + 1
                if a["y"] <= b["y"]:
                    a["y"] -= push
                    b["y"] += push
                else:
                    a["y"] += push
                    b["y"] -= push
        for n, box in enumerate(boxes):
            if _clear_of_markers(box, markers, n):
                moved = True
        if not moved:
            return
        for box in boxes:
            box["y"] += 0.012 * (box["cy"] - box["y"])


def _side(box, left):
    box["x"] = (box["cx"] - box["r"] - box["pad"] - box["w"]) if left \
        else (box["cx"] + box["r"] + box["pad"])
    box["left"] = left


def label_layout(items, font, measure, width, height, stroke, max_iter=600):
    """Choose where each marker label goes, nudging apart any that collide.

    ``items`` is a sequence of ``(cx, cy, radius, text)`` in panel pixels.
    Returns one ``(x, y, leader)`` per item: the left-centre anchor for the
    text, and whether the label ended up far enough from its marker to need a
    line drawn back to it.

    A label that collides with nothing keeps its usual place beside the marker,
    so maps without crowding are unchanged.
    """
    boxes = []
    for cx, cy, radius, text in items:
        left, top, right, bottom = measure.textbbox((0, 0), text, font=font)
        box = {"y": float(cy), "w": right - left, "h": bottom - top,
               "cx": cx, "cy": cy, "r": radius, "pad": stroke + 3}
        _side(box, False)
        boxes.append(box)
    markers = [(b["cx"], b["cy"], b["r"]) for b in boxes]

    _relax(boxes, max_iter, markers)
    # Where labels are still piled up, try putting one on the other side of its
    # marker: in a dense group there is usually room on the left.
    for _ in range(3):
        crowded = [b for b in boxes if any(_overlap(b, o) for o in boxes if o is not b)]
        if not crowded:
            break
        for box in crowded:
            before = sum(_overlap(box, o) for o in boxes if o is not box)
            start_x, start_y, start_left = box["x"], box["y"], box["left"]
            _side(box, not start_left)
            box["y"] = box["cy"]
            after = sum(_overlap(box, o) for o in boxes if o is not box)
            # Keep the swap only if it genuinely helps and stays on the panel:
            # a label clipped by the edge is worse than one that overlaps.
            fits = box["x"] >= 0 and box["x"] + box["w"] <= width
            if after >= before or not fits:
                box["x"], box["y"], box["left"] = start_x, start_y, start_left
        _relax(boxes, max_iter, markers)

    out = []
    for box in boxes:
        y = min(max(box["y"], box["h"] / 2), max(box["h"] / 2, height - box["h"] / 2))
        x = min(max(box["x"], 0), max(0, width - box["w"]))
        out.append({"x": x, "y": y, "w": box["w"], "h": box["h"], "left": box["left"],
                    "leader": abs(y - box["cy"]) > max(2.0, box["h"] * 0.35) or box["left"]})
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
    leader_width = max(1, int(round(label_font.size * 0.02)))
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
                    shelf_y = y + place["h"] / 2 + max(1.0, place["h"] * 0.14)
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
