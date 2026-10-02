"""State for one inspection: a backlit/frontlit image pair, its alignment,
tone settings and annotations."""

import copy
import re

from . import geometry as geo
from .imaging import RAW_NOISE_LEVELS, build_lut, default_develop

BACKLIT = 0
FRONTLIT = 1

ADJUST_DEFAULTS = {"brightness": 1.0, "contrast": 1.0, "blacks": 0.0, "whites": 255.0}
NR_DEFAULTS = {"amount": 0, "aggressive": False, "color": 50, "edge": 100}

_LABEL_PATTERN = re.compile(r"^(.*?)(\d+)$")


def marker_text(ann):
    """The label drawn beside a marker; a trailing '?' flags one the inspector was unsure about."""
    label = ann.get("label", "")
    return label + "?" if ann.get("unsure") else label


def normalise_annotation(ann):
    """Return a clean annotation record in backlit-image pixel coordinates."""
    record = dict(ann)
    record.pop("img2_x", None)
    record.pop("img2_y", None)
    record["img1_x"] = float(ann.get("img1_x", ann.get("img2_x", 0.0)))
    record["img1_y"] = float(ann.get("img1_y", ann.get("img2_y", 0.0)))
    record["radius"] = float(ann.get("radius", 20.0))
    record["colour"] = ann.get("colour", "#ff0000")
    record["label"] = ann.get("label", "")
    if record.get("unsure"):
        record["unsure"] = True
    else:
        record.pop("unsure", None)
    return record


class ImagePair:
    def __init__(self):
        self.paths = [None, None]
        self.base_images = [None, None]   # as loaded from disk
        self.pyramids = [None, None]      # what is displayed (after any noise reduction)
        self.off_x = 0.0
        self.off_y = 0.0
        self.rot = 0.0
        self.scale = 1.0
        self.glob_rot = 0.0
        self.adjust = [dict(ADJUST_DEFAULTS), dict(ADJUST_DEFAULTS)]
        self.nr = [dict(NR_DEFAULTS), dict(NR_DEFAULTS)]
        self.develop = [default_develop(), default_develop()]   # how each image is built from its file(s)
        self.camera = [{}, {}]            # exposure settings read from each file
        self.outline = []                 # edge of the filter membrane, in backlit pixels
        self.annotations = []
        self.colour_labels = {}
        self.label_prefixes = {}
        self.label = ""
        self.session_path = None

    # ------------------------------------------------------------------ #
    # Images
    # ------------------------------------------------------------------ #

    def has_image(self, idx):
        return self.pyramids[idx] is not None

    def has_any_image(self):
        return self.has_image(BACKLIT) or self.has_image(FRONTLIT)

    def size(self, idx):
        pyramid = self.pyramids[idx]
        return pyramid.size if pyramid is not None else None

    def centre(self, idx):
        size = self.size(idx)
        if size is None:
            return (0.0, 0.0)
        return (size[0] / 2.0, size[1] / 2.0)

    def set_image(self, idx, path, base_image, pyramid):
        self.paths[idx] = path
        self.base_images[idx] = base_image
        self.pyramids[idx] = pyramid
        self.camera[idx] = dict(getattr(base_image, "info", {}).get("camera") or {})

    def lut(self, idx):
        pyramid = self.pyramids[idx]
        if pyramid is None:
            return None
        a = self.adjust[idx]
        return build_lut(a["brightness"], a["contrast"], a["blacks"], a["whites"], pyramid.mean)

    # ------------------------------------------------------------------ #
    # Geometry: image pixels -> "pair space" (the upright backlit frame)
    # ------------------------------------------------------------------ #

    def matrix(self, idx):
        if idx == BACKLIT:
            return geo.about(self.centre(BACKLIT), 1.0, self.glob_rot)
        return geo.translation(self.off_x, self.off_y) @ geo.about(
            self.centre(FRONTLIT), self.scale, self.glob_rot + self.rot)

    def set_frontlit_matrix(self, matrix):
        """Set offset/rotation/scale so the frontlit image is placed by ``matrix``."""
        scale, total_rot, tx, ty = geo.decompose_about(matrix, self.centre(FRONTLIT))
        self.scale = float(scale)
        self.rot = float(geo.wrap_angle(total_rot - self.glob_rot))
        self.off_x = float(tx)
        self.off_y = float(ty)

    def set_global_rotation(self, deg):
        """Turn both images together about the backlit centre, keeping them registered."""
        delta = deg - self.glob_rot
        if delta == 0.0:
            return
        frontlit = geo.about(self.centre(BACKLIT), 1.0, delta) @ self.matrix(FRONTLIT)
        self.glob_rot = deg
        self.set_frontlit_matrix(frontlit)

    def reset_alignment(self):
        self.off_x = self.off_y = self.rot = 0.0
        self.scale = 1.0

    # ------------------------------------------------------------------ #
    # Annotations
    # ------------------------------------------------------------------ #

    def legend(self):
        """One ``(colour, text)`` entry per colour in use, with marker counts."""
        counts, unsure = {}, {}
        for ann in self.annotations:
            counts[ann["colour"]] = counts.get(ann["colour"], 0) + 1
            if ann.get("unsure"):
                unsure[ann["colour"]] = unsure.get(ann["colour"], 0) + 1
        entries = []
        for colour, n in counts.items():
            tally = f"n={n}" + (f", {unsure[colour]} unsure" if colour in unsure else "")
            name = self.colour_labels.get(colour, "")
            entries.append((colour, f"{name}  ({tally})" if name else f"({tally})"))
        return entries

    def prefix_for(self, colour):
        """Label prefix for a colour: the stored one, else inferred from existing labels."""
        if colour in self.label_prefixes:
            return self.label_prefixes[colour]
        for ann in reversed(self.annotations):
            if ann["colour"] == colour and ann.get("label"):
                match = _LABEL_PATTERN.match(ann["label"])
                if match:
                    return match.group(1)
        return None

    def next_label(self, colour):
        prefix = self.prefix_for(colour)
        if not prefix:
            return ""
        highest = 0
        for ann in self.annotations:
            match = _LABEL_PATTERN.match(ann.get("label", ""))
            if match and match.group(1) == prefix:
                highest = max(highest, int(match.group(2)))
        return f"{prefix}{highest + 1}"

    # ------------------------------------------------------------------ #
    # Snapshots (undo) and session records
    # ------------------------------------------------------------------ #

    def alignment_record(self):
        return {
            "off_x": round(self.off_x, 3),
            "off_y": round(self.off_y, 3),
            "rot": round(self.rot, 4),
            "img2_scale": round(self.scale, 5),
            "glob_rot": round(self.glob_rot, 4),
        }

    def apply_alignment_record(self, record):
        record = record or {}
        self.off_x = _as_float(record.get("off_x"), 0.0)
        self.off_y = _as_float(record.get("off_y"), 0.0)
        self.rot = _as_float(record.get("rot"), 0.0)
        self.scale = max(0.01, _as_float(record.get("img2_scale"), 1.0))
        self.glob_rot = _as_float(record.get("glob_rot"), 0.0)

    def apply_adjust_records(self, records):
        for i in range(2):
            self.adjust[i] = dict(ADJUST_DEFAULTS)
            if records and i < len(records) and isinstance(records[i], dict):
                for key in ADJUST_DEFAULTS:
                    if key in records[i]:
                        self.adjust[i][key] = _as_float(records[i][key], ADJUST_DEFAULTS[key])

    def apply_nr_records(self, records):
        for i in range(2):
            self.nr[i] = dict(NR_DEFAULTS)
            if records and i < len(records) and isinstance(records[i], dict):
                cfg = records[i]
                self.nr[i] = {
                    "amount": int(_as_float(cfg.get("amount"), 0)),
                    "aggressive": bool(cfg.get("aggressive", False)),
                    "color": int(_as_float(cfg.get("color"), 50)),
                    "edge": int(_as_float(cfg.get("edge"), 100)),
                }

    def apply_develop_records(self, records):
        for i in range(2):
            self.develop[i] = default_develop()
            if records and i < len(records) and isinstance(records[i], dict):
                noise = str(records[i].get("noise", "standard")).lower()
                self.develop[i] = {
                    "exposure": max(-4.0, min(6.0, _as_float(records[i].get("exposure"), 0.0))),
                    "noise": noise if noise in RAW_NOISE_LEVELS else "standard",
                    "frames": [p for p in records[i].get("frames") or [] if isinstance(p, str)],
                    "dark": [p for p in records[i].get("dark") or [] if isinstance(p, str)],
                }

    def snapshot(self):
        return copy.deepcopy({
            "alignment": (self.off_x, self.off_y, self.rot, self.scale, self.glob_rot),
            "adjust": self.adjust,
            "annotations": self.annotations,
            "colour_labels": self.colour_labels,
            "label_prefixes": self.label_prefixes,
            "outline": self.outline,
        })

    def restore(self, snap):
        snap = copy.deepcopy(snap)
        self.off_x, self.off_y, self.rot, self.scale, self.glob_rot = snap["alignment"]
        self.adjust = snap["adjust"]
        self.annotations = snap["annotations"]
        self.colour_labels = snap["colour_labels"]
        self.label_prefixes = snap["label_prefixes"]
        self.outline = snap["outline"]


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
