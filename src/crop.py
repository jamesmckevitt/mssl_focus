import datetime
import tkinter as tk
from tkinter import filedialog

from PIL import Image, ImageDraw, ImageFont, ImageTk

from .metadata import APP_VERSION


class CropMixin:
    def _attach_legend_sidebar(self, result, font_size=None):
        data = self._legend_data()
        if not data:
            return result
        img_h = result.height
        if font_size is None:
            font_size = max(12, img_h // 50)
        pad = max(8, font_size // 2)
        row_h = int(font_size * 1.7)
        swatch = int(font_size * 0.9)
        try:
            legend_font = ImageFont.load_default(size=font_size)
        except TypeError:
            legend_font = ImageFont.load_default()
        texts = [
            f" {label}  (n={count})" if label else f" (n={count})"
            for _, label, count in data
        ]
        tmp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        max_text_w = max(tmp_draw.textbbox((0, 0), t, font=legend_font)[2] for t in texts)
        box_w = pad * 2 + swatch + 6 + max_text_w
        box_h = pad * 2 + len(data) * row_h
        sidebar_w = box_w + pad * 2
        final = Image.new("RGB", (result.width + sidebar_w, img_h), (30, 30, 30))
        final.paste(result, (0, 0))
        drw = ImageDraw.Draw(final)
        x0 = result.width + pad
        y0 = max(pad, (img_h - box_h) // 2)
        drw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill="#1e1e1e", outline="#555555")
        for i, ((colour, _label, _count), text) in enumerate(zip(data, texts)):
            row_y = y0 + pad + i * row_h
            sy = row_y + (row_h - swatch) // 2
            drw.rectangle([x0 + pad, sy, x0 + pad + swatch, sy + swatch], fill=colour)
            drw.text((x0 + pad + swatch + 6, sy), text, fill=colour, font=legend_font)
        return final

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
        x0, y0 = self._crop_corner1
        for canvas in (self.canvas1, self.canvas2):
            canvas.delete("crop_preview")
            canvas.create_rectangle(x0, y0, cursor_x, cursor_y,
                                    outline="#ffcc88", width=1, dash=(6, 4),
                                    tags="crop_preview")

    def _on_crop_click(self, event):
        if self._crop_corner1 is None:
            self._crop_corner1 = (event.x, event.y)
            self.status_var.set("Crop export  -  first corner set; click second corner")
        else:
            x0, y0 = self._crop_corner1
            x1, y1 = event.x, event.y
            self.crop_mode_var.set(False)
            self._on_crop_mode_change()
            self._do_export_crop(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _draw_watermark_pil(self, img):
        font_size = max(8, min(img.width, img.height) // 80)
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()
        text = f"MSSL Filter Inspector v{APP_VERSION}  |  {datetime.date.today().isoformat()}"
        drw = ImageDraw.Draw(img)
        bb = drw.textbbox((0, 0), text, font=font)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        pad = max(4, font_size // 3)
        bx = pad
        by = img.height - pad - th - pad * 2
        drw.rectangle([bx, by, bx + tw + pad * 2, by + th + pad * 2],
                      fill="#1e1e1e", outline="#555555")
        drw.text((bx + pad - bb[0], by + pad - bb[1]),
                 text, fill="#cccccc", font=font)

    def _render_crop_pil(self, x0, y0, x1, y1, label_size=12, legend_size=None, ann_width=None):
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        mode = self.mode_var.get()
        was_interacting = self._interacting
        self._interacting = False

        pad = int(self.crop_pad_var.get())
        current_zoom = self.zoom
        saved_pan_x, saved_pan_y = self.pan_x, self.pan_y

        out_crop_w = max(1, int(round((x1 - x0) / current_zoom)))
        out_crop_h = max(1, int(round((y1 - y0) / current_zoom)))
        out_w = out_crop_w + 2 * pad
        out_h = out_crop_h + 2 * pad

        self.zoom = 1.0
        self.pan_x = (saved_pan_x - x0) / current_zoom + pad
        self.pan_y = (saved_pan_y - y0) / current_zoom + pad

        v1 = self._get_view(self.images[0], 0, 0, glob_rot, out_w, out_h, idx=0).convert("RGB")
        v2 = self._get_view(self.images[1], off_x, off_y,
                            total_rot, out_w, out_h, idx=1).convert("RGB")

        zoom_inv = 1.0 / current_zoom if current_zoom > 0 else 1.0
        pil_label_size = max(1, round(label_size * zoom_inv))
        leg_size = legend_size if legend_size is not None else self.canvas_legend_size_var.get()
        pil_legend_size = max(1, round(leg_size * zoom_inv))
        _aw = ann_width if ann_width is not None else self.annot_width_var.get()
        ann_width = max(1, round(_aw * zoom_inv))

        try:
            label_font = ImageFont.load_default(size=pil_label_size)
        except TypeError:
            label_font = ImageFont.load_default()

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
                            outline=ann["colour"], width=ann_width)
                if ann.get("label"):
                    drw.text((cx + r + 5, cy - pil_label_size // 2),
                             ann["label"], fill=ann["colour"], font=label_font)
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
                            outline=ann["colour"], width=ann_width)
                if ann.get("label"):
                    drw.text((cx1 + r + 5, cy1 - pil_label_size // 2),
                             ann["label"], fill=ann["colour"], font=label_font)
                if self.images[1] is not None:
                    cx2, cy2 = self._img2_to_canvas2(ann["img2_x"], ann["img2_y"],
                                                     off_x, off_y, total_rot)
                    drw.ellipse([out_w + gap + cx2 - r, cy2 - r,
                                 out_w + gap + cx2 + r, cy2 + r],
                                outline=ann["colour"], width=ann_width)
                    if ann.get("label"):
                        drw.text((out_w + gap + cx2 + r + 5, cy2 - pil_label_size // 2),
                                 ann["label"], fill=ann["colour"], font=label_font)

        self._draw_watermark_pil(result)
        result = self._attach_legend_sidebar(result, font_size=pil_legend_size)
        self.zoom = current_zoom
        self.pan_x = saved_pan_x
        self.pan_y = saved_pan_y
        self._interacting = was_interacting
        return result

    def _show_crop_preview(self, x0, y0, x1, y1):
        default_label_size = self.annot_label_size_var.get()
        default_legend_size = self.canvas_legend_size_var.get()

        win = tk.Toplevel(self.root)
        win.title("Crop preview  -  adjust sizes, then export")
        win.configure(bg="#2b2b2b")
        win.wait_visibility()
        win.grab_set()

        label_size_var = tk.IntVar(value=default_label_size)
        legend_size_var = tk.IntVar(value=default_legend_size)
        ann_width_var = tk.DoubleVar(value=self.annot_width_var.get())
        photo_ref = [None]
        current_result = [None]

        preview_lbl = tk.Label(win, bg="#1a1a1a")
        preview_lbl.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        def render_preview(*_):
            result = self._render_crop_pil(
                x0, y0, x1, y1,
                label_size=label_size_var.get(),
                legend_size=legend_size_var.get(),
                ann_width=ann_width_var.get(),
            )
            current_result[0] = result
            max_w = max(400, min(self.root.winfo_screenwidth() - 120, 1400))
            max_h = max(300, min(self.root.winfo_screenheight() - 280, 800))
            scale = min(max_w / result.width, max_h / result.height, 1.0)
            if scale < 1.0:
                preview = result.resize(
                    (int(result.width * scale), int(result.height * scale)),
                    Image.LANCZOS,
                )
            else:
                preview = result
            photo = ImageTk.PhotoImage(preview)
            preview_lbl.config(image=photo)
            photo_ref[0] = photo

        render_preview()

        ctrl = tk.Frame(win, bg="#2b2b2b")
        ctrl.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        for text, var, lo, hi, res in [
            ("Annotation label size (pt)", label_size_var, 6, 60, 1),
            ("Legend text size (pt)", legend_size_var, 6, 60, 1),
            ("Annotation width", ann_width_var, 0.5, 3.5, 0.5),
        ]:
            col = tk.Frame(ctrl, bg="#2b2b2b")
            col.pack(side=tk.LEFT, padx=16)
            tk.Label(col, text=text, bg="#2b2b2b", fg="#ccc",
                     font=("TkDefaultFont", 9)).pack(anchor=tk.W)
            tk.Scale(col, variable=var, from_=lo, to=hi,
                     resolution=res, orient=tk.HORIZONTAL, length=220,
                     bg="#2b2b2b", fg="#ccc", troughcolor="#444",
                     highlightthickness=0,
                     command=render_preview).pack()

        btn = tk.Frame(win, bg="#2b2b2b")
        btn.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(2, 8))

        def do_export():
            result = current_result[0]
            if result is None:
                return
            path = filedialog.asksaveasfilename(
                title="Export crop as PNG",
                defaultextension=".png",
                filetypes=[("PNG - lossless", "*.png"),
                           ("TIFF - lossless", "*.tif *.tiff")],
                parent=win,
            )
            if path:
                result.save(path, compress_level=3)
                self.status_var.set(
                    f"Crop exported -> {path}  ({result.width}x{result.height} px)"
                )
                win.destroy()

        tk.Button(btn, text="Export", command=do_export,
                  bg="#336633", fg="white", relief=tk.FLAT, padx=16, pady=4,
                  cursor="hand2",
                  font=("TkDefaultFont", 10, "bold")).pack(side=tk.RIGHT, padx=4)
        tk.Button(btn, text="Cancel", command=win.destroy,
                  bg="#555", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  cursor="hand2").pack(side=tk.RIGHT, padx=4)

    def _do_export_crop(self, x0, y0, x1, y1):
        self._show_crop_preview(x0, y0, x1, y1)
