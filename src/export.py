"""Export a region of the view, with markers, legend and watermark, as an image."""

import datetime
import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import geometry as geo
from . import theme
from .imaging import blank_frame
from .metadata import APP_VERSION
from .pair import BACKLIT, FRONTLIT, marker_text
from .viewer import CURRENT, REFERENCE

MAX_EXPORT_PIXELS = 160e6
GAP = 4


def _font(size):
    try:
        return ImageFont.load_default(size=max(6, int(size)))
    except TypeError:  # Pillow without a scalable default font
        return ImageFont.load_default()


class ExportMixin:
    def export_view(self):
        """Export everything currently visible in the first panel."""
        if not self.pairs[CURRENT].has_any_image():
            self.set_status("Load an image before exporting.")
            return
        canvas = self.panes[0].canvas
        self.show_export_preview(0, 0, canvas.winfo_width(), canvas.winfo_height())

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _export_geometry(self, x0, y0, x1, y1, rows):
        """Output scale, padding and panel size for a canvas rectangle."""
        pad = max(0, int(self.crop_pad_var.get()))
        panels = len(rows) * (1 if self.mode_var.get() == "overlay" else 2)
        world_w = max(1.0, (x1 - x0) / self.zoom)
        world_h = max(1.0, (y1 - y0) / self.zoom)
        # Native resolution of the current backlit image, unless that would be enormous.
        scale = min(1.0, math.sqrt(MAX_EXPORT_PIXELS / (world_w * world_h * panels)))
        width = max(1, int(round(world_w * scale))) + 2 * pad
        height = max(1, int(round(world_h * scale))) + 2 * pad
        world_x0 = (x0 - self.pan_x) / self.zoom
        world_y0 = (y0 - self.pan_y) / self.zoom
        view = geo.translation(pad, pad) @ geo.scaling(scale) @ geo.translation(-world_x0, -world_y0)
        return view, scale, (width, height)

    def _export_images(self, x0, y0, x1, y1, rows):
        """The image part of an export (slow); markers and text are added per preview."""
        view, scale, size = self._export_geometry(x0, y0, x1, y1, rows)
        overlay = self.mode_var.get() == "overlay"
        rendered = []
        for row in rows:
            if overlay:
                frames = [self._compose_pane(row, BACKLIT, size, view, True) or blank_frame(size)]
            else:
                frames = [self._render_frame(row, idx, size, view, True) or blank_frame(size)
                          for idx in (BACKLIT, FRONTLIT)]
            rendered.append((row, frames))
        return {"view": view, "scale": scale, "size": size, "rows": rendered}

    def _compose_export(self, images, label_size, legend_size, line_width):
        view, scale, (width, height) = images["view"], images["scale"], images["size"]
        rows = images["rows"]
        # Sizes are given as on screen; convert to output pixels.
        per_screen_px = scale / self.zoom
        px_per_point = self.root.winfo_fpixels("1p")
        label_font = _font(label_size * px_per_point * per_screen_px)
        legend_font = _font(legend_size * px_per_point * per_screen_px)
        stroke = max(1, int(round(line_width * per_screen_px)))
        with_titles = len(rows) > 1
        title_font = _font(max(14, height // 45))
        title_h = int(title_font.size * 2.0) if with_titles else 0

        panel_count = len(rows[0][1])
        total_w = width * panel_count + GAP * (panel_count - 1)
        total_h = (height + title_h) * len(rows) + GAP * (len(rows) - 1)
        result = Image.new("RGB", (total_w, total_h), (40, 40, 40))
        draw = ImageDraw.Draw(result)

        for n, (row, frames) in enumerate(rows):
            top = n * (height + title_h + GAP)
            pair = self.pairs[row]
            if with_titles:
                name = ("Reference: " if row == REFERENCE else "Current: ") + (pair.label or "untitled")
                draw.text((title_font.size // 2, top + title_font.size // 2), name, fill="#dddddd",
                          font=title_font)
            to_output = view @ self.world_matrix(row, BACKLIT)
            marker_scale = geo.scale_of(to_output)
            for col, frame in enumerate(frames):
                # Markers are drawn on the panel itself so they never spill into its neighbour.
                panel = frame.copy()
                panel_draw = ImageDraw.Draw(panel)
                for ann in pair.annotations:
                    cx, cy = geo.apply(to_output, ann["img1_x"], ann["img1_y"])
                    radius = max(2.0, ann["radius"] * marker_scale)
                    if cx + radius < 0 or cy + radius < 0 or cx - radius > width or cy - radius > height:
                        continue
                    panel_draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                                       outline=ann["colour"], width=stroke)
                    text = marker_text(ann)
                    if text:
                        panel_draw.text((cx + radius + stroke + 3, cy), text, fill=ann["colour"],
                                        font=label_font, anchor="lm")
                result.paste(panel, (col * (width + GAP), top + title_h))

        self._draw_watermark(result)
        legends = [(self.pairs[row].label if with_titles else None, self.pairs[row].legend())
                   for row, _frames in rows]
        return self._attach_legend(result, legends, legend_font)

    @staticmethod
    def _draw_watermark(img):
        size = max(10, min(img.width, img.height) // 80)
        font = _font(size)
        text = f"MSSL FOCUS v{APP_VERSION}  |  {datetime.date.today().isoformat()}"
        draw = ImageDraw.Draw(img)
        box = draw.textbbox((0, 0), text, font=font)
        text_w, text_h = box[2] - box[0], box[3] - box[1]
        pad = max(4, size // 3)
        x = pad
        y = img.height - text_h - pad * 3
        draw.rectangle([x, y, x + text_w + pad * 2, y + text_h + pad * 2], fill="#1e1e1e", outline="#555555")
        draw.text((x + pad - box[0], y + pad - box[1]), text, fill="#cccccc", font=font)

    @staticmethod
    def _attach_legend(result, legends, font):
        legends = [(title, data) for title, data in legends if data]
        if not legends:
            return result
        line = int(font.size * 1.7)
        swatch = int(font.size * 0.9)
        pad = max(8, font.size // 2)
        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        rows = []  # (kind, colour, text)
        for title, data in legends:
            if title:
                rows.append(("title", "#dddddd", title))
            for colour, text in data:
                rows.append(("entry", colour, text))
            rows.append(("gap", None, ""))
        rows.pop()
        text_w = max(measure.textbbox((0, 0), text, font=font)[2] for _k, _c, text in rows)
        box_w = pad * 2 + swatch + 6 + text_w
        box_h = pad * 2 + sum(line // 2 if kind == "gap" else line for kind, _c, _t in rows)
        final = Image.new("RGB", (result.width + box_w + pad * 2, max(result.height, box_h + pad * 2)),
                          (30, 30, 30))
        final.paste(result, (0, 0))
        draw = ImageDraw.Draw(final)
        x0 = result.width + pad
        y = max(pad, (final.height - box_h) // 2)
        draw.rectangle([x0, y, x0 + box_w, y + box_h], fill="#1e1e1e", outline="#555555")
        y += pad
        for kind, colour, text in rows:
            if kind == "gap":
                y += line // 2
                continue
            middle = y + line // 2
            if kind == "title":
                draw.text((x0 + pad, middle), text, fill=colour, font=font, anchor="lm")
            else:
                draw.rectangle([x0 + pad, middle - swatch // 2, x0 + pad + swatch, middle + swatch // 2],
                               fill=colour)
                draw.text((x0 + pad + swatch + 6, middle), text, fill=colour, font=font, anchor="lm")
            y += line
        return final

    def render_export(self, x0, y0, x1, y1, include_reference=False,
                      label_size=None, legend_size=None, line_width=None):
        rows = [CURRENT] + ([REFERENCE] if include_reference and self._reference_ready() else [])
        images = self._export_images(x0, y0, x1, y1, rows)
        return self._compose_export(
            images,
            self.annot_label_size_var.get() if label_size is None else label_size,
            self.canvas_legend_size_var.get() if legend_size is None else legend_size,
            self.annot_width_var.get() if line_width is None else line_width,
        )

    # ------------------------------------------------------------------ #
    # Preview dialog
    # ------------------------------------------------------------------ #

    def show_export_preview(self, x0, y0, x1, y1):
        win = tk.Toplevel(self.root)
        win.title("Export preview")
        win.configure(bg=theme.PANEL)
        win.transient(self.root)

        label_size_var = tk.IntVar(value=int(self.annot_label_size_var.get()))
        legend_size_var = tk.IntVar(value=int(self.canvas_legend_size_var.get()))
        line_width_var = tk.DoubleVar(value=float(self.annot_width_var.get()))
        reference_var = tk.BooleanVar(value=self._reference_ready())
        state = {"images": None, "result": None, "photo": None, "job": None}

        preview = tk.Label(win, bg=theme.CANVAS_BG)
        preview.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=self.px(10), pady=(self.px(10), self.px(6)))
        info_var = tk.StringVar()

        def rows():
            return [CURRENT] + ([REFERENCE] if reference_var.get() and self._reference_ready() else [])

        def recompose():
            state["job"] = None
            result = self._compose_export(state["images"], label_size_var.get(), legend_size_var.get(),
                                          line_width_var.get())
            state["result"] = result
            max_w = max(400, min(self.root.winfo_screenwidth() - self.px(160), self.px(1500)))
            max_h = max(300, min(self.root.winfo_screenheight() - self.px(360), self.px(900)))
            factor = min(max_w / result.width, max_h / result.height, 1.0)
            shown = result if factor >= 1.0 else result.resize(
                (max(1, int(result.width * factor)), max(1, int(result.height * factor))),
                Image.Resampling.LANCZOS)
            state["photo"] = ImageTk.PhotoImage(shown)
            preview.config(image=state["photo"])
            info_var.set(f"Output: {result.width} x {result.height} px")

        def schedule_recompose(*_):
            if state["images"] is None:
                return
            if state["job"] is not None:
                win.after_cancel(state["job"])
            state["job"] = win.after(80, recompose)

        def rerender(*_):
            state["images"] = self._export_images(x0, y0, x1, y1, rows())
            recompose()

        controls = ttk.Frame(win)
        controls.pack(side=tk.TOP, fill=tk.X, padx=self.px(10), pady=self.px(4))
        for text, var, low, high in [
            ("Marker label size", label_size_var, 6, 60),
            ("Legend text size", legend_size_var, 6, 60),
            ("Marker line width", line_width_var, 0.5, 6.0),
        ]:
            column = ttk.Frame(controls)
            column.pack(side=tk.LEFT, padx=(0, self.px(18)))
            ttk.Label(column, text=text).pack(anchor=tk.W)
            is_int = isinstance(var, tk.IntVar)
            ttk.Scale(column, variable=var, from_=low, to=high, length=self.px(200),
                      command=lambda value, v=var, whole=is_int: (
                          v.set(int(round(float(value))) if whole else round(float(value) * 2) / 2),
                          schedule_recompose())).pack()
        if self._reference_ready():
            ttk.Checkbutton(controls, text="Include reference row", variable=reference_var,
                            command=rerender).pack(side=tk.LEFT, padx=(0, self.px(18)))

        buttons = ttk.Frame(win)
        buttons.pack(side=tk.TOP, fill=tk.X, padx=self.px(10), pady=(self.px(4), self.px(10)))
        ttk.Label(buttons, textvariable=info_var, style="Muted.TLabel").pack(side=tk.LEFT)

        def save():
            result = state["result"]
            if result is None:
                return
            path = filedialog.asksaveasfilename(
                parent=win, title="Export image", defaultextension=".png",
                initialdir=self._dialog_dir(),
                filetypes=[("PNG - lossless", "*.png"), ("TIFF - lossless", "*.tif *.tiff")])
            if not path:
                return
            try:
                if path.lower().endswith((".tif", ".tiff")):
                    result.save(path)
                else:
                    result.save(path, compress_level=3)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Export image", f"Could not save the image:\n{path}\n\n{exc}", parent=win)
                return
            self._remember_dir(path)
            self.set_status(f"Exported {path}  ({result.width} x {result.height} px)")
            win.destroy()

        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Save image...", style="Accent.TButton", command=save).pack(
            side=tk.RIGHT, padx=(0, self.px(8)))
        win.bind("<Escape>", lambda _e: win.destroy())

        rerender()
        self._centre_dialog(win)
        try:
            win.grab_set()
        except tk.TclError:
            pass
        if self.tool_var.get() == "crop":
            self.set_tool("pan")
