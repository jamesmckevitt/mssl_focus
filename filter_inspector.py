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
from tkinter import filedialog, ttk
from PIL import Image, ImageTk
import numpy as np


class ImageComparer:
    def __init__(self, root):
        self.root = root
        self.root.title("Engineering Image Comparer")
        self.root.geometry("1400x900")
        self.root.configure(bg="#2b2b2b")

        self.images = [None, None]       # Original PIL images (full res)
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

        tk.Label(toolbar2, text="Image 2 alignment — Offset X:",
                 bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(8, 2))
        self.off_x_var = tk.StringVar(value="0")
        self._make_spinbox(toolbar2, self.off_x_var, -9999, 9999)

        tk.Label(toolbar2, text="Y:", bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(6, 2))
        self.off_y_var = tk.StringVar(value="0")
        self._make_spinbox(toolbar2, self.off_y_var, -9999, 9999)

        tk.Label(toolbar2, text="  Rotation (°):", bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(12, 2))
        self.rot_var = tk.StringVar(value="0.0")
        self._make_spinbox(toolbar2, self.rot_var, -180, 180, inc=0.1, width=6)

        tk.Label(toolbar2, text="  [Arrow keys nudge X/Y · Shift+Arrow nudges rotation]",
                 bg="#2f2f2f", fg="#888", font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=12)

        tk.Button(toolbar2, text="Reset alignment",
                  command=self._reset_alignment,
                  bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

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
            canvas.bind("<ButtonPress-1>", self._on_pan_start)
            canvas.bind("<B1-Motion>", self._on_pan)
            canvas.bind("<Configure>", lambda e: self._schedule_render())

        self.root.bind("<Left>",  lambda e: self._nudge(-1, 0, 0))
        self.root.bind("<Right>", lambda e: self._nudge(1,  0, 0))
        self.root.bind("<Up>",    lambda e: self._nudge(0, -1, 0))
        self.root.bind("<Down>",  lambda e: self._nudge(0,  1, 0))
        self.root.bind("<Shift-Left>",  lambda e: self._nudge(0, 0, -0.1))
        self.root.bind("<Shift-Right>", lambda e: self._nudge(0, 0,  0.1))

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
                ("Image files", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.webp"),
                ("All files", "*.*")
            ])
        if not path:
            return
        img = Image.open(path)
        # Convert to RGB for display (handles 16-bit, RGBA, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        self.images[idx] = img
        self.preview_images[idx], self.preview_scales[idx] = self._make_preview(img)
        self._rotated_cache[idx] = None  # Invalidate rotation cache
        self._last_rot[idx] = None
        self._rotated_preview_cache[idx] = None
        self._last_rot_preview[idx] = None
        self.status_var.set(f"Image {idx + 1} loaded: {path}  ({img.width}×{img.height})")
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
        # Move canvas items directly — instant, no PIL re-render needed
        self.canvas1.move("img", dx, dy)
        self.canvas2.move("img", dx, dy)
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
        # Convert canvas coords → image-1 pixel coords
        img_x = (event.x - self.pan_x) / self.zoom
        img_y = (event.y - self.pan_y) / self.zoom
        self.status_var.set(
            f"Image coords: ({img_x:.1f}, {img_y:.1f})  |  "
            f"Zoom: {self.zoom:.2f}×  |  "
            f"Offset: ({self.off_x_var.get()}, {self.off_y_var.get()})  |  "
            f"Rotation: {self.rot_var.get()}°"
        )
        self._draw_cursors()

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
        except ValueError:
            off_x, off_y, rot = 0, 0, 0.0

        w1 = max(self.canvas1.winfo_width(), 1)
        h1 = max(self.canvas1.winfo_height(), 1)

        if mode == "overlay":
            v1 = self._get_view(self.images[0], 0, 0, 0.0, w1, h1, idx=0)
            v2 = self._get_view(self.images[1], off_x, off_y, rot, w1, h1, idx=1)
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

            v1 = self._get_view(self.images[0], 0, 0, 0.0, w1, h1, idx=0)
            v2 = self._get_view(self.images[1], off_x, off_y, rot, w2, h2, idx=1)

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

        self._draw_cursors()

    def _get_view(self, img, off_x, off_y, rotation, canvas_w, canvas_h, idx=None):
        """Return a canvas_w × canvas_h PIL image showing the current view."""
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

        # Apply rotation with caching — rotation (BICUBIC) is the most expensive step
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


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageComparer(root)
    root.mainloop()