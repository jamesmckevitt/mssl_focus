import json

from src.pair import ImagePair
from src.session import (
    describe_location,
    fill_pair_from_session,
    read_session,
    resolve_image_path,
    session_has_reference,
    session_image_paths,
    write_session,
)


def v1_session(image_dir):
    """A session exactly as v1.0.4 wrote it: absolute paths and blank compare_* defaults."""
    return {
        "version": 1,
        "image_paths": [f"{image_dir}/back.TIF", f"{image_dir}/front.TIF"],
        "mode": "sidebyside",
        "opacity": 0.5,
        "zoom": 0.33,
        "pan_x": -100.0,
        "pan_y": -50.0,
        "alignment": {"off_x": "118", "off_y": "13", "rot": "-0.38", "img2_scale": "0.996",
                      "glob_rot": "0.96"},
        "annotations": [
            {"img1_x": 1706.5, "img1_y": 1150.0, "radius": 20.08, "colour": "#00cc44", "label": "I1"},
            {"img1_x": 2184.2, "img1_y": 1983.5, "radius": 20.2, "colour": "#ff0000", "label": "S1"},
        ],
        "colour_labels": {"#00cc44": "Incoming Pinholes", "#ff0000": "Shock Test"},
        "align_pts_img1": [],
        "align_pts_img2": [],
        "adjustments": [{"brightness": 1.4, "contrast": 1.0, "blacks": 5.0, "whites": 240.0},
                        {"brightness": 1.0, "contrast": 1.0, "blacks": 0.0, "whites": 255.0}],
        "noise_reduction": [{"amount": 30, "aggressive": False, "color": 50, "edge": 100},
                            {"amount": 0, "aggressive": False, "color": 50, "edge": 100}],
        "compare_row_enabled": False,
        "compare_image_paths": [None, None],
        "compare_alignment": {"off_x": "0", "off_y": "0", "rot": "0.0", "img2_scale": "1.000",
                              "glob_rot": "0.0"},
        "compare_row_transform": {"off_x": "0", "off_y": "0", "rot": "0.0", "scale": "1.000"},
        "compare_adjustments": [{"brightness": 1.0, "contrast": 1.0, "blacks": 0.0, "whites": 255.0}] * 2,
        "compare_noise_reduction": [{"amount": 0, "aggressive": False, "color": 50, "edge": 100}] * 2,
    }


def test_images_are_found_beside_the_session_after_a_folder_rename(tmp_path):
    """The real case: sessions saved under 'Pinhole testing #3 em2 em4/em2' now
    live in '3_shock_test/em2' and every stored absolute path is dead."""
    stage = tmp_path / "3_shock_test" / "em2"
    stage.mkdir(parents=True)
    (stage / "back.TIF").write_bytes(b"x")
    (stage / "front.TIF").write_bytes(b"x")
    session = v1_session("C:/old/Pinhole testing #3 em2 em4/em2")
    session_file = stage / "session.json"
    resolved, saved = session_image_paths(session, session_file)
    assert resolved == [str(stage / "back.TIF"), str(stage / "front.TIF")]
    assert saved[0].endswith("em2/back.TIF")


def test_images_are_found_when_the_saved_path_lacked_the_subfolder(tmp_path):
    stage = tmp_path / "5_thermal_test" / "em2"
    stage.mkdir(parents=True)
    (stage / "back.TIF").write_bytes(b"x")
    assert resolve_image_path("C:/somewhere/5_thermal_test/back.TIF", None, stage) == str(stage / "back.TIF")


def test_relative_path_wins_and_survives_moving_the_whole_tree(tmp_path):
    old = tmp_path / "old" / "stage" / "em2"
    new = tmp_path / "new" / "stage" / "em2"
    for folder in (old, new):
        (folder / "raw").mkdir(parents=True)
        (folder / "raw" / "DSC0001.ARW").write_bytes(b"x")
    found = resolve_image_path(str(old / "raw" / "DSC0001.ARW"), "raw/DSC0001.ARW", new)
    assert found == str(new / "raw" / "DSC0001.ARW")


def test_missing_image_resolves_to_none(tmp_path):
    assert resolve_image_path("C:/gone/back.TIF", None, tmp_path) is None
    assert resolve_image_path(None, None, tmp_path) is None


def test_blank_compare_fields_do_not_count_as_a_reference_row():
    session = v1_session("C:/x")
    assert not session_has_reference(session)
    session["compare_image_paths"] = ["C:/x/ref_back.TIF", None]
    assert session_has_reference(session)


def test_loading_as_reference_uses_the_sessions_own_pair():
    """v1.0.4 took the blank compare_* defaults here, giving empty paths,
    zero alignment and default tone settings."""
    session = v1_session("C:/x")
    pair = ImagePair()
    fill_pair_from_session(pair, session)
    assert (pair.off_x, pair.off_y, pair.rot, pair.scale, pair.glob_rot) == (118.0, 13.0, -0.38, 0.996, 0.96)
    assert pair.adjust[0]["brightness"] == 1.4
    assert pair.nr[0]["amount"] == 30
    assert [a["label"] for a in pair.annotations] == ["I1", "S1"]
    assert pair.colour_labels["#ff0000"] == "Shock Test"


def test_reference_records_are_read_from_the_compare_fields():
    session = v1_session("C:/x")
    session["compare_alignment"]["glob_rot"] = "2.5"
    session["compare_adjustments"] = [{"brightness": 2.0}, {}]
    pair = ImagePair()
    fill_pair_from_session(pair, session, reference=True)
    assert pair.glob_rot == 2.5
    assert pair.adjust[0] == {"brightness": 2.0, "contrast": 1.0, "blacks": 0.0, "whites": 255.0}
    assert pair.annotations == []


def test_malformed_numbers_fall_back_to_defaults():
    pair = ImagePair()
    pair.apply_alignment_record({"off_x": "abc", "img2_scale": None, "rot": "1.5"})
    assert (pair.off_x, pair.scale, pair.rot) == (0.0, 1.0, 1.5)


def test_write_session_is_atomic_and_round_trips(tmp_path):
    path = tmp_path / "session.json"
    write_session(path, {"version": 2, "zoom": 1.5})
    assert read_session(path) == {"version": 2, "zoom": 1.5}
    assert not (tmp_path / "session.json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8"))["zoom"] == 1.5


def test_describe_location(tmp_path):
    stage = tmp_path / "5_thermal_test" / "em2"
    stage.mkdir(parents=True)
    assert describe_location(stage / "session.json") == "5_thermal_test / em2"
    assert describe_location(None) == ""
