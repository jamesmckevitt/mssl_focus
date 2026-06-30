import sys
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