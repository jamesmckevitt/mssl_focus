"""Choosing an inspection's photographs from a folder of RAW files."""

from pathlib import Path

import pytest

from src import photos


def shot(name, kind, exposure, brightness):
    return {"path": name, "kind": kind, "exposure": exposure, "brightness": brightness,
            "sequence": photos._sequence(name)}


def test_the_longest_backlit_exposure_and_the_standard_frontlit_are_chosen():
    shots = [shot("DSC00076.ARW", "frontlit", 2.0, 234), shot("DSC00078.ARW", "frontlit", 0.2, 168),
             shot("DSC00079.ARW", "frontlit", 0.05, 139), shot("DSC00083.ARW", "backlit", 2.0, 1.2),
             shot("DSC00084.ARW", "backlit", 5.0, 2.0), shot("DSC00085.ARW", "backlit", 10.0, 4.0)]
    back, front = photos.choose(shots)
    assert back["path"] == "DSC00085.ARW" and front["path"] == "DSC00078.ARW"


def test_a_repeated_series_uses_the_latest_set_up():
    # As on EM3: the filter was photographed twice, and only the second series matches.
    shots = [shot("DSC00055.ARW", "frontlit", 0.2, 178), shot("DSC00058.ARW", "backlit", 10.0, 5.6),
             shot("DSC00065.ARW", "frontlit", 0.2, 168), shot("DSC00068.ARW", "frontlit", 0.2, 168),
             shot("DSC00075.ARW", "backlit", 10.0, 4.9)]
    back, front = photos.choose(shots)
    assert back["path"] == "DSC00075.ARW"
    assert front["path"] == "DSC00068.ARW", "the frontlit photograph nearest the backlit one"


def test_a_dim_frontlit_lighting_is_passed_over():
    shots = [shot("DSC00001.ARW", "frontlit", 0.25, 138), shot("DSC00005.ARW", "frontlit", 3.2, 159),
             shot("DSC00007.ARW", "frontlit", 0.25, 76), shot("DSC00008.ARW", "backlit", 10.0, 3.0)]
    _back, front = photos.choose(shots)
    assert front["path"] == "DSC00001.ARW"


def test_an_unreadable_raw_file_is_listed_and_left_out(tmp_path, monkeypatch):
    for name in ("DSC00001.ARW", "DSC00002.ARW", "DSC00003.ARW"):
        (tmp_path / name).write_bytes(b"not really a raw file")
    readings = {"DSC00001.ARW": (0.25, 150.0), "DSC00003.ARW": (10.0, 3.0)}

    def camera(path):
        return {"exposure_time": readings.get(Path(path).name, (None, None))[0]}

    def brightness(path):
        if Path(path).name not in readings:
            import rawpy
            raise rawpy.LibRawFileUnsupportedError(b"Unsupported file format or not RAW file")
        return readings[Path(path).name][1]

    monkeypatch.setattr(photos, "read_camera_info", camera)
    monkeypatch.setattr(photos, "_preview_brightness", brightness)
    back, front, shots = photos.choose_in(tmp_path)
    assert Path(back).name == "DSC00003.ARW" and Path(front).name == "DSC00001.ARW"
    assert [s["kind"] for s in shots] == ["frontlit", "unreadable", "backlit"]
    assert any("DSC00002.ARW" in line and "could not be read" in line for line in photos.describe(shots, back, front))


def test_a_folder_without_a_backlit_photograph_is_refused():
    with pytest.raises(photos.PhotoError, match="backlit"):
        photos.choose([shot("DSC00001.ARW", "frontlit", 0.25, 138)])
