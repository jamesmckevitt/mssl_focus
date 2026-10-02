"""Colours, fonts and ttk styling for the dark interface."""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

BG = "#1b1c1f"           # window background
PANEL = "#25272b"        # toolbars, sidebar
PANEL_ALT = "#2d3035"    # section headers, inputs
FIELD = "#1f2124"        # entry backgrounds
BORDER = "#3b3f46"
TEXT = "#e8e8ea"
MUTED = "#9aa0a8"
ACCENT = "#4c9aff"
ACCENT_DARK = "#2f6fd0"
SUCCESS = "#3fb46b"
DANGER = "#e5534b"
HINT_BG = "#1d2b44"
HINT_TEXT = "#d6e4ff"
CANVAS_BG = "#181818"

BACKLIT = "#ffcc33"
FRONTLIT = "#4fd0ff"
ALIGN_POINT = "#7dffb0"
ROW_POINT = "#ff8cf0"
CURSOR = "#ff4d4d"
MISMATCH = "#ff6b6b"     # a setting that differs between the two rows


def ui_scale(widget):
    """Screen pixels per 96-dpi pixel, so fixed sizes look right on HiDPI displays."""
    try:
        return max(1.0, widget.winfo_fpixels("1i") / 96.0)
    except tk.TclError:
        return 1.0


def apply_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    scale = ui_scale(root)

    def px(value):
        return int(round(value * scale))

    base = tkfont.nametofont("TkDefaultFont", root=root)
    family = base.actual("family")
    size = base.actual("size")
    fonts = {
        "base": (family, size),
        "small": (family, max(7, size - 1)),
        "bold": (family, size, "bold"),
        "title": (family, size + 2, "bold"),
        "heading": (family, size + 6, "bold"),
    }

    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    style.configure(".", background=PANEL, foreground=TEXT, bordercolor=BORDER,
                    darkcolor=PANEL, lightcolor=PANEL, troughcolor=FIELD,
                    focuscolor=ACCENT, font=fonts["base"])

    style.configure("TFrame", background=PANEL)
    style.configure("Window.TFrame", background=BG)
    style.configure("Hint.TFrame", background=HINT_BG)
    style.configure("Header.TFrame", background=PANEL_ALT)

    style.configure("TLabel", background=PANEL, foreground=TEXT)
    style.map("TLabel", foreground=[("disabled", "#666b73")], background=[("disabled", PANEL)])
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=fonts["small"])
    style.configure("Value.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Status.TLabel", background=BG, foreground=MUTED, font=fonts["small"])
    style.configure("StatusMsg.TLabel", background=BG, foreground=TEXT, font=fonts["small"])
    style.configure("Hint.TLabel", background=HINT_BG, foreground=HINT_TEXT)
    style.configure("HintTitle.TLabel", background=HINT_BG, foreground="#ffffff", font=fonts["bold"])
    style.configure("Group.TLabel", background=PANEL, foreground=MUTED, font=fonts["small"])
    style.configure("Backlit.TLabel", background=PANEL, foreground=BACKLIT, font=fonts["bold"])
    style.configure("Frontlit.TLabel", background=PANEL, foreground=FRONTLIT, font=fonts["bold"])

    button_pad = (px(10), px(4))
    style.configure("TButton", background=PANEL_ALT, foreground=TEXT, bordercolor=BORDER,
                    lightcolor=PANEL_ALT, darkcolor=PANEL_ALT, padding=button_pad, relief="flat")
    style.map("TButton",
              background=[("disabled", PANEL), ("pressed", ACCENT_DARK), ("active", "#3a3e45")],
              foreground=[("disabled", "#666b73")],
              bordercolor=[("focus", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT_DARK, foreground="#ffffff",
                    lightcolor=ACCENT_DARK, darkcolor=ACCENT_DARK, bordercolor=ACCENT_DARK)
    style.map("Accent.TButton",
              background=[("disabled", "#2b3340"), ("pressed", "#255aa8"), ("active", ACCENT)],
              foreground=[("disabled", "#7c8696")])
    style.configure("Danger.TButton", foreground="#ffb4ae")
    style.configure("Small.TButton", padding=(px(6), px(2)), font=fonts["small"])
    style.configure("Section.TButton", background=PANEL_ALT, foreground=TEXT, anchor="w",
                    padding=(px(10), px(6)), font=fonts["bold"], bordercolor=PANEL_ALT,
                    lightcolor=PANEL_ALT, darkcolor=PANEL_ALT)
    style.map("Section.TButton", background=[("active", "#383c43")])

    # Toggle buttons in the toolbar (tools, view mode).
    style.configure("Tool.Toolbutton", background=PANEL, foreground=TEXT, padding=(px(11), px(6)),
                    bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, relief="flat")
    style.map("Tool.Toolbutton",
              background=[("selected", ACCENT_DARK), ("active", "#3a3e45")],
              foreground=[("selected", "#ffffff"), ("disabled", "#666b73")],
              bordercolor=[("selected", ACCENT)],
              lightcolor=[("selected", ACCENT_DARK)], darkcolor=[("selected", ACCENT_DARK)])

    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=PANEL, foreground=TEXT, indicatorbackground=FIELD,
                        indicatorforeground="#ffffff", upperbordercolor=BORDER, lowerbordercolor=BORDER,
                        padding=(px(2), px(2)))
        style.map(name,
                  background=[("active", PANEL)],
                  indicatorbackground=[("selected", ACCENT_DARK), ("pressed", ACCENT_DARK)],
                  foreground=[("disabled", "#666b73")])
    style.configure("Hint.TCheckbutton", background=HINT_BG, foreground=HINT_TEXT)
    style.map("Hint.TCheckbutton", background=[("active", HINT_BG)])

    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD,
                        arrowcolor=TEXT, background=PANEL_ALT, padding=px(3),
                        selectbackground=ACCENT_DARK, selectforeground="#ffffff")
        style.map(name,
                  fieldbackground=[("readonly", FIELD), ("disabled", PANEL)],
                  foreground=[("disabled", "#666b73")],
                  bordercolor=[("focus", ACCENT)])

    style.configure("Horizontal.TScale", background=PANEL, troughcolor=FIELD,
                    bordercolor=BORDER, lightcolor=ACCENT_DARK, darkcolor=ACCENT_DARK)
    style.configure("TScrollbar", background=PANEL_ALT, troughcolor=PANEL, bordercolor=PANEL,
                    arrowcolor=MUTED, lightcolor=PANEL_ALT, darkcolor=PANEL_ALT)
    style.map("TScrollbar", background=[("active", "#4a4f57")])
    style.configure("TProgressbar", background=ACCENT, troughcolor=FIELD, bordercolor=BORDER,
                    lightcolor=ACCENT, darkcolor=ACCENT)
    style.configure("TSeparator", background=BORDER)

    return fonts, scale


class Tooltip:
    """Delayed hover text for a widget."""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._job = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._job = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job = None

    def _show(self):
        self._job = None
        if self._tip is not None or not self.text:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        scale = ui_scale(self.widget)
        label = tk.Label(tip, text=self.text, bg="#101114", fg=TEXT, justify=tk.LEFT,
                         relief=tk.SOLID, bd=1, padx=int(8 * scale), pady=int(5 * scale),
                         wraplength=int(320 * scale))
        label.pack()
        x = self.widget.winfo_rootx() + int(8 * scale)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + int(6 * scale)
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
