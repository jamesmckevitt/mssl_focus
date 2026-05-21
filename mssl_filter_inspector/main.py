import tkinter as tk

from .app import ImageComparer


def run_app():
    root = tk.Tk()
    ImageComparer(root)
    root.mainloop()