"""The filter history: automatic alignment, detection across inspections, review,
migration from sessions, and the command line.  None of this needs a display."""

import json

import numpy as np
import pytest
from PIL import Image

from src import autoalign
from src import cli
from src import geometry as geo
from src import history as hist
from src.session_data import write_session
from tests.helpers import FRAMED_SIZE, framed_position, make_framed_filter

# Pinholes in the upright, unshifted picture, inside the opening (centre 750, 500; 660 x 600).
PINHOLES = [(480, 260), (560, 700), (640, 420), (760, 300), (820, 560), (900, 720), (990, 380)]


def write_inspection(folder, pinholes, tilt=0.0, shift=(0.0, 0.0), turned=False, front_shift=None):
    folder.mkdir(parents=True, exist_ok=True)
    make_framed_filter("back", pinholes, tilt, shift, turned).save(folder / "back.png")
    make_framed_filter("front", pinholes, tilt, front_shift or shift, turned).save(folder / "front.png")
    return folder / "back.png", folder / "front.png"


def load(path):
    return Image.open(path).convert("RGB")


# --------------------------------------------------------------------------- #
# A history built up inspection by inspection
# --------------------------------------------------------------------------- #

def _inspect(history, path, stage, back, front, **detect):
    insp = hist.add_inspection(history, path, stage, back, front, date="2026-01-01")
    index = len(history["inspections"]) - 1
    images = load(back), load(front)
    report = hist.align_inspection(history, index, *images)
    summary, added = hist.detect_inspection(history, index, *images, **detect)
    return insp, report, summary, added


def test_pinholes_carry_across_inspections_and_rejected_spots_stay_rejected(tmp_path):
    path = tmp_path / "em9.json"
    history = hist.new_history("em9")

    # Incoming: everything found is new, numbered left to right.
    back, front = write_inspection(tmp_path / "incoming", PINHOLES, 0.8, (12, -6))
    insp, report, summary, added = _inspect(history, path, "incoming", back, front)
    assert report["registration"] == "defines the filter frame"
    assert report["rotation"] == pytest.approx(-0.8, abs=0.05)
    assert [p["id"] for p in added] == [f"I{n}" for n in range(1, len(PINHOLES) + 1)]
    assert [p["first_seen"] for p in added] == ["incoming"] * len(PINHOLES)
    assert summary["found_again"] == [] and summary["not_seen"] == []
    xs = [p["x"] for p in added]
    assert xs == sorted(xs)

    # Two of them were dust after all.
    changed, _same, unknown = hist.set_status(history, ["I2", "i5"], hist.REJECTED)
    assert changed == ["I2", "I5"] and unknown == []

    # Shock test: the filter sits differently, and one new pinhole has appeared.
    extra = (700, 560)
    back, front = write_inspection(tmp_path / "shock", PINHOLES + [extra], -1.1, (-30, 18))
    insp, report, summary, added = _inspect(history, path, "shock", back, front)
    assert report["registration"]["matched"] >= 4
    assert [p["id"] for p in added] == ["S1"]
    assert summary["skipped_rejected"] == ["I2", "I5"]
    assert summary["found_again"] == ["I1", "I3", "I4", "I6", "I7"]
    # The new pinhole is placed where it really is, in filter coordinates.
    s1 = hist.pinhole(history, "S1")
    x, y, _r = hist.image_position(insp, s1)
    assert (x, y) == pytest.approx(framed_position(extra, -1.1, (-30, 18)), abs=1.5)
    # And every known pinhole lands on its spot in this inspection's image.
    for p, true in zip(sorted(hist.known_at(history, 0, (hist.ACCEPTED, hist.REJECTED)),
                              key=lambda q: q["x"]), sorted(PINHOLES)):
        x, y, _r = hist.image_position(insp, p)
        assert (x, y) == pytest.approx(framed_position(true, -1.1, (-30, 18)), abs=1.5)

    # Accepting one again brings it back; IDs are never reused.
    hist.set_status(history, ["I5"], hist.ACCEPTED)
    assert hist.next_id(history, "I") == f"I{len(PINHOLES) + 1}"

    hist.write_history(path, history)
    again = hist.read_history(path)
    assert [i["id"] for i in again["inspections"]] == ["incoming", "shock"]
    assert hist.pinhole(again, "I2")["status"] == hist.REJECTED


def test_a_filter_mounted_the_other_way_round_is_recognised(tmp_path):
    path = tmp_path / "em9.json"
    history = hist.new_history("em9")
    back, front = write_inspection(tmp_path / "incoming", PINHOLES)
    _inspect(history, path, "incoming", back, front)
    back, front = write_inspection(tmp_path / "thermal", PINHOLES, 0.4, (10, 10), turned=True)
    insp, report, summary, added = _inspect(history, path, "thermal", back, front)
    assert report["registration"]["turned"] == 180.0
    assert added == [] and len(summary["found_again"]) == len(PINHOLES)


def test_a_rerun_with_redo_replaces_only_unreviewed_detections(tmp_path):
    path = tmp_path / "em9.json"
    history = hist.new_history("em9")
    back, front = write_inspection(tmp_path / "incoming", PINHOLES)
    _inspect(history, path, "incoming", back, front)
    hist.set_status(history, ["I3"], hist.REJECTED)
    summary, added = hist.detect_inspection(history, 0, load(back), load(front), redo=True)
    assert "I3" in summary["skipped_rejected"] and "I3" not in summary["replaced"]
    assert len(added) == len(PINHOLES) - 1
    assert hist.pinhole(history, "I3")["status"] == hist.REJECTED


def test_a_spot_also_seen_from_the_front_is_flagged(tmp_path):
    path = tmp_path / "em9.json"
    history = hist.new_history("em9")
    back, front = write_inspection(tmp_path / "incoming", PINHOLES)
    glint = PINHOLES[0]
    shown = make_framed_filter("front", [])
    arr = np.asarray(shown).copy()
    x, y = int(glint[0]), int(glint[1])
    arr[y - 2:y + 3, x - 2:x + 3] = 250
    Image.fromarray(arr).save(front)
    _insp, _report, _summary, added = _inspect(history, path, "incoming", back, front)
    flagged = [p["id"] for p in added if p.get("in_frontlit")]
    assert flagged == ["I1"]


def test_changes_made_in_the_window_are_written_back(tmp_path):
    path = tmp_path / "em9.json"
    history = hist.new_history("em9")
    back, front = write_inspection(tmp_path / "incoming", PINHOLES)
    _inspect(history, path, "incoming", back, front)
    hist.set_status(history, ["I7"], hist.REJECTED)

    view = hist.session_view(history, 0, path)
    labels = [a["label"] for a in view["annotations"]]
    assert "I7" not in labels and len(labels) == len(PINHOLES) - 1
    annotations = [dict(a) for a in view["annotations"] if a["label"] != "I1"]   # I1 deleted
    annotations[0]["img1_x"] += 5.0                                               # I2 moved
    # A marker placed by hand, numbered by the window as if I7 were free.
    annotations.append({"img1_x": 700.0, "img1_y": 640.0, "radius": 20.0, "colour": "#00cc44", "label": "I7"})
    summary = hist.apply_view(history, 0, annotations)
    assert summary["rejected"] == ["I1"]
    assert summary["moved"] == ["I2"]
    assert summary["added"] == ["I8"], "a rejected pinhole's ID is not taken over"
    assert hist.pinhole(history, "I7")["status"] == hist.REJECTED
    assert hist.pinhole(history, "I8")["source"] == "manual"

    with_rejected = hist.session_view(history, 0, path, show_rejected=True)
    grey = {a["label"] for a in with_rejected["annotations"] if a["colour"] == hist.REJECTED_COLOUR}
    assert grey == {"I1", "I7"}


def test_inspections_are_found_by_id_stage_or_number(tmp_path):
    history = hist.new_history("em9")
    back, front = write_inspection(tmp_path / "a", PINHOLES)
    for stage in ("incoming", "thermal", "thermal"):
        hist.add_inspection(history, tmp_path / "em9.json", stage, back, front)
    assert [i["id"] for i in history["inspections"]] == ["incoming", "thermal", "thermal-2"]
    assert hist.inspection_index(history, "thermal-2") == 2
    assert hist.inspection_index(history, "1") == 0
    assert hist.inspection_index(history, "incoming_inspection") == 0
    assert hist.inspection_index(history, None) == 2
    assert hist.inspection_index(history, "thermal") == 1, "an exact ID wins"
    with pytest.raises(hist.HistoryError, match="several"):
        hist.inspection_index(history, "thermal_test")
    assert hist.stage_key("5_thermal_test") == "thermal"
    assert hist.stage_key("6_ship_to_naoj") == "ship"


def test_the_standard_categories():
    keys = {c["key"]: (c["name"], c["colour"], c["prefix"]) for c in hist.CATEGORIES}
    assert keys == {
        "incoming": ("Incoming Pinholes", "#00cc44", "I"),
        "repairs": ("Incoming Repairs", "#ff0088", "R"),
        "shock": ("Shock Test", "#ff0000", "S"),
        "acoustic": ("Acoustic Test", "#ff6600", "A"),
        "thermal": ("Thermal Test", "#00cccc", "T"),
        "ship": ("Ship to NAOJ", "#ffff00", "X"),
    }


# --------------------------------------------------------------------------- #
# Migration from sessions
# --------------------------------------------------------------------------- #

def _session(folder, back, front, annotations, glob_rot=0.0, outline=None):
    session = {
        "version": 1,
        "image_paths": [str(back), str(front)],
        "alignment": {"off_x": "0", "off_y": "0", "rot": "0.0", "img2_scale": "1.000", "glob_rot": str(glob_rot)},
        "annotations": annotations,
        "colour_labels": {},
    }
    if outline:
        session["filter_outline"] = outline
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "session.json"
    write_session(path, session)
    return path


def _marker(point, label, colour):
    return {"img1_x": point[0], "img1_y": point[1], "radius": 20.0, "colour": colour, "label": label}


def test_sessions_migrate_into_one_history(tmp_path):
    green, red = "#00cc44", "#ff0000"
    first = PINHOLES[:5]
    back, front = write_inspection(tmp_path / "2_incoming_inspection" / "em9", first)
    incoming = _session(tmp_path / "2_incoming_inspection" / "em9", back, front,
                        [_marker(p, f"I{n + 1}", green) for n, p in enumerate(first)])

    tilt, shift = 1.2, (-25, 14)
    new = PINHOLES[5]
    back, front = write_inspection(tmp_path / "3_shock_test" / "em9", first + [new], tilt, shift)
    # As the window carried them: the earlier markers moved with the filter, but a
    # few pixels off their spots, as a row alignment by hand leaves them.
    carried = [geo.apply(geo.translation(4, -3), *framed_position(p, tilt, shift)) for p in first]
    shock = _session(tmp_path / "3_shock_test" / "em9", back, front,
                     [_marker(p, f"I{n + 1}", green) for n, p in enumerate(carried)]
                     + [_marker(framed_position(new, tilt, shift), "S1", red)])

    out = tmp_path / "em9.json"

    def find_outline(session_path, session, frame):
        return autoalign.find_aperture(load(session["image_paths"][1]))

    history, notes = hist.migrate_sessions(
        [(incoming, hist.stage_from_path(incoming)), (shock, hist.stage_from_path(shock))], out, "em9",
        find_outline=find_outline, backlit_image=lambda path, session: load(session["image_paths"][0]))
    assert [i["id"] for i in history["inspections"]] == ["incoming", "shock"]
    assert [(p["id"], p["first_seen"], p["category"]) for p in history["pinholes"]] == \
        [(f"I{n + 1}", "incoming", "incoming") for n in range(5)] + [("S1", "shock", "shock")]
    assert history["inspections"][1]["registration"]["matched"] == 5
    assert any("carried-over markers were up to" in n for n in notes)

    shock_insp = history["inspections"][1]
    for n, p in enumerate(first):
        x, y, _r = hist.image_position(shock_insp, hist.pinhole(history, f"I{n + 1}"))
        assert (x, y) == pytest.approx(framed_position(p, tilt, shift), abs=1.5), "on its spot, not the marker"
    assert len(shock_insp["outline"]) > 20

    view = hist.session_view(history, 1, out)
    assert {a["label"] for a in view["annotations"]} == {"I1", "I2", "I3", "I4", "I5", "S1"}
    assert view["colour_labels"] == {green: "Incoming Pinholes", red: "Shock Test"}


def test_migration_without_images_keeps_the_markers_as_they_were(tmp_path):
    back, front = write_inspection(tmp_path / "2_incoming_inspection" / "em9", PINHOLES[:3])
    outline = [[400.0, 200.0], [1100.0, 200.0], [1100.0, 800.0], [400.0, 800.0]]
    a = _session(tmp_path / "2_incoming_inspection" / "em9", back, front,
                 [_marker(p, f"I{n + 1}", "#00cc44") for n, p in enumerate(PINHOLES[:3])], outline=outline)
    moved = [(x + 50, y + 20) for x, y in PINHOLES[:3]]
    b = _session(tmp_path / "5_thermal_test" / "em9", back, front,
                 [_marker(p, f"I{n + 1}", "#00cc44") for n, p in enumerate(moved)]
                 + [_marker((300, 300), "T1", "#123456")])
    history, notes = hist.migrate_sessions([(a, "incoming"), (b, "thermal")], tmp_path / "h.json")
    assert history["frame"]["width"] == pytest.approx(700) and history["frame"]["height"] == pytest.approx(600)
    assert hist.pinhole(history, "I1")["x"] == pytest.approx(PINHOLES[0][0] - 750)
    x, y, _r = hist.image_position(history["inspections"][1], hist.pinhole(history, "I2"))
    assert (x, y) == pytest.approx(moved[1], abs=1e-6)
    assert hist.pinhole(history, "T1")["category"] == "thermal"
    assert any("non-standard colour" in n for n in notes)


def test_an_outline_gives_back_its_rounded_rectangle():
    from src.autoalign import Aperture
    shape = Aperture(1000, 800, 900, 700, 0.7, 120)
    found = hist.aperture_from_outline(shape.points())
    assert (found.cx, found.cy, found.width, found.height) == pytest.approx((1000, 800, 900, 700), abs=0.5)
    assert found.tilt == pytest.approx(0.7, abs=0.01)
    assert found.radius == pytest.approx(120, abs=6)


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #

def test_the_command_line_runs_a_whole_inspection_history(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    back, front = write_inspection(tmp_path / "incoming", PINHOLES)
    assert cli.main(["add", "em9", "incoming", str(back), str(front), "--detect", "-q"]) == 0
    out = capsys.readouterr().out
    assert "added inspection incoming" in out and f"{len(PINHOLES)} new" in out

    assert cli.main(["reject", "em9", "I3", "I4"]) == 0
    assert "rejected: I3 I4" in capsys.readouterr().out
    assert cli.main(["reject", "em9", "I99"]) == 1

    back, front = write_inspection(tmp_path / "shock", PINHOLES + [(700, 560)], 0.9, (20, 10))
    assert cli.main(["add", "em9", "shock", str(back), str(front), "-q"]) == 0
    assert cli.main(["detect", "em9", "-q"]) == 0
    out = capsys.readouterr().out
    assert "new: S1" in out and "skipped (rejected before): I3 I4" in out

    assert cli.main(["accept", "em9", "I4"]) == 0
    assert cli.main(["show", "em9", "--pinholes"]) == 0
    shown = capsys.readouterr().out
    assert "Shock Test (S): 1 accepted" in shown
    assert "Incoming Pinholes (I): 6 accepted, 1 rejected" in shown

    assert cli.main(["export", "em9", "--inspection", "incoming", "-o", "incoming.png", "-q"]) == 0
    assert cli.main(["export", "em9", "-o", "latest.png", "--show-rejected", "-q"]) == 0
    with Image.open(tmp_path / "latest.png") as image:
        assert image.width > 500

    data = json.loads((tmp_path / "em9.json").read_text(encoding="utf-8"))
    assert data["type"] == hist.HISTORY_TYPE
    assert [p["id"] for p in data["pinholes"]][-1] == "S1"


def test_a_session_still_exports_as_before(tmp_path, capsys):
    back, front = write_inspection(tmp_path / "s", PINHOLES[:2])
    session = _session(tmp_path / "s", back, front,
                       [_marker(PINHOLES[0], "I1", "#00cc44"), _marker(PINHOLES[1], "S1", "#ff0000")])
    out = tmp_path / "map.png"
    assert cli.main(["export", str(session), "-o", str(out), "--fit", "image"]) == 0
    assert str(out) in capsys.readouterr().out
    with Image.open(out) as image:
        assert image.size[0] > FRAMED_SIZE[0]    # two panels and a legend
    with pytest.raises(SystemExit, match="filter history"):
        cli.main(["export", str(session), "--inspection", "thermal"])


def test_a_stage_added_late_goes_in_by_date_and_reports_what_was_already_there(tmp_path):
    path = tmp_path / "em9.json"
    history = hist.new_history("em9")
    late = (700, 560)
    back, front = write_inspection(tmp_path / "incoming", PINHOLES)
    hist.add_inspection(history, path, "incoming", back, front, date="2025-10-13")
    hist.align_inspection(history, 0, load(back), load(front))
    hist.detect_inspection(history, 0, load(back), load(front))
    back, front = write_inspection(tmp_path / "ship", PINHOLES + [late], 0.5, (8, 4))
    hist.add_inspection(history, path, "ship", back, front, date="2026-09-30")
    hist.align_inspection(history, 1, load(back), load(front))
    _summary, added = hist.detect_inspection(history, 1, load(back), load(front))
    assert [p["id"] for p in added] == ["X1"]

    # The shock test, photographed between the two, is added afterwards.
    back, front = write_inspection(tmp_path / "shock", PINHOLES + [late], -0.7, (-12, 6))
    insp = hist.add_inspection(history, path, "shock", back, front, date="2026-05-14")
    assert [i["id"] for i in history["inspections"]] == ["incoming", "shock", "ship"]
    index = history["inspections"].index(insp)
    hist.align_inspection(history, index, load(back), load(front))
    summary, added = hist.detect_inspection(history, index, load(back), load(front))
    assert added == [], "X1 is recognised, not found again as a shock pinhole"
    assert summary["already_here"] == ["X1"]
