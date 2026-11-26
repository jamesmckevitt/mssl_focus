"""Reading and writing session files, and locating the files a session refers to.

The helpers have no user-interface dependency, so the command line (`cli.py`) can
use them as well as the window (`session.py`).
"""

import json
import os
from pathlib import Path

from . import geometry as geo
from .camera import camera_differences, describe_camera, exposure_stops
from .imaging import is_raw
from .pair import BACKLIT, FRONTLIT, ImagePair, normalise_annotation

SESSION_VERSION = 3      # one inspection (one row) per session; versions 1 and 2 could hold two
RAW_CROP_VERSION = 2     # first version with markers on the cropped, not the uncropped, RAW frame
CURRENT, REFERENCE = 0, 1
SETTINGS_FILE_TYPE = "mssl_focus_image_settings"

# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def read_session(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("this is not a MSSL FOCUS session file")
    return data


def write_session(path, data):
    """Write atomically so a crash or sync conflict cannot leave half a file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def describe_location(path):
    """Short label from a file's two parent folders, such as `5_thermal_test / em2`."""
    if not path:
        return ""
    parent = Path(path).resolve().parent
    if parent.parent.name:
        return f"{parent.parent.name} / {parent.name}"
    return parent.name


def relative_to(path, base_dir):
    if not path:
        return None
    try:
        return os.path.relpath(path, base_dir).replace("\\", "/")
    except ValueError:  # different drive on Windows
        return None


def resolve_image_path(saved, relative, session_dir):
    """Find an image named in a session file, even after folders were moved or renamed."""
    session_dir = Path(session_dir)
    candidates = []
    if relative:
        candidates.append(session_dir / relative)
    if saved:
        candidates.append(Path(saved))
        parts = Path(str(saved).replace("\\", "/")).parts
        # Try the file name beside the session, then with more and more of its old folders,
        # each one level further up.
        for depth in range(1, min(4, len(parts)) + 1):
            base = session_dir
            for _ in range(depth - 1):
                base = base.parent
            candidates.append(base.joinpath(*parts[-depth:]))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _pair_of(values):
    values = list(values or [])[:2]
    while len(values) < 2:
        values.append(None)
    return values


def session_image_paths(session, session_path, reference=False):
    """Return `(resolved, saved)` image path pairs for a session's main or reference row."""
    key = "compare_image_paths" if reference else "image_paths"
    saved = _pair_of(session.get(key))
    relative = _pair_of(session.get(key + "_rel"))
    session_dir = Path(session_path).resolve().parent
    resolved = [resolve_image_path(s, r, session_dir) if (s or r) else None
                for s, r in zip(saved, relative)]
    saved = [s or r for s, r in zip(saved, relative)]
    return resolved, saved


def session_has_reference(session):
    """Whether a session holds a second (reference) row, as versions 1 and 2 could."""
    return bool(session.get("compare_row_enabled")) or any(_pair_of(session.get("compare_image_paths")))


def describe_saved_reference(session):
    """Description of the second row of a two-row session, for the user."""
    label = session.get("compare_label") or ""
    names = [Path(str(p).replace("\\", "/")).name for p in _pair_of(session.get("compare_image_paths")) if p]
    files = ", ".join(names)
    return f"{label} ({files})" if label and files else label or files or "unnamed"


def alignment_key(other_session_path, session_dir):
    """Key a session uses for another session it is lined up with, its relative path if possible."""
    return relative_to(other_session_path, session_dir) or str(other_session_path)


def row_alignments_from_session(session):
    """How a session's row lines up with other sessions shown as its reference row.

    Returns `{key of the other session: record}`. A two-row session from version 1 or 2
    stored one such alignment with its reference row, and that one is included."""
    found = {}
    stored = session.get("row_alignments")
    if isinstance(stored, dict):
        found.update({str(key): dict(value) for key, value in stored.items() if isinstance(value, dict)})
    other = session.get("compare_session_path_rel")
    transform = session.get("compare_row_transform")
    if other and isinstance(transform, dict) and other not in found and session_has_reference(session):
        found[str(other)] = {
            "off_x": _float(transform.get("off_x"), 0.0),
            "off_y": _float(transform.get("off_y"), 0.0),
            "rot": _float(transform.get("rot"), 0.0),
            "scale": _float(transform.get("scale"), 1.0),
            "current_rotation": _float((session.get("alignment") or {}).get("glob_rot"), 0.0),
            "reference_rotation": _float((session.get("compare_alignment") or {}).get("glob_rot"), 0.0),
        }
    return found


def row_matrix_from_record(record, current, reference):
    """Matrix from `reference`'s pair space to `current`'s, from a saved alignment record.

    It allows for either row having been levelled differently since the record was saved."""
    centre_c, centre_r = current.centre(BACKLIT), reference.centre(BACKLIT)
    saved = geo.translation(_float(record.get("off_x"), 0.0), _float(record.get("off_y"), 0.0)) @ geo.about(
        centre_r, max(0.01, _float(record.get("scale"), 1.0)), _float(record.get("rot"), 0.0))
    turned_c = current.glob_rot - _float(record.get("current_rotation"), current.glob_rot)
    turned_r = reference.glob_rot - _float(record.get("reference_rotation"), reference.glob_rot)
    return geo.about(centre_c, 1.0, turned_c) @ saved @ geo.about(centre_r, 1.0, -turned_r)


def fill_pair_from_session(pair, session, reference=False):
    """Copy a session's alignment, tone, noise and annotation records into `pair`."""
    prefix = "compare_" if reference else ""
    pair.apply_alignment_record(session.get(prefix + "alignment"))
    pair.apply_adjust_records(session.get(prefix + "adjustments"))
    pair.apply_nr_records(session.get(prefix + "noise_reduction"))
    pair.apply_develop_records(session.get(prefix + "raw_develop"))
    pair.annotations = [normalise_annotation(a) for a in session.get(prefix + "annotations", [])]
    pair.colour_labels = dict(session.get(prefix + "colour_labels", {}))
    pair.label_prefixes = dict(session.get(prefix + "label_prefixes", {}))
    pair.legend_colours = list(session.get(prefix + "legend_colours", []))
    pair.outline = []
    for point in session.get(prefix + "filter_outline") or []:
        try:
            pair.outline.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError, IndexError):
            pair.outline = []
            break


def shift_legacy_raw_markers(pair, session, base_image):
    """Move the markers of a v1.x session from the uncropped RAW frame to the cropped one.

    RAW files are cropped to the camera's image area, so the markers move by the crop margin.
    Sessions of `RAW_CROP_VERSION` or later, and backlit images that are not RAW, are left alone."""
    if int(_float(session.get("version"), 1)) >= RAW_CROP_VERSION or not is_raw(pair.paths[BACKLIT]):
        return
    left, top = getattr(base_image, "info", {}).get("raw_crop_margins", (0, 0))
    for ann in pair.annotations:
        ann["img1_x"] -= left
        ann["img1_y"] -= top


def develop_record(develop, session_dir):
    """Development recipe as stored in a session, with frame paths both absolute and relative."""
    record = dict(develop)
    for key in ("frames", "dark"):
        record[key] = list(develop.get(key) or [])
        record[key + "_rel"] = [relative_to(p, session_dir) for p in record[key]]
    return record


def resolve_frame_paths(pair, records, session_dir):
    """Locate the extra frames and dark frames named in a session. Returns how many are missing."""
    missing = 0
    for i in range(2):
        record = records[i] if isinstance(records, list) and i < len(records) and isinstance(records[i], dict) else {}
        for key in ("frames", "dark"):
            saved = list(record.get(key) or [])
            relative = list(record.get(key + "_rel") or [])
            found = []
            for n, path in enumerate(saved):
                located = resolve_image_path(path, relative[n] if n < len(relative) else None, session_dir)
                if located:
                    found.append(located)
                else:
                    missing += 1
            pair.develop[i][key] = found
    return missing


def _float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Session commands
# --------------------------------------------------------------------------- #
