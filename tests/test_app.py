"""End-to-end tests that drive the real window with synthetic filter images."""

import math
import tkinter as tk
from tkinter import filedialog, messagebox

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
    confirmations = []
    answers = {"ok": True}
    monkeypatch.setattr(messagebox, "askokcancel",
                        lambda title, message, **k: (confirmations.append(message), answers["ok"])[1])
    shown_errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: shown_errors.append(a))
    application = ImageComparer(root, config=config)
    application.shown_errors = shown_errors
    application.confirmations = confirmations
    application.confirm_answers = answers
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


def test_found_pinholes_are_reviewed_one_by_one(app, tmp_path):
    load_stage(app, make_stage(tmp_path / "s", DOTS))
    app.set_tool("annotate")
    click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *DOTS[0]))   # already marked
    app.set_tool("detect")
    canvas = pane(app, 0, BACKLIT).canvas
    drag(app, pane(app, 0, BACKLIT), (2, 2), (canvas.winfo_width() - 2, canvas.winfo_height() - 2))
    wait_idle(app)
    assert app.tool_var.get() == "review"
    assert len(app._candidates) == len(DOTS) - 1, "the marked spot must not be offered again"
    assert app._candidate_summary["marked"] == 1

    first = dict(app._current_candidate())
    app.review_accept()
    wait_idle(app)
    newest = app.pairs[0].annotations[-1]
    assert (newest["img1_x"], newest["img1_y"]) == pytest.approx((first["x"], first["y"]))
    assert newest["label"] == "P2"
    app.review_reject()
    app.review_skip()
    wait_idle(app)
    assert len(app._candidates) == len(DOTS) - 3
    app._on_escape()
    assert app.tool_var.get() == "pan" and app._candidates == []
    assert len(app.pairs[0].annotations) == 2
    app.undo()
    assert len(app.pairs[0].annotations) == 1


def test_new_pinholes_are_offered_first_when_a_reference_is_loaded(app, tmp_path):
    back1 = (0.8, (0, 0))
    stage1 = make_stage(tmp_path / "1_incoming" / "em9", DOTS[:3], back1, (0.8, (0, 0), 1.0))
    load_stage(app, stage1)
    app._write_session(str(stage1 / "session.json"))

    back2 = (-1.0, (22, -14))
    stage2 = make_stage(tmp_path / "2_shock" / "em9", DOTS, back2, (-1.0, (22, -14), 1.0))
    app.new_session()
    load_stage(app, stage2)
    app.open_reference_session(str(stage1 / "session.json"))
    wait_idle(app)
    app.set_tool("align_rows")
    for dot in DOTS[:3]:
        click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *placed(dot, *back2)))
        click(app, pane(app, 1, BACKLIT), *app.image_to_canvas(1, BACKLIT, *placed(dot, *back1)))
    app.apply_tool_points()
    wait_idle(app)

    app.set_tool("detect")
    canvas = pane(app, 0, BACKLIT).canvas
    drag(app, pane(app, 0, BACKLIT), (2, 2), (canvas.winfo_width() - 2, canvas.winfo_height() - 2))
    wait_idle(app)
    assert app._candidate_summary["with_reference"]
    assert app._candidate_summary["new"] == 2
    flags = [c["in_reference"] for c in app._candidates]
    assert flags == [False, False, True, True, True]
    new_positions = sorted((round(c["x"]), round(c["y"])) for c in app._candidates[:2])
    expected = sorted((round(x + 0.5), round(y + 0.5)) for x, y in (placed(d, *back2) for d in DOTS[3:]))
    assert new_positions == pytest.approx(expected, abs=1)
    app.detect_new_only_var.set(True)
    assert len(app._review_candidates()) == 2


def test_reference_images_are_only_offered_when_there_is_a_reference_row(app, tmp_path):
    stage = make_stage(tmp_path / "1_incoming" / "em9", DOTS)
    load_stage(app, stage)
    assert list(app.adjust_target_box.cget("values")) == ["Backlit image", "Frontlit image"]
    app._write_session(str(stage / "session.json"))
    app.open_reference_session(str(stage / "session.json"))
    wait_idle(app)
    assert len(app.adjust_target_box.cget("values")) == 4
    app.adjust_target_var.set("Reference frontlit image")
    app._sync_controls()
    app.show_reference_var.set(False)
    app._on_reference_toggle()
    assert list(app.adjust_target_box.cget("values")) == ["Backlit image", "Frontlit image"]
    assert app.adjust_target_var.get() == "Backlit image"


def test_an_exact_value_can_be_typed_beside_a_slider(app, tmp_path):
    load_stage(app, make_stage(tmp_path / "s", DOTS))
    text, commit = app.slider_inputs["Brightness"]
    assert text.get() == "1.00"
    text.set("2")
    commit()
    assert app.pairs[0].adjust[BACKLIT]["brightness"] == 2.0
    assert text.get() == "2.00"
    text.set("99")                      # beyond the slider's range: held at its limit
    commit()
    assert app.pairs[0].adjust[BACKLIT]["brightness"] == 3.0
    text.set("oops")                    # not a number: the box goes back to the real value
    commit()
    assert text.get() == "3.00"
    app.undo()
    assert app.pairs[0].adjust[BACKLIT]["brightness"] == 1.0
    assert text.get() == "1.00"


def test_image_settings_are_saved_to_a_file_and_loaded_onto_another_image(app, tmp_path, monkeypatch):
    load_stage(app, make_stage(tmp_path / "a", DOTS))
    app.adjust_target_var.set("Frontlit image")
    app._sync_controls()
    app.pairs[0].adjust[FRONTLIT].update({"brightness": 1.7, "contrast": 1.2, "blacks": 12.0, "whites": 230.0})
    preset = tmp_path / "frontlit_settings.json"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **k: str(preset))
    assert app.save_image_settings() == str(preset)
    assert read_session(preset)["adjust"]["brightness"] == 1.7

    app.new_session()
    load_stage(app, make_stage(tmp_path / "b", DOTS))
    app.adjust_target_var.set("Frontlit image")
    app._sync_controls()
    app.load_image_settings(str(preset))
    wait_idle(app)
    assert app.pairs[0].adjust[FRONTLIT] == {"brightness": 1.7, "contrast": 1.2, "blacks": 12.0, "whites": 230.0}
    assert app.pairs[0].adjust[BACKLIT]["brightness"] == 1.0, "the other image is left alone"
    assert app.slider_inputs["Brightness"][0].get() == "1.70"
    app.undo()
    assert app.pairs[0].adjust[FRONTLIT]["brightness"] == 1.0


def test_matching_makes_the_reference_frontlit_look_like_the_current_one(app, tmp_path):
    import numpy as np

    def textured(folder, gain):
        folder.mkdir(parents=True)
        rng = np.random.default_rng(5)
        base = np.clip(rng.normal(90, 25, (800, 1200)), 10, 170)
        from PIL import Image
        Image.fromarray(np.clip(base * gain, 0, 255).astype(np.uint8)).convert("RGB").save(folder / "front.png")
        make_filter_image(SIZE, DOTS).save(folder / "back.png")
        return folder

    earlier = textured(tmp_path / "1_incoming" / "em9", 0.75)     # darker exposure
    load_stage(app, earlier)
    app._write_session(str(earlier / "session.json"))
    app.new_session()
    load_stage(app, textured(tmp_path / "2_shock" / "em9", 1.0))
    app.open_reference_session(str(earlier / "session.json"))
    wait_idle(app)

    def shown_median(row):
        pair = app.pairs[row]
        values = np.asarray(pair.pyramids[FRONTLIT].levels[-1].convert("L"))
        lut = pair.lut(FRONTLIT)
        return float(np.median(values if lut is None else np.asarray(lut)[values]))

    assert shown_median(1) < shown_median(0) - 15
    app.adjust_target_var.set("Reference frontlit image")
    app._sync_controls()
    app.match_to_other_row()
    wait_idle(app)
    assert shown_median(1) == pytest.approx(shown_median(0), abs=3)
    assert app.pairs[1].adjust[FRONTLIT]["brightness"] == pytest.approx(1 / 0.75, abs=0.06)
    assert app.pairs[0].adjust[FRONTLIT]["brightness"] == 1.0
    # The backlit images are identical here, so matching leaves them as they were.
    assert app.pairs[1].adjust[BACKLIT]["brightness"] == pytest.approx(1.0, abs=0.02)
    app.undo()
    assert app.pairs[1].adjust[FRONTLIT]["brightness"] == 1.0


def test_backlit_images_of_different_brightness_are_matched_too(app, tmp_path):
    import numpy as np

    def stage(folder, dot_value):
        folder.mkdir(parents=True)
        spots = [(int(x), int(y)) for x, y in np.random.default_rng(8).uniform((60, 60), (1140, 740), (300, 2))]
        make_filter_image(SIZE, spots, mesh=False, dot_value=dot_value, background=0).save(folder / "back.png")
        make_filter_image(SIZE, DOTS, background=60).save(folder / "front.png")
        return folder

    earlier = stage(tmp_path / "1_incoming" / "em9", 110)       # dimmer pinholes
    load_stage(app, earlier)
    app._write_session(str(earlier / "session.json"))
    app.new_session()
    load_stage(app, stage(tmp_path / "2_shock" / "em9", 220))
    app.open_reference_session(str(earlier / "session.json"))
    wait_idle(app)
    app.adjust_target_var.set("Reference backlit image")
    app._sync_controls()
    app.match_to_other_row()
    wait_idle(app)
    assert app.pairs[1].adjust[BACKLIT]["brightness"] == pytest.approx(2.0, abs=0.1)
    assert app.pairs[1].adjust[BACKLIT]["contrast"] == 1.0


def test_an_unsure_candidate_gets_a_question_mark(app, tmp_path):
    stage = make_stage(tmp_path / "1_incoming" / "em9", DOTS)
    load_stage(app, stage)
    app.set_tool("detect")
    canvas = pane(app, 0, BACKLIT).canvas
    drag(app, pane(app, 0, BACKLIT), (2, 2), (canvas.winfo_width() - 2, canvas.winfo_height() - 2))
    wait_idle(app)
    app.review_unsure()
    app.review_accept()
    wait_idle(app)
    app._on_escape()
    first, second = app.pairs[0].annotations
    assert first["label"] == "P1" and first["unsure"] is True
    assert second["label"] == "P2" and "unsure" not in second, "numbering carries on past an unsure marker"
    assert app.pairs[0].legend() == [("#ff0000", "Pinholes  (n=2, 1 unsure)")]

    shown = [canvas.itemcget(item, "text") for item in canvas.find_withtag("world")
             if canvas.type(item) == "text"]
    assert "P1?" in shown and "P2" in shown

    app._write_session(str(stage / "session.json"))
    app.new_session()
    app.open_session(str(stage / "session.json"))
    wait_idle(app)
    assert app.pairs[0].annotations[0].get("unsure") is True
    app._toggle_annotation_unsure(0)
    assert "unsure" not in app.pairs[0].annotations[0]
    assert app.pairs[0].legend() == [("#ff0000", "Pinholes  (n=2)")]


def test_matching_direction_and_scope_can_be_chosen(app, tmp_path):
    import numpy as np
    from PIL import Image

    def stage(folder, gain):
        folder.mkdir(parents=True)
        rng = np.random.default_rng(5)
        base = np.clip(rng.normal(90, 25, (800, 1200)), 10, 170)
        Image.fromarray(np.clip(base * gain, 0, 255).astype(np.uint8)).convert("RGB").save(folder / "front.png")
        spots = [(int(x), int(y)) for x, y in np.random.default_rng(8).uniform((60, 60), (1140, 740), (300, 2))]
        make_filter_image(SIZE, spots, mesh=False, dot_value=int(200 * gain), background=0).save(folder / "back.png")
        return folder

    earlier = stage(tmp_path / "1_incoming" / "em9", 0.6)
    load_stage(app, earlier)
    app._write_session(str(earlier / "session.json"))
    app.new_session()
    load_stage(app, stage(tmp_path / "2_shock" / "em9", 1.0))
    app.open_reference_session(str(earlier / "session.json"))
    wait_idle(app)
    current, reference = app.pairs

    def brightness():
        return [round(p.adjust[i]["brightness"], 2) for p in (current, reference) for i in (BACKLIT, FRONTLIT)]

    assert brightness() == [1.0, 1.0, 1.0, 1.0]

    # Current row towards the reference row, frontlit only.
    app.match_direction_var.set("Current row, to look like reference row")
    app.match_scope_var.set("Frontlit only")
    app.match_to_other_row()
    wait_idle(app)
    after = brightness()
    assert after[1] == pytest.approx(0.6, abs=0.05)
    assert [after[0], after[2], after[3]] == [1.0, 1.0, 1.0], "only the current frontlit image changes"
    assert app.adjust_target_var.get() == "Frontlit image", "the sliders show the image that was adjusted"
    app.undo()
    assert brightness() == [1.0, 1.0, 1.0, 1.0]

    # Reference row towards the current row, backlit only.
    app.match_direction_var.set("Reference row, to look like current row")
    app.match_scope_var.set("Backlit only")
    app.match_to_other_row()
    wait_idle(app)
    after = brightness()
    assert after[2] == pytest.approx(1 / 0.6, abs=0.1)
    assert [after[0], after[1], after[3]] == [1.0, 1.0, 1.0], "only the reference backlit image changes"
    assert app.adjust_target_var.get() == "Reference backlit image"


def test_panels_show_how_each_photo_was_taken(app, tmp_path):
    from tests.test_camera import save_with_exif

    app.load_image_path(str(save_with_exif(tmp_path / "back.jpg", 8, (10, 1))), BACKLIT)
    wait_idle(app)
    app.load_image_path(str(save_with_exif(tmp_path / "front.jpg", 9, (1, 4))), FRONTLIT)
    wait_idle(app)

    def badge(idx, row=0):
        canvas = pane(app, row, idx).canvas
        return "".join(canvas.itemcget(item, "text") for item in canvas.find_withtag("hud")
                       if canvas.type(item) == "text")

    assert "f/8  |  10 s  |  ISO 2000  |  30 mm  |  ILCE-6400" in badge(BACKLIT)
    assert "f/9  |  1/4 s  |  ISO 2000  |  30 mm  |  ILCE-6400" in badge(FRONTLIT)
    app.mode_var.set("overlay")
    app._on_mode_change()
    wait_idle(app)
    assert "Backlit:  f/8" in badge(BACKLIT) and "Frontlit:  f/9" in badge(BACKLIT)


def test_settings_that_differ_between_rows_are_shown_in_red(app, tmp_path):
    from src import theme
    from tests.test_camera import save_with_exif

    app.load_image_path(str(save_with_exif(tmp_path / "back_new.jpg", 9, (10, 1))), BACKLIT)
    wait_idle(app)
    app.load_image_path(str(save_with_exif(tmp_path / "front_new.jpg", 9, (1, 4))), FRONTLIT)
    wait_idle(app)

    def red(row, idx):
        canvas = pane(app, row, idx).canvas
        return sorted(canvas.itemcget(item, "text") for item in canvas.find_withtag("hud")
                      if canvas.type(item) == "text" and canvas.itemcget(item, "fill") == theme.MISMATCH)

    assert red(0, BACKLIT) == [] and red(0, FRONTLIT) == [], "nothing to compare with yet"

    app.load_image_path(str(save_with_exif(tmp_path / "back_old.jpg", 8, (10, 1))), BACKLIT, 1)
    wait_idle(app)
    app.load_image_path(str(save_with_exif(tmp_path / "front_old.jpg", 8, (1, 5))), FRONTLIT, 1)
    wait_idle(app)
    # Backlit: only the aperture changed.  Frontlit: aperture and exposure time.
    assert red(0, BACKLIT) == ["f/9"] and red(1, BACKLIT) == ["f/8"]
    assert red(0, FRONTLIT) == ["1/4 s", "f/9"] and red(1, FRONTLIT) == ["1/5 s", "f/8"]

    app.show_reference_var.set(False)
    app._on_reference_toggle()
    wait_idle(app)
    assert red(0, BACKLIT) == [] and red(0, FRONTLIT) == []


def test_loading_settings_reports_the_camera_they_were_saved_with(app, tmp_path, monkeypatch):
    from tests.test_camera import save_with_exif

    app.load_image_path(str(save_with_exif(tmp_path / "front_a.jpg", 8, (1, 5))), FRONTLIT)
    wait_idle(app)
    app.adjust_target_var.set("Frontlit image")
    app._sync_controls()
    app.pairs[0].adjust[FRONTLIT]["brightness"] = 1.5
    preset = tmp_path / "frontlit_settings.json"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **k: str(preset))
    app.save_image_settings()
    saved = read_session(preset)
    assert saved["camera"]["f_number"] == 8.0 and saved["camera"]["exposure_time"] == 0.2
    assert saved["saved_from"] == "front_a.jpg"

    # Same camera settings: the user is told so.
    app.pairs[0].adjust[FRONTLIT]["brightness"] = 1.0
    app.load_image_settings(str(preset))
    wait_idle(app)
    message = app.confirmations[-1]
    assert "f/8  |  1/5 s  |  ISO 2000" in message
    assert "are the same" in message and "different" not in message
    assert app.pairs[0].adjust[FRONTLIT]["brightness"] == 1.5

    # A photo taken differently: the differences are listed, and declining changes nothing.
    app.new_session()
    app.load_image_path(str(save_with_exif(tmp_path / "front_b.jpg", 9, (1, 4))), FRONTLIT)
    wait_idle(app)
    app.adjust_target_var.set("Frontlit image")
    app._sync_controls()
    app.confirm_answers["ok"] = False
    app.load_image_settings(str(preset))
    wait_idle(app)
    message = app.confirmations[-1]
    assert "aperture f/8 then, f/9 now" in message
    assert "exposure time 1/5 s then, 1/4 s now" in message
    assert "almost the same" in message
    assert app.pairs[0].adjust[FRONTLIT]["brightness"] == 1.0, "declined: nothing applied"
    app.confirm_answers["ok"] = True
    app.load_image_settings(str(preset))
    wait_idle(app)
    assert app.pairs[0].adjust[FRONTLIT]["brightness"] == 1.5


def test_rows_can_be_swapped_when_loaded_the_wrong_way_round(app, tmp_path):
    back1, front1 = (1.0, (0, 0)), (0.3, (10, -6), 1.0)
    stage1 = make_stage(tmp_path / "1_incoming" / "em9", DOTS, back1, front1)
    load_stage(app, stage1)
    align_frontlit(app, 0, back1, front1)
    app.set_tool("annotate")
    click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *placed(DOTS[0], *back1)))
    app._write_session(str(stage1 / "session.json"))

    back2 = (-1.5, (30, 18))
    stage2 = make_stage(tmp_path / "2_shock" / "em9", DOTS, back2, (-1.5, (30, 18), 1.0))
    app.new_session()
    load_stage(app, stage2)
    app.pairs[0].adjust[BACKLIT]["brightness"] = 1.3
    app.open_reference_session(str(stage1 / "session.json"))
    wait_idle(app)
    app.set_tool("align_rows")
    for dot in (DOTS[0], DOTS[4], DOTS[3]):
        click(app, pane(app, 0, BACKLIT), *app.image_to_canvas(0, BACKLIT, *placed(dot, *back2)))
        click(app, pane(app, 1, BACKLIT), *app.image_to_canvas(1, BACKLIT, *placed(dot, *back1)))
    app.apply_tool_points()
    wait_idle(app)
    shift_before = dict(app.row_shift)
    app.dirty = False

    app.swap_rows()
    wait_idle(app)
    current, reference = app.pairs
    assert current.label == "1_incoming / em9" and reference.label == "2_shock / em9"
    assert current.paths[BACKLIT] == str(stage1 / "back.png")
    assert len(current.annotations) == 1 and reference.annotations == []
    assert reference.adjust[BACKLIT]["brightness"] == 1.3, "each row keeps its own settings"
    assert app.session_path == str(stage1 / "session.json")
    assert app.dirty and not app._undo_stack
    assert app.show_reference_var.get()
    # The rows are still registered to each other: every feature coincides on screen.
    for dot in DOTS:
        on_current = app.image_to_canvas(0, BACKLIT, *placed(dot, *back1))
        assert app.image_to_canvas(1, BACKLIT, *placed(dot, *back2)) == pytest.approx(on_current, abs=0.75)
        assert app.image_to_canvas(0, FRONTLIT, *placed(dot, *front1)) == pytest.approx(on_current, abs=1.0)

    app.dirty = False
    app.swap_rows()
    wait_idle(app)
    assert app.pairs[0].label == "2_shock / em9"
    assert app.row_shift == pytest.approx(shift_before, abs=1e-6)
    assert app.session_path is None, "the second inspection was never saved, so Save will ask for a name"


def test_swap_needs_a_reference_row(app, tmp_path):
    load_stage(app, make_stage(tmp_path / "s", DOTS))
    path_before = app.pairs[0].paths[BACKLIT]
    app.swap_rows()
    assert app.pairs[0].paths[BACKLIT] == path_before
