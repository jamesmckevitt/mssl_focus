"""Choosing an inspection's photographs from a folder of RAW files."""

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


def test_a_folder_without_a_backlit_photograph_is_refused():
    with pytest.raises(photos.PhotoError, match="backlit"):
        photos.choose([shot("DSC00001.ARW", "frontlit", 0.25, 138)])
