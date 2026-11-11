"""The command line: map export, and a filter's inspection history.

    python mssl_focus.py export SESSION.json -o map.png
    python mssl_focus.py export em2 --inspection thermal -o map.png

    python mssl_focus.py migrate SESSION.json ... -o em2.json
    python mssl_focus.py photos 5_thermal_test/em2
    python mssl_focus.py add em2 thermal 5_thermal_test/em2
    python mssl_focus.py detect em2 thermal
    python mssl_focus.py reject em2 T4 T7
    python mssl_focus.py accept em2 T7
    python mssl_focus.py show em2

A history is named by its file, or by the filter's name for ``<name>.json`` in
the current folder.  Nothing here needs a display: the picture is drawn by
``render.py``, the same code the window uses, so a map made here matches one
exported from the application.
"""

import argparse
import os
import sys
from pathlib import Path

from . import history as hist
from . import render
from .imaging import Pyramid, denoise, open_image
from .pair import BACKLIT, FRONTLIT, ImagePair
from .session_data import (fill_pair_from_session, read_session, resolve_frame_paths,
                           session_image_paths, shift_legacy_raw_markers)

COMMANDS = ("export", "add", "align", "detect", "accept", "reject", "show", "migrate", "photos",
            "replace-photos", "remove")


def _say(message, quiet=False):
    if not quiet:
        print(message, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Loading images
# --------------------------------------------------------------------------- #

def _load_one(path, nr, develop, dark_field):
    """Load one image exactly as the viewer does."""
    base = open_image(path, develop=develop, dark_field=dark_field)
    shown = base
    if nr and nr.get("amount", 0) > 0:
        shown = denoise(base, nr["amount"], nr["color"], nr["edge"], nr["aggressive"])
    return base, Pyramid(shown)


def pair_from_session(session, session_path, label=None, quiet=False):
    """Build an ImagePair from a session record, with its images loaded.
    ``session_path`` is the file that image paths are relative to."""
    session_path = str(Path(session_path).resolve())
    session_dir = Path(session_path).parent
    pair = ImagePair()
    fill_pair_from_session(pair, session)
    resolve_frame_paths(pair, session.get("raw_develop"), session_dir)
    pair.label = label or Path(session_path).stem
    pair.session_path = session_path

    paths, saved = session_image_paths(session, session_path)
    missing = [s for p, s in zip(paths, saved) if s and not p]
    if missing:
        raise SystemExit("Image file not found:\n  " + "\n  ".join(str(m) for m in missing))
    if not any(paths):
        raise SystemExit(f"{session_path}: no images are named.")

    for idx, image_path in enumerate(paths):
        if not image_path:
            continue
        _say(f"  loading {'backlit' if idx == BACKLIT else 'frontlit'}: {os.path.basename(image_path)}", quiet)
        base, pyramid = _load_one(image_path, pair.nr[idx], pair.develop[idx], dark_field=(idx == BACKLIT))
        pair.set_image(idx, image_path, base, pyramid)
        if idx == BACKLIT:
            shift_legacy_raw_markers(pair, session, base)
    return pair


def load_pair(session_path, quiet=False):
    """Build an ImagePair from a session file, with its images loaded."""
    session = read_session(session_path)
    return pair_from_session(session, session_path, quiet=quiet), session


def _inspection_images(history, index, history_file, quiet=False):
    """The backlit and frontlit images of an inspection, as the window shows them."""
    insp = history["inspections"][index]
    view = hist.session_view(history, index, history_file)
    pair = pair_from_session(view, history_file, label=insp["id"], quiet=quiet)
    images = [pair.pyramids[i].image if pair.has_image(i) else None for i in (BACKLIT, FRONTLIT)]
    if images[BACKLIT] is None:
        raise SystemExit(f"inspection {insp['id']} has no backlit image")
    return images


NOISY_SPOTS = 300    # in the middle of a backlit image: clean ones offer up to about 150 spots, noisy thousands


def _settle_development(history, index, history_file, quiet=False):
    """Develop a RAW backlit photograph darker if the standard stretch turns its
    sensor noise into spots.  A frame with little bright in it gets a strong
    stretch, and on some (EM4's shock test) that floods the search with
    thousands of candidates; a stop or two darker leaves the pinholes and loses
    the noise.  The setting is kept with the inspection, so the window shows the
    same image."""
    from .imaging import default_develop, is_raw
    from .session_data import develop_record
    insp = history["inspections"][index]
    resolved, _saved = hist.image_paths(insp, history_file)
    back = resolved[BACKLIT]
    if not back or not is_raw(back):
        return
    develop = default_develop()
    for _step in range(5):
        count = hist.crowded_spots(open_image(back, develop=develop, dark_field=True))
        if count <= NOISY_SPOTS:
            break
        _say(f"  {count} candidate spots at {develop['exposure']:+g} stops: sensor noise; developing darker", quiet)
        develop["exposure"] -= 1.0
    if develop["exposure"]:
        base = Path(history_file).resolve().parent
        insp["raw_develop"] = [develop_record(develop, base), develop_record(default_develop(), base)]
        print(f"{insp['id']}: backlit developed {develop['exposure']:+g} stops, as the standard stretch "
              "made its noise look like pinholes")


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #

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


def build_export_parser():
    p = argparse.ArgumentParser(
        prog="mssl_focus export",
        description="Render a pinhole map to an image file, without a window, from a session "
                    "or from one inspection of a filter history.")
    p.add_argument("source", help="session .json file, or filter history (file or filter name)")
    p.add_argument("-o", "--out", help="output image (default: beside the source, as .png)")
    p.add_argument("-i", "--inspection",
                   help="history only: the inspection to map, by ID, stage or number (default: the latest). "
                        "The map shows every pinhole known up to it.")
    p.add_argument("--show-rejected", action="store_true",
                   help="history only: also draw rejected pinholes, in grey")
    p.add_argument("--fit", choices=["outline", "annotations", "image"], default="outline",
                   help="what to frame: the filter outline (falling back to the markers, then the "
                        "whole image), the markers, or the whole image. Default: outline")
    p.add_argument("--margin", type=float, default=0.04,
                   help="blank margin around the framed content, as a fraction. Default: 0.04")
    p.add_argument("--zoom", type=float,
                   help="view scale the point sizes are relative to, as in the window "
                        "(default: the zoom saved in the session, else 0.3). Lower values give larger "
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


# Kept for callers of the earlier, export-only command line.
build_parser = build_export_parser

HISTORY_EXPORT_ZOOM = 0.3


def export_main(argv=None):
    args = build_export_parser().parse_args(argv)
    source = args.source
    data = None
    path = Path(source)
    if not path.is_file():
        path = hist.history_path(source)
    data = read_session(path)
    if hist.is_history(data):
        history = hist.read_history(path)
        index = hist.inspection_index(history, args.inspection)
        insp = history["inspections"][index]
        session = hist.session_view(history, index, path, show_rejected=args.show_rejected)
        label = f"{history.get('filter') or path.stem} {insp['name']}".strip()
        pair = pair_from_session(session, path, label=label, quiet=args.quiet)
        default_out = path.with_name(f"{path.stem}_{insp['id']}.png")
        zoom = args.zoom or HISTORY_EXPORT_ZOOM
    else:
        if args.inspection or args.show_rejected:
            raise SystemExit("--inspection and --show-rejected apply to a filter history, not a session")
        session = data
        pair = pair_from_session(session, path, quiet=args.quiet)
        default_out = path.with_suffix(".png")
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

    out = Path(args.out) if args.out else default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    if not args.quiet:
        counts = ", ".join(f"{name}={n}" for name, n in
                           sorted((pair.colour_labels.get(c, c), sum(
                               1 for a in pair.annotations if a["colour"] == c))
                               for c in {a["colour"] for a in pair.annotations}))
        print(f"{out}  {image.width}x{image.height}  [{counts}]")
    return 0


# --------------------------------------------------------------------------- #
# History commands
# --------------------------------------------------------------------------- #

def _open(name):
    path = hist.history_path(name)
    return path, hist.read_history(path)


def _print_alignment(report):
    parts = [f"turned {report.get('rotation', 0.0):+.3f} deg to upright",
             f"outline from the {report.get('outline_from', '?')} image"]
    if "frontlit_match" in report:
        parts.append(f"frontlit matched (edge agreement {report['frontlit_match']:.2f})")
    registration = report.get("registration")
    if isinstance(registration, dict):
        if registration.get("rms") is not None:
            parts.append(f"placed on the filter by {registration['matched']} of {registration['known']} "
                         f"known pinholes (rms {registration['rms']} px"
                         + (", filter turned 180 deg" if registration.get("turned") else "") + ")")
        elif registration.get("known"):
            parts.append(f"placed on the filter by its outline (only {registration.get('matched', 0)} of "
                         f"{registration['known']} known pinholes found)")
        else:
            parts.append("placed on the filter by its outline")
    elif registration:
        parts.append(registration)
    print(f"{report['inspection']}: " + "; ".join(parts))
    for warning in report.get("warnings", []):
        print(f"  warning: {warning}")


def _align(history, index, path, args):
    backlit, frontlit = _inspection_images(history, index, path, quiet=args.quiet)
    report = hist.align_inspection(history, index, backlit, frontlit,
                                   inset=args.inset / 100.0, keep_frontlit=args.keep_frontlit)
    _print_alignment(report)
    return backlit, frontlit


def _print_detection(insp, summary, added):
    print(f"{insp['id']}: {summary['spots']} spot(s) at sensitivity {summary['sensitivity']}; "
          f"{len(added)} new, {len(summary['found_again'])} known pinhole(s) found again, "
          f"{len(summary['skipped_rejected'])} rejected spot(s) skipped")
    if added:
        print("  new: " + "  ".join(f"{p['id']}({p['tier']}" + (", also frontlit" if p.get("in_frontlit") else "")
                                    + ")" for p in added))
    if summary["skipped_rejected"]:
        print("  skipped (rejected before): " + " ".join(summary["skipped_rejected"]))
    if summary["not_seen"]:
        print("  known but not seen now: " + " ".join(summary["not_seen"]))
    if summary.get("already_here"):
        print("  already here, though first recorded later: " + " ".join(summary["already_here"]))
    if summary.get("replaced"):
        print("  replaced earlier detections: " + " ".join(summary["replaced"]))


def _photo_paths(source, frontlit=None, quiet=False):
    """The backlit and frontlit photographs: as given, or chosen from a folder."""
    if not Path(source).is_dir():
        return source, frontlit
    if frontlit:
        raise SystemExit("give either a folder or two photographs, not both")
    from . import photos
    back, front, shots = photos.choose_in(source)
    if not quiet:
        print(f"photographs chosen in {source}:")
        for line in photos.describe(shots, back, front):
            print(line)
    return back, front


def cmd_photos(args):
    from . import photos
    back, front, shots = photos.choose_in(args.folder)
    for line in photos.describe(shots, back, front):
        print(line)
    return 0


def cmd_add(args):
    path = hist.history_path(args.history, must_exist=False)
    history = hist.read_history(path) if path.is_file() else hist.new_history(args.filter or path.stem)
    backlit, frontlit = _photo_paths(args.backlit, args.frontlit, args.quiet)
    insp = hist.add_inspection(history, path, args.stage, backlit, frontlit,
                               date=args.date, name=args.name, category_key=args.category)
    index = history["inspections"].index(insp)
    where = "" if index == len(history["inspections"]) - 1 else \
        f", before {history['inspections'][index + 1]['id']} (by date)"
    print(f"added inspection {insp['id']} ({insp['name']}, {insp['date']}) to {path}{where}")
    _settle_development(history, index, path, args.quiet)
    if not args.no_align:
        backlit, frontlit = _align(history, index, path, args)
        if args.detect:
            summary, added = hist.detect_inspection(history, index, backlit, frontlit,
                                                    sensitivity=args.sensitivity)
            _print_detection(insp, summary, added)
    hist.write_history(path, history)
    return 0


def cmd_replace_photos(args):
    path, history = _open(args.history)
    index = hist.inspection_index(history, args.inspection)
    backlit, frontlit = _photo_paths(args.backlit, args.frontlit, args.quiet)
    insp = hist.replace_photos(history, path, index, backlit, frontlit)
    _settle_development(history, index, path, args.quiet)
    images = _inspection_images(history, index, path, quiet=args.quiet)
    report = hist.align_inspection(history, index, *images, inset=args.inset / 100.0, refit=True)
    _print_alignment(report)
    hist.write_history(path, history)
    print(f"{insp['id']} now uses {Path(backlit).name}" + (f" and {Path(frontlit).name}" if frontlit else ""))
    return 0


def cmd_remove(args):
    path, history = _open(args.history)
    insp, gone = hist.remove_inspection(history, args.inspection)
    hist.write_history(path, history)
    print(f"removed inspection {insp['id']}" + (f" and the {len(gone)} pinhole(s) first seen in it: "
                                                + " ".join(gone) if gone else ""))
    return 0


def cmd_align(args):
    path, history = _open(args.history)
    index = hist.inspection_index(history, args.inspection)
    _align(history, index, path, args)
    hist.write_history(path, history)
    return 0


def cmd_detect(args):
    path, history = _open(args.history)
    index = hist.inspection_index(history, args.inspection)
    insp = history["inspections"][index]
    backlit, frontlit = _inspection_images(history, index, path, quiet=args.quiet)
    if hist.to_filter(insp) is None:
        report = hist.align_inspection(history, index, backlit, frontlit)
        _print_alignment(report)
    summary, added = hist.detect_inspection(history, index, backlit, frontlit, sensitivity=args.sensitivity,
                                            category_key=args.category, redo=args.redo)
    _print_detection(insp, summary, added)
    hist.write_history(path, history)
    return 0


def _set_status(args, status):
    path, history = _open(args.history)
    changed, unchanged, unknown = hist.set_status(history, args.ids, status)
    if changed:
        hist.write_history(path, history)
        print(f"{status}: " + " ".join(changed))
    if unchanged:
        print(f"already {status}: " + " ".join(unchanged))
    if unknown:
        print("no such pinhole: " + " ".join(unknown), file=sys.stderr)
        return 1
    return 0


def cmd_show(args):
    _path, history = _open(args.history)
    for line in hist.summary_lines(history):
        print(line)
    if args.pinholes:
        print()
        for p in history["pinholes"]:
            extra = []
            if p.get("tier"):
                extra.append(p["tier"])
            if p.get("in_frontlit"):
                extra.append("also frontlit")
            if p.get("unsure"):
                extra.append("unsure")
            print(f"  {p['id']:<6} {p.get('status', hist.ACCEPTED):<9} first seen {p['first_seen']:<10} "
                  f"at ({p['x']:8.1f}, {p['y']:8.1f})  {p.get('source', '')}"
                  + (f"  [{', '.join(extra)}]" if extra else ""))
    return 0


def cmd_migrate(args):
    stages = [s.strip() for s in args.stages.split(",")] if args.stages else []
    if stages and len(stages) != len(args.sessions):
        raise SystemExit(f"--stages names {len(stages)} stage(s) for {len(args.sessions)} session(s)")
    entries = [(s, stages[n] if stages else hist.stage_from_path(s)) for n, s in enumerate(args.sessions)]
    out = hist.history_path(args.out, must_exist=False)
    if out.exists() and not args.force:
        raise SystemExit(f"{out} exists; use --force to replace it")

    def backlit_image(session_path, session):
        paths, _saved = session_image_paths(session, session_path)
        if not paths[BACKLIT]:
            return None
        pair = ImagePair()
        fill_pair_from_session(pair, session)
        resolve_frame_paths(pair, session.get("raw_develop"), Path(session_path).resolve().parent)
        _say(f"  loading backlit: {os.path.basename(paths[BACKLIT])}", args.quiet)
        base, pyramid = _load_one(paths[BACKLIT], pair.nr[BACKLIT], pair.develop[BACKLIT], dark_field=True)
        return pyramid.image

    def find_outline(session_path, session, frame):
        from . import geometry as geo
        from .autoalign import AlignmentError, find_aperture
        pair = pair_from_session(session, session_path, quiet=args.quiet)
        expect = (frame["width"], frame["height"]) if frame else None
        to_back = geo.invert(pair.matrix(BACKLIT)) @ pair.matrix(FRONTLIT)
        for idx, matrix in ((FRONTLIT, to_back), (BACKLIT, geo.identity())):
            if not pair.has_image(idx):
                continue
            try:
                return find_aperture(pair.pyramids[idx].image, expect=expect).transformed(matrix)
            except AlignmentError as exc:
                _say(f"  outline not found in the {'frontlit' if idx == FRONTLIT else 'backlit'} image: {exc}",
                     args.quiet)
        return None

    history, notes = hist.migrate_sessions(entries, out, filter_name=args.filter or out.stem,
                                           find_outline=None if args.no_images else find_outline,
                                           backlit_image=None if args.no_images else backlit_image)
    hist.write_history(out, history)
    print(f"wrote {out}")
    for line in hist.summary_lines(history):
        print(line)
    for note in notes:
        print(f"  note: {note}")
    return 0


def _history_parser():
    p = argparse.ArgumentParser(prog="mssl_focus", description="A filter's inspection history.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(q):
        q.add_argument("-q", "--quiet", action="store_true", help="do not report images as they load")

    def aligning(q):
        q.add_argument("--inset", type=float, default=hist.OUTLINE_INSET * 100,
                       help="keep the search area this %% of the opening's size inside its edge. Default: 1")
        q.add_argument("--keep-frontlit", action="store_true",
                       help="keep the stored frontlit alignment instead of finding it again")

    q = sub.add_parser("add", help="add an inspection from a backlit and a frontlit photograph")
    q.add_argument("history", help="history file or filter name (created if new)")
    q.add_argument("stage", help="stage: " + ", ".join(hist.STAGES))
    q.add_argument("backlit", help="backlit photograph, or a folder of RAW photographs to choose from "
                                   "(see the photos command)")
    q.add_argument("frontlit", nargs="?", help="frontlit photograph")
    q.add_argument("--date", help="inspection date, YYYY-MM-DD (default: when the photograph was taken)")
    q.add_argument("--name", help="a name for the inspection (default: from the stage)")
    q.add_argument("--category", help="category for its new pinholes (default: from the stage)")
    q.add_argument("--filter", help="filter name, for a new history (default: the file name)")
    q.add_argument("--no-align", action="store_true", help="do not align it yet")
    q.add_argument("--detect", action="store_true", help="also search it for pinholes")
    q.add_argument("--sensitivity", type=float, help="with --detect: 0-100 (default 75)")
    aligning(q)
    common(q)

    q = sub.add_parser("photos", help="show which RAW photographs in a folder would be used, and why")
    q.add_argument("folder")

    q = sub.add_parser("replace-photos",
                       help="use other photographs of an inspection (say, RAW originals) and place them "
                            "on its known pinholes")
    q.add_argument("history")
    q.add_argument("inspection", help="ID, stage or number")
    q.add_argument("backlit", help="backlit photograph, or a folder of RAW photographs to choose from")
    q.add_argument("frontlit", nargs="?", help="frontlit photograph")
    aligning(q)
    common(q)

    q = sub.add_parser("remove", help="remove an inspection and the pinholes first seen in it")
    q.add_argument("history")
    q.add_argument("inspection", help="ID, stage or number")

    q = sub.add_parser("align", help="align an inspection again from its photographs")
    q.add_argument("history")
    q.add_argument("inspection", nargs="?", help="ID, stage or number (default: the latest)")
    aligning(q)
    common(q)

    q = sub.add_parser("detect", help="search an inspection for pinholes not known before")
    q.add_argument("history")
    q.add_argument("inspection", nargs="?", help="ID, stage or number (default: the latest)")
    q.add_argument("--sensitivity", type=float,
                   help="0-100: 50 offers only clear spots, 75 clear and likely, 100 everything. Default: 75")
    q.add_argument("--category", help="category for the new pinholes (default: the inspection's)")
    q.add_argument("--redo", action="store_true",
                   help="first drop the pinholes an earlier detect added to this inspection "
                        "(rejected ones stay remembered)")
    common(q)

    for name, verb in (("accept", "accept"), ("reject", "reject")):
        q = sub.add_parser(name, help=f"{verb} pinholes by ID")
        q.add_argument("history")
        q.add_argument("ids", nargs="+", metavar="ID")

    q = sub.add_parser("show", help="summarise a history")
    q.add_argument("history")
    q.add_argument("-p", "--pinholes", action="store_true", help="list every pinhole")

    q = sub.add_parser("migrate", help="build a history from a filter's session files, oldest first")
    q.add_argument("sessions", nargs="+", help="session .json files, in inspection order")
    q.add_argument("-o", "--out", required=True, help="history file to write")
    q.add_argument("--stages", help="comma-separated stage of each session (default: from its folder names)")
    q.add_argument("--filter", help="filter name (default: the output file name)")
    q.add_argument("--no-images", action="store_true",
                   help="do not open the photographs: no outline is looked for where a session has none, "
                        "and later inspections are placed by their markers alone, not checked against "
                        "the spots in their images")
    q.add_argument("--force", action="store_true", help="replace an existing history file")
    common(q)
    return p


HANDLERS = {"add": cmd_add, "align": cmd_align, "detect": cmd_detect, "show": cmd_show,
            "migrate": cmd_migrate, "photos": cmd_photos, "replace-photos": cmd_replace_photos,
            "remove": cmd_remove,
            "accept": lambda a: _set_status(a, hist.ACCEPTED),
            "reject": lambda a: _set_status(a, hist.REJECTED)}


def usage():
    return (__doc__ or "").strip() + "\n\nCommands: " + ", ".join(COMMANDS) + \
        "\nRun 'python mssl_focus.py COMMAND -h' for a command's options."


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(usage())
        return 0
    if argv[0] == "export":
        try:
            return export_main(argv[1:])
        except (hist.HistoryError, OSError, ValueError) as exc:
            raise SystemExit(f"export: {exc}") from None
    if argv[0] not in HANDLERS:
        raise SystemExit(f"unknown command {argv[0]!r}\n\n{usage()}")
    args = _history_parser().parse_args(argv)
    from .autoalign import AlignmentError
    try:
        return HANDLERS[args.command](args)
    except (hist.HistoryError, AlignmentError, OSError, ValueError) as exc:
        raise SystemExit(f"{args.command}: {exc}") from None


if __name__ == "__main__":
    raise SystemExit(main())
