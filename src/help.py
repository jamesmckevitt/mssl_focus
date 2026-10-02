"""In-app guidance: the step-by-step guide, shortcut list and About box."""

import tkinter as tk
from tkinter import ttk

from . import theme
from .metadata import APP_AUTHOR, APP_EMAIL, APP_INSTITUTION, APP_VERSION

# (heading, paragraphs).  A paragraph starting with "- " is shown as a bullet.
GUIDE = [
    ("1.  Load the two images of a filter", [
        "Each inspection uses two photographs of the same filter: a backlit image (light shining "
        "through, so pinholes show as bright points) and a frontlit image (surface detail).",
        "- Click the empty Backlit panel and choose the backlit file, then do the same for Frontlit.",
        "- TIFF, PNG, JPEG and camera RAW files (ARW, NEF, CR2, DNG, ...) all work.",
        "- Drag to pan and scroll to zoom.  All panels move together and the red crosshair marks "
        "the same spot in each.  Press F to fit the image to the window.",
    ]),
    ("2.  Make the filter upright (Level)", [
        "If the filter is slightly rotated in the photographs, straighten it first so every "
        "inspection is viewed the same way up.",
        "- Choose Level (L).",
        "- Find an edge that should be vertical, such as a mesh bar or the edge of the frame, and "
        "drag along it.  A longer line gives a more accurate result.",
        "- Both images rotate together so that the line becomes vertical.",
        "- Fine-tune with Ctrl+Left / Ctrl+Right, or type a value under Alignment > Both images.",
    ]),
    ("3.  Align the frontlit image to the backlit image", [
        "The two photographs are rarely pixel-for-pixel identical.  Aligning them makes a marker "
        "sit on the same feature in both.",
        "- Choose Align (G).",
        "- Click a small, sharp feature on the backlit image, then the same feature on the "
        "frontlit image.  Numbered points appear.",
        "- Repeat for at least two features, as far apart as possible.  Three or more gives a "
        "better fit and reports the residual error.",
        "- Press Apply (or Enter).  Right-click removes the last point; Esc clears them all.",
        "- Tick 'Allow scale change' only if the images were taken at different magnifications.",
        "- Check the result in Overlay view (O): slide Frontlit mix back and forth and look for "
        "features that jump.  Arrow keys nudge by one pixel while the Align tool is active.",
    ]),
    ("4.  Mark what you find (Annotate)", [
        "- Choose Annotate (A) and pick a colour in the Annotations panel.  Use one colour per "
        "category, for example incoming pinholes, repairs, or damage found after a test.",
        "- The first time a colour is used you are asked for its legend name and a label prefix; "
        "markers are then numbered automatically (T1, T2, ...).",
        "- Click a feature to mark it.  Dragging still pans, so you do not need to switch tools.",
        "- Right-click a marker to delete it, edit its label or change its colour.  Use Move (M) "
        "to drag a marker.  Ctrl+Z undoes any change.",
    ]),
    ("5.  Save the session", [
        "- Ctrl+S saves everything except the image data itself: which images, the alignment, "
        "markers, legend and display settings.",
        "- Keep the session file in the same folder as its images.  The session then still opens "
        "after the folder is moved, renamed or synced to another computer.",
        "- A star in the title bar means there are unsaved changes.",
    ]),
    ("6.  Compare with an earlier inspection", [
        "To see what a test did to a filter, show the earlier inspection underneath the new one.",
        "- Open the newer session (or load its images) as usual.",
        "- File > Load reference session, and choose the earlier inspection's session file.  It "
        "appears as the reference row, with its own alignment and markers (dashed circles).",
        "- Choose Align rows (R).  Click a feature of the filter in the top row, then the same "
        "feature in the bottom row; repeat for two or more features and press Apply.",
        "- The crosshair now marks the same place on the filter in all four panels.",
        "- Edit > Copy markers from reference row brings the earlier markers into the current "
        "inspection, so you only need to add what is new.",
    ]),
    ("7.  Export a figure", [
        "- Choose Crop export (C) and drag a rectangle around the region of interest, or use "
        "File > Export current view.",
        "- A preview opens where you can adjust label, legend and line sizes, and choose whether "
        "to include the reference row.",
        "- The image is saved at the full resolution of the backlit image, with markers, a legend "
        "with counts, and a date stamp.",
    ]),
]

SHORTCUTS = [
    ("Mouse", [
        ("Drag", "Pan (in Pan, Annotate and the Align tools)"),
        ("Middle-button drag", "Pan in any tool"),
        ("Scroll wheel", "Zoom about the pointer"),
        ("Click an empty panel", "Load an image into it"),
        ("Right-click a marker", "Delete, relabel or recolour it"),
        ("Right-click while aligning", "Remove the last point"),
    ]),
    ("Tools", [
        ("V", "Pan"),
        ("A", "Annotate"),
        ("M", "Move markers"),
        ("L", "Level (make upright)"),
        ("G", "Align frontlit to backlit"),
        ("R", "Align reference row to current row"),
        ("C", "Crop export"),
        ("Esc", "Clear points, or return to Pan"),
        ("Enter", "Apply the alignment points"),
    ]),
    ("View", [
        ("F", "Fit to window"),
        ("1", "Actual size (100%)"),
        ("+  /  -", "Zoom in / out"),
        ("O", "Switch between Side by side and Overlay"),
    ]),
    ("Fine adjustment", [
        ("Arrow keys", "Nudge the frontlit image 1 px (Align tool)"),
        ("Shift + Left / Right", "Rotate the frontlit image 0.1 deg (Align tool)"),
        ("Ctrl + Left / Right", "Rotate both images 0.1 deg (Align or Level tool)"),
    ]),
    ("Session", [
        ("Ctrl+N", "New session"),
        ("Ctrl+O", "Open session"),
        ("Ctrl+S", "Save session"),
        ("Ctrl+Shift+S", "Save session as"),
        ("Ctrl+Z  /  Ctrl+Y", "Undo / redo"),
        ("F1", "Step-by-step guide"),
    ]),
]


def _text_window(app, title, width, height):
    window = tk.Toplevel(app.root)
    window.title(title)
    window.configure(bg=theme.PANEL)
    window.transient(app.root)
    window.geometry(f"{app.px(width)}x{app.px(height)}")

    footer = ttk.Frame(window)
    footer.pack(side=tk.BOTTOM, fill=tk.X, padx=app.px(14), pady=app.px(10))
    ttk.Button(footer, text="Close", command=window.destroy).pack(side=tk.RIGHT)

    scroll = ttk.Scrollbar(window, orient=tk.VERTICAL)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    text = tk.Text(window, wrap=tk.WORD, bg=theme.PANEL, fg=theme.TEXT, relief=tk.FLAT, bd=0,
                   padx=app.px(22), pady=app.px(16), font=app.fonts["base"], cursor="arrow",
                   yscrollcommand=scroll.set, spacing1=app.px(2), spacing3=app.px(4),
                   highlightthickness=0)
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.config(command=text.yview)
    text.tag_configure("title", font=app.fonts["heading"], foreground="#ffffff", spacing3=app.px(6))
    text.tag_configure("heading", font=app.fonts["title"], foreground=theme.ACCENT,
                       spacing1=app.px(16), spacing3=app.px(6))
    text.tag_configure("muted", foreground=theme.MUTED)
    text.tag_configure("bullet", lmargin1=app.px(14), lmargin2=app.px(28))
    text.tag_configure("key", font=app.fonts["bold"], foreground="#ffffff")
    window.bind("<Escape>", lambda _e: window.destroy())
    return window, text, footer


def show_guide(app):
    existing = getattr(app, "_guide_window", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.focus_set()
        return
    window, text, footer = _text_window(app, "MSSL FOCUS - Step-by-step guide", 720, 760)
    app._guide_window = window

    text.insert(tk.END, "Inspecting a filter, step by step\n", "title")
    text.insert(tk.END, "The blue bar under the toolbar always tells you what the selected tool "
                        "expects next.  This guide stays open while you work.\n", "muted")
    for heading, paragraphs in GUIDE:
        text.insert(tk.END, heading + "\n", "heading")
        for paragraph in paragraphs:
            if paragraph.startswith("- "):
                text.insert(tk.END, "•  " + paragraph[2:] + "\n", "bullet")
            else:
                text.insert(tk.END, paragraph + "\n")
    text.configure(state=tk.DISABLED)

    show_var = tk.BooleanVar(value=bool(app.config.get("show_guide_at_start", True)))
    ttk.Checkbutton(footer, text="Show this guide when MSSL FOCUS starts", variable=show_var,
                    command=lambda: app.config.set("show_guide_at_start", bool(show_var.get()))).pack(
        side=tk.LEFT)
    ttk.Button(footer, text="Shortcuts...", command=lambda: show_shortcuts(app)).pack(
        side=tk.RIGHT, padx=(0, app.px(8)))
    app._centre_dialog(window)


def show_shortcuts(app):
    window, text, _footer = _text_window(app, "MSSL FOCUS - Shortcuts", 560, 700)
    text.configure(tabs=(app.px(210),))
    text.insert(tk.END, "Keyboard and mouse shortcuts\n", "title")
    for heading, rows in SHORTCUTS:
        text.insert(tk.END, heading + "\n", "heading")
        for keys, action in rows:
            text.insert(tk.END, keys, "key")
            text.insert(tk.END, "\t" + action + "\n")
    text.configure(state=tk.DISABLED)
    app._centre_dialog(window)


def show_about(app):
    window, text, _footer = _text_window(app, "About MSSL FOCUS", 520, 330)
    text.insert(tk.END, "MSSL FOCUS\n", "title")
    text.insert(tk.END, "Filter Optical Characterisation Utility Software\n")
    text.insert(tk.END, f"Version {APP_VERSION}\n\n", "muted")
    text.insert(tk.END, f"{APP_AUTHOR}, {APP_INSTITUTION}\n{APP_EMAIL}\n\n")
    text.insert(tk.END, "Copyright (c) 2026 James McKevitt, UCL Mullard Space Science Laboratory.  "
                        "All rights reserved.\n", "muted")
    text.configure(state=tk.DISABLED)
    app._centre_dialog(window)
