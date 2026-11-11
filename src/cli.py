"""Command-line map export: render a session to an image without opening a window.

    python mssl_focus.py export SESSION.json -o map.png

Useful for regenerating a batch of maps after a change, and for building maps on
a machine with no display.  The picture is drawn by ``render.py``, the same code
the window uses, so a map made here matches one exported from the application.
"""

import argparse
import os
import sys
from pathlib import Path

from . import render
from .imaging import Pyramid, denoise, open_image
from .pair import BACKLIT, FRONTLIT, ImagePair
from .session_data import (fill_pair_from_session, read_session, resolve_frame_paths,
                           session_image_paths, shift_legacy_raw_markers)


def _load_one(path, nr, develop, dark_field):
    """Load one image exactly as the viewer does."""
    base = open_image(path, develop=develop, dark_field=dark_field)
    shown = base
    if nr and nr.get("amount", 0) > 0:
        shown = denoise(base, nr["amount"], nr["color"], nr["edge"], nr["aggressive"])
    return base, Pyramid(shown)


def load_pair(session_path, quiet=False):
    """Build an ImagePair from a session file, with its images loaded."""
    session_path = str(Path(session_path).resolve())
    session = read_session(session_path)
    session_dir = Path(session_path).parent
    pair = ImagePair()
    fill_pair_from_session(pair, session)
    resolve_frame_paths(pair, session.get("raw_develop"), session_dir)
    pair.label = Path(session_path).stem
    pair.session_path = session_path

    paths, saved = session_image_paths(session, session_path)
    missing = [s for p, s in zip(paths, saved) if s and not p]
    if missing:
        raise SystemExit("Image file not found:\n  " + "\n  ".join(str(m) for m in missing))
    if not any(paths):
        raise SystemExit(f"{session_path}: the session names no images.")

    for idx, image_path in enumerate(paths):
        if not image_path:
            continue
        if not quiet:
            print(f"  loading {'backlit' if idx == BACKLIT else 'frontlit'}: "
                  f"{os.path.basename(image_path)}", file=sys.stderr)
        base, pyramid = _load_one(image_path, pair.nr[idx], pair.develop[idx],
                                  dark_field=(idx == BACKLIT))
        pair.set_image(idx, image_path, base, pyramid)
        if idx == BACKLIT:
            shift_legacy_raw_markers(pair, session, base)
    return pair, session


def content_rectangle(scene, pair, fit="outline", margin=0.04):
    """The world rectangle to export: the filter outline, the markers, or the whole image."""
    from . import geometry as geo
    to_world = scene.world_matrix(render.CURRENT, BACKLIT)
    points = []
    if fit in ("outline", "auto") and len(pair.outline) >= 3:
        points = [tuple(p) for p in pair.outline]
    if not points and fit in ("annotations", "auto", "outline") and pair.annotations:
        points = [(a["img1_x"], a["img1_y"]) for a in pair.annotations]
    if not points:
        w, h = pair.size(BACKLIT) if pair.has_image(BACKLIT) else pair.size(FRONTLIT)
        points = [(0, 0), (w, 0), (w, h), (0, h)]
    world = geo.apply_many(to_world, points)
    xs = [p[0] for p in world]
    ys = [p[1] for p in world]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad_x = (x1 - x0) * margin
    pad_y = (y1 - y0) * margin
    return x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y


def build_parser():
    p = argparse.ArgumentParser(
        prog="mssl_focus export",
        description="Render a session's pinhole map to an image file, without a window.")
    p.add_argument("session", help="session .json file")
    p.add_argument("-o", "--out", help="output image (default: <session>.png beside the session)")
    p.add_argument("--fit", choices=["outline", "annotations", "image"], default="outline",
                   help="what to frame: the filter outline (falling back to the markers, then the "
                        "whole image), the markers, or the whole image. Default: outline")
    p.add_argument("--margin", type=float, default=0.04,
                   help="blank margin around the framed content, as a fraction. Default: 0.04")
    p.add_argument("--zoom", type=float,
                   help="view scale the point sizes are relative to, as in the window "
                        "(default: the zoom saved in the session). Lower values give larger "
                        "marker labels relative to the filter.")
    p.add_argument("--mode", choices=["sidebyside", "overlay"],
                   help="panel layout (default: as saved in the session)")
    p.add_argument("--opacity", type=float, help="overlay blend, 0-1 (default: as saved)")
    p.add_argument("--label-size", type=int, default=12, help="marker label point size. Default: 12")
    p.add_argument("--legend-size", type=int, default=10, help="legend point size. Default: 10")
    p.add_argument("--line-width", type=float, default=2.0, help="marker stroke width. Default: 2.0")
    p.add_argument("--crop-pad", type=int, default=20, help="padding inside each panel. Default: 20")
    p.add_argument("--dpi", type=float, default=96.0,
                   help="screen dpi the point sizes refer to. Default: 96")
    p.add_argument("--max-width", type=int,
                   help="downscale the finished image to at most this many pixels wide")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    pair, session = load_pair(args.session, quiet=args.quiet)

    zoom = args.zoom or float(session.get("zoom") or 1.0)
    scene = render.Scene(
        pairs=[pair, ImagePair()],
        zoom=zoom, pan_x=0.0, pan_y=0.0,
        mode=args.mode or session.get("mode", "sidebyside"),
        opacity=args.opacity if args.opacity is not None else float(session.get("opacity", 0.5)),
        crop_pad=args.crop_pad,
        label_size=args.label_size,
        legend_size=args.legend_size,
        line_width=args.line_width,
        px_per_point=args.dpi / 72.0,
    )
    x0, y0, x1, y1 = content_rectangle(scene, pair, fit=args.fit, margin=args.margin)
    # content_rectangle works in world units; the renderer takes canvas units, and with
    # no pan those differ only by the zoom.
    image = render.render_rect(scene, x0 * zoom, y0 * zoom, x1 * zoom, y1 * zoom)

    if args.max_width and image.width > args.max_width:
        height = round(image.height * args.max_width / image.width)
        image = image.resize((args.max_width, height))

    out = args.out or str(Path(args.session).with_suffix(".png"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    if not args.quiet:
        counts = ", ".join(f"{name}={n}" for name, n in
                           sorted((pair.colour_labels.get(c, c), sum(
                               1 for a in pair.annotations if a["colour"] == c))
                               for c in {a["colour"] for a in pair.annotations}))
        print(f"{out}  {image.width}x{image.height}  [{counts}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
