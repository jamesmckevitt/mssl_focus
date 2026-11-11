"""Export a region of the view, with markers, legend and watermark, as an image.

The drawing itself lives in ``render.py`` so that the command line (``cli.py``)
produces exactly the same picture; this module holds the window's side of it:
turning the current widget state into a :class:`render.Scene`, and the preview
dialog.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from . import render
from . import theme
from .render import MAX_EXPORT_PIXELS, GAP, _font  # re-exported: used by callers and tests
from .viewer import CURRENT, REFERENCE


class ExportMixin:
    def export_view(self):
        """Export everything currently visible in the first panel."""
        if not self.pairs[CURRENT].has_any_image():
            self.set_status("Load an image before exporting.")
            return
        canvas = self.panes[0].canvas
        self.show_export_preview(0, 0, canvas.winfo_width(), canvas.winfo_height())

    # ------------------------------------------------------------------ #
    # Rendering - the window's state, handed to render.py
    # ------------------------------------------------------------------ #

    def _scene(self, label_size=None, legend_size=None, line_width=None):
        """Everything render.py needs, taken from the current widget state."""
        return render.Scene(
            pairs=self.pairs,
            zoom=self.zoom,
            pan_x=self.pan_x,
            pan_y=self.pan_y,
            mode=self.mode_var.get(),
            opacity=float(self.opacity_var.get()),
            crop_pad=max(0, int(self.crop_pad_var.get())),
            label_size=self.annot_label_size_var.get() if label_size is None else label_size,
            legend_size=self.canvas_legend_size_var.get() if legend_size is None else legend_size,
            line_width=self.annot_width_var.get() if line_width is None else line_width,
            px_per_point=self.root.winfo_fpixels("1p"),
            row_matrix=self.row_matrix(),
        )

    def _export_geometry(self, x0, y0, x1, y1, rows):
        """Output scale, padding and panel size for a canvas rectangle."""
        return render.export_geometry(self._scene(), x0, y0, x1, y1, rows)

    def _export_images(self, x0, y0, x1, y1, rows):
        """The image part of an export (slow); markers and text are added per preview."""
        return render.export_images(self._scene(), x0, y0, x1, y1, rows)

    def _compose_export(self, images, label_size, legend_size, line_width):
        return render.compose_export(self._scene(label_size, legend_size, line_width),
                                     images, label_size, legend_size, line_width)

    @staticmethod
    def _draw_watermark(img):
        return render.draw_watermark(img)

    @staticmethod
    def _attach_legend(result, legends, font):
        return render.attach_legend(result, legends, font)

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
