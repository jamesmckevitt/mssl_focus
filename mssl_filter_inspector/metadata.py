from pathlib import Path
import sys


APP_AUTHOR = "James McKevitt"
APP_INSTITUTION = "UCL MSSL"
APP_EMAIL = "jm2@mssl.ucl.ac.uk"


def _read_app_version():
    """Read version from a bundled or workspace-local _version.txt file."""
    if getattr(sys, "frozen", False):
        candidates = [Path(sys._MEIPASS) / "_version.txt"]
    else:
        here = Path(__file__).resolve().parent
        candidates = [
            here / "_version.txt",
            here.parent / "_version.txt",
        ]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return "dev"


APP_VERSION = _read_app_version()
