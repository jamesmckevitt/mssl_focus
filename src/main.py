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


def _install_error_reporting(root):
    """Tell the user when something goes wrong instead of failing silently.

    The packaged app has no console, so an unhandled error in a button or mouse
    handler would otherwise just look like the click did nothing.
    """
    import datetime
    import traceback

    from .config import config_dir

    log_path = config_dir() / "error.log"

    def report(exc_type, exc_value, exc_traceback):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n--- {datetime.datetime.now().isoformat(timespec='seconds')} ---\n{details}")
        except OSError:
            pass
        sys.stderr.write(details)
        messagebox.showerror(
            "MSSL FOCUS - Unexpected error",
            f"Something went wrong:\n\n{exc_type.__name__}: {exc_value}\n\n"
            "Your session is still open; save it under a new name if you are unsure.\n"
            f"Details were written to:\n{log_path}",
            parent=root,
        )

    root.report_callback_exception = report


def run_app():
    check_license(license_backend)
    root = tk.Tk()
    _install_error_reporting(root)
    ImageComparer(root)
    root.mainloop()
