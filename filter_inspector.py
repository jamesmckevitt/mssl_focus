"""
Engineering Image Comparer
--------------------------
- Side-by-side view with synchronized crosshair cursor
- Overlay mode with opacity slider
- Translate and rotate image 2 relative to image 1
- Synchronized zoom and pan

Requirements: pip install pillow numpy
Run: python image_comparer.py
"""

import tkinter as tk
import math
import json
from tkinter import filedialog, messagebox, ttk, colorchooser, simpledialog
from PIL import Image, ImageTk, ImageDraw, ImageEnhance
import numpy as np


_PRESET_COLOURS = [
    "#ff0000", "#ff6600", "#ffcc00", "#ffff00",
    "#00cc44", "#00cccc", "#0088ff", "#0000ff",
    "#8800cc", "#cc00cc", "#ff0088", "#ff99cc",
    "#ffffff", "#bbbbbb", "#666666", "#000000",
]


class ImageComparer:
    def __init__(self, root):
        self.root = root
        self.root.title("MSSL thin-film filter inspector")
        self.root.geometry("1400x900")
        self.root.configure(bg="#2b2b2b")

        self.images = [None, None]       # Original PIL images (full res)
        self.image_paths = [None, None]  # Filesystem paths for save/load session
        self.preview_images = [None, None]  # Downsampled images for interaction
        self.preview_scales = [1.0, 1.0]    # preview_px = original_px * scale
        self.photos = [None, None]       # ImageTk references (prevent GC)

        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.offset_x = 0              # Image 2 translation relative to image 1 (pixels)
        self.offset_y = 0
        self.rotation = 0.0            # Image 2 rotation in degrees
        self.opacity = 0.5
        self.cursor_pos = (0, 0)       # Current cursor in canvas coords
        self.last_pan = (0, 0)
        self._render_pending = False
        self._interacting = False      # True during pan/zoom for fast resampling
        self._quality_timer = None     # after() id for quality re-render on interaction end
        self._rotated_cache = [None, None]   # Cached rotated PIL images
        self._last_rot = [None, None]        # Rotation angle at last cache fill
        self._rotated_preview_cache = [None, None]
        self._last_rot_preview = [None, None]

        # Annotation state
        self.annotations = []       # list of {img1_x, img1_y, img2_x, img2_y, radius, colour, label}
        self.annot_colour = "#ff0000"

        # Level line tool
        self._level_start = None   # (x, y) canvas coords while drawing

        # Point alignment tool
        self._align_pts_img1 = []  # raw image-1 pixel coords [(x,y), ...]
        self._align_pts_img2 = []  # raw image-2 pixel coords [(x,y), ...]
        self._align_guide_cursor = None  # canvas-2 coords while guide is active, else None

        # Crop export tool
        self._crop_corner1 = None  # canvas (x, y) of first crop corner, or None

        # Per-image adjustment variables (brightness, contrast, blacks, whites)
        self.adj_vars = [
            {"brightness": tk.DoubleVar(value=1.0),
             "contrast":   tk.DoubleVar(value=1.0),
             "blacks":     tk.DoubleVar(value=0.0),
             "whites":     tk.DoubleVar(value=255.0)},
            {"brightness": tk.DoubleVar(value=1.0),
             "contrast":   tk.DoubleVar(value=1.0),
             "blacks":     tk.DoubleVar(value=0.0),
             "whites":     tk.DoubleVar(value=255.0)},
        ]

        self._build_ui()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        # ---- Top toolbar ----
        toolbar = tk.Frame(self.root, bg="#3c3c3c", pady=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        btn_style = {"bg": "#555", "fg": "white", "relief": tk.FLAT,
                     "padx": 8, "pady": 3, "cursor": "hand2"}

        tk.Button(toolbar, text="Load Image 1", command=lambda: self.load_image(0),
                  **btn_style).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="Load Image 2", command=lambda: self.load_image(1),
                  **btn_style).pack(side=tk.LEFT, padx=4)

        sep = tk.Frame(toolbar, bg="#666", width=2, height=28)
        sep.pack(side=tk.LEFT, padx=8, fill=tk.Y)

        # Mode toggle
        tk.Label(toolbar, text="Mode:", bg="#3c3c3c", fg="white").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="sidebyside")
        tk.Radiobutton(toolbar, text="Side by Side", variable=self.mode_var,
                       value="sidebyside", command=self._on_mode_change,
                       bg="#3c3c3c", fg="white", selectcolor="#555",
                       activebackground="#3c3c3c").pack(side=tk.LEFT, padx=2)
        tk.Radiobutton(toolbar, text="Overlay", variable=self.mode_var,
                       value="overlay", command=self._on_mode_change,
                       bg="#3c3c3c", fg="white", selectcolor="#555",
                       activebackground="#3c3c3c").pack(side=tk.LEFT, padx=2)

        sep2 = tk.Frame(toolbar, bg="#666", width=2, height=28)
        sep2.pack(side=tk.LEFT, padx=8, fill=tk.Y)

        # Opacity
        tk.Label(toolbar, text="Opacity (img 2):", bg="#3c3c3c", fg="white").pack(side=tk.LEFT)
        self.opacity_var = tk.DoubleVar(value=0.5)
        opacity_slider = ttk.Scale(toolbar, from_=0.0, to=1.0, length=160,
                                   orient=tk.HORIZONTAL, variable=self.opacity_var,
                                   command=lambda v: self._schedule_render())
        opacity_slider.pack(side=tk.LEFT, padx=4)

        sep3 = tk.Frame(toolbar, bg="#666", width=2, height=28)
        sep3.pack(side=tk.LEFT, padx=8, fill=tk.Y)

        # ---- Second toolbar row for alignment ----
        toolbar2 = tk.Frame(self.root, bg="#2f2f2f", pady=4)
        toolbar2.pack(side=tk.TOP, fill=tk.X)

        tk.Label(toolbar2, text="Image 2 alignment  -  Offset X:",
                 bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(8, 2))
        self.off_x_var = tk.StringVar(value="0")
        self._make_spinbox(toolbar2, self.off_x_var, -9999, 9999)

        tk.Label(toolbar2, text="Y:", bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(6, 2))
        self.off_y_var = tk.StringVar(value="0")
        self._make_spinbox(toolbar2, self.off_y_var, -9999, 9999)

        tk.Label(toolbar2, text="  Rotation (deg):", bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(12, 2))
        self.rot_var = tk.StringVar(value="0.0")
        self._make_spinbox(toolbar2, self.rot_var, -180, 180, inc=0.1, width=6)

        tk.Label(toolbar2, text="  [Arrow keys nudge X/Y  | Shift+Arrow nudges rotation]",
                 bg="#2f2f2f", fg="#888", font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=12)

        tk.Button(toolbar2, text="Reset alignment",
                  command=self._reset_alignment,
                  bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

        # ---- Third toolbar row: global rotation ----
        toolbar3 = tk.Frame(self.root, bg="#282828", pady=4)
        toolbar3.pack(side=tk.TOP, fill=tk.X)

        tk.Label(toolbar3, text="Global rotation (both images, deg):",
                 bg="#282828", fg="#aaffaa").pack(side=tk.LEFT, padx=(8, 2))
        self.glob_rot_var = tk.StringVar(value="0.0")
        self._make_spinbox(toolbar3, self.glob_rot_var, -360, 360, inc=0.1, width=7)

        tk.Label(toolbar3, text="  [Ctrl+<> to nudge  | rotates both images together]",
                 bg="#282828", fg="#666", font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=6)

        tk.Frame(toolbar3, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        self.level_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar3, text="_|_ Level line  (drag a line that should be vertical -> auto-corrects rotation)",
                       variable=self.level_mode_var, command=self._on_level_mode_change,
                       bg="#282828", fg="#aaffaa", selectcolor="#444",
                       activebackground="#282828").pack(side=tk.LEFT, padx=4)

        tk.Button(toolbar3, text="Reset global rot",
                  command=lambda: (self.glob_rot_var.set("0.0"), self._schedule_render()),
                  bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

        # ---- Fourth toolbar row: annotations + export ----
        toolbar4 = tk.Frame(self.root, bg="#1e1e2e", pady=4)
        toolbar4.pack(side=tk.TOP, fill=tk.X)

        self.annot_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar4, text=" Annotate  (click=place  | right-click=delete)",
                       variable=self.annot_mode_var, command=self._on_annot_mode_change,
                       bg="#1e1e2e", fg="#ffff88", selectcolor="#444",
                       activebackground="#1e1e2e").pack(side=tk.LEFT, padx=(8, 4))

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=6, fill=tk.Y)

        self.annot_colour_btn = tk.Button(toolbar4, text="  Colour  ",
                                          bg=self.annot_colour, fg="white",
                                          relief=tk.FLAT, padx=6, pady=2,
                                          cursor="hand2", command=self._pick_colour)
        self.annot_colour_btn.pack(side=tk.LEFT, padx=4)

        tk.Label(toolbar4, text="Radius (px):", bg="#1e1e2e", fg="#ccc").pack(side=tk.LEFT, padx=(8, 2))
        self.annot_radius_var = tk.IntVar(value=20)
        tk.Spinbox(toolbar4, textvariable=self.annot_radius_var, from_=2, to=2000,
                   increment=1, width=5, bg="#444", fg="white",
                   insertbackground="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=6, fill=tk.Y)

        self.annot_label_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar4, text="Floating label",
                       variable=self.annot_label_var,
                       bg="#1e1e2e", fg="#ccc", selectcolor="#444",
                       activebackground="#1e1e2e").pack(side=tk.LEFT, padx=4)

        tk.Button(toolbar4, text="Clear all", command=self._clear_annotations,
                  bg="#663333", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=6, fill=tk.Y)

        tk.Button(toolbar4, text=" Export PNG", command=self._export,
                  bg="#336633", fg="white", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        self.align_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar4,
                       text=" Point align  (click pts on img 1, then same pts on img 2  | 2 pairs needed)",
                       variable=self.align_mode_var, command=self._on_align_mode_change,
                       bg="#1e1e2e", fg="#88ffff", selectcolor="#444",
                       activebackground="#1e1e2e").pack(side=tk.LEFT, padx=(4, 2))

        self._align_apply_btn = tk.Button(
            toolbar4, text="Apply align",
            command=self._apply_point_alignment,
            bg="#224444", fg="#88ffff", relief=tk.FLAT, padx=6, pady=2,
            cursor="hand2", state=tk.DISABLED)
        self._align_apply_btn.pack(side=tk.LEFT, padx=2)

        tk.Button(toolbar4, text="Clear pts", command=self._clear_align_pts,
                  bg="#224444", fg="#88ffff", relief=tk.FLAT, padx=4, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=2)

        # ---- Fifth toolbar row: per-image adjustments ----
        toolbar5 = tk.Frame(self.root, bg="#12121a", pady=4)
        toolbar5.pack(side=tk.TOP, fill=tk.X)

        adj_defs = [("brightness", 0.1, 3.0, "Bright"),
                    ("contrast",   0.1, 3.0, "Contr"),
                    ("blacks",     0.0, 200.0, "Blacks"),
                    ("whites",    55.0, 255.0, "Whites")]

        for img_idx, (img_label, label_col) in enumerate([("Image 1", "#ffcc00"),
                                                           ("Image 2", "#00ccff")]):
            if img_idx > 0:
                tk.Frame(toolbar5, bg="#555", width=2, height=20).pack(
                    side=tk.LEFT, padx=8, fill=tk.Y)
            tk.Label(toolbar5, text=img_label + ":", bg="#12121a", fg=label_col,
                     font=("TkDefaultFont", 8, "bold")).pack(side=tk.LEFT, padx=(8, 4))
            for key, lo, hi, lbl in adj_defs:
                tk.Label(toolbar5, text=lbl + ":", bg="#12121a", fg="#aaa",
                         font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=(4, 0))
                ttk.Scale(toolbar5, from_=lo, to=hi, length=75, orient=tk.HORIZONTAL,
                          variable=self.adj_vars[img_idx][key],
                          command=lambda _v: self._schedule_render()).pack(side=tk.LEFT, padx=2)

            tk.Button(toolbar5, text="Reset",
                      command=lambda index=img_idx: self._reset_image_adjustments(index),
                      bg="#444", fg="white", relief=tk.FLAT, padx=5, pady=2,
                      cursor="hand2").pack(side=tk.LEFT, padx=(6, 2))

        tk.Button(toolbar5, text="Reset all", command=self._reset_adjustments,
                  bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

        # ---- Sixth toolbar row: crop export and session management ----
        toolbar6 = tk.Frame(self.root, bg="#0d0d1a", pady=4)
        toolbar6.pack(side=tk.TOP, fill=tk.X)

        self.crop_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar6,
                       text=" Crop export  (click 2 corners on either canvas)",
                       variable=self.crop_mode_var, command=self._on_crop_mode_change,
                       bg="#0d0d1a", fg="#ffcc88", selectcolor="#444",
                       activebackground="#0d0d1a").pack(side=tk.LEFT, padx=(8, 4))

        tk.Label(toolbar6, text="Padding (px):", bg="#0d0d1a", fg="#ccc").pack(side=tk.LEFT, padx=(8, 2))
        self.crop_pad_var = tk.IntVar(value=20)
        tk.Spinbox(toolbar6, textvariable=self.crop_pad_var, from_=0, to=500,
                   increment=5, width=5, bg="#444", fg="white",
                   insertbackground="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Frame(toolbar6, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=12, fill=tk.Y)

        tk.Button(toolbar6, text="\U0001f4be Save session", command=self._save_session,
                  bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        tk.Button(toolbar6, text="\U0001f4c2 Load session", command=self._load_session,
                  bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        # ---- Canvas area ----
        self.canvas_frame = tk.Frame(self.root, bg="#1e1e1e")
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas1 = tk.Canvas(self.canvas_frame, bg="#1e1e1e",
                                  cursor="crosshair", highlightthickness=0)
        self.canvas2 = tk.Canvas(self.canvas_frame, bg="#1e1e1e",
                                  cursor="crosshair", highlightthickness=0)
        self.canvas1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Label badges
        self.canvas1.create_text(8, 8, anchor=tk.NW, text="IMAGE 1",
                                  fill="#ffcc00", font=("TkDefaultFont", 9, "bold"),
                                  tags="badge1")
        self.canvas2.create_text(8, 8, anchor=tk.NW, text="IMAGE 2",
                                  fill="#00ccff", font=("TkDefaultFont", 9, "bold"),
                                  tags="badge2")

        # ---- Status bar ----
        self.status_var = tk.StringVar(value="Load two images to begin.")
        tk.Label(self.root, textvariable=self.status_var, anchor=tk.W,
                 bg="#1a1a1a", fg="#aaa", font=("TkDefaultFont", 8),
                 padx=6).pack(side=tk.BOTTOM, fill=tk.X)

        # ---- Bind events ----
        for canvas in (self.canvas1, self.canvas2):
            canvas.bind("<Motion>", self._on_mouse_move)
            canvas.bind("<MouseWheel>", self._on_zoom)   # Windows / macOS
            canvas.bind("<Button-4>", self._on_zoom)     # Linux scroll up
            canvas.bind("<Button-5>", self._on_zoom)     # Linux scroll down
            canvas.bind("<ButtonPress-1>", self._on_left_press)
            canvas.bind("<B1-Motion>", self._on_b1_motion)
            canvas.bind("<ButtonRelease-1>", self._on_left_release)
            canvas.bind("<Button-3>", self._on_right_click)
            canvas.bind("<Configure>", lambda e: self._schedule_render())
            canvas.bind("<Leave>", self._on_canvas_leave)

        self.root.bind("<Left>",  lambda e: self._nudge(-1, 0, 0))
        self.root.bind("<Right>", lambda e: self._nudge(1,  0, 0))
        self.root.bind("<Up>",    lambda e: self._nudge(0, -1, 0))
        self.root.bind("<Down>",  lambda e: self._nudge(0,  1, 0))
        self.root.bind("<Shift-Left>",   lambda e: self._nudge(0, 0, -0.1))
        self.root.bind("<Shift-Right>",  lambda e: self._nudge(0, 0,  0.1))
        self.root.bind("<Control-Left>",  lambda e: self._nudge_global(-0.5))
        self.root.bind("<Control-Right>", lambda e: self._nudge_global( 0.5))

    def _make_spinbox(self, parent, var, from_, to, inc=1, width=5):
        sb = tk.Spinbox(parent, textvariable=var, from_=from_, to=to,
                        increment=inc, width=width, bg="#444", fg="white",
                        insertbackground="white", relief=tk.FLAT,
                        command=self._on_alignment_change)
        sb.bind("<Return>", lambda e: self._on_alignment_change())
        sb.bind("<FocusOut>", lambda e: self._on_alignment_change())
        sb.pack(side=tk.LEFT, padx=2)
        return sb

    # --------------------------------------------------------- Event handlers

    def load_image(self, idx):
        path = filedialog.askopenfilename(
            title=f"Open Image {idx + 1}",
            filetypes=[
                ("Image files", "*.tif *.tiff *.TIF *.TIFF *.png *.PNG *.jpg *.JPG *.jpeg *.JPEG *.bmp *.BMP *.webp *.WEBP"),
                ("All files", "*.*")
            ])
        if not path:
            return
        img = Image.open(path)
        # Convert to RGB for display (handles 16-bit, RGBA, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        self.images[idx] = img
        self.image_paths[idx] = path
        self.preview_images[idx], self.preview_scales[idx] = self._make_preview(img)
        self._rotated_cache[idx] = None  # Invalidate rotation cache
        self._last_rot[idx] = None
        self._rotated_preview_cache[idx] = None
        self._last_rot_preview[idx] = None
        self.status_var.set(f"Image {idx + 1} loaded: {path}  ({img.width}x{img.height})")
        self._schedule_render()

    def _on_mode_change(self):
        if self.mode_var.get() == "overlay":
            self.canvas2.pack_forget()
        else:
            self.canvas2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._schedule_render()

    def _on_alignment_change(self):
        self._schedule_render()

    def _on_opacity(self, val):
        self.opacity = float(val)
        self._schedule_render()

    def _reset_alignment(self):
        self.off_x_var.set("0")
        self.off_y_var.set("0")
        self.rot_var.set("0.0")
        self.glob_rot_var.set("0.0")
        self._schedule_render()

    def _nudge_global(self, dr):
        try:
            r = float(self.glob_rot_var.get()) + dr
            self.glob_rot_var.set(f"{r:.1f}")
        except ValueError:
            pass
        self._schedule_render()

    def _nudge(self, dx, dy, dr):
        try:
            x = float(self.off_x_var.get()) + dx
            y = float(self.off_y_var.get()) + dy
            r = float(self.rot_var.get()) + dr
            self.off_x_var.set(str(int(x)))
            self.off_y_var.set(str(int(y)))
            self.rot_var.set(f"{r:.1f}")
        except ValueError:
            pass
        self._schedule_render()

    def _on_pan_start(self, event):
        self._interacting = True
        self.last_pan = (event.x, event.y)

    def _on_pan(self, event):
        dx = event.x - self.last_pan[0]
        dy = event.y - self.last_pan[1]
        self.pan_x += dx
        self.pan_y += dy
        self.last_pan = (event.x, event.y)
        # Move canvas items directly  -  instant, no PIL re-render needed
        self.canvas1.move("img", dx, dy)
        self.canvas2.move("img", dx, dy)
        self.canvas1.move("annotations", dx, dy)
        self.canvas2.move("annotations", dx, dy)
        self._draw_cursors()
        # Also render quickly during drag so newly exposed areas appear immediately.
        self._schedule_render()
        # Quality re-render once the drag settles
        self._schedule_quality_render()

    def _on_zoom(self, event):
        # Use delta magnitude for smoother trackpad zoom; keep button scroll fallback.
        if hasattr(event, "delta") and event.delta:
            factor = 1.0015 ** event.delta
        elif getattr(event, "num", None) == 4:
            factor = 1.12
        else:
            factor = 1 / 1.12
        factor = max(0.5, min(2.0, factor))
        # Zoom towards cursor
        cx, cy = event.x, event.y
        self.pan_x = cx - (cx - self.pan_x) * factor
        self.pan_y = cy - (cy - self.pan_y) * factor
        self.zoom *= factor
        self.zoom = max(0.02, min(100.0, self.zoom))
        self._interacting = True      # Use fast resampling until scroll stops
        self._schedule_render()
        self._schedule_quality_render()

    def _on_mouse_move(self, event):
        self.cursor_pos = (event.x, event.y)
        # Convert canvas coords -> image-1 pixel coords
        img_x = (event.x - self.pan_x) / self.zoom
        img_y = (event.y - self.pan_y) / self.zoom
        self.status_var.set(
            f"Image coords: ({img_x:.1f}, {img_y:.1f})  |  "
            f"Zoom: {self.zoom:.2f}x  |  "
            f"Offset: ({self.off_x_var.get()}, {self.off_y_var.get()})  |  "
            f"Rotation: {self.rot_var.get()}deg"
        )
        self._draw_cursors()
        # Update alignment guide on canvas 2
        if self.align_mode_var.get():
            if event.widget is self.canvas2:
                self._align_guide_cursor = (event.x, event.y)
            else:
                self._align_guide_cursor = None
            self._draw_align_guide()
        # Update crop rectangle preview
        if self.crop_mode_var.get() and self._crop_corner1 is not None:
            self._draw_crop_preview(event.x, event.y)

    # --------------------------------------------------------------- Rendering

    def _schedule_quality_render(self):
        """Start (or restart) a timer that fires a full-quality render once interaction stops."""
        if self._quality_timer is not None:
            self.root.after_cancel(self._quality_timer)
        self._quality_timer = self.root.after(150, self._on_interaction_end)

    def _on_interaction_end(self):
        """Called ~150 ms after the last pan/zoom event; renders at full quality."""
        self._quality_timer = None
        self._interacting = False
        self._render()

    def _make_preview(self, img, max_dim=2200):
        """Build an interaction preview image with bounded size for fast zoom/pan."""
        largest = max(img.width, img.height)
        if largest <= max_dim:
            return img, 1.0
        scale = max_dim / float(largest)
        w = max(1, int(round(img.width * scale)))
        h = max(1, int(round(img.height * scale)))
        return img.resize((w, h), resample=Image.BILINEAR), scale

    def _schedule_render(self):
        """Debounce renders to avoid flooding during drag."""
        if not self._render_pending:
            self._render_pending = True
            self.root.after(16, self._render)  # ~60fps cap

    def _render(self):
        self._render_pending = False
        mode = self.mode_var.get()
        try:
            off_x = int(float(self.off_x_var.get()))
            off_y = int(float(self.off_y_var.get()))
            rot = float(self.rot_var.get())
            glob_rot = float(self.glob_rot_var.get())
        except ValueError:
            off_x, off_y, rot, glob_rot = 0, 0, 0.0, 0.0

        w1 = max(self.canvas1.winfo_width(), 1)
        h1 = max(self.canvas1.winfo_height(), 1)

        if mode == "overlay":
            v1 = self._get_view(self.images[0], 0, 0, glob_rot, w1, h1, idx=0)
            v2 = self._get_view(self.images[1], off_x, off_y, glob_rot + rot, w1, h1, idx=1)
            alpha = self.opacity_var.get()
            if self.images[0] and self.images[1]:
                blended = Image.blend(v1.convert("RGB"), v2.convert("RGB"), alpha)
            elif self.images[0]:
                blended = v1
            else:
                blended = v2
            self.photos[0] = ImageTk.PhotoImage(blended)
            if self.canvas1.find_withtag("img"):
                self.canvas1.itemconfig("img", image=self.photos[0])
                self.canvas1.coords("img", 0, 0)
            else:
                self.canvas1.create_image(0, 0, anchor=tk.NW,
                                          image=self.photos[0], tags="img")
            self.canvas1.tag_raise("badge1")
        else:
            w2 = max(self.canvas2.winfo_width(), 1)
            h2 = max(self.canvas2.winfo_height(), 1)

            v1 = self._get_view(self.images[0], 0, 0, glob_rot, w1, h1, idx=0)
            v2 = self._get_view(self.images[1], off_x, off_y, glob_rot + rot, w2, h2, idx=1)

            self.photos[0] = ImageTk.PhotoImage(v1)
            self.photos[1] = ImageTk.PhotoImage(v2)

            if self.canvas1.find_withtag("img"):
                self.canvas1.itemconfig("img", image=self.photos[0])
                self.canvas1.coords("img", 0, 0)
            else:
                self.canvas1.create_image(0, 0, anchor=tk.NW,
                                          image=self.photos[0], tags="img")

            if self.canvas2.find_withtag("img"):
                self.canvas2.itemconfig("img", image=self.photos[1])
                self.canvas2.coords("img", 0, 0)
            else:
                self.canvas2.create_image(0, 0, anchor=tk.NW,
                                          image=self.photos[1], tags="img")
            self.canvas1.tag_raise("badge1")
            self.canvas2.tag_raise("badge2")

        self._draw_annotations()
        self._draw_align_pts()
        self._draw_cursors()

    def _get_view(self, img, off_x, off_y, rotation, canvas_w, canvas_h, idx=None):
        """Return a canvas_w x canvas_h PIL image showing the current view."""
        placeholder = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
        if img is None:
            return placeholder

        # Use smaller source during interaction for smoother response.
        source = img
        source_scale = 1.0
        rot_cache = self._rotated_cache
        rot_last = self._last_rot
        if self._interacting and idx is not None and self.preview_images[idx] is not None:
            source = self.preview_images[idx]
            source_scale = self.preview_scales[idx]
            rot_cache = self._rotated_preview_cache
            rot_last = self._last_rot_preview

        # Apply rotation with caching  -  rotation (BICUBIC) is the most expensive step
        if rotation != 0.0:
            if (idx is not None
                    and rot_last[idx] == rotation
                    and rot_cache[idx] is not None):
                working = rot_cache[idx]
            else:
                working = source.rotate(-rotation, resample=Image.BICUBIC, expand=False)
                if idx is not None:
                    rot_cache[idx] = working
                    rot_last[idx] = rotation
        else:
            working = source

        # Adjust coordinates when using a downsampled source image.
        zoom = max(self.zoom / source_scale, 1e-6)
        off_x = off_x * source_scale
        off_y = off_y * source_scale
        paste_x = self.pan_x + off_x * zoom
        paste_y = self.pan_y + off_y * zoom

        # Compute visible source region (in source image coordinates).
        src_x0_f = max(0.0, (0.0 - paste_x) / zoom)
        src_y0_f = max(0.0, (0.0 - paste_y) / zoom)
        src_x1_f = min(float(working.width), (canvas_w - paste_x) / zoom)
        src_y1_f = min(float(working.height), (canvas_h - paste_y) / zoom)

        if src_x1_f <= src_x0_f or src_y1_f <= src_y0_f:
            return placeholder

        # Expand crop to integer pixels, then map exact fraction back to destination.
        src_x0 = max(0, int(math.floor(src_x0_f)))
        src_y0 = max(0, int(math.floor(src_y0_f)))
        src_x1 = min(working.width, int(math.ceil(src_x1_f)))
        src_y1 = min(working.height, int(math.ceil(src_y1_f)))

        if src_x1 <= src_x0 or src_y1 <= src_y0:
            return placeholder

        # During active pan/zoom use BILINEAR (fast); otherwise higher quality.
        if self._interacting:
            resample = Image.NEAREST
        else:
            resample = Image.LANCZOS if zoom <= 1.0 else Image.BICUBIC

        region = working.crop((src_x0, src_y0, src_x1, src_y1))

        dst_x0 = int(round(paste_x + src_x0_f * zoom))
        dst_y0 = int(round(paste_y + src_y0_f * zoom))
        dst_x1 = int(round(paste_x + src_x1_f * zoom))
        dst_y1 = int(round(paste_y + src_y1_f * zoom))

        dst_x0 = max(0, min(canvas_w, dst_x0))
        dst_y0 = max(0, min(canvas_h, dst_y0))
        dst_x1 = max(0, min(canvas_w, dst_x1))
        dst_y1 = max(0, min(canvas_h, dst_y1))

        target_w = dst_x1 - dst_x0
        target_h = dst_y1 - dst_y0
        if target_w <= 0 or target_h <= 0:
            return placeholder

        if region.size != (target_w, target_h):
            region = region.resize((target_w, target_h), resample=resample)

        if idx is not None:
            region = self._apply_adjustments(region, idx)

        result = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
        result.paste(region, (dst_x0, dst_y0))
        return result

    def _draw_cursors(self):
        cx, cy = self.cursor_pos
        mode = self.mode_var.get()
        canvases = [self.canvas1] if mode == "overlay" else [self.canvas1, self.canvas2]

        for canvas in canvases:
            canvas.delete("cursor")
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 2 or h < 2:
                continue
            # Full-width / full-height crosshair lines
            canvas.create_line(0, cy, w, cy, fill="#ff3333",
                                tags="cursor", width=1)
            canvas.create_line(cx, 0, cx, h, fill="#ff3333",
                                tags="cursor", width=1)
            # Small circle at intersection
            r = 6
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                outline="#ff3333", tags="cursor", width=1)
            canvas.tag_raise("cursor")


    # ----------------------------------------- Annotation helpers / transforms

    def _get_alignment_values(self):
        """Return (off_x, off_y, rot, glob_rot) from current spinbox values."""
        try:
            return (int(float(self.off_x_var.get())),
                    int(float(self.off_y_var.get())),
                    float(self.rot_var.get()),
                    float(self.glob_rot_var.get()))
        except ValueError:
            return 0, 0, 0.0, 0.0

    def _rotate_display_point(self, x, y, cx, cy, rot_deg):
        """Rotate a point around (cx, cy) using the same sign convention as PIL.rotate(-rot)."""
        if not rot_deg:
            return x, y
        theta = math.radians(rot_deg)
        dx, dy = x - cx, y - cy
        return (cx + dx * math.cos(theta) - dy * math.sin(theta),
                cy + dx * math.sin(theta) + dy * math.cos(theta))

    def _unrotate_display_point(self, x, y, cx, cy, rot_deg):
        """Inverse of _rotate_display_point."""
        if not rot_deg:
            return x, y
        theta = math.radians(rot_deg)
        dx, dy = x - cx, y - cy
        return (cx + dx * math.cos(theta) + dy * math.sin(theta),
                cy - dx * math.sin(theta) + dy * math.cos(theta))

    def _expected_align_canvas(self):
        """Return 0 when the next point should be clicked on image 1, else 1 for image 2."""
        return 0 if len(self._align_pts_img1) <= len(self._align_pts_img2) else 1

    def _draw_align_guide(self):
        """Draw the distance-constraint circle and pointer line on canvas 2.

        Active when: align mode on, n1 >= 2, and we are waiting for the next img-2 click
        (n1 == n2 + 1).  The circle is centred on the previous img-2 point and has a radius
        equal to the distance between the two most recent img-1 points (in canvas pixels), so
        the user only selects an angle  -  not a distance.
        """
        self.canvas2.delete("align_guide")
        if not self.align_mode_var.get():
            return
        n1 = len(self._align_pts_img1)
        n2 = len(self._align_pts_img2)
        if n1 < 2 or n1 != n2 + 1:
            return
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        # Circle centre: last img-2 point projected onto canvas 2
        prev_img2 = self._align_pts_img2[-1]
        gx, gy = self._img2_to_canvas2(prev_img2[0], prev_img2[1], off_x, off_y, total_rot)
        # Radius: distance (canvas pixels) between the two most recent img-1 points
        p1a = np.array(self._align_pts_img1[-2])
        p1b = np.array(self._align_pts_img1[-1])
        r_canvas = float(np.linalg.norm(p1b - p1a)) * self.zoom
        # Draw dashed guide circle
        self.canvas2.create_oval(
            gx - r_canvas, gy - r_canvas, gx + r_canvas, gy + r_canvas,
            outline="#ffaa00", width=1, dash=(4, 4), tags="align_guide")
        # Draw line from centre toward cursor (to circle edge)
        if self._align_guide_cursor is not None:
            cx, cy = self._align_guide_cursor
            dx, dy = cx - gx, cy - gy
            dist = math.hypot(dx, dy)
            if dist > 1.0:
                lx = gx + dx / dist * r_canvas
                ly = gy + dy / dist * r_canvas
                self.canvas2.create_line(gx, gy, lx, ly,
                                         fill="#ffaa00", width=1, dash=(4, 4),
                                         tags="align_guide")
        self.canvas2.tag_raise("align_guide")
        self.canvas2.tag_raise("align_pts")

    def _on_canvas_leave(self, event):
        """Clear overlays when the cursor leaves a canvas."""
        if event.widget is self.canvas2:
            self._align_guide_cursor = None
            self.canvas2.delete("align_guide")
        if self.crop_mode_var.get() and self._crop_corner1 is not None:
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")

    def _img1_to_canvas1(self, img_x, img_y, glob_rot):
        """Map image-1 pixel -> canvas-1 pixel (accounts for global rotation)."""
        if self.images[0] is not None:
            cx0, cy0 = self.images[0].width / 2.0, self.images[0].height / 2.0
        else:
            cx0 = cy0 = 0.0
        rx, ry = self._rotate_display_point(img_x, img_y, cx0, cy0, glob_rot)
        return self.pan_x + rx * self.zoom, self.pan_y + ry * self.zoom

    def _img1_to_canvas2(self, img_x, img_y, off_x, off_y, total_rot):
        """Map image-1 pixel -> canvas-2 pixel (accounts for alignment + total rotation)."""
        if self.images[1] is not None:
            cx2, cy2 = self.images[1].width / 2.0, self.images[1].height / 2.0
        else:
            cx2 = cy2 = 0.0
        rx, ry = self._rotate_display_point(img_x, img_y, cx2, cy2, total_rot)
        return (self.pan_x + off_x * self.zoom + rx * self.zoom,
                self.pan_y + off_y * self.zoom + ry * self.zoom)

    def _canvas_to_img1(self, canvas_x, canvas_y, canvas_is_2=False):
        """Convert a canvas click position to image-1 raw pixel coordinates.
        Both canvases share pan/zoom, so canvas_is_2 does not change the result.
        """
        _, _, _, glob_rot = self._get_alignment_values()
        rx = (canvas_x - self.pan_x) / self.zoom
        ry = (canvas_y - self.pan_y) / self.zoom
        cx0 = self.images[0].width / 2.0 if self.images[0] else 0.0
        cy0 = self.images[0].height / 2.0 if self.images[0] else 0.0
        return self._unrotate_display_point(rx, ry, cx0, cy0, glob_rot)

    def _canvas_to_img2(self, canvas_x, canvas_y):
        """Convert a canvas position to raw image-2 pixel coordinates using current alignment."""
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        rx = (canvas_x - self.pan_x) / self.zoom - off_x
        ry = (canvas_y - self.pan_y) / self.zoom - off_y
        cx2 = self.images[1].width / 2.0 if self.images[1] else 0.0
        cy2 = self.images[1].height / 2.0 if self.images[1] else 0.0
        return self._unrotate_display_point(rx, ry, cx2, cy2, total_rot)

    # ------------------------------------------- Annotation event handlers

    def _on_annot_mode_change(self):
        if self.annot_mode_var.get():
            # Turn off competing modes
            self.level_mode_var.set(False)
            self.canvas1.delete("level_line")
            self.canvas2.delete("level_line")
            self._level_start = None
            self.align_mode_var.set(False)
            self.canvas1.delete("align_pts")
            self.canvas2.delete("align_pts")
            self.crop_mode_var.set(False)
            self._crop_corner1 = None
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")
        active = (self.annot_mode_var.get() or self.level_mode_var.get()
                  or self.align_mode_var.get() or self.crop_mode_var.get())
        cur = "tcross" if active else "crosshair"
        self.canvas1.config(cursor=cur)
        self.canvas2.config(cursor=cur)

    def _on_level_mode_change(self):
        if not self.level_mode_var.get():
            self.canvas1.delete("level_line")
            self.canvas2.delete("level_line")
            self._level_start = None
        if self.level_mode_var.get():
            # Turn off competing modes
            self.annot_mode_var.set(False)
            self.align_mode_var.set(False)
            self.canvas1.delete("align_pts")
            self.canvas2.delete("align_pts")
            self.crop_mode_var.set(False)
            self._crop_corner1 = None
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")
        active = (self.level_mode_var.get() or self.annot_mode_var.get()
                  or self.align_mode_var.get() or self.crop_mode_var.get())
        cur = "tcross" if active else "crosshair"
        self.canvas1.config(cursor=cur)
        self.canvas2.config(cursor=cur)

    def _on_align_mode_change(self):
        if self.align_mode_var.get():
            # Turn off competing modes
            self.level_mode_var.set(False)
            self.canvas1.delete("level_line")
            self.canvas2.delete("level_line")
            self._level_start = None
            self.annot_mode_var.set(False)
            self.crop_mode_var.set(False)
            self._crop_corner1 = None
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")
        else:
            self._align_guide_cursor = None
            self.canvas1.delete("align_pts")
            self.canvas2.delete("align_pts")
            self.canvas2.delete("align_guide")
        active = (self.align_mode_var.get() or self.annot_mode_var.get()
                  or self.level_mode_var.get() or self.crop_mode_var.get())
        cur = "tcross" if active else "crosshair"
        self.canvas1.config(cursor=cur)
        self.canvas2.config(cursor=cur)
        self._update_align_status()

    def _update_align_status(self):
        n1 = len(self._align_pts_img1)
        n2 = len(self._align_pts_img2)
        n_pairs = min(n1, n2)
        can_apply = n_pairs >= 2 and self.images[0] and self.images[1]
        self._align_apply_btn.config(state=tk.NORMAL if can_apply else tk.DISABLED)
        if self.align_mode_var.get():
            next_target = "Image 1" if self._expected_align_canvas() == 0 else "Image 2"
            self.status_var.set(
                f"Point align  -  Image 1: {n1} pt(s)  |  Image 2: {n2} pt(s)  |  "
                f"{'Ready  -  click Apply' if can_apply else 'Next click: ' + next_target}"
            )

    def _add_align_point(self, event):
        canvas_is_2 = (event.widget == self.canvas2)
        expected_canvas = self._expected_align_canvas()
        if int(canvas_is_2) != expected_canvas:
            expected_name = "Image 2" if expected_canvas else "Image 1"
            self.status_var.set(f"Point align  -  next click should be on {expected_name}.")
            return
        if canvas_is_2:
            if self.images[1] is None:
                return
            off_x, off_y, rot, glob_rot = self._get_alignment_values()
            total_rot = glob_rot + rot
            cx2 = self.images[1].width / 2.0
            cy2 = self.images[1].height / 2.0
            # If the guide circle is active, snap the click to the circle edge so
            # only the angle is chosen (not the distance).
            click_x, click_y = event.x, event.y
            n1_now = len(self._align_pts_img1)
            n2_now = len(self._align_pts_img2)
            if n1_now >= 2 and n1_now == n2_now + 1:
                prev_img2 = self._align_pts_img2[-1]
                gx, gy = self._img2_to_canvas2(prev_img2[0], prev_img2[1], off_x, off_y, total_rot)
                p1a = np.array(self._align_pts_img1[-2])
                p1b = np.array(self._align_pts_img1[-1])
                r_canvas = float(np.linalg.norm(p1b - p1a)) * self.zoom
                dx, dy = click_x - gx, click_y - gy
                dist = math.hypot(dx, dy)
                if dist > 1.0:
                    click_x = gx + dx / dist * r_canvas
                    click_y = gy + dy / dist * r_canvas
                else:
                    click_x = gx + r_canvas  # fallback: due east
            rx = (click_x - self.pan_x) / self.zoom - off_x
            ry = (click_y - self.pan_y) / self.zoom - off_y
            img2_x, img2_y = self._unrotate_display_point(rx, ry, cx2, cy2, total_rot)
            self._align_pts_img2.append((img2_x, img2_y))
        else:
            if self.images[0] is None:
                return
            img_x, img_y = self._canvas_to_img1(event.x, event.y, canvas_is_2=False)
            self._align_pts_img1.append((img_x, img_y))
        self._update_align_status()
        self._schedule_render()

    def _clear_align_pts(self):
        self._align_pts_img1.clear()
        self._align_pts_img2.clear()
        self._align_guide_cursor = None
        self._align_apply_btn.config(state=tk.DISABLED)
        self.canvas1.delete("align_pts")
        self.canvas2.delete("align_pts")
        self.canvas2.delete("align_guide")
        self._update_align_status()

    def _apply_point_alignment(self):
        n = min(len(self._align_pts_img1), len(self._align_pts_img2))
        if n < 2 or self.images[0] is None or self.images[1] is None:
            return

        p1 = np.array(self._align_pts_img1[:n], dtype=float)  # (n, 2) image-1 raw
        p2 = np.array(self._align_pts_img2[:n], dtype=float)  # (n, 2) image-2 raw

        glob_rot = float(self.glob_rot_var.get())
        g = math.radians(glob_rot)
        cos_g, sin_g = math.cos(g), math.sin(g)
        R_g = np.array([[cos_g, -sin_g], [sin_g, cos_g]])

        c1 = np.array([self.images[0].width / 2.0, self.images[0].height / 2.0])
        c2 = np.array([self.images[1].width / 2.0, self.images[1].height / 2.0])

        # Convert image-1 points to display space (apply glob_rot around c1)
        u = (R_g @ (p1 - c1).T).T + c1          # (n, 2)

        # Centre both sets
        u_mean = u.mean(axis=0)
        d_mean = (p2 - c2).mean(axis=0)
        u_c = u - u_mean                          # centred target
        d_c = (p2 - c2) - d_mean                 # centred source

        # Kabsch: find rotation R_new s.t. R_new @ d_c[i] ~= u_c[i]
        H = d_c.T @ u_c                           # (2, 2) cross-covariance
        U_s, _, Vt = np.linalg.svd(H)
        R_new = Vt.T @ U_s.T
        # Correct reflections (det should be +1)
        if np.linalg.det(R_new) < 0:
            Vt[-1] *= -1
            R_new = Vt.T @ U_s.T

        total_rot = math.degrees(math.atan2(R_new[1, 0], R_new[0, 0]))
        delta_rot = total_rot - glob_rot

        # Translation: off = u_mean - c2 - R_new @ d_mean
        off = u_mean - c2 - R_new @ d_mean

        self.off_x_var.set(str(int(round(off[0]))))
        self.off_y_var.set(str(int(round(off[1]))))
        self.rot_var.set(f"{delta_rot:.2f}")
        self._schedule_render()
        self.status_var.set(
            f"Alignment applied  -  offset ({off[0]:.0f}, {off[1]:.0f}) px  | "
            f"rotation {delta_rot:.2f}deg  | from {n} point pair(s)"
        )

    def _img2_to_canvas2(self, img2_x, img2_y, off_x, off_y, total_rot):
        """Map raw image-2 pixel -> canvas-2 pixel."""
        cx2 = self.images[1].width / 2.0 if self.images[1] else 0.0
        cy2 = self.images[1].height / 2.0 if self.images[1] else 0.0
        rx, ry = self._rotate_display_point(img2_x, img2_y, cx2, cy2, total_rot)
        return (self.pan_x + off_x * self.zoom + rx * self.zoom,
                self.pan_y + off_y * self.zoom + ry * self.zoom)

    def _draw_align_pts(self):
        """Draw collected alignment point markers on both canvases."""
        self.canvas1.delete("align_pts")
        self.canvas2.delete("align_pts")
        if not self.align_mode_var.get():
            return
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        r = 7
        for i, (px, py) in enumerate(self._align_pts_img1):
            cx, cy = self._img1_to_canvas1(px, py, glob_rot)
            self.canvas1.create_oval(cx - r, cy - r, cx + r, cy + r,
                                     outline="#88ffff", width=2, tags="align_pts")
            self.canvas1.create_text(cx, cy, text=str(i + 1), fill="#88ffff",
                                     font=("TkDefaultFont", 7, "bold"), tags="align_pts")
        if self.images[1] is not None:
            for i, (px, py) in enumerate(self._align_pts_img2):
                cx, cy = self._img2_to_canvas2(px, py, off_x, off_y, total_rot)
                self.canvas2.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         outline="#88ffff", width=2, tags="align_pts")
                self.canvas2.create_text(cx, cy, text=str(i + 1), fill="#88ffff",
                                         font=("TkDefaultFont", 7, "bold"), tags="align_pts")
        self.canvas1.tag_raise("align_pts")
        self.canvas2.tag_raise("align_pts")
        self._draw_align_guide()

    def _pick_colour(self):
        popup = tk.Toplevel(self.root)
        popup.title("Marker colour")
        popup.resizable(False, False)
        popup.configure(bg="#2b2b2b")
        popup.transient(self.root)
        popup.grab_set()
        cols = 4
        for i, col in enumerate(_PRESET_COLOURS):
            r, c = divmod(i, cols)
            tk.Button(popup, bg=col, width=3, height=1, relief=tk.RIDGE,
                      cursor="hand2",
                      command=lambda clr=col: self._set_annot_colour(clr, popup)
                      ).grid(row=r, column=c, padx=3, pady=3)
        rows_used = (len(_PRESET_COLOURS) + cols - 1) // cols
        tk.Button(popup, text="Custom...", bg="#555", fg="white",
                  relief=tk.FLAT, padx=8, pady=3, cursor="hand2",
                  command=lambda: self._custom_colour(popup)
                  ).grid(row=rows_used, column=0, columnspan=cols,
                         padx=3, pady=(4, 3), sticky="ew")

    def _set_annot_colour(self, colour, popup):
        self.annot_colour = colour
        self.annot_colour_btn.config(bg=colour)
        popup.destroy()

    def _custom_colour(self, popup):
        popup.destroy()
        result = colorchooser.askcolor(color=self.annot_colour,
                                       title="Custom marker colour")
        if result and result[1]:
            self.annot_colour = result[1]
            self.annot_colour_btn.config(bg=self.annot_colour)

    def _on_left_press(self, event):
        if self.crop_mode_var.get():
            self._on_crop_click(event)
        elif self.level_mode_var.get():
            self._level_start = (event.x, event.y)
            event.widget.delete("level_line")
        elif self.align_mode_var.get():
            self._add_align_point(event)
        elif self.annot_mode_var.get():
            self._place_annotation(event)
        else:
            self._on_pan_start(event)

    def _on_b1_motion(self, event):
        if self.crop_mode_var.get():
            pass  # no panning in crop mode
        elif self.level_mode_var.get():
            if self._level_start:
                event.widget.delete("level_line")
                x0, y0 = self._level_start
                event.widget.create_line(x0, y0, event.x, event.y,
                                         fill="#ffff44", width=2,
                                         tags="level_line", dash=(6, 4))
        elif self.align_mode_var.get():
            pass  # no panning in align mode
        elif not self.annot_mode_var.get():
            self._on_pan(event)

    def _on_left_release(self, event):
        if not self.level_mode_var.get() or self._level_start is None:
            return
        x0, y0 = self._level_start
        x1, y1 = event.x, event.y
        event.widget.delete("level_line")
        self._level_start = None
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) > 3 or abs(dy) > 3:
            # Normalise direction so dy >= 0 (tool is agnostic to draw direction)
            if dy < 0:
                dx, dy = -dx, -dy
            # Angle the drawn line makes with vertical; add it to undo the tilt.
            angle = math.degrees(math.atan2(dx, dy))
            try:
                current = float(self.glob_rot_var.get())
            except ValueError:
                current = 0.0
            self.glob_rot_var.set(f"{current + angle:.2f}")
            self._schedule_render()

    def _place_annotation(self, event):
        if self.images[0] is None and self.images[1] is None:
            return
        canvas_is_2 = (event.widget == self.canvas2)
        # Both canvases share pan/zoom; use the same click coords for both images.
        img1_x, img1_y = self._canvas_to_img1(event.x, event.y)
        img2_x, img2_y = self._canvas_to_img2(event.x, event.y)
        label = ""
        if self.annot_label_var.get():
            label = simpledialog.askstring("Label", "Annotation label (leave blank for none):",
                                           parent=self.root) or ""
        self.annotations.append({
            "img1_x": img1_x,
            "img1_y": img1_y,
            "img2_x": img2_x,
            "img2_y": img2_y,
            "radius": self.annot_radius_var.get(),
            "colour": self.annot_colour,
            "label": label,
        })
        self._schedule_render()

    def _on_right_click(self, event):
        if not self.annotations:
            return
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        canvas_is_2 = (event.widget == self.canvas2)
        tolerance = 30
        closest, min_dist = None, float("inf")
        for i, ann in enumerate(self.annotations):
            if canvas_is_2 and self.images[1] is not None:
                cx, cy = self._img2_to_canvas2(ann["img2_x"], ann["img2_y"],
                                               off_x, off_y, total_rot)
            else:
                cx, cy = self._img1_to_canvas1(ann["img1_x"], ann["img1_y"], glob_rot)
            d = math.hypot(event.x - cx, event.y - cy)
            if d < tolerance and d < min_dist:
                min_dist, closest = d, i
        if closest is not None:
            del self.annotations[closest]
            self._schedule_render()

    def _clear_annotations(self):
        if not self.annotations:
            return
        if not messagebox.askyesno("Clear all markers",
                                   "Delete all annotation markers? This cannot be undone.",
                                   parent=self.root):
            return
        self.annotations.clear()
        self.canvas1.delete("annotations")
        self.canvas2.delete("annotations")

    def _apply_adjustments(self, img, idx):
        """Apply per-image blacks/whites/brightness/contrast to a PIL image."""
        d = self.adj_vars[idx]
        blacks     = d["blacks"].get()
        whites     = d["whites"].get()
        brightness = d["brightness"].get()
        contrast   = d["contrast"].get()
        if (blacks == 0.0 and whites == 255.0
                and abs(brightness - 1.0) < 1e-3
                and abs(contrast - 1.0) < 1e-3):
            return img
        if img.mode != "RGB":
            img = img.convert("RGB")
        if blacks != 0.0 or whites != 255.0:
            scale = 255.0 / max(whites - blacks, 1.0)
            arr = np.array(img, dtype=np.float32)
            arr = (arr - blacks) * scale
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        if abs(brightness - 1.0) >= 1e-3:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if abs(contrast - 1.0) >= 1e-3:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        return img

    def _reset_adjustments(self):
        for d in self.adj_vars:
            d["brightness"].set(1.0)
            d["contrast"].set(1.0)
            d["blacks"].set(0.0)
            d["whites"].set(255.0)
        self._schedule_render()

    def _reset_image_adjustments(self, idx):
        d = self.adj_vars[idx]
        d["brightness"].set(1.0)
        d["contrast"].set(1.0)
        d["blacks"].set(0.0)
        d["whites"].set(255.0)
        self._schedule_render()

    def _draw_annotations(self):
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        mode = self.mode_var.get()
        self.canvas1.delete("annotations")
        self.canvas2.delete("annotations")
        if not self.annotations:
            return
        for ann in self.annotations:
            ix1, iy1 = ann["img1_x"], ann["img1_y"]
            ix2, iy2 = ann["img2_x"], ann["img2_y"]
            colour = ann["colour"]
            label = ann.get("label", "")
            r = max(3, ann["radius"] * self.zoom)

            # Draw on canvas-1 (always)
            cx, cy = self._img1_to_canvas1(ix1, iy1, glob_rot)
            self.canvas1.create_oval(cx - r, cy - r, cx + r, cy + r,
                                     outline=colour, width=2, tags="annotations")
            if label:
                self.canvas1.create_text(cx + r + 5, cy, text=label, fill=colour,
                                         anchor=tk.W, tags="annotations",
                                         font=("TkDefaultFont", 9, "bold"))

            # Draw on canvas-2 (side-by-side only)
            if mode == "sidebyside" and self.images[1] is not None:
                cx2, cy2 = self._img2_to_canvas2(ix2, iy2, off_x, off_y, total_rot)
                self.canvas2.create_oval(cx2 - r, cy2 - r, cx2 + r, cy2 + r,
                                         outline=colour, width=2, tags="annotations")
                if label:
                    self.canvas2.create_text(cx2 + r + 5, cy2, text=label, fill=colour,
                                             anchor=tk.W, tags="annotations",
                                             font=("TkDefaultFont", 9, "bold"))

        self.canvas1.tag_raise("annotations")
        if mode == "sidebyside":
            self.canvas2.tag_raise("annotations")

    # ----------------------------------------------------------------- Export

    def _export(self):
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        mode = self.mode_var.get()
        was_interacting = self._interacting
        self._interacting = False

        # ---- Render at native (1 source-pixel = 1 output-pixel) resolution ----
        current_zoom = self.zoom
        saved_pan_x, saved_pan_y = self.pan_x, self.pan_y

        # Best image resolution caps the output size so we don't produce a huge
        # grey-padded canvas when the user is zoomed far out.
        imgs_loaded = [img for img in self.images if img is not None]
        best_w = max((img.width  for img in imgs_loaded), default=1)
        best_h = max((img.height for img in imgs_loaded), default=1)

        w1 = max(self.canvas1.winfo_width(), 1)
        h1 = max(self.canvas1.winfo_height(), 1)
        out_w1 = max(1, min(int(round(w1 / current_zoom)), best_w))
        out_h1 = max(1, min(int(round(h1 / current_zoom)), best_h))

        self.zoom  = 1.0
        self.pan_x = saved_pan_x / current_zoom
        self.pan_y = saved_pan_y / current_zoom

        v1 = self._get_view(self.images[0], 0, 0, glob_rot, out_w1, out_h1, idx=0).convert("RGB")

        if mode == "overlay":
            v2 = self._get_view(self.images[1], off_x, off_y,
                                 total_rot, out_w1, out_h1, idx=1).convert("RGB")
            alpha = self.opacity_var.get()
            if self.images[0] and self.images[1]:
                result = Image.blend(v1, v2, alpha)
            elif self.images[0]:
                result = v1
            else:
                result = v2
            drw = ImageDraw.Draw(result)
            for ann in self.annotations:
                cx, cy = self._img1_to_canvas1(ann["img1_x"], ann["img1_y"], glob_rot)
                r = max(2, int(round(ann["radius"] * self.zoom)))
                drw.ellipse([cx - r, cy - r, cx + r, cy + r],
                            outline=ann["colour"], width=2)
                if ann.get("label"):
                    drw.text((cx + r + 5, cy - 8), ann["label"], fill=ann["colour"])
        else:
            w2 = max(self.canvas2.winfo_width(), 1)
            h2 = max(self.canvas2.winfo_height(), 1)
            out_w2 = max(1, min(int(round(w2 / current_zoom)), best_w))
            out_h2 = max(1, min(int(round(h2 / current_zoom)), best_h))
            v2 = self._get_view(self.images[1], off_x, off_y,
                                 total_rot, out_w2, out_h2, idx=1).convert("RGB")
            gap = 4
            result = Image.new("RGB", (out_w1 + gap + out_w2, max(out_h1, out_h2)), (40, 40, 40))
            result.paste(v1, (0, 0))
            result.paste(v2, (out_w1 + gap, 0))
            drw = ImageDraw.Draw(result)
            for ann in self.annotations:
                r = max(2, int(round(ann["radius"] * self.zoom)))
                # Left panel
                cx1e, cy1e = self._img1_to_canvas1(ann["img1_x"], ann["img1_y"], glob_rot)
                drw.ellipse([cx1e - r, cy1e - r, cx1e + r, cy1e + r],
                            outline=ann["colour"], width=2)
                if ann.get("label"):
                    drw.text((cx1e + r + 5, cy1e - 8), ann["label"], fill=ann["colour"])
                # Right panel
                if self.images[1] is not None:
                    cx2e, cy2e = self._img2_to_canvas2(ann["img2_x"], ann["img2_y"],
                                                       off_x, off_y, total_rot)
                    drw.ellipse([out_w1 + gap + cx2e - r, cy2e - r,
                                 out_w1 + gap + cx2e + r, cy2e + r],
                                outline=ann["colour"], width=2)
                    if ann.get("label"):
                        drw.text((out_w1 + gap + cx2e + r + 5, cy2e - 8),
                                 ann["label"], fill=ann["colour"])

        self.zoom  = current_zoom
        self.pan_x = saved_pan_x
        self.pan_y = saved_pan_y
        self._interacting = was_interacting

        path = filedialog.asksaveasfilename(
            title="Export view as PNG",
            defaultextension=".png",
            filetypes=[("PNG \u2013 lossless", "*.png"),
                       ("TIFF \u2013 lossless with metadata", "*.tif *.tiff")]
        )
        if path:
            result.save(path, compress_level=3)
            self.status_var.set(f"Exported \u2192 {path}")

    # ----------------------------------------------------------------- Crop export

    def _on_crop_mode_change(self):
        if self.crop_mode_var.get():
            self.level_mode_var.set(False)
            self.canvas1.delete("level_line")
            self.canvas2.delete("level_line")
            self._level_start = None
            self.annot_mode_var.set(False)
            self._align_guide_cursor = None
            self.align_mode_var.set(False)
            self.canvas1.delete("align_pts")
            self.canvas2.delete("align_pts")
            self.canvas2.delete("align_guide")
            self.status_var.set("Crop export  -  click first corner")
        else:
            self._crop_corner1 = None
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")
        active = (self.crop_mode_var.get() or self.level_mode_var.get()
                  or self.annot_mode_var.get() or self.align_mode_var.get())
        cur = "tcross" if active else "crosshair"
        self.canvas1.config(cursor=cur)
        self.canvas2.config(cursor=cur)

    def _draw_crop_preview(self, cursor_x, cursor_y):
        """Draw a live dashed rectangle on both canvases showing the prospective crop."""
        x0, y0 = self._crop_corner1
        for canvas in (self.canvas1, self.canvas2):
            canvas.delete("crop_preview")
            canvas.create_rectangle(x0, y0, cursor_x, cursor_y,
                                    outline="#ffcc88", width=1, dash=(6, 4),
                                    tags="crop_preview")

    def _on_crop_click(self, event):
        """Handle a canvas click in crop mode."""
        if self._crop_corner1 is None:
            self._crop_corner1 = (event.x, event.y)
            self.status_var.set("Crop export  -  first corner set; click second corner")
        else:
            x0, y0 = self._crop_corner1
            x1, y1 = event.x, event.y
            self.crop_mode_var.set(False)
            self._on_crop_mode_change()   # clears corner + preview, resets cursor
            self._do_export_crop(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _do_export_crop(self, x0, y0, x1, y1):
        """Render both images cropped to the canvas-coord rectangle at native resolution."""
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        mode = self.mode_var.get()
        was_interacting = self._interacting
        self._interacting = False

        # ---- Native-resolution crop ----
        pad = int(self.crop_pad_var.get())
        current_zoom = self.zoom
        saved_pan_x, saved_pan_y = self.pan_x, self.pan_y

        # Output dimensions: crop region scaled to 1 source pixel per output pixel
        out_crop_w = max(1, int(round((x1 - x0) / current_zoom)))
        out_crop_h = max(1, int(round((y1 - y0) / current_zoom)))
        out_w = out_crop_w + 2 * pad
        out_h = out_crop_h + 2 * pad

        # At zoom=1: pan must place canvas-pixel x0 at output column `pad`
        self.zoom  = 1.0
        self.pan_x = (saved_pan_x - x0) / current_zoom + pad
        self.pan_y = (saved_pan_y - y0) / current_zoom + pad

        v1 = self._get_view(self.images[0], 0, 0, glob_rot, out_w, out_h, idx=0).convert("RGB")
        v2 = self._get_view(self.images[1], off_x, off_y,
                             total_rot, out_w, out_h, idx=1).convert("RGB")

        # Draw annotations while zoom=1 and pan are in export coords
        if mode == "overlay":
            alpha = self.opacity_var.get()
            if self.images[0] and self.images[1]:
                result = Image.blend(v1, v2, alpha)
            elif self.images[0]:
                result = v1
            else:
                result = v2
            drw = ImageDraw.Draw(result)
            for ann in self.annotations:
                cx, cy = self._img1_to_canvas1(ann["img1_x"], ann["img1_y"], glob_rot)
                r = max(2, int(round(ann["radius"] * self.zoom)))
                drw.ellipse([cx - r, cy - r, cx + r, cy + r],
                            outline=ann["colour"], width=2)
                if ann.get("label"):
                    drw.text((cx + r + 5, cy - 8), ann["label"], fill=ann["colour"])
        else:
            gap = 4
            result = Image.new("RGB", (out_w * 2 + gap, out_h), (40, 40, 40))
            result.paste(v1, (0, 0))
            result.paste(v2, (out_w + gap, 0))
            drw = ImageDraw.Draw(result)
            for ann in self.annotations:
                r = max(2, int(round(ann["radius"] * self.zoom)))
                cx1, cy1 = self._img1_to_canvas1(ann["img1_x"], ann["img1_y"], glob_rot)
                drw.ellipse([cx1 - r, cy1 - r, cx1 + r, cy1 + r],
                            outline=ann["colour"], width=2)
                if ann.get("label"):
                    drw.text((cx1 + r + 5, cy1 - 8), ann["label"], fill=ann["colour"])
                if self.images[1] is not None:
                    cx2, cy2 = self._img2_to_canvas2(ann["img2_x"], ann["img2_y"],
                                                     off_x, off_y, total_rot)
                    drw.ellipse([out_w + gap + cx2 - r, cy2 - r,
                                 out_w + gap + cx2 + r, cy2 + r],
                                outline=ann["colour"], width=2)
                    if ann.get("label"):
                        drw.text((out_w + gap + cx2 + r + 5, cy2 - 8),
                                 ann["label"], fill=ann["colour"])

        self.zoom  = current_zoom
        self.pan_x = saved_pan_x
        self.pan_y = saved_pan_y
        self._interacting = was_interacting

        path = filedialog.asksaveasfilename(
            title="Export crop as PNG",
            defaultextension=".png",
            filetypes=[("PNG \u2013 lossless", "*.png"),
                       ("TIFF \u2013 lossless", "*.tif *.tiff")]
        )
        if path:
            result.save(path, compress_level=3)
            self.status_var.set(f"Crop exported \u2192 {path}  "
                                f"({result.width}\u00d7{result.height} px)")

    # ----------------------------------------------------------------- Session save/load

    def _save_session(self):
        """Save all state to a JSON session file."""
        session = {
            "version": 1,
            "image_paths": self.image_paths,
            "mode": self.mode_var.get(),
            "opacity": self.opacity_var.get(),
            "zoom": self.zoom,
            "pan_x": self.pan_x,
            "pan_y": self.pan_y,
            "alignment": {
                "off_x": self.off_x_var.get(),
                "off_y": self.off_y_var.get(),
                "rot": self.rot_var.get(),
                "glob_rot": self.glob_rot_var.get(),
            },
            "annotations": self.annotations,
            "align_pts_img1": self._align_pts_img1,
            "align_pts_img2": self._align_pts_img2,
            "adjustments": [
                {k: v.get() for k, v in d.items()} for d in self.adj_vars
            ],
        }
        path = filedialog.asksaveasfilename(
            title="Save session",
            defaultextension=".json",
            filetypes=[("Session file", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        with open(path, "w") as f:
            json.dump(session, f, indent=2)
        self.status_var.set(f"Session saved \u2192 {path}")

    def _load_session(self):
        """Load a session from a JSON file with an interactive path-verification dialog."""
        path = filedialog.askopenfilename(
            title="Load session",
            filetypes=[("Session file", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path) as f:
                session = json.load(f)
        except Exception as e:
            messagebox.showerror("Load error", f"Could not read session file:\n{e}",
                                 parent=self.root)
            return

        # Dialog: show saved paths and let the user optionally override each
        dlg = tk.Toplevel(self.root)
        dlg.title("Load Session \u2014 Verify image paths")
        dlg.configure(bg="#2b2b2b")
        dlg.resizable(True, False)
        dlg.transient(self.root)
        dlg.grab_set()

        saved_paths = list(session.get("image_paths", [None, None]))
        while len(saved_paths) < 2:
            saved_paths.append(None)
        path_vars = [tk.StringVar(value=p or "") for p in saved_paths]

        tk.Label(dlg, text="Image files to load  (edit or Browse to choose different files):",
                 bg="#2b2b2b", fg="#ccc",
                 font=("TkDefaultFont", 9, "bold")).pack(padx=12, pady=(10, 4), anchor=tk.W)

        for i, (pv, label) in enumerate(zip(path_vars, ["Image 1:", "Image 2:"])):
            row = tk.Frame(dlg, bg="#2b2b2b")
            row.pack(fill=tk.X, padx=10, pady=3)
            tk.Label(row, text=label, bg="#2b2b2b", fg="#aaa",
                     width=8, anchor=tk.W).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=pv, bg="#444", fg="white",
                     insertbackground="white", relief=tk.FLAT,
                     width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            def _browse(var=pv):
                p = filedialog.askopenfilename(
                    filetypes=[
                        ("Image files",
                         "*.tif *.tiff *.TIF *.TIFF *.png *.PNG "
                         "*.jpg *.JPG *.jpeg *.JPEG *.bmp *.BMP"),
                        ("All files", "*.*")
                    ])
                if p:
                    var.set(p)
            tk.Button(row, text="Browse\u2026", command=_browse,
                      bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                      cursor="hand2").pack(side=tk.LEFT, padx=4)

        btn_row = tk.Frame(dlg, bg="#2b2b2b")
        btn_row.pack(pady=10)
        confirmed = [False]

        def _on_ok():
            confirmed[0] = True
            dlg.destroy()

        tk.Button(btn_row, text="Load", command=_on_ok,
                  bg="#336633", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg="#555", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)

        self.root.wait_window(dlg)
        if not confirmed[0]:
            return

        # Load images from (possibly updated) paths
        final_paths = [pv.get().strip() or None for pv in path_vars]
        for i, p in enumerate(final_paths):
            if p:
                try:
                    img = Image.open(p)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    self.images[i] = img
                    self.image_paths[i] = p
                    self.preview_images[i], self.preview_scales[i] = self._make_preview(img)
                    self._rotated_cache[i] = None
                    self._last_rot[i] = None
                    self._rotated_preview_cache[i] = None
                    self._last_rot_preview[i] = None
                except Exception as e:
                    messagebox.showerror("Load error",
                                         f"Could not load image {i + 1}:\n{p}\n\n{e}",
                                         parent=self.root)

        # Restore alignment
        a = session.get("alignment", {})
        self.off_x_var.set(str(a.get("off_x", "0")))
        self.off_y_var.set(str(a.get("off_y", "0")))
        self.rot_var.set(str(a.get("rot", "0.0")))
        self.glob_rot_var.set(str(a.get("glob_rot", "0.0")))
        # Restore view
        if "mode" in session:
            self.mode_var.set(session["mode"])
            self._on_mode_change()
        if "opacity" in session:
            self.opacity_var.set(float(session["opacity"]))
        if "zoom" in session:
            self.zoom = float(session["zoom"])
        if "pan_x" in session:
            self.pan_x = float(session["pan_x"])
        if "pan_y" in session:
            self.pan_y = float(session["pan_y"])
        # Restore annotations and alignment points
        if "annotations" in session:
            self.annotations = session["annotations"]
        if "align_pts_img1" in session:
            self._align_pts_img1 = [tuple(p) for p in session["align_pts_img1"]]
        if "align_pts_img2" in session:
            self._align_pts_img2 = [tuple(p) for p in session["align_pts_img2"]]
        # Restore per-image adjustments
        for i, d in enumerate(session.get("adjustments", [{}, {}])[:2]):
            for k in ("brightness", "contrast", "blacks", "whites"):
                if k in d:
                    self.adj_vars[i][k].set(float(d[k]))

        self._schedule_render()
        self.status_var.set(f"Session loaded from {path}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageComparer(root)
    root.mainloop()