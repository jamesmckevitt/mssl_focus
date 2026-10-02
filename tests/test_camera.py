import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from src.camera import (
    camera_differences,
    describe_camera,
    exposure_stops,
    format_exposure_time,
    read_camera_info,
)
from src.imaging import open_image


def save_with_exif(path, f_number, exposure, iso=2000, model="ILCE-6400"):
    """A small photo carrying the exposure settings a camera would record."""
    exif = Image.Exif()
    exif[0x0110] = model
    details = exif.get_ifd(0x8769)
    details[0x829A] = IFDRational(*exposure)
    details[0x829D] = IFDRational(f_number, 1)
    details[0x8827] = iso
    details[0x920A] = IFDRational(30, 1)
    Image.new("RGB", (64, 48), (90, 90, 90)).save(path, exif=exif)
    return path


@pytest.mark.parametrize("seconds, text", [
    (10.0, "10 s"), (2.5, "2.5 s"), (1.0, "1 s"), (0.2, "1/5 s"), (0.25, "1/4 s"),
    (1 / 3, "1/3 s"), (0.004, "1/250 s"), (0.7, "0.7 s"),
])
def test_exposure_times_read_like_a_camera_shows_them(seconds, text):
    assert format_exposure_time(seconds) == text


def test_settings_are_read_from_a_photo(tmp_path):
    info = read_camera_info(str(save_with_exif(tmp_path / "front.jpg", 9, (1, 4))))
    assert info == {"exposure_time": 0.25, "f_number": 9.0, "iso": 2000, "focal_length": 30.0,
                    "model": "ILCE-6400"}
    assert describe_camera(info) == "f/9  |  1/4 s  |  ISO 2000  |  30 mm  |  ILCE-6400"
    assert describe_camera(info, with_equipment=False) == "f/9  |  1/4 s  |  ISO 2000"


def test_files_without_settings_give_nothing(tmp_path):
    plain = tmp_path / "plain.png"
    Image.new("RGB", (8, 8)).save(plain)
    assert read_camera_info(str(plain)) == {}
    assert read_camera_info(str(tmp_path / "missing.tif")) == {}
    assert describe_camera({}) == ""


def test_open_image_carries_the_camera_settings(tmp_path):
    image = open_image(str(save_with_exif(tmp_path / "back.jpg", 8, (10, 1))))
    assert image.info["camera"]["exposure_time"] == 10.0
    assert image.info["camera"]["f_number"] == 8.0


def test_differences_between_two_photos_are_spelled_out():
    then = {"f_number": 8.0, "exposure_time": 0.2, "iso": 2000}
    now = {"f_number": 9.0, "exposure_time": 0.25, "iso": 2000}
    assert camera_differences(then, now) == ["aperture f/8 then, f/9 now",
                                             "exposure time 1/5 s then, 1/4 s now"]
    assert camera_differences(then, dict(then)) == []
    assert camera_differences(then, {}) == []
    # f/9 at 1/4 s against f/8 at 1/5 s: almost exactly the same amount of light.
    assert exposure_stops(then, now) == pytest.approx(-0.018, abs=0.01)
    assert exposure_stops(then, {"f_number": 8.0, "exposure_time": 0.4, "iso": 2000}) == pytest.approx(1.0)
    assert exposure_stops(then, {}) is None
