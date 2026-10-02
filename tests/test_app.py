"""End-to-end tests that drive the real window with synthetic filter images."""

import math
import tkinter as tk
from tkinter import messagebox

import pytest

from src import geometry as geo
from src.config import Config
from src.pair import BACKLIT, FRONTLIT
from src.session import read_session
from tests.helpers import click, dot_centroid, drag, make_filter_image, wait_idle, write_json

DOTS = [(260, 210), (930, 190), (610, 420), (300, 620), (980, 610)]
SIZE = (1200, 800)


def placed(point, rotation=0.0, shift=(0, 0), scale=1.0):
    """Where ``make_filter_image`` draws a dot given the same transform."""
    cx, cy = SIZE[0] / 2, SIZE[1] / 2
    theta = math.radians(rotation)
    dx, dy = (point[0] - cx) * scale, (point[1] - cy) * scale
    return (cx + dx * math.cos(theta) - dy * math.sin(theta) + shift[0],
            cy + dx * math.sin(theta) + dy * math.cos(theta) + shift[1])


@pytest.fixture(scope="session")
def tk_root():
    """One Tk interpreter for the whole run; each test gets its own window from it."""
    try:
        master = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    master.withdraw()
    yield master
    master.destroy()


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    from src.app import ImageComparer

    root = tk.Toplevel(tk_root)

    config = Config(path=tmp_path / "config.json")
    config.data = {"show_guide_at_start": False}
    problems = []
    tk_root.report_callback_exception = lambda *exc: problems.append(exc)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    shown_errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: shown_errors.append(a))
    application = ImageComparer(root, config=config)
    application.shown_errors = shown_errors
    application._ask_colour_details = lambda colour: ("Pinholes", "P")
    root.geometry("1300x800+40+40")
    wait_idle(application)
    yield application
    try:
        root.destroy()
    except tk.TclError:
        pass
    assert not problems, f"unhandled errors in Tk callbacks: {problems}"


def pane(app, row, idx):
    return next(p for p in app.panes if p.row == row and p.idx == idx)


def make_stage(folder, dots, back=(0.0, (0, 0)), front=(0.0, (0, 0), 1.0)):
    folder.mkdir(parents=True, exist_ok=True)
    make_filter_image(SIZE, dots, rotation=back[0], shift=back[1]).save(folder / "back.png")
    make_filter_image(SIZE, dots, rotation=front[0], shift=front[1], scale=front[2],
                      background=60, dot_value=200).save(folder / "front.png")
    return folder


def load_stage(app, folder, row=0):
    app.load_image_path(str(folder / "back.png"), BACKLIT, row)
    wait_idle(app)
    app.load_image_path(str(folder / "front.png"), FRONTLIT, row)
    wait_idle(app)


def align_frontlit(app, row, back, front, dots=DOTS[:3]):
    app.set_tool("align")
    for dot in dots:
        click(app, pane(app, row, BACKLIT), *app.image_to_canvas(row, BACKLIT, *placed(dot, *back)))
        click(app, pane(app, row, FRONTLIT), *app.image_to_canvas(row, FRONTLIT, *placed(dot, *front)))
    app.apply_tool_points()
    wait_idle(app)


def test_point_alignment_registers_frontlit_to_backlit(app, tmp_path):
    back, front = (1.2, (0, 0)), (0.5, (14, -9), 1.0)
    load_stage(app, make_stage(tmp_path / "s", DOTS, back, front))
    align_frontlit(app, 0, back, front)
    pair = app.pairs[0]
    front_to_back = geo.invert(pair.matrix(BACKLIT)) @ pair.matrix(FRONTLIT)
    for dot in DOTS:
        assert geo.apply(front_to_back, *placed(dot, *front)) == pytest.approx(placed(dot, *back), abs=0.75)
    assert pair.scale == pytest.approx(1.0)
    # The same feature now sits under the same canvas position in both panels.
    for dot in DOTS:
        on_back = app.image_to_canvas(0, BACKLIT, *placed(dot, *back))
        on_front = app.image_to_canvas(0, FRONTLIT, *placed(dot, *front))
        assert on_front == pytest.approx(on_back, abs=0.75)


def test_alignment_with_scale(app, tmp_path):
    back, front = (0.0, (0, 0)), (2.0, (-20, 15), 1.05)
    load_stage(app, make_stage(tmp_path / "s", DOTS, back, front))
    app.align_scale_var.set(True)
    align_frontlit(app, 0, back, front)
    assert app.pairs[0].scale == pytest.approx(1 / 1.05, abs=2e-3)
    for dot in DOTS:
        on_back = app.image_to_canvas(0, BACKLIT, *placed(dot, *back))
        on_front = app.image_to_canvas(0, FRONTLIT, *placed(dot, *front))
        assert on_front == pytest.approx(on_back, abs=0.75)


def test_level_makes_the_drawn_line_vertical(app, tmp_path):
    back = (2.5, (0, 0))
    load_stage(app, make_stage(tmp_path / "s", DOTS, back, (2.5, (0, 0), 1.0)))
    app.set_tool("level")
    top = app.image_to_canvas(0, BACKLIT, *placed((600, 100), *back))
    bottom = app.image_to_canvas(0, BACKLIT, *placed((600, 700), *back))
    drag(app, pane(app, 0, BACKLIT), top, bottom)
    wait_idle(app)
    assert app.pairs[0].glob_rot == pytest.approx(-2.5, abs=0.05)
    top = app.image_to_canvas(0, BACKLIT, *placed((600, 100), *back))
    bottom = app.image_to_canvas(0, BACKLIT, *placed((600, 700), *back))
    assert top[0] == pytest.approx(bottom[0], abs=0.5)


def test_markers_are_numbered_saved_and_restored(app, tmp_path):
    stage = make_stage(tmp_path / "1_incoming" / "em9", DOTS)
    load_stage(app, stage)
    app.set_tool("annotate")
    for dot in DOTS[:3]:
        click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *dot))
    pair = app.pairs[0]
    assert [a["label"] for a in pair.annotations] == ["P1", "P2", "P3"]
    assert (pair.annotations[1]["img1_x"], pair.annotations[1]["img1_y"]) == pytest.approx(DOTS[1], abs=0.5)
    assert app.dirty

    session_file = stage / "session.json"
    assert app._write_session(str(session_file)) == str(session_file)
    assert not app.dirty
    saved = read_session(session_file)
    assert saved["image_paths_rel"] == ["back.png", "front.png"]

    app.new_session()
    assert not app.pairs[0].has_any_image()
    app.open_session(str(session_file))
    wait_idle(app)
    pair = app.pairs[0]
    assert pair.has_image(BACKLIT) and pair.has_image(FRONTLIT)
    assert [a["label"] for a in pair.annotations] == ["P1", "P2", "P3"]
    assert pair.colour_labels == {"#ff0000": "Pinholes"}
    assert pair.label == "1_incoming / em9"
    assert not app.dirty


def test_session_opens_after_its_folder_is_renamed(app, tmp_path):
    stage = make_stage(tmp_path / "Pinhole testing #2" / "em2", DOTS)
    load_stage(app, stage)
    app._write_session(str(stage / "session.json"))
    # Strip the relative paths to mimic a v1.0.4 file, then rename the stage folder.
    session = read_session(stage / "session.json")
    session.pop("image_paths_rel")
    write_json(stage / "session.json", session)
    renamed = tmp_path / "2_incoming_inspection"
    (tmp_path / "Pinhole testing #2").rename(renamed)

    app.new_session()
    app.open_session(str(renamed / "em2" / "session.json"))
    wait_idle(app)
    assert app.pairs[0].has_image(BACKLIT) and app.pairs[0].has_image(FRONTLIT)
    assert not app.shown_errors


def test_reference_session_brings_its_alignment_and_markers(app, tmp_path):
    back1, front1 = (1.0, (0, 0)), (0.3, (10, -6), 1.0)
    stage1 = make_stage(tmp_path / "1_incoming" / "em9", DOTS, back1, front1)
    load_stage(app, stage1)
    align_frontlit(app, 0, back1, front1)
    app.set_tool("annotate")
    for dot in DOTS:
        click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *placed(dot, *back1)))
    saved_alignment = app.pairs[0].alignment_record()
    app._write_session(str(stage1 / "session.json"))

    back2 = (-1.5, (30, 18))
    stage2 = make_stage(tmp_path / "2_shock" / "em9", DOTS, back2, (-1.5, (30, 18), 1.0))
    app.new_session()
    load_stage(app, stage2)
    app.open_reference_session(str(stage1 / "session.json"))
    wait_idle(app)

    reference = app.pairs[1]
    assert app.show_reference_var.get()
    assert reference.has_image(BACKLIT) and reference.has_image(FRONTLIT)
    assert reference.alignment_record() == saved_alignment
    assert len(reference.annotations) == len(DOTS)
    assert reference.label == "1_incoming / em9"
    assert len(app.visible_panes()) == 4

    # Align the rows on three features, then every feature must coincide on screen
    # in all four panels -- including the reference frontlit image.
    app.set_tool("align_rows")
    for dot in (DOTS[0], DOTS[4], DOTS[3]):
        click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *placed(dot, *back2)))
        click(app, pane(app, 1, BACKLIT), *app.image_to_canvas(1, BACKLIT, *placed(dot, *back1)))
    app.apply_tool_points()
    wait_idle(app)
    for dot in DOTS:
        target = app.image_to_canvas(0, BACKLIT, *placed(dot, *back2))
        assert app.image_to_canvas(1, BACKLIT, *placed(dot, *back1)) == pytest.approx(target, abs=0.75)
        assert app.image_to_canvas(1, FRONTLIT, *placed(dot, *front1)) == pytest.approx(target, abs=1.0)

    # What is drawn agrees with the maths: the reference backlit dot is under that pixel.
    frame = app._render_frame(1, BACKLIT, (1300, 800), app.view_matrix(), True)
    expected = app.image_to_canvas(1, BACKLIT, *placed(DOTS[2], *back1))
    assert dot_centroid(frame, expected) == pytest.approx(expected, abs=1.0)

    # Carry the markers forward: they land on the same features in the new images.
    app.copy_reference_annotations()
    current = app.pairs[0]
    assert len(current.annotations) == len(DOTS)
    for ann, dot in zip(current.annotations, DOTS):
        assert (ann["img1_x"], ann["img1_y"]) == pytest.approx(placed(dot, *back2), abs=1.0)
    app.copy_reference_annotations()
    assert len(current.annotations) == len(DOTS), "copying twice must not duplicate markers"

    # The comparison survives a save and reopen.
    app._write_session(str(stage2 / "session.json"))
    row_shift = dict(app.row_shift)
    app.new_session()
    app.open_session(str(stage2 / "session.json"))
    wait_idle(app)
    assert app.show_reference_var.get()
    assert app.row_shift == pytest.approx(row_shift, abs=1e-2)
    assert len(app.pairs[1].annotations) == len(DOTS)
    assert app.pairs[1].label == "1_incoming / em9"


def test_only_one_tool_is_active_and_points_do_not_leak(app, tmp_path):
    stage = make_stage(tmp_path / "s", DOTS)
    load_stage(app, stage)
    app.set_tool("align")
    click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *DOTS[0]))
    click(app, pane(app, 0, FRONTLIT), *app.image_to_canvas(0, FRONTLIT, *DOTS[0]))
    assert app._point_counts() == (1, 1)
    app.set_tool("annotate")
    assert app.tool_var.get() == "annotate"
    assert app._point_counts() == (0, 0)
    before = app.pairs[0].alignment_record()
    app.apply_tool_points()          # stale Apply must do nothing
    assert app.pairs[0].alignment_record() == before
    app.set_tool("align_rows")       # needs a reference row
    assert app.tool_var.get() == "pan"


def test_wrong_panel_click_is_refused_and_right_click_removes_a_point(app, tmp_path):
    load_stage(app, make_stage(tmp_path / "s", DOTS))
    app.set_tool("align")
    back, front = pane(app, 0, BACKLIT), pane(app, 0, FRONTLIT)
    click(app, back, *app.image_to_canvas(0, BACKLIT, *DOTS[0]))
    click(app, back, *app.image_to_canvas(0, BACKLIT, *DOTS[1]))
    assert app._point_counts() == (1, 0)
    assert "frontlit" in app.status_var.get().lower()
    click(app, front, *app.image_to_canvas(0, FRONTLIT, *DOTS[0]))
    app._undo_tool_point()
    assert app._point_counts() == (1, 0)


def test_dragging_pans_instead_of_placing_a_marker(app, tmp_path):
    load_stage(app, make_stage(tmp_path / "s", DOTS))
    app.set_tool("annotate")
    pan_before = (app.pan_x, app.pan_y)
    drag(app, pane(app, 0, BACKLIT), (300, 300), (360, 340))
    wait_idle(app)
    assert app.pairs[0].annotations == []
    assert (app.pan_x, app.pan_y) == pytest.approx((pan_before[0] + 60, pan_before[1] + 40))


def test_undo_and_redo(app, tmp_path):
    load_stage(app, make_stage(tmp_path / "s", DOTS))
    app.set_tool("annotate")
    target = pane(app, 0, BACKLIT)
    click(app, target, *app.image_to_canvas(0, BACKLIT, *DOTS[0]))
    click(app, target, *app.image_to_canvas(0, BACKLIT, *DOTS[1]))
    app._delete_annotation(0)
    assert [a["label"] for a in app.pairs[0].annotations] == ["P2"]
    app.undo()
    assert [a["label"] for a in app.pairs[0].annotations] == ["P1", "P2"]
    app.undo()
    assert [a["label"] for a in app.pairs[0].annotations] == ["P1"]
    app.redo()
    assert [a["label"] for a in app.pairs[0].annotations] == ["P1", "P2"]

    app.pairs[0].set_global_rotation(0.0)
    app._checkpoint("Level")
    app.pairs[0].set_global_rotation(3.0)
    app.undo()
    assert app.pairs[0].glob_rot == 0.0


def test_move_tool_drags_a_marker(app, tmp_path):
    load_stage(app, make_stage(tmp_path / "s", DOTS))
    app.set_tool("annotate")
    start = app.image_to_canvas(0, BACKLIT, *DOTS[0])
    click(app, pane(app, 0, BACKLIT), *start)
    app.set_tool("move")
    drag(app, pane(app, 0, BACKLIT), start, (start[0] + 50, start[1] + 20))
    wait_idle(app)
    ann = app.pairs[0].annotations[0]
    assert (ann["img1_x"], ann["img1_y"]) == pytest.approx(
        (DOTS[0][0] + 50 / app.zoom, DOTS[0][1] + 20 / app.zoom), abs=0.5)


def test_failed_open_leaves_the_current_session_untouched(app, tmp_path):
    stage = make_stage(tmp_path / "good", DOTS)
    load_stage(app, stage)
    app.set_tool("annotate")
    click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *DOTS[0]))

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "back.png").write_bytes(b"this is not an image")
    make_filter_image(SIZE, DOTS).save(broken / "front.png")
    write_json(broken / "session.json", {
        "version": 1, "image_paths": [str(broken / "back.png"), str(broken / "front.png")],
        "alignment": {"off_x": "50", "off_y": "0", "rot": "5.0", "img2_scale": "1.0", "glob_rot": "9.0"},
        "annotations": [],
    })
    app.open_session(str(broken / "session.json"))
    wait_idle(app)
    assert app.shown_errors, "the user must be told the image failed to load"
    pair = app.pairs[0]
    assert pair.paths[BACKLIT] == str(stage / "back.png")
    assert pair.glob_rot == 0.0
    assert len(pair.annotations) == 1


def test_export_contains_both_rows_and_the_legend(app, tmp_path):
    stage = make_stage(tmp_path / "1_incoming" / "em9", DOTS)
    load_stage(app, stage)
    app.set_tool("annotate")
    click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *DOTS[2]))
    app._write_session(str(stage / "session.json"))
    canvas = pane(app, 0, BACKLIT).canvas
    rect = (0, 0, canvas.winfo_width(), canvas.winfo_height())
    single = app.render_export(*rect)
    pad = app.crop_pad_var.get()
    marker_x, marker_y = geo.apply(
        geo.translation(pad, pad) @ geo.translation(app.pan_x / app.zoom, app.pan_y / app.zoom), *DOTS[2])
    single_width_floor = 2 * rect[2] / app.zoom * 0.9
    app.open_reference_session(str(stage / "session.json"))
    wait_idle(app)
    canvas = pane(app, 0, BACKLIT).canvas
    rect = (0, 0, canvas.winfo_width(), canvas.winfo_height())
    double = app.render_export(*rect, include_reference=True)
    assert single.width > single_width_floor     # two panels plus legend, at native resolution
    assert double.height > single.height * 0.9
    # The marker ring (radius 20 px, red) is drawn around the feature.
    assert single.getpixel((int(marker_x + 20 - 2), int(marker_y))) == (255, 0, 0)
    assert single.getpixel((int(marker_x), int(marker_y)))[0] > 200   # the dot itself, untouched
