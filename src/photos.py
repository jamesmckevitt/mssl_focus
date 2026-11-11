"""Choosing an inspection's photographs from a folder of camera RAW files.

Each inspection is photographed several times: backlit at a range of exposures,
and frontlit at a few exposures and lightings.  The rule, checked against the
hand-made maps of EM1 to EM4:

* **Backlit** photographs are the dark ones.  The one used is the **longest
  exposure**: at 10 s the search finds every marked pinhole (or all but the
  faintest) with fewest false spots, while below 2 s sensor noise swamps it with
  thousands.  If several share the longest exposure, the **latest** is used: a
  repeated series means the filter was set up again (on EM3 the first series
  does not match the filter as marked at all).

* **Frontlit** photographs are the bright ones.  Dim shots (a different
  lighting) are left out; of the rest the one used has the exposure **closest
  to 0.25 s**, and of those the one **nearest in the sequence** to the backlit
  photograph, so both come from the same set-up.  This picks the frontlit
  photograph chosen by hand in every marked inspection.

Only RAW files are considered: TIFF and JPEG files in these folders are
reprocessed copies.
"""

import io
import math
import re
from pathlib import Path

import numpy as np

from .camera import RAW_EXTENSIONS, read_camera_info

DARK_LEVEL = 30           # mean brightness (0-255) of the camera's preview below which a shot is backlit
DIM_LEVEL = 100           # frontlit shots below this are a dimmer lighting, not the standard one
FRONTLIT_EXPOSURE = 0.25  # seconds


class PhotoError(ValueError):
    """The folder does not hold a usable backlit and frontlit photograph."""


def _sequence(path):
    """The camera's running number, from a name such as DSC00085.ARW."""
    numbers = re.findall(r"\d+", Path(path).stem)
    return int(numbers[-1]) if numbers else 0


def _preview_brightness(path):
    """Mean brightness of the preview the camera embeds in a RAW file (fast)."""
    import rawpy
    from PIL import Image
    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
    if thumb.format == rawpy.ThumbFormat.JPEG:
        with Image.open(io.BytesIO(thumb.data)) as preview:
            return float(np.asarray(preview.convert("L")).mean())
    return float(np.asarray(thumb.data).mean())


def survey(folder):
    """Every RAW photograph in a folder: ``[{path, exposure, brightness, sequence, kind}]``,
    in sequence order.  ``kind`` is ``backlit`` or ``frontlit``."""
    shots = []
    for path in sorted(Path(folder).iterdir()):
        if path.suffix.lower() not in RAW_EXTENSIONS or not path.is_file():
            continue
        info = read_camera_info(str(path))
        brightness = _preview_brightness(path)
        shots.append({
            "path": str(path),
            "exposure": info.get("exposure_time"),
            "brightness": round(brightness, 1),
            "sequence": _sequence(path),
            "kind": "backlit" if brightness < DARK_LEVEL else "frontlit",
        })
    shots.sort(key=lambda s: s["sequence"])
    return shots


def choose(shots):
    """Pick ``(backlit, frontlit)`` from a survey, by the rule above.  ``frontlit``
    is None if there is no usable one."""
    backlit = [s for s in shots if s["kind"] == "backlit"]
    if not backlit:
        raise PhotoError("no backlit (dark) RAW photograph found")
    back = max(backlit, key=lambda s: (s["exposure"] or 0.0, s["sequence"]))
    usable = [s for s in shots if s["kind"] == "frontlit" and s["brightness"] >= DIM_LEVEL]
    if not usable:
        return back, None

    def closeness(s):
        exposure = s["exposure"] or FRONTLIT_EXPOSURE
        return abs(math.log(exposure / FRONTLIT_EXPOSURE))

    nearest = min(round(closeness(s), 6) for s in usable)
    front = min((s for s in usable if round(closeness(s), 6) == nearest),
                key=lambda s: abs(s["sequence"] - back["sequence"]))
    return back, front


def choose_in(folder):
    """``(backlit_path, frontlit_path, survey)`` for a folder."""
    shots = survey(folder)
    if not shots:
        raise PhotoError(f"no RAW photographs in {folder}")
    back, front = choose(shots)
    return back["path"], front["path"] if front else None, shots


def describe(shots, back=None, front=None):
    """Lines describing a survey, with the chosen photographs marked."""
    lines = []
    for s in shots:
        mark = "  <- backlit" if back and s["path"] == back else "  <- frontlit" if front and s["path"] == front else ""
        exposure = f"{s['exposure']:g} s" if s["exposure"] else "? s"
        lines.append(f"  {Path(s['path']).name:<14} {s['kind']:<8} {exposure:>7}  brightness {s['brightness']:5.1f}{mark}")
    return lines
