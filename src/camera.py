"""Camera exposure settings recorded in an image file: reading, describing, comparing."""

import io
import math
import os

from PIL import Image

RAW_EXTENSIONS = {'.arw', '.nef', '.cr2', '.cr3', '.orf', '.rw2', '.dng', '.raf', '.pef', '.srw'}

_EXIF_IFD = 0x8769
_TAGS = {
    "exposure_time": 0x829A,
    "f_number": 0x829D,
    "iso": 0x8827,
    "focal_length": 0x920A,
    "lens": 0xA434,
    "taken": 0x9003,
}


def _number(value):
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    try:
        number = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _text(value):
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    text = str(value).replace("\x00", "").strip() if value is not None else ""
    return text or None


def _from_exif(exif):
    info = {}
    details = exif.get_ifd(_EXIF_IFD)
    for key in ("exposure_time", "f_number", "iso", "focal_length"):
        number = _number(details.get(_TAGS[key]))
        if number is not None:
            info[key] = int(round(number)) if key == "iso" else round(number, 6)
    for key, value in (("lens", details.get(_TAGS["lens"])), ("taken", details.get(_TAGS["taken"])),
                       ("model", exif.get(0x0110))):
        text = _text(value)
        if text:
            info[key] = text
    return info


def read_camera_info(path):
    """The exposure settings stored in an image file, or ``{}`` if there are none.

    Keys, each present only when known: ``exposure_time`` (seconds),
    ``f_number``, ``iso``, ``focal_length`` (mm), ``lens``, ``model``, ``taken``.
    """
    try:
        if os.path.splitext(path)[1].lower() in RAW_EXTENSIONS:
            import rawpy
            with rawpy.imread(path) as raw:
                thumb = raw.extract_thumb()
            if thumb.format != rawpy.ThumbFormat.JPEG:
                return {}
            with Image.open(io.BytesIO(thumb.data)) as preview:
                return _from_exif(preview.getexif())
        with Image.open(path) as handle:
            return _from_exif(handle.getexif())
    except Exception:  # metadata is a nicety: never let it stop an image loading
        return {}


def format_exposure_time(seconds):
    if seconds >= 1.0:
        return f"{round(seconds, 1):g} s"
    reciprocal = 1.0 / seconds
    if abs(reciprocal - round(reciprocal)) <= 0.03 * reciprocal:
        return f"1/{round(reciprocal)} s"
    return f"{seconds:.3g} s"


def camera_parts(info, with_equipment=True):
    """The settings as ``(key, text)`` pairs, in display order."""
    info = info or {}
    parts = []
    if "f_number" in info:
        parts.append(("f_number", f"f/{info['f_number']:g}"))
    if "exposure_time" in info:
        parts.append(("exposure_time", format_exposure_time(info["exposure_time"])))
    if "iso" in info:
        parts.append(("iso", f"ISO {info['iso']}"))
    if with_equipment:
        if "focal_length" in info:
            parts.append(("focal_length", f"{info['focal_length']:g} mm"))
        if "model" in info:
            parts.append(("model", info["model"]))
    return parts


def describe_camera(info, with_equipment=True):
    """One line such as ``f/8  |  10 s  |  ISO 2000  |  30 mm  |  ILCE-6400``."""
    return "  |  ".join(text for _key, text in camera_parts(info, with_equipment))


def mismatched_settings(a, b):
    """Keys of the settings that both images record but with different values."""
    a, b = a or {}, b or {}
    differing = set()
    for key in ("f_number", "exposure_time", "iso", "focal_length", "model"):
        if key not in a or key not in b:
            continue
        if isinstance(a[key], str) or isinstance(b[key], str):
            if a[key] != b[key]:
                differing.add(key)
        elif abs(a[key] - b[key]) > 1e-3 * max(abs(a[key]), abs(b[key])):
            differing.add(key)
    return differing


def exposure_stops(saved, target):
    """How many stops more light ``target`` recorded than ``saved`` (negative: less),
    or ``None`` if either lacks the aperture, time or ISO."""
    def light(info):
        if not all(key in info for key in ("exposure_time", "f_number", "iso")):
            return None
        return info["exposure_time"] * info["iso"] / info["f_number"] ** 2

    a, b = light(saved or {}), light(target or {})
    if a is None or b is None:
        return None
    return math.log2(b / a)


def camera_differences(saved, target):
    """Human-readable list of exposure settings that differ between two images."""
    saved, target = saved or {}, target or {}
    differences = []
    for key, name, show in (
        ("f_number", "aperture", lambda v: f"f/{v:g}"),
        ("exposure_time", "exposure time", format_exposure_time),
        ("iso", "ISO", lambda v: f"{v}"),
    ):
        if key in saved and key in target and abs(saved[key] - target[key]) > 1e-3 * max(saved[key], target[key]):
            differences.append(f"{name} {show(saved[key])} then, {show(target[key])} now")
    return differences
