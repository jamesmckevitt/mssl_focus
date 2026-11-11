"""A filter's inspection history: every inspection of one filter, and every pinhole
ever found in it, in one file (for example ``em2.json``).

Sessions describe one inspection each and know nothing of the last, so a spot
rejected in one inspection looked new in the next.  A history holds instead:

* each **inspection** in order: its stage (incoming, shock test, ...), date,
  backlit and frontlit photographs, how they line up, the filter outline, and
  how its backlit pixels map onto the filter;
* each **pinhole** with a permanent ID (``I3``, ``S1``, ...), the inspection it was
  first seen in, and its status, ``accepted`` or ``rejected``.  Positions are kept
  in *filter coordinates*, so a pinhole found once is known in every later
  inspection, and a rejected spot is recognised and skipped when found again.

Filter coordinates are pixels of the first aligned inspection's backlit image,
turned upright, with the origin at the centre of the membrane's opening.  Each
inspection stores ``to_filter``, the similarity taking its backlit pixels there.

This module has no user-interface dependency; ``cli.py`` drives it from the
command line and ``session.py`` opens a history in the window.
"""

import datetime
import math
import os
import re
from pathlib import Path

import numpy as np

from . import geometry as geo
from .pair import BACKLIT, FRONTLIT, ImagePair, normalise_annotation
from .session_data import (RAW_CROP_VERSION, SESSION_VERSION, develop_record, read_session,
                           relative_to, resolve_frame_paths, resolve_image_path,
                           session_image_paths, write_session, _float)

HISTORY_TYPE = "mssl_focus_filter_history"
HISTORY_VERSION = 1

ACCEPTED, REJECTED = "accepted", "rejected"
STATUSES = (ACCEPTED, REJECTED)
REJECTED_COLOUR = "#9a9a9a"

# The standard categories: key, legend name, colour, label prefix.
CATEGORIES = [
    {"key": "incoming", "name": "Incoming Pinholes", "colour": "#00cc44", "prefix": "I"},
    {"key": "repairs", "name": "Incoming Repairs", "colour": "#ff0088", "prefix": "R"},
    {"key": "shock", "name": "Shock Test", "colour": "#ff0000", "prefix": "S"},
    {"key": "acoustic", "name": "Acoustic Test", "colour": "#ff6600", "prefix": "A"},
    {"key": "thermal", "name": "Thermal Test", "colour": "#00cccc", "prefix": "T"},
    {"key": "ship", "name": "Ship to NAOJ", "colour": "#ffff00", "prefix": "X"},
]

# Inspection stages, each with the category its new pinholes go in by default.
STAGES = {
    "incoming": ("Incoming inspection", "incoming"),
    "shock": ("Shock test", "shock"),
    "acoustic": ("Acoustic test", "acoustic"),
    "thermal": ("Thermal test", "thermal"),
    "ship": ("Ship to NAOJ", "ship"),
}
_STAGE_WORDS = [
    ("incoming", "incoming"), ("shock", "shock"), ("acoustic", "acoustic"), ("vibration", "acoustic"),
    ("thermal", "thermal"), ("naoj", "ship"), ("ship", "ship"),
]

OUTLINE_INSET = 0.01      # the search area stays this fraction of the opening's size inside its edge
MATCH_REACH = 12.0        # filter pixels: a spot this close to a known pinhole (or its circle) is that pinhole
REGISTER_REACH = 30.0     # how far known pinholes are looked for when lining an inspection up
FRONTLIT_REACH = 6.0      # backlit pixels: a frontlit spot this close flags a candidate
SEARCH_PAD = 80           # pixels searched beyond the outline, so spots on its edge are judged fairly
SPOT_LIMIT = 12000
MARKER_RADIUS = 20.0      # backlit pixels: the circle drawn round a new pinhole, as in the window

_ID_PATTERN = re.compile(r"^(.*?)(\d+)$")


class HistoryError(ValueError):
    """Something asked of a history that it cannot do."""


# --------------------------------------------------------------------------- #
# Categories and stages
# --------------------------------------------------------------------------- #

def stage_key(text):
    """A stage key from a name, alias or folder name (``5_thermal_test`` -> ``thermal``)."""
    word = str(text or "").strip().lower()
    if word in STAGES:
        return word
    for fragment, key in _STAGE_WORDS:
        if fragment in word:
            return key
    raise HistoryError(f"unknown stage {text!r}; use one of: {', '.join(STAGES)}")


def categories(history):
    return history.get("categories") or [dict(c) for c in CATEGORIES]


def category(history, key):
    for entry in categories(history):
        if entry["key"] == key:
            return entry
    raise HistoryError(f"unknown category {key!r}; use one of: "
                       + ", ".join(c["key"] for c in categories(history)))


def category_for_colour(history, colour):
    colour = str(colour or "").lower()
    for entry in categories(history):
        if entry["colour"].lower() == colour:
            return entry
    return None


def category_for_label(history, label):
    match = _ID_PATTERN.match(str(label or ""))
    if match:
        for entry in categories(history):
            if entry["prefix"] == match.group(1):
                return entry
    return None


# --------------------------------------------------------------------------- #
# The file
# --------------------------------------------------------------------------- #

def new_history(filter_name=""):
    return {
        "type": HISTORY_TYPE,
        "version": HISTORY_VERSION,
        "filter": filter_name,
        "categories": [dict(c) for c in CATEGORIES],
        "frame": None,
        "inspections": [],
        "pinholes": [],
    }


def is_history(data):
    return isinstance(data, dict) and data.get("type") == HISTORY_TYPE


def read_history(path):
    data = read_session(path)
    if not is_history(data):
        raise HistoryError(f"{path} is not a filter history file")
    data.setdefault("categories", [dict(c) for c in CATEGORIES])
    data.setdefault("frame", None)
    data.setdefault("inspections", [])
    data.setdefault("pinholes", [])
    return data


def write_history(path, history):
    write_session(path, history)


def history_path(name, must_exist=True):
    """The history file a name refers to: a path, or a bare filter name such as
    ``em2`` for ``em2.json`` in the current folder."""
    path = Path(name)
    if path.is_file():
        return path
    if path.suffix.lower() != ".json":
        with_suffix = path.with_name(path.name + ".json")
        if with_suffix.is_file() or not must_exist:
            return with_suffix
    if must_exist:
        raise HistoryError(f"no history file {name!r} (looked for {path} and {path}.json)")
    return path


# --------------------------------------------------------------------------- #
# Inspections
# --------------------------------------------------------------------------- #

def inspection_index(history, ref=None):
    """Index of an inspection named by its ID, its stage, its number (1 = first)
    or ``latest``; the latest when ``ref`` is None."""
    inspections = history["inspections"]
    if not inspections:
        raise HistoryError("the history has no inspections yet")
    if ref is None or str(ref).lower() in ("latest", "last"):
        return len(inspections) - 1
    text = str(ref).strip()
    for n, insp in enumerate(inspections):
        if insp["id"] == text:
            return n
    if text.isdigit():
        n = int(text) - 1
        if 0 <= n < len(inspections):
            return n
    try:
        key = stage_key(text)
    except HistoryError:
        key = None
    matches = [n for n, insp in enumerate(inspections) if insp.get("stage") == key]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise HistoryError(f"{text!r} matches several inspections ({', '.join(inspections[n]['id'] for n in matches)}); "
                           "name one by its ID")
    raise HistoryError(f"no inspection {text!r}; this history has: "
                       + ", ".join(i["id"] for i in inspections))


def inspection(history, ref=None):
    return history["inspections"][inspection_index(history, ref)]


def _new_inspection_id(history, stage):
    taken = {insp["id"] for insp in history["inspections"]}
    if stage not in taken:
        return stage
    n = 2
    while f"{stage}-{n}" in taken:
        n += 1
    return f"{stage}-{n}"


def capture_date(path):
    """The date a photograph was taken, from its metadata, else the file's date."""
    from .camera import read_camera_info
    taken = read_camera_info(path).get("taken") if path else None
    if taken:
        try:
            return datetime.datetime.strptime(taken[:19], "%Y:%m:%d %H:%M:%S").date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except (OSError, TypeError):
        return datetime.date.today().isoformat()


def add_inspection(history, history_file, stage, backlit, frontlit=None, date=None, name=None,
                   category_key=None):
    """Add an inspection (not yet aligned) and return it.

    Inspections are kept in date order, so one photographed before the latest
    (a stage added late) goes in its place; ``history["inspections"].index(insp)``
    says where."""
    stage = stage_key(stage)
    default_name, default_category = STAGES[stage]
    category(history, category_key or default_category)     # check it exists
    base = Path(history_file).resolve().parent
    paths = [str(Path(p).resolve()) if p else None for p in (backlit, frontlit)]
    for p in paths:
        if p and not Path(p).is_file():
            raise HistoryError(f"image not found: {p}")
    insp = {
        "id": _new_inspection_id(history, stage),
        "stage": stage,
        "name": name or default_name,
        "date": date or capture_date(paths[BACKLIT]),
        "category": category_key or default_category,
        "images": _image_record(paths, base),
    }
    later = [n for n, other in enumerate(history["inspections"])
             if other.get("date") and insp["date"] and other["date"] > insp["date"]]
    history["inspections"].insert(later[0] if later else len(history["inspections"]), insp)
    return insp


def _image_record(paths, base_dir):
    return {
        "backlit": paths[BACKLIT],
        "frontlit": paths[FRONTLIT],
        "backlit_rel": relative_to(paths[BACKLIT], base_dir),
        "frontlit_rel": relative_to(paths[FRONTLIT], base_dir),
    }


def image_paths(insp, history_file):
    """``(resolved, saved)`` for an inspection's backlit and frontlit images."""
    base = Path(history_file).resolve().parent
    images = insp.get("images") or {}
    resolved, saved = [], []
    for kind in ("backlit", "frontlit"):
        stored, rel = images.get(kind), images.get(kind + "_rel")
        resolved.append(resolve_image_path(stored, rel, base) if (stored or rel) else None)
        saved.append(stored or rel)
    return resolved, saved


def to_filter(insp):
    """The matrix taking an inspection's backlit pixels to filter coordinates, or None."""
    rows = insp.get("to_filter")
    if not rows:
        return None
    return np.vstack([np.asarray(rows, dtype=float).reshape(2, 3), [0.0, 0.0, 1.0]])


def _store_matrix(matrix):
    return [[round(float(v), 9) for v in row] for row in np.asarray(matrix)[:2]]


def frontlit_to_backlit(insp, sizes):
    """Frontlit pixels -> backlit pixels from an inspection's alignment record.
    ``sizes`` are the (width, height) of the backlit and frontlit images."""
    pair = _sized_pair(sizes)
    pair.apply_alignment_record(insp.get("alignment"))
    return geo.invert(pair.matrix(BACKLIT)) @ pair.matrix(FRONTLIT)


def _sized_pair(sizes):
    """An ImagePair that knows only its images' sizes, for the alignment arithmetic."""
    pair = ImagePair()
    for idx, size in enumerate(sizes):
        if size is not None:
            pair.pyramids[idx] = _Sized(size)
    return pair


class _Sized:
    def __init__(self, size):
        self.size = tuple(size)


# --------------------------------------------------------------------------- #
# Pinholes
# --------------------------------------------------------------------------- #

def pinhole(history, pid):
    for p in history["pinholes"]:
        if p["id"].lower() == str(pid).lower():
            return p
    return None


def next_id(history, prefix):
    """The next unused ID for a prefix.  IDs are never reused, rejected or not."""
    highest = 0
    for p in history["pinholes"]:
        match = _ID_PATTERN.match(p["id"])
        if match and match.group(1) == prefix:
            highest = max(highest, int(match.group(2)))
    return f"{prefix}{highest + 1}"


def _first_seen_index(history, p):
    for n, insp in enumerate(history["inspections"]):
        if insp["id"] == p.get("first_seen"):
            return n
    return len(history["inspections"])


def known_at(history, index, statuses=(ACCEPTED,)):
    """Pinholes first seen in or before inspection ``index`` with one of ``statuses``."""
    return [p for p in history["pinholes"]
            if p.get("status", ACCEPTED) in statuses and _first_seen_index(history, p) <= index]


def set_status(history, ids, status):
    """Accept or reject pinholes by ID.  Returns ``(changed, unchanged, unknown)`` ID lists."""
    if status not in STATUSES:
        raise HistoryError(f"status must be one of {', '.join(STATUSES)}")
    changed, unchanged, unknown = [], [], []
    today = datetime.date.today().isoformat()
    for pid in ids:
        p = pinhole(history, pid)
        if p is None:
            unknown.append(pid)
        elif p.get("status", ACCEPTED) == status:
            unchanged.append(p["id"])
        else:
            p["status"] = status
            p["status_date"] = today
            changed.append(p["id"])
    return changed, unchanged, unknown


def image_position(insp, p):
    """Where a pinhole is in an inspection's backlit image: ``(x, y, radius)``."""
    matrix = to_filter(insp)
    if matrix is None:
        raise HistoryError(f"inspection {insp['id']} has not been aligned yet")
    back = geo.invert(matrix)
    x, y = geo.apply(back, p["x"], p["y"])
    return x, y, float(p.get("radius", 20.0)) * geo.scale_of(back)


def _nearest(points, x, y):
    """Index and distance of the nearest of ``points`` (``(x, y, reach)``) whose
    reach covers ``(x, y)``, or ``(None, inf)``."""
    best, best_d = None, math.inf
    for n, (px, py, reach) in enumerate(points):
        d = math.hypot(px - x, py - y)
        if d <= reach and d < best_d:
            best, best_d = n, d
    return best, best_d


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #

def _inset_outline(aperture, inset_fraction=OUTLINE_INSET):
    from .autoalign import Aperture
    inset = inset_fraction * min(aperture.width, aperture.height)
    shrunk = Aperture(aperture.cx, aperture.cy, aperture.width - 2 * inset, aperture.height - 2 * inset,
                      aperture.tilt, max(0.0, aperture.radius - inset))
    return [[round(x, 3), round(y, 3)] for x, y in shrunk.points()]


def aperture_from_outline(points):
    """The rounded rectangle an outline (image pixels) describes, as an Aperture."""
    import cv2
    from .autoalign import Aperture
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(pts) < 3:
        raise HistoryError("an outline needs at least three points")
    rect = cv2.minAreaRect(pts)
    (cx, cy) = rect[0]
    corners = cv2.boxPoints(rect).astype(float)
    first, second = corners[1] - corners[0], corners[2] - corners[1]
    # The side nearer horizontal gives the tilt and the width.
    if abs(first[1]) * abs(second[0]) <= abs(second[1]) * abs(first[0]):
        flat, upright = first, second
    else:
        flat, upright = second, first
    if flat[0] < 0:
        flat = -flat
    tilt = math.degrees(math.atan2(float(flat[1]), float(flat[0])))
    width = float(np.hypot(*flat))
    height = float(np.hypot(*upright))
    area = abs(float(cv2.contourArea(pts)))
    radius = math.sqrt(max(0.0, width * height - area) / (4.0 - math.pi))
    return Aperture(cx, cy, width, height, tilt, radius)


def _frame_matrix(aperture, frame=None):
    """Backlit pixels -> filter coordinates from the opening alone: centred on it,
    turned upright, and scaled to the reference inspection's size if known."""
    matrix = geo.about((0.0, 0.0), 1.0, -aperture.tilt) @ geo.translation(-aperture.cx, -aperture.cy)
    if frame:
        scale = math.sqrt(frame["width"] * frame["height"] / (aperture.width * aperture.height))
        matrix = geo.scaling(scale) @ matrix
    return matrix


def _frame_record(aperture, insp_id):
    return {"width": round(aperture.width, 2), "height": round(aperture.height, 2),
            "radius": round(aperture.radius, 1), "reference": insp_id}


def find_spots(image, outline, pad=SEARCH_PAD):
    """Every spot the pinhole search finds in and around ``outline`` (image pixels)."""
    from .detect import find_pinholes, inside_polygon
    pts = np.asarray(outline, dtype=float).reshape(-1, 2)
    width, height = image.size
    box = (int(max(0, math.floor(pts[:, 0].min()) - pad)), int(max(0, math.floor(pts[:, 1].min()) - pad)),
           int(min(width, math.ceil(pts[:, 0].max()) + pad)), int(min(height, math.ceil(pts[:, 1].max()) + pad)))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return []
    found, _total = find_pinholes(image.crop(box), limit=SPOT_LIMIT)
    for c in found:
        c["x"] += box[0]
        c["y"] += box[1]
    if not found:
        return []
    inside = inside_polygon([c["x"] for c in found], [c["y"] for c in found], outline)
    return [c for c, ok in zip(found, inside) if ok]


def _register_on_pinholes(history, index, matrix, spots):
    """Improve ``matrix`` (backlit pixels -> filter) using pinholes already known
    from earlier inspections, matched to spots found now.  Also tries the filter
    turned half a turn, in case it was mounted the other way round.

    Returns ``(matrix, report)``; the matrix is unchanged if too few match.
    """
    known = [p for p in known_at(history, index - 1) if _first_seen_index(history, p) < index]
    report = {"known": len(known), "matched": 0}
    sure = [c for c in spots if c["tier"] != "faint"] or spots
    if len(known) < 4 or len(sure) < 4:
        return matrix, report
    spot_xy = np.array([(c["x"], c["y"]) for c in sure], dtype=float)
    filter_xy = np.array([(p["x"], p["y"]) for p in known], dtype=float)

    def matches(m, reach):
        image_xy = geo.apply_many(geo.invert(m), filter_xy)
        reach_px = reach / geo.scale_of(m)
        pairs = []
        for k, (x, y) in enumerate(image_xy):
            d = np.hypot(spot_xy[:, 0] - x, spot_xy[:, 1] - y)
            j = int(np.argmin(d))
            if d[j] <= reach_px:
                pairs.append((k, j, float(d[j])))
        # One spot per pinhole: the closest claim wins.
        pairs.sort(key=lambda t: t[2])
        used, out = set(), []
        for k, j, _d in pairs:
            if j not in used:
                used.add(j)
                out.append((k, j))
        return out

    best = None
    for turn in (0.0, 180.0):
        start = geo.about((0.0, 0.0), 1.0, turn) @ matrix
        m = start
        pairs = []
        for reach in (REGISTER_REACH, REGISTER_REACH / 2, MATCH_REACH / 2):
            pairs = matches(m, reach)
            if len(pairs) < 4:
                break
            src = spot_xy[[j for _k, j in pairs]]
            dst = filter_xy[[k for k, _j in pairs]]
            fitted, _rms = geo.fit_similarity(src, dst)
            m = fitted
        if len(pairs) >= 4 and (best is None or len(pairs) > len(best[1])):
            best = (m, pairs, turn)
    if best is None:
        return matrix, report
    m, pairs, turn = best
    src = spot_xy[[j for _k, j in pairs]]
    dst = filter_xy[[k for k, _j in pairs]]
    residual = np.hypot(*(geo.apply_many(m, src) - dst).T)
    # Trust it only if a good share of the known pinholes agree.
    if len(pairs) < max(4, 0.3 * len(known)):
        report["matched"] = len(pairs)
        return matrix, report
    report.update({"matched": len(pairs), "rms": round(float(np.sqrt((residual ** 2).mean())), 2),
                   "turned": turn})
    return m, report


def align_inspection(history, index, backlit, frontlit=None, inset=OUTLINE_INSET, keep_frontlit=False):
    """Align an inspection from its photographs: the frontlit image onto the backlit
    one, the filter upright, its outline, and the map onto filter coordinates.

    ``backlit`` and ``frontlit`` are PIL images.  With ``keep_frontlit`` the stored
    frontlit alignment is kept (as when it was set by hand).  Returns a report.
    """
    from .autoalign import AlignmentError, find_aperture, register_frontlit
    insp = history["inspections"][index]
    report = {"inspection": insp["id"]}
    sizes = (backlit.size, frontlit.size if frontlit is not None else None)

    front_to_back = geo.identity()
    if frontlit is not None:
        if keep_frontlit and insp.get("alignment"):
            front_to_back = frontlit_to_backlit(insp, sizes)
        else:
            try:
                front_to_back, quality = register_frontlit(backlit, frontlit)
                report["frontlit_match"] = round(quality, 3)
            except AlignmentError as exc:
                report["warnings"] = [f"frontlit not registered ({exc}); assumed not moved"]

    frame = history.get("frame")
    expect = (frame["width"], frame["height"]) if frame else None
    aperture, errors = None, []
    for image, to_back, name in ((frontlit, front_to_back, "frontlit"), (backlit, geo.identity(), "backlit")):
        if image is None:
            continue
        try:
            hint = None
            if expect:
                scale = geo.scale_of(geo.invert(to_back))
                hint = (expect[0] * scale, expect[1] * scale)
            aperture = find_aperture(image, expect=hint).transformed(to_back)
            report["outline_from"] = name
            break
        except AlignmentError as exc:
            errors.append(f"{name}: {exc}")
    if aperture is None:
        raise AlignmentError("the filter's opening was not found (" + "; ".join(errors) + ")")

    insp["aperture"] = aperture.as_record()
    insp["outline"] = _inset_outline(aperture, inset)
    # The window's alignment record: upright by the frame, frontlit placed on backlit.
    pair = _sized_pair(sizes)
    pair.glob_rot = round(-aperture.tilt, 4)
    if frontlit is not None:
        pair.set_frontlit_matrix(pair.matrix(BACKLIT) @ front_to_back)
    insp["alignment"] = pair.alignment_record()
    report["rotation"] = pair.glob_rot

    is_reference = frame is not None and frame.get("reference") == insp["id"]
    if frame is None or (is_reference and not history["pinholes"]):
        history["frame"] = _frame_record(aperture, insp["id"])
        insp["to_filter"] = _store_matrix(_frame_matrix(aperture))
        report["registration"] = "defines the filter frame"
    elif is_reference:
        # Pinholes are already placed in this frame; keep it as it is.
        report["registration"] = "reference frame kept"
    else:
        matrix = _frame_matrix(aperture, frame)
        spots = find_spots(backlit, insp["outline"])
        matrix, by_pinholes = _register_on_pinholes(history, index, matrix, spots)
        insp["to_filter"] = _store_matrix(matrix)
        insp["registration"] = by_pinholes
        report["registration"] = by_pinholes
    insp["aligned"] = datetime.date.today().isoformat()
    return report


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

def detect_inspection(history, index, backlit, frontlit=None, sensitivity=None, category_key=None,
                      redo=False):
    """Search an inspection's backlit image for pinholes inside its outline.

    Spots at known pinholes are recognised (and listed as found again), spots at
    rejected positions are skipped, and the rest are added as new pinholes,
    first seen in this inspection, numbered left to right.  A spot that also
    shows in the frontlit image is flagged (``in_frontlit``): a pinhole lets light
    through only from behind, so it is often dust or a glint instead.
    """
    from .detect import DEFAULT_SENSITIVITY, flag_present_in, minimum_score
    sensitivity = DEFAULT_SENSITIVITY if sensitivity is None else sensitivity
    insp = history["inspections"][index]
    matrix = to_filter(insp)
    outline = insp.get("outline") or []
    if matrix is None or len(outline) < 3:
        raise HistoryError(f"inspection {insp['id']} has not been aligned yet")
    cat = category(history, category_key or insp.get("category") or STAGES[insp["stage"]][1])

    removed = []
    if redo:
        keep = []
        for p in history["pinholes"]:
            if (p.get("first_seen") == insp["id"] and p.get("source") == "detected"
                    and p.get("status", ACCEPTED) == ACCEPTED):
                removed.append(p["id"])
            else:
                keep.append(p)
        history["pinholes"] = keep

    spots = find_spots(backlit, outline)
    floor = minimum_score(sensitivity)
    offered = [c for c in spots if c["score"] >= floor]

    if frontlit is not None and offered:
        to_back = frontlit_to_backlit(insp, (backlit.size, frontlit.size))
        front_outline = geo.apply_many(geo.invert(to_back), outline)
        front_spots = find_spots(frontlit, front_outline)
        others = [tuple(p) for p in geo.apply_many(to_back, [(c["x"], c["y"]) for c in front_spots])] \
            if front_spots else []
        flag_present_in(offered, others, tolerance=FRONTLIT_REACH)
        for c in offered:
            c["in_frontlit"] = c.pop("in_reference", False)

    scale = geo.scale_of(matrix)
    everything = [(p["x"], p["y"], max(MATCH_REACH, float(p.get("radius", 20.0)))) for p in history["pinholes"]]
    found_again, skipped, new = {}, {}, []
    for c in offered:
        fx, fy = geo.apply(matrix, c["x"], c["y"])
        n, _d = _nearest(everything, fx, fy)
        if n is None:
            new.append((fx, fy, c))
            continue
        p = history["pinholes"][n]
        if p.get("status", ACCEPTED) == REJECTED:
            skipped[p["id"]] = c
        else:
            found_again[p["id"]] = c
        # Two spots on one known pinhole are both that pinhole.

    # Known pinholes with any spot at all under them, however faint: still there.
    present = set(found_again)
    for p in known_at(history, index):
        if p["id"] in present:
            continue
        x, y, radius = image_position(insp, p)
        reach = max(radius, MATCH_REACH / scale)
        if any(math.hypot(c["x"] - x, c["y"] - y) <= reach for c in spots):
            present.add(p["id"])
    not_seen = [p["id"] for p in known_at(history, index) if p["id"] not in present]

    added = []
    new.sort(key=lambda item: (item[0], item[1]))
    for fx, fy, c in new:
        # Two new spots on top of each other are one pinhole.
        if any(math.hypot(fx - q["x"], fy - q["y"]) <= MATCH_REACH for q in added):
            continue
        record = {
            "id": next_id(history, cat["prefix"]),
            "category": cat["key"],
            "first_seen": insp["id"],
            "status": ACCEPTED,
            "x": round(fx, 2),
            "y": round(fy, 2),
            "radius": round(max(MARKER_RADIUS, 2.0 * c["radius"]) * scale, 2),
            "source": "detected",
            "score": round(c["score"], 2),
            "tier": c["tier"],
        }
        if c.get("in_frontlit"):
            record["in_frontlit"] = True
        history["pinholes"].append(record)
        added.append(record)

    summary = {
        "date": datetime.date.today().isoformat(),
        "sensitivity": sensitivity,
        "spots": len(offered),
        "new": [p["id"] for p in added],
        "found_again": sorted(found_again, key=_id_order),
        "skipped_rejected": sorted(skipped, key=_id_order),
        "not_seen": sorted(not_seen, key=_id_order),
    }
    # Pinholes recorded as first seen in a later inspection, but already here.
    earlier = [pid for pid in summary["found_again"]
               if _first_seen_index(history, pinhole(history, pid)) > index]
    if earlier:
        summary["already_here"] = earlier
    if removed:
        summary["replaced"] = removed
    insp["detection"] = summary
    return summary, added


def _id_order(pid):
    match = _ID_PATTERN.match(pid)
    return (match.group(1), int(match.group(2))) if match else (pid, 0)


# --------------------------------------------------------------------------- #
# Views: an inspection as a session, for the window and for maps
# --------------------------------------------------------------------------- #

def session_view(history, index, history_file, show_rejected=False):
    """An inspection as a session record: its images and settings, and every pinhole
    known up to it, placed on its backlit image."""
    insp = history["inspections"][index]
    base = Path(history_file).resolve().parent
    resolved, saved = image_paths(insp, history_file)
    paths = [r or s for r, s in zip(resolved, saved)]
    annotations, colour_labels, prefixes = [], {}, {}
    if to_filter(insp) is not None:
        statuses = (ACCEPTED, REJECTED) if show_rejected else (ACCEPTED,)
        for p in sorted(known_at(history, index, statuses), key=lambda q: _first_seen_index(history, q)):
            cat = category(history, p["category"])
            rejected = p.get("status") == REJECTED
            x, y, radius = image_position(insp, p)
            colour = REJECTED_COLOUR if rejected else cat["colour"]
            ann = {"img1_x": x, "img1_y": y, "radius": radius, "colour": colour, "label": p["id"],
                   "pinhole": p["id"]}
            if p.get("unsure"):
                ann["unsure"] = True
            annotations.append(ann)
            colour_labels[colour] = "Rejected" if rejected else cat["name"]
            if not rejected:
                prefixes[colour] = cat["prefix"]
    return {
        "version": SESSION_VERSION,
        "image_paths": paths,
        "image_paths_rel": [relative_to(p, base) for p in paths],
        "mode": "sidebyside",
        "opacity": 0.5,
        "alignment": dict(insp.get("alignment") or {}),
        "annotations": annotations,
        "colour_labels": colour_labels,
        "label_prefixes": prefixes,
        "filter_outline": [list(p) for p in insp.get("outline") or []],
        "adjustments": insp.get("adjustments") or [],
        "noise_reduction": insp.get("noise_reduction") or [],
        "raw_develop": insp.get("raw_develop") or [],
        "history_inspection": insp["id"],
    }


def apply_view(history, index, annotations, outline=None, alignment=None, adjustments=None,
               noise_reduction=None, raw_develop=None):
    """Write changes made in the window back into the history.

    A marker opened from the history (its ``pinhole`` key) moves that pinhole; any
    other marker is a new pinhole first seen in this inspection, keeping its label
    as the ID unless that ID is taken; a known pinhole whose marker was deleted is
    rejected, so it stays remembered.  Returns a summary.
    """
    insp = history["inspections"][index]
    matrix = to_filter(insp)
    if matrix is None:
        raise HistoryError(f"inspection {insp['id']} has not been aligned yet")
    scale = geo.scale_of(matrix)
    shown = {p["id"] for p in known_at(history, index, (ACCEPTED,))}
    kept, moved, added, retyped = set(), [], [], []
    for ann in annotations:
        ann = normalise_annotation(ann)
        fx, fy = geo.apply(matrix, ann["img1_x"], ann["img1_y"])
        # Only the ID a marker was opened with ties it to a pinhole: a new marker
        # numbered by the window may carry the label of a pinhole rejected earlier.
        p = pinhole(history, ann["pinhole"]) if ann.get("pinhole") else None
        label = ann.get("label") or ""
        cat = (category_for_colour(history, ann["colour"]) or category_for_label(history, label)
               or category(history, insp.get("category") or STAGES[insp["stage"]][1]))
        if p is not None and p["id"] in kept:
            p = None   # the same pinhole twice: the second marker is a new pinhole
        if p is None:
            own = _ID_PATTERN.match(label)
            fits = bool(own) and own.group(1) == cat["prefix"] and pinhole(history, label) is None
            pid = label if fits else next_id(history, cat["prefix"])
            p = {"id": pid, "category": cat["key"], "first_seen": insp["id"], "status": ACCEPTED,
                 "x": round(fx, 2), "y": round(fy, 2), "radius": round(ann["radius"] * scale, 2),
                 "source": "manual"}
            history["pinholes"].append(p)
            added.append(pid)
        else:
            if math.hypot(p["x"] - fx, p["y"] - fy) > 0.05:
                p["x"], p["y"] = round(fx, 2), round(fy, 2)
                moved.append(p["id"])
            p["radius"] = round(ann["radius"] * scale, 2)
            if p.get("status") == REJECTED and ann["colour"] != REJECTED_COLOUR:
                p["status"] = ACCEPTED
            if ann["colour"] not in (REJECTED_COLOUR,) and cat["key"] != p["category"]:
                p["category"] = cat["key"]
                retyped.append(p["id"])
        if ann.get("unsure"):
            p["unsure"] = True
        else:
            p.pop("unsure", None)
        kept.add(p["id"])
    rejected = sorted(shown - kept, key=_id_order)
    set_status(history, rejected, REJECTED)
    if outline is not None:
        insp["outline"] = [[round(float(x), 3), round(float(y), 3)] for x, y in outline]
    for key, value in (("alignment", alignment), ("adjustments", adjustments),
                       ("noise_reduction", noise_reduction), ("raw_develop", raw_develop)):
        if value is not None:
            insp[key] = value
    return {"moved": moved, "added": added, "rejected": rejected, "recategorised": retyped}


# --------------------------------------------------------------------------- #
# Migration from sessions
# --------------------------------------------------------------------------- #

def stage_from_path(path):
    """The stage a session belongs to, from its folders or name (``5_thermal_test/em2``)."""
    path = Path(path).resolve()
    for part in [path.stem] + [p.name for p in path.parents][:3]:
        try:
            return stage_key(part)
        except HistoryError:
            continue
    raise HistoryError(f"cannot tell the stage of {path}; give it with --stages")


def migrate_sessions(entries, history_file, filter_name="", find_outline=None, backlit_image=None,
                     inset=OUTLINE_INSET):
    """Build a history from a filter's session files, oldest first.

    ``entries`` is a list of ``(session_path, stage)``.  Markers with the same label
    in different sessions are the same pinhole, and give a first mapping of each
    inspection onto the filter.  The first inspection defines the filter frame,
    from its outline; ``find_outline(session_path, session, frame)``, if given, is
    asked for the opening (an ``autoalign.Aperture`` in backlit pixels) where a
    session has no outline.  ``backlit_image(session_path, session)``, if given,
    supplies the backlit image, so that each later inspection can be lined up on
    the spots of the pinholes already known rather than on carried-over markers.

    Returns ``(history, notes)``, notes being things worth telling the user.
    """
    history = new_history(filter_name)
    base = Path(history_file).resolve().parent
    notes = []
    for session_path, stage in entries:
        session = read_session(session_path)
        session_dir = Path(session_path).resolve().parent
        resolved, saved = session_image_paths(session, session_path)
        paths = [r or s for r, s in zip(resolved, saved)]
        for r, s in zip(resolved, saved):
            if s and not r:
                notes.append(f"{Path(session_path).name}: image not found: {s}")
        stage = stage_key(stage)
        insp = {
            "id": _new_inspection_id(history, stage),
            "stage": stage,
            "name": STAGES[stage][0],
            "date": capture_date(resolved[BACKLIT]) if resolved[BACKLIT] else None,
            "category": STAGES[stage][1],
            "images": _image_record(paths, base),
            "migrated_from": relative_to(str(Path(session_path).resolve()), base) or str(session_path),
        }
        pair = ImagePair()
        pair.apply_alignment_record(session.get("alignment"))
        insp["alignment"] = pair.alignment_record()
        for key in ("adjustments", "noise_reduction"):
            if session.get(key):
                insp[key] = session[key]
        if session.get("raw_develop"):
            pair.apply_develop_records(session.get("raw_develop"))
            resolve_frame_paths(pair, session.get("raw_develop"), session_dir)
            insp["raw_develop"] = [develop_record(d, base) for d in pair.develop]
        history["inspections"].append(insp)
        index = len(history["inspections"]) - 1

        annotations = [normalise_annotation(a) for a in session.get("annotations", [])]
        margins = _legacy_raw_margins(session, resolved[BACKLIT])
        if margins != (0, 0):
            for ann in annotations:
                ann["img1_x"] -= margins[0]
                ann["img1_y"] -= margins[1]
            notes.append(f"{Path(session_path).name}: markers moved by the RAW crop margin {margins}")

        outline = [list(map(float, p)) for p in session.get("filter_outline") or []]
        aperture = None
        if len(outline) >= 3:
            aperture = aperture_from_outline(outline)
            insp["outline"] = [[round(x, 3), round(y, 3)] for x, y in outline]

        # Map onto the filter from markers already known, if there are enough.
        known = {p["id"]: p for p in history["pinholes"]}
        common = [a for a in annotations if a["label"] in known]
        matrix = None
        if len(common) >= 2:
            src = [(a["img1_x"], a["img1_y"]) for a in common]
            dst = [(known[a["label"]]["x"], known[a["label"]]["y"]) for a in common]
            matrix, rms = geo.fit_similarity(src, dst)
            insp["registration"] = {"method": "markers", "matched": len(common), "rms": round(rms, 3)}
            if rms > 3.0:
                notes.append(f"{insp['id']}: its markers fit the earlier ones only to {rms:.1f} px")
        if matrix is None:
            if aperture is None and find_outline is not None:
                aperture = find_outline(session_path, session, history.get("frame"))
                if aperture is not None:
                    insp["aperture"] = aperture.as_record()
                    insp["outline"] = _inset_outline(aperture, inset)
            if aperture is None:
                notes.append(f"{insp['id']}: no outline, so the filter frame is centred on the image")
                size = _image_size(resolved[BACKLIT]) or (6000, 4000)
                from .autoalign import Aperture
                aperture = Aperture(size[0] / 2.0, size[1] / 2.0, size[0], size[1], -pair.glob_rot, 0.0)
            if history["frame"] is None:
                history["frame"] = _frame_record(aperture, insp["id"])
                matrix = _frame_matrix(aperture)
                insp["registration"] = {"method": "defines the filter frame"}
            else:
                matrix = _frame_matrix(aperture, history["frame"])
                insp["registration"] = {"method": "outline"}
                notes.append(f"{insp['id']}: shares no markers with earlier inspections; placed by its outline")
        insp["to_filter"] = _store_matrix(matrix)
        by_markers = matrix

        # Markers carried over from an earlier inspection are only as good as the row
        # alignment they were carried by; the spots themselves say where they are now.
        if backlit_image is not None and insp["registration"]["method"] in ("markers", "outline"):
            image = backlit_image(session_path, session)
            if image is not None:
                region = insp.get("outline") or _frame_outline_in(insp, history["frame"], inset)
                refined, report = _register_on_pinholes(history, index, matrix, find_spots(image, region))
                if report.get("rms") is not None:
                    earlier = [(p["x"], p["y"]) for p in history["pinholes"]]
                    moved = np.hypot(*(geo.apply_many(geo.invert(matrix), earlier)
                                       - geo.apply_many(geo.invert(refined), earlier)).T)
                    insp["registration"] = {"method": insp["registration"]["method"] + ", then spots",
                                            **report, "markers_moved_up_to": round(float(moved.max()), 1)}
                    if moved.max() > 3.0:
                        notes.append(f"{insp['id']}: lined up on the spots of {report['matched']} known pinholes "
                                     f"(rms {report['rms']} px); its carried-over markers were up to "
                                     f"{moved.max():.0f} px off them")
                    matrix = refined
                    insp["to_filter"] = _store_matrix(matrix)
                else:
                    notes.append(f"{insp['id']}: too few known pinholes found in its image to check "
                                 f"its markers ({report.get('matched', 0)} of {report['known']})")
        if "outline" not in insp and history["frame"]:
            insp["outline"] = _frame_outline_in(insp, history["frame"], inset)

        scale = geo.scale_of(matrix)
        seen = set()
        for ann in annotations:
            label = ann["label"]
            fx, fy = geo.apply(matrix, ann["img1_x"], ann["img1_y"])
            if label in known:
                # A marker out of step with the others (not the set as a whole, which the
                # spots may have moved) is worth a look.
                mx, my = geo.apply(by_markers, ann["img1_x"], ann["img1_y"])
                drift = math.hypot(known[label]["x"] - mx, known[label]["y"] - my)
                if drift > 10.0:
                    notes.append(f"{insp['id']}: {label} is {drift:.1f} px from where it was first marked")
                seen.add(label)
                continue
            if not label or label in seen:
                cat = category_for_colour(history, ann["colour"]) or category(history, insp["category"])
                label = next_id(history, cat["prefix"])
                notes.append(f"{insp['id']}: an unlabelled or repeated marker was given the ID {label}")
            cat = (category_for_colour(history, ann["colour"]) or category_for_label(history, label)
                   or category(history, insp["category"]))
            if category_for_colour(history, ann["colour"]) is None:
                notes.append(f"{insp['id']}: {label} has the non-standard colour {ann['colour']}; "
                             f"filed under {cat['name']}")
            p = {"id": label, "category": cat["key"], "first_seen": insp["id"], "status": ACCEPTED,
                 "x": round(fx, 2), "y": round(fy, 2), "radius": round(ann["radius"] * scale, 2),
                 "source": "migrated"}
            if ann.get("unsure"):
                p["unsure"] = True
            history["pinholes"].append(p)
            known[label] = p
            seen.add(label)
        missing = [pid for pid in known if pid not in seen
                   and _first_seen_index(history, known[pid]) < index]
        if missing:
            notes.append(f"{insp['id']}: no marker for " + ", ".join(sorted(missing, key=_id_order))
                         + " (kept as accepted)")
    return history, notes


def _frame_outline_in(insp, frame, inset=OUTLINE_INSET):
    """The reference opening, inset, in an inspection's backlit pixels."""
    from .autoalign import Aperture
    shape = Aperture(0.0, 0.0, frame["width"], frame["height"], 0.0, frame.get("radius", 0.0))
    points = _inset_outline(shape, inset)
    back = geo.invert(to_filter(insp))
    return [[round(x, 3), round(y, 3)] for x, y in geo.apply_many(back, points)]


def _image_size(path):
    if not path:
        return None
    try:
        from .imaging import is_raw
        if is_raw(path):
            import rawpy
            with rawpy.imread(path) as raw:
                return (raw.sizes.crop_width or raw.sizes.width, raw.sizes.crop_height or raw.sizes.height)
        from PIL import Image
        with Image.open(path) as handle:
            return handle.size
    except Exception:
        return None


def _legacy_raw_margins(session, backlit_path):
    """Sessions from v1.x placed markers on the uncropped RAW frame (see
    ``session_data.shift_legacy_raw_markers``): the crop margin to take off."""
    from .imaging import is_raw
    if int(_float(session.get("version"), 1)) >= RAW_CROP_VERSION or not backlit_path or not is_raw(backlit_path):
        return (0, 0)
    try:
        from .imaging import raw_crop_margins
        return raw_crop_margins(backlit_path)
    except Exception:
        return (0, 0)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

def summary_lines(history):
    """A plain-text overview: inspections, and pinholes by category and status."""
    lines = [f"Filter {history.get('filter') or '?'}: {len(history['inspections'])} inspection(s), "
             f"{len(history['pinholes'])} pinhole record(s)"]
    for n, insp in enumerate(history["inspections"]):
        first = [p for p in history["pinholes"] if p.get("first_seen") == insp["id"]]
        accepted = [p for p in first if p.get("status", ACCEPTED) == ACCEPTED]
        rejected = [p for p in first if p.get("status") == REJECTED]
        total = len(known_at(history, n))
        state = "aligned" if insp.get("to_filter") else "not aligned"
        lines.append(f"  {n + 1}. {insp['id']:<10} {insp.get('date') or '':<10}  {state:<11}  "
                     f"new: {len(accepted)} accepted, {len(rejected)} rejected;  known by then: {total}")
        if accepted:
            lines.append("       " + " ".join(p["id"] for p in sorted(accepted, key=lambda q: _id_order(q["id"]))))
        detection = insp.get("detection")
        if detection and detection.get("not_seen"):
            lines.append("       not seen again: " + " ".join(detection["not_seen"]))
    by_category = {}
    for p in history["pinholes"]:
        key = (p["category"], p.get("status", ACCEPTED))
        by_category[key] = by_category.get(key, 0) + 1
    for cat in categories(history):
        a = by_category.get((cat["key"], ACCEPTED), 0)
        r = by_category.get((cat["key"], REJECTED), 0)
        if a or r:
            lines.append(f"  {cat['name']} ({cat['prefix']}): {a} accepted" + (f", {r} rejected" if r else ""))
    return lines
