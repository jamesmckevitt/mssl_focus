import sys

_WINDOWS_APP_USER_MODEL_ID = "UCL.MSSL.MSSLFocus"


def _enable_windows_dpi_awareness():
    """Opt in to native-resolution rendering before creating any Tk windows."""
    if sys.platform != "win32":
        return

    import ctypes

    try:
        # Windows 10 1703+: sharp rendering when a window changes monitors too.
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass

    try:
        # Windows 8.1 fallback.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass

    try:
        # Windows Vista/7 fallback.
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _set_windows_app_user_model_id():
    """Give Windows a stable identity for taskbar grouping and icon lookup."""
    if sys.platform != "win32":
        return

    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        pass


_enable_windows_dpi_awareness()
_set_windows_app_user_model_id()

import tkinter as tk
from tkinter import messagebox

try:
    from . import license as license_backend
except ImportError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "MSSL FOCUS - Missing Module",
        "A required licensing module is missing.\n\n"
        "This copy of the software is incomplete and cannot run.\n"
        "Please download the official release from:\n"
        "https://github.com/jamesmckevitt/mssl_focus/releases"
    )
    root.destroy()
    sys.exit(1)

from .app import ImageComparer
from .license_flow import check_license


def run_app():
    check_license(license_backend)
    root = tk.Tk()
    ImageComparer(root)
    root.mainloop()
