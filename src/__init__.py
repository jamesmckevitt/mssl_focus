"""MSSL FOCUS.

The detection, alignment, history and licence modules are private. A release build has them
compiled in. Running from source, they are found in `src` of a private checkout named by the
`MSSL_FOCUS_PRIVATE` environment variable, or in `mssl_focus_private` beside this repository.
"""

import os as _os
import sys as _sys
from pathlib import Path as _Path

if not getattr(_sys, "frozen", False):
    _private = _Path(_os.environ.get("MSSL_FOCUS_PRIVATE")
                     or _Path(__file__).resolve().parents[2] / "mssl_focus_private")
    if (_private / "src").is_dir():
        __path__.append(str(_private / "src"))

from .metadata import APP_AUTHOR, APP_EMAIL, APP_INSTITUTION, APP_VERSION  # noqa: E402


def __getattr__(name):
    # Imported on demand, since the application modules need Tk and `main` needs
    # the private licence module, and the pure helpers need neither.
    if name == "ImageComparer":
        from .app import ImageComparer
        return ImageComparer
    if name == "run_app":
        from .main import run_app
        return run_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "APP_AUTHOR",
    "APP_EMAIL",
    "APP_INSTITUTION",
    "APP_VERSION",
    "ImageComparer",
    "run_app",
]
