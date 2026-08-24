import tkinter as tk
from tkinter import filedialog

from .window_icon import set_app_icon


_BACKGROUND = "#2b2b2b"
_FOREGROUND = "#eeeeee"
_SECONDARY_TEXT = "#c7c7c7"


def _new_window(title, minimum_size):
    window = tk.Tk()
    window.title(title)
    window.configure(bg=_BACKGROUND)
    window.minsize(*minimum_size)
    window.resizable(False, False)
    set_app_icon(window)
    return window


def _centre_window(window):
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = max(0, (window.winfo_screenwidth() - width) // 2)
    y = max(0, (window.winfo_screenheight() - height) // 2)
    window.geometry(f"+{x}+{y}")


def ask_license_method():
    """Ask whether to use a licence file or the master password."""
    window = _new_window("MSSL FOCUS - License Required", (520, 270))
    result = {"value": None}

    def finish(value):
        result["value"] = value
        window.destroy()

    tk.Label(
        window,
        text="Welcome to MSSL FOCUS",
        bg=_BACKGROUND,
        fg=_FOREGROUND,
        font=("TkDefaultFont", 14, "bold"),
        pady=18,
    ).pack(fill=tk.X)
    tk.Label(
        window,
        text=(
            "Do you have a license file (license.dat)?\n\n"
            "Choose Yes to locate your license file, or No to enter "
            "a master password."
        ),
        bg=_BACKGROUND,
        fg=_SECONDARY_TEXT,
        font=("TkDefaultFont", 10),
        justify=tk.CENTER,
        wraplength=460,
        padx=24,
    ).pack(fill=tk.BOTH, expand=True)

    button_row = tk.Frame(window, bg=_BACKGROUND, pady=18)
    button_row.pack()
    tk.Button(
        button_row,
        text="Yes",
        command=lambda: finish("yes"),
        bg="#2a5a3a",
        fg="white",
        activebackground="#36734a",
        activeforeground="white",
        width=12,
        padx=8,
        pady=5,
    ).pack(side=tk.LEFT, padx=8)
    tk.Button(
        button_row,
        text="No",
        command=lambda: finish("no"),
        bg="#555555",
        fg="white",
        activebackground="#686868",
        activeforeground="white",
        width=12,
        padx=8,
        pady=5,
    ).pack(side=tk.LEFT, padx=8)

    window.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    window.bind("<Escape>", lambda _event: finish(None))
    _centre_window(window)
    window.mainloop()
    return result["value"]


def ask_license_file():
    """Open the file picker with a visible, icon-bearing owner window."""
    window = _new_window("MSSL FOCUS - Select License", (500, 170))
    tk.Label(
        window,
        text="Select your license.dat file",
        bg=_BACKGROUND,
        fg=_FOREGROUND,
        font=("TkDefaultFont", 12, "bold"),
        pady=28,
    ).pack(fill=tk.X)
    tk.Label(
        window,
        text="The Windows file picker should open in front of this window.",
        bg=_BACKGROUND,
        fg=_SECONDARY_TEXT,
        font=("TkDefaultFont", 9),
    ).pack(fill=tk.X)
    _centre_window(window)
    window.update()
    try:
        return filedialog.askopenfilename(
            parent=window,
            title="Select your license.dat file",
            filetypes=[("License files", "*.dat"), ("All files", "*.*")],
        )
    finally:
        window.destroy()


def ask_password(text):
    """Prompt for the master password in a correctly sized application window."""
    window = _new_window("MSSL FOCUS - License", (500, 210))
    result = {"value": None}
    password = tk.StringVar(window)

    def submit():
        result["value"] = password.get()
        window.destroy()

    def cancel():
        window.destroy()

    tk.Label(
        window,
        text=text,
        bg=_BACKGROUND,
        fg=_FOREGROUND,
        font=("TkDefaultFont", 11, "bold"),
        pady=24,
    ).pack(fill=tk.X)
    entry = tk.Entry(
        window,
        textvariable=password,
        show="*",
        width=42,
        font=("TkDefaultFont", 11),
    )
    entry.pack(padx=28, pady=(0, 18), fill=tk.X)

    button_row = tk.Frame(window, bg=_BACKGROUND)
    button_row.pack(pady=(0, 20))
    tk.Button(
        button_row,
        text="OK",
        command=submit,
        bg="#2a5a3a",
        fg="white",
        activebackground="#36734a",
        activeforeground="white",
        width=10,
        pady=4,
    ).pack(side=tk.LEFT, padx=6)
    tk.Button(
        button_row,
        text="Cancel",
        command=cancel,
        bg="#555555",
        fg="white",
        activebackground="#686868",
        activeforeground="white",
        width=10,
        pady=4,
    ).pack(side=tk.LEFT, padx=6)

    window.protocol("WM_DELETE_WINDOW", cancel)
    window.bind("<Return>", lambda _event: submit())
    window.bind("<Escape>", lambda _event: cancel())
    _centre_window(window)
    entry.focus_set()
    window.mainloop()
    return result["value"]


def show_license_error(message):
    """Display a modal-looking error with the application icon and taskbar entry."""
    window = _new_window("MSSL FOCUS - License Error", (520, 210))

    tk.Label(
        window,
        text=message,
        bg=_BACKGROUND,
        fg=_FOREGROUND,
        font=("TkDefaultFont", 10),
        justify=tk.LEFT,
        wraplength=460,
        padx=28,
        pady=26,
    ).pack(fill=tk.BOTH, expand=True)
    tk.Button(
        window,
        text="OK",
        command=window.destroy,
        bg="#555555",
        fg="white",
        activebackground="#686868",
        activeforeground="white",
        width=10,
        pady=4,
    ).pack(pady=(0, 22))

    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.bind("<Return>", lambda _event: window.destroy())
    window.bind("<Escape>", lambda _event: window.destroy())
    _centre_window(window)
    window.mainloop()


__all__ = [
    "ask_license_file",
    "ask_license_method",
    "ask_password",
    "show_license_error",
]
