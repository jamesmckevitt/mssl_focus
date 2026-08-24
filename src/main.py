import sys


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


_enable_windows_dpi_awareness()

import tkinter as tk
from tkinter import messagebox

try:
    from .license import check_license
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


def run_app():
    check_license()
    root = tk.Tk()
    ImageComparer(root)
    root.mainloop()
