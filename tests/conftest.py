"""Test setup: render windows at native resolution, as the real app does."""
import sys

if sys.platform == "win32":
    import ctypes

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
