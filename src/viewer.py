import math
import os
import tkinter as tk
from tkinter import filedialog

from PIL import Image, ImageTk

_RAW_EXTENSIONS = {'.arw', '.nef', '.cr2', '.cr3', '.orf', '.rw2', '.dng', '.raf', '.pef', '.srw'}


def _open_image(path):
    """Open a standard or camera RAW image and return a PIL Image."""
    if os.path.splitext(path)[1].lower() in _RAW_EXTENSIONS:
        import rawpy
        import numpy as np
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True)
        return Image.fromarray(rgb)
    return Image.open(path)

class ViewerMixin:
    def load_image(self, idx):
        path = filedialog.askopenfilename(
            title=f"Open Image {idx + 1}",
            filetypes=[
                ("Image files",
                 "*.tif *.tiff *.TIF *.TIFF "
                 "*.png *.PNG "
                 "*.jpg *.JPG *.jpeg *.JPEG "
                 "*.bmp *.BMP *.webp *.WEBP "
                 "*.arw *.ARW *.nef *.NEF *.cr2 *.CR2 *.cr3 *.CR3 "
                 "*.dng *.DNG *.orf *.ORF *.rw2 *.RW2 *.raf *.RAF"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        img = _open_image(path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        self.images[idx] = img
        self.image_paths[idx] = path
        self.preview_images[idx], self.preview_scales[idx] = self._make_preview(img)
        self._rotated_cache[idx] = None
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
        self.canvas1.move("img", dx, dy)
        self.canvas2.move("img", dx, dy)
        self.canvas1.move("annotations", dx, dy)
        self.canvas2.move("annotations", dx, dy)
        self._draw_cursors()
        self._schedule_render()
        self._schedule_quality_render()

    def _on_zoom(self, event):
        if hasattr(event, "delta") and event.delta:
            factor = 1.0015 ** event.delta
        elif getattr(event, "num", None) == 4:
            factor = 1.12
        else:
            factor = 1 / 1.12
        factor = max(0.5, min(2.0, factor))
        cx, cy = event.x, event.y
        self.pan_x = cx - (cx - self.pan_x) * factor
        self.pan_y = cy - (cy - self.pan_y) * factor
        self.zoom *= factor
        self.zoom = max(0.02, min(100.0, self.zoom))
        self._interacting = True
        self._schedule_render()
        self._schedule_quality_render()

    def _on_mouse_move(self, event):
        self.cursor_pos = (event.x, event.y)
        img_x = (event.x - self.pan_x) / self.zoom
        img_y = (event.y - self.pan_y) / self.zoom
        self.status_var.set(
            f"Image coords: ({img_x:.1f}, {img_y:.1f})  |  "
            f"Zoom: {self.zoom:.2f}x  |  "
            f"Offset: ({self.off_x_var.get()}, {self.off_y_var.get()})  |  "
            f"Rotation: {self.rot_var.get()}deg"
        )
        self._draw_cursors()
        if self.align_mode_var.get():
            if event.widget is self.canvas2:
                self._align_guide_cursor = (event.x, event.y)
            else:
                self._align_guide_cursor = None
            self._draw_align_guide()
        if self.crop_mode_var.get() and self._crop_corner1 is not None:
            self._draw_crop_preview(event.x, event.y)

    def _schedule_quality_render(self):
        if self._quality_timer is not None:
            self.root.after_cancel(self._quality_timer)
        self._quality_timer = self.root.after(150, self._on_interaction_end)

    def _on_interaction_end(self):
        self._quality_timer = None
        self._interacting = False
        self._render()

    def _make_preview(self, img, max_dim=2200):
        largest = max(img.width, img.height)
        if largest <= max_dim:
            return img, 1.0
        scale = max_dim / float(largest)
        w = max(1, int(round(img.width * scale)))
        h = max(1, int(round(img.height * scale)))
        return img.resize((w, h), resample=Image.BILINEAR), scale

    def _schedule_render(self):
        if not self._render_pending:
            self._render_pending = True
            self.root.after(16, self._render)

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
        placeholder = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
        if img is None:
            return placeholder

        source = img
        source_scale = 1.0
        rot_cache = self._rotated_cache
        rot_last = self._last_rot
        if self._interacting and idx is not None and self.preview_images[idx] is not None:
            source = self.preview_images[idx]
            source_scale = self.preview_scales[idx]
            rot_cache = self._rotated_preview_cache
            rot_last = self._last_rot_preview

        if rotation != 0.0:
            if idx is not None and rot_last[idx] == rotation and rot_cache[idx] is not None:
                working = rot_cache[idx]
            else:
                working = source.rotate(-rotation, resample=Image.BICUBIC, expand=False)
                if idx is not None:
                    rot_cache[idx] = working
                    rot_last[idx] = rotation
        else:
            working = source

        zoom = max(self.zoom / source_scale, 1e-6)
        off_x = off_x * source_scale
        off_y = off_y * source_scale
        paste_x = self.pan_x + off_x * zoom
        paste_y = self.pan_y + off_y * zoom

        src_x0_f = max(0.0, (0.0 - paste_x) / zoom)
        src_y0_f = max(0.0, (0.0 - paste_y) / zoom)
        src_x1_f = min(float(working.width), (canvas_w - paste_x) / zoom)
        src_y1_f = min(float(working.height), (canvas_h - paste_y) / zoom)

        if src_x1_f <= src_x0_f or src_y1_f <= src_y0_f:
            return placeholder

        src_x0 = max(0, int(math.floor(src_x0_f)))
        src_y0 = max(0, int(math.floor(src_y0_f)))
        src_x1 = min(working.width, int(math.ceil(src_x1_f)))
        src_y1 = min(working.height, int(math.ceil(src_y1_f)))

        if src_x1 <= src_x0 or src_y1 <= src_y0:
            return placeholder

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
            canvas.create_line(0, cy, w, cy, fill="#ff3333", tags="cursor", width=1)
            canvas.create_line(cx, 0, cx, h, fill="#ff3333", tags="cursor", width=1)
            r = 6
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               outline="#ff3333", tags="cursor", width=1)
            canvas.tag_raise("cursor")

    def _get_alignment_values(self):
        try:
            return (
                int(float(self.off_x_var.get())),
                int(float(self.off_y_var.get())),
                float(self.rot_var.get()),
                float(self.glob_rot_var.get()),
            )
        except ValueError:
            return 0, 0, 0.0, 0.0

    def _rotate_display_point(self, x, y, cx, cy, rot_deg):
        if not rot_deg:
            return x, y
        theta = math.radians(rot_deg)
        dx, dy = x - cx, y - cy
        return (
            cx + dx * math.cos(theta) - dy * math.sin(theta),
            cy + dx * math.sin(theta) + dy * math.cos(theta),
        )

    def _unrotate_display_point(self, x, y, cx, cy, rot_deg):
        if not rot_deg:
            return x, y
        theta = math.radians(rot_deg)
        dx, dy = x - cx, y - cy
        return (
            cx + dx * math.cos(theta) + dy * math.sin(theta),
            cy - dx * math.sin(theta) + dy * math.cos(theta),
        )

    def _expected_align_canvas(self):
        return 0 if len(self._align_pts_img1) <= len(self._align_pts_img2) else 1

    def _on_canvas_leave(self, event):
        if event.widget is self.canvas2:
            self._align_guide_cursor = None
            self.canvas2.delete("align_guide")
        if self.crop_mode_var.get() and self._crop_corner1 is not None:
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")

    def _img1_to_canvas1(self, img_x, img_y, glob_rot):
        if self.images[0] is not None:
            cx0, cy0 = self.images[0].width / 2.0, self.images[0].height / 2.0
        else:
            cx0 = cy0 = 0.0
        rx, ry = self._rotate_display_point(img_x, img_y, cx0, cy0, glob_rot)
        return self.pan_x + rx * self.zoom, self.pan_y + ry * self.zoom

    def _img1_to_canvas2(self, img_x, img_y, off_x, off_y, total_rot):
        if self.images[1] is not None:
            cx2, cy2 = self.images[1].width / 2.0, self.images[1].height / 2.0
        else:
            cx2 = cy2 = 0.0
        rx, ry = self._rotate_display_point(img_x, img_y, cx2, cy2, total_rot)
        return (
            self.pan_x + off_x * self.zoom + rx * self.zoom,
            self.pan_y + off_y * self.zoom + ry * self.zoom,
        )

    def _canvas_to_img1(self, canvas_x, canvas_y, canvas_is_2=False):
        _, _, _, glob_rot = self._get_alignment_values()
        rx = (canvas_x - self.pan_x) / self.zoom
        ry = (canvas_y - self.pan_y) / self.zoom
        cx0 = self.images[0].width / 2.0 if self.images[0] else 0.0
        cy0 = self.images[0].height / 2.0 if self.images[0] else 0.0
        return self._unrotate_display_point(rx, ry, cx0, cy0, glob_rot)

    def _canvas_to_img2(self, canvas_x, canvas_y):
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        rx = (canvas_x - self.pan_x) / self.zoom - off_x
        ry = (canvas_y - self.pan_y) / self.zoom - off_y
        cx2 = self.images[1].width / 2.0 if self.images[1] else 0.0
        cy2 = self.images[1].height / 2.0 if self.images[1] else 0.0
        return self._unrotate_display_point(rx, ry, cx2, cy2, total_rot)
