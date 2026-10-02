"""View geometry, rendering, image loading and navigation."""

import gc
import math
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import geometry as geo
from . import theme
from .constants import BACKLIT_IMAGE_LABEL, FRONTLIT_IMAGE_LABEL
from .imaging import IMAGE_FILETYPES, Pyramid, blank_frame, denoise, is_raw, open_image
from .pair import BACKLIT, FRONTLIT
from .session import describe_location

CURRENT = 0
REFERENCE = 1

MIN_ZOOM = 0.02
MAX_ZOOM = 100.0


class Pane:
    """One image canvas: a (row, image) slot in the grid."""

    def __init__(self, row, idx, canvas):
        self.row = row
        self.idx = idx
        self.canvas = canvas
        self.photo = None
        self.image_item = canvas.create_image(0, 0, anchor=tk.NW, tags="img")


def _load_one(path, nr, develop, dark_field):
    base = open_image(path, develop=develop, dark_field=dark_field)
    shown = base
    if nr and nr.get("amount", 0) > 0:
        shown = denoise(base, nr["amount"], nr["color"], nr["edge"], nr["aggressive"])
    return base, Pyramid(shown)


class ViewerMixin:
    # ------------------------------------------------------------------ #
    # Naming
    # ------------------------------------------------------------------ #

    def _image_label(self, idx, row=CURRENT):
        base = BACKLIT_IMAGE_LABEL if idx == BACKLIT else FRONTLIT_IMAGE_LABEL
        return f"Reference {base.lower()}" if row == REFERENCE else base

    def _row_name(self, row):
        return "reference row" if row == REFERENCE else "current row"

    # ------------------------------------------------------------------ #
    # Geometry
    # ------------------------------------------------------------------ #

    def view_matrix(self):
        return geo.translation(self.pan_x, self.pan_y) @ geo.scaling(self.zoom)

    def row_matrix(self):
        """Reference-row pair space -> current-row pair space (the shared world)."""
        centre = self.pairs[REFERENCE].centre(BACKLIT)
        return geo.translation(self.row_shift["x"], self.row_shift["y"]) @ geo.about(
            centre, self.row_shift["scale"], self.row_shift["rot"])

    def set_row_matrix(self, matrix):
        centre = self.pairs[REFERENCE].centre(BACKLIT)
        scale, deg, tx, ty = geo.decompose_about(matrix, centre)
        self.row_shift = {"x": float(tx), "y": float(ty), "rot": float(geo.wrap_angle(deg)),
                          "scale": float(scale)}

    def reset_row_shift(self):
        self.row_shift = {"x": 0.0, "y": 0.0, "rot": 0.0, "scale": 1.0}

    def pair_to_world(self, row):
        return self.row_matrix() if row == REFERENCE else geo.identity()

    def world_matrix(self, row, idx):
        """Image pixels -> world."""
        return self.pair_to_world(row) @ self.pairs[row].matrix(idx)

    def canvas_matrix(self, row, idx):
        """Image pixels -> canvas pixels (the same for every canvas: views are linked)."""
        return self.view_matrix() @ self.world_matrix(row, idx)

    def canvas_to_image(self, row, idx, x, y):
        return geo.apply(geo.invert(self.canvas_matrix(row, idx)), x, y)

    def image_to_canvas(self, row, idx, x, y):
        return geo.apply(self.canvas_matrix(row, idx), x, y)

    def canvas_to_pair(self, row, x, y):
        return geo.apply(geo.invert(self.view_matrix() @ self.pair_to_world(row)), x, y)

    def pair_to_canvas(self, row, x, y):
        return geo.apply(self.view_matrix() @ self.pair_to_world(row), x, y)

    # ------------------------------------------------------------------ #
    # Panes
    # ------------------------------------------------------------------ #

    def pane_for_widget(self, widget):
        for pane in self.panes:
            if pane.canvas is widget:
                return pane
        return None

    def visible_panes(self):
        side_by_side = self.mode_var.get() != "overlay"
        rows = [CURRENT, REFERENCE] if self.show_reference_var.get() else [CURRENT]
        return [p for p in self.panes
                if p.row in rows and (side_by_side or p.idx == BACKLIT)]

    def _layout_panes(self):
        for pane in self.panes:
            pane.canvas.grid_forget()
        visible = self.visible_panes()
        gap = self.px(1)
        for pane in visible:
            pane.canvas.grid(row=pane.row, column=pane.idx, sticky="nsew", padx=gap, pady=gap)
        rows = {p.row for p in visible}
        cols = {p.idx for p in visible}
        for r in (0, 1):
            self.canvas_area.grid_rowconfigure(r, weight=1 if r in rows else 0, uniform="rows" if r in rows else "")
        for c in (0, 1):
            self.canvas_area.grid_columnconfigure(c, weight=1 if c in cols else 0, uniform="cols" if c in cols else "")
        self._on_canvas_resized()

    def _on_canvas_resized(self, _event=None):
        """Keep a fitted view fitted when the panels change size; otherwise just redraw."""
        if self._view_is_fit:
            if self._refit_job is None:
                self._refit_job = self.root.after(30, self._refit)
        else:
            self._schedule_render()

    def _refit(self):
        self._refit_job = None
        self.fit_view(settle=False)

    def _on_mode_change(self):
        if self.mode_var.get() == "overlay" and self.tool_var.get() == "align":
            self.set_tool("pan")
        self._layout_panes()
        self._refresh_hint()

    def _on_reference_toggle(self):
        if not self.show_reference_var.get() and self.tool_var.get() == "align_rows":
            self.set_tool("pan")
        self._layout_panes()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _schedule_render(self, interactive=False):
        if interactive:
            self._interacting = True
            if self._quality_job is not None:
                self.root.after_cancel(self._quality_job)
            self._quality_job = self.root.after(180, self._finish_interaction)
        if self._render_job is None:
            self._render_job = self.root.after(12, self._render)

    def _finish_interaction(self):
        self._quality_job = None
        self._interacting = False
        self._schedule_render()

    def _render_frame(self, row, idx, size, view, quality):
        pair = self.pairs[row]
        pyramid = pair.pyramids[idx]
        if pyramid is None:
            return None
        matrix = view @ self.world_matrix(row, idx)
        return pyramid.render(matrix, size, quality=quality, lut=pair.lut(idx))

    def _compose_pane(self, row, idx, size, view, quality):
        """The picture for one pane: a single image, or the blend in overlay mode."""
        if self.mode_var.get() != "overlay":
            return self._render_frame(row, idx, size, view, quality)
        back = self._render_frame(row, BACKLIT, size, view, quality)
        front = self._render_frame(row, FRONTLIT, size, view, quality)
        if back is not None and front is not None:
            return Image.blend(back, front, float(self.opacity_var.get()))
        return back if back is not None else front

    def _render(self):
        self._render_job = None
        view = self.view_matrix()
        quality = not self._interacting
        for pane in self.visible_panes():
            canvas = pane.canvas
            size = (canvas.winfo_width(), canvas.winfo_height())
            if size[0] < 2 or size[1] < 2:
                continue
            frame = self._compose_pane(pane.row, pane.idx, size, view, quality)
            if frame is None:
                pane.photo = None
                canvas.itemconfig(pane.image_item, image="")
            elif pane.photo is not None and (pane.photo.width(), pane.photo.height()) == frame.size:
                pane.photo.paste(frame)   # much cheaper than building a new Tk image
                canvas.itemconfig(pane.image_item, image=pane.photo)
            else:
                pane.photo = ImageTk.PhotoImage(frame)
                canvas.itemconfig(pane.image_item, image=pane.photo)
            canvas.coords(pane.image_item, 0, 0)
        self._draw_overlays()

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    def _pan_by(self, dx, dy):
        self._view_is_fit = False
        self.pan_x += dx
        self.pan_y += dy
        for pane in self.visible_panes():
            pane.canvas.move("world", dx, dy)
            pane.canvas.move("img", dx, dy)
        self._schedule_render(interactive=True)

    def zoom_at(self, factor, cx, cy):
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        factor = new_zoom / self.zoom
        self._view_is_fit = False
        self.pan_x = cx - (cx - self.pan_x) * factor
        self.pan_y = cy - (cy - self.pan_y) * factor
        self.zoom = new_zoom
        self._update_zoom_readout()
        self._schedule_render(interactive=True)

    def _on_wheel(self, event):
        if getattr(event, "delta", 0):
            factor = 1.0015 ** event.delta
        elif getattr(event, "num", None) == 4:
            factor = 1.12
        else:
            factor = 1 / 1.12
        self.zoom_at(max(0.5, min(2.0, factor)), event.x, event.y)

    def _view_centre(self):
        canvas = self.panes[0].canvas
        return canvas.winfo_width() / 2.0, canvas.winfo_height() / 2.0

    def zoom_step(self, factor):
        cx, cy = self._view_centre()
        self.zoom_at(factor, cx, cy)

    def zoom_actual(self):
        cx, cy = self._view_centre()
        self.zoom_at(1.0 / self.zoom, cx, cy)

    def _world_bounds(self):
        points = []
        for row in (CURRENT, REFERENCE):
            if row == REFERENCE and not self.show_reference_var.get():
                continue
            for idx in (BACKLIT, FRONTLIT):
                pyramid = self.pairs[row].pyramids[idx]
                if pyramid is not None:
                    points.extend(pyramid.corners(self.world_matrix(row, idx)))
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    def fit_view(self, settle=True):
        self._view_is_fit = True
        bounds = self._world_bounds()
        canvas = self.panes[0].canvas
        if settle:
            self.root.update_idletasks()
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if bounds is None or width < 2 or height < 2:
            self._schedule_render()
            return
        x0, y0, x1, y1 = bounds
        span_x, span_y = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, 0.96 * min(width / span_x, height / span_y)))
        self.pan_x = width / 2.0 - self.zoom * (x0 + x1) / 2.0
        self.pan_y = height / 2.0 - self.zoom * (y0 + y1) / 2.0
        self._update_zoom_readout()
        self._schedule_render()

    # ------------------------------------------------------------------ #
    # Background work
    # ------------------------------------------------------------------ #

    def _run_in_background(self, title, steps, on_done):
        """Run ``steps`` -- a list of ``(description, callable)`` -- off the UI thread.

        ``on_done(results)`` is called on the UI thread with one entry per step:
        the callable's return value, or the exception it raised.
        """
        if not steps:
            on_done([])
            return
        self._busy = True
        results = [None] * len(steps)
        messages = queue.SimpleQueue()

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=theme.PANEL)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        text_var = tk.StringVar(value=steps[0][0])
        ttk.Label(dialog, textvariable=text_var, style="Panel.TLabel", wraplength=self.px(420),
                  justify=tk.LEFT).pack(fill=tk.X, padx=self.px(18), pady=(self.px(16), self.px(8)))
        bar = ttk.Progressbar(dialog, mode="indeterminate", length=self.px(420))
        bar.pack(padx=self.px(18), pady=(0, self.px(18)))
        bar.start(12)
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

        # Tk objects must only ever be finalised on the UI thread.  A garbage
        # collection that happened to run inside the worker would try to do so
        # there and stall, so collect now and hold collection off until done.
        gc.collect()
        gc.disable()

        def worker():
            for i, (description, func) in enumerate(steps):
                messages.put(("step", i, description))
                try:
                    results[i] = func()
                except Exception as exc:  # reported to the user by the caller
                    results[i] = exc
            messages.put(("done", None, None))

        def poll():
            finished = False
            try:
                while True:
                    kind, i, description = messages.get_nowait()
                    if kind == "step":
                        prefix = f"({i + 1} of {len(steps)})  " if len(steps) > 1 else ""
                        text_var.set(prefix + description)
                    else:
                        finished = True
            except queue.Empty:
                pass
            if not finished:
                self.root.after(40, poll)
                return
            bar.stop()
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
            gc.enable()
            self._busy = False
            on_done(results)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(40, poll)

    def _load_images(self, jobs, on_done, title="Loading images"):
        """Load ``jobs`` -- a list of ``((row, idx), path, nr_settings, raw_develop_settings)``,
        either setting may be ``None`` -- in the background.

        ``on_done(loaded, errors)`` receives ``{key: (path, base_image, pyramid)}``
        and ``{key: message}``.
        """
        steps = []
        for (_row, idx), path, nr, develop in jobs:
            size_mb = ""
            try:
                size_mb = f"  ({os.path.getsize(path) / 1e6:.0f} MB)"
            except OSError:
                pass
            verb = "Developing" if is_raw(path) else "Loading"
            steps.append((f"{verb} {os.path.basename(path)}{size_mb}",
                          lambda p=path, n=nr, d=develop, dark=(idx == BACKLIT): _load_one(p, n, d, dark)))

        def finished(results):
            loaded, errors = {}, {}
            for (key, path, _nr, _develop), result in zip(jobs, results):
                if isinstance(result, Exception):
                    errors[key] = f"{path}\n{type(result).__name__}: {result}"
                else:
                    loaded[key] = (path, result[0], result[1])
            on_done(loaded, errors)

        self._run_in_background(title, steps, finished)

    def _report_load_errors(self, title, errors):
        if not errors:
            return
        lines = []
        for (row, idx), message in errors.items():
            lines.append(f"{self._image_label(idx, row)}:\n{message}")
        messagebox.showerror(title, "Could not load:\n\n" + "\n\n".join(lines), parent=self.root)

    # ------------------------------------------------------------------ #
    # Loading single images
    # ------------------------------------------------------------------ #

    def load_image(self, idx, row=CURRENT):
        path = filedialog.askopenfilename(
            parent=self.root,
            title=f"Open {self._image_label(idx, row).lower()}",
            initialdir=self._dialog_dir(),
            filetypes=IMAGE_FILETYPES,
        )
        if path:
            self._remember_dir(path)
            self.load_image_path(path, idx, row)

    def load_image_path(self, path, idx, row=CURRENT):
        was_empty = not any(pair.has_any_image() for pair in self.pairs)

        def finished(loaded, errors):
            self._report_load_errors("Load image", errors)
            if (row, idx) not in loaded:
                return
            loaded_path, base, pyramid = loaded[(row, idx)]
            pair = self.pairs[row]
            pair.set_image(idx, loaded_path, base, pyramid)
            pair.nr[idx]["amount"] = 0
            if not pair.label:
                pair.label = describe_location(loaded_path)
            if row == REFERENCE:
                self.show_reference_var.set(True)
                self._layout_panes()
            self._mark_dirty()
            if was_empty or self._view_is_fit:
                self.fit_view()
            self._sync_controls()
            self._schedule_render()
            self.set_status(
                f"{self._image_label(idx, row)} loaded: {os.path.basename(loaded_path)} "
                f"({pyramid.size[0]} x {pyramid.size[1]} px)")

        self._load_images([((row, idx), path, None, self.pairs[row].develop[idx])], finished)

    def redevelop_image(self, idx, row=CURRENT):
        """Develop a RAW image again with the current exposure and noise settings."""
        pair = self.pairs[row]
        path = pair.paths[idx]
        label = self._image_label(idx, row)
        if not is_raw(path):
            self.set_status(f"{label} is not a camera RAW file.")
            return

        def finished(loaded, errors):
            self._report_load_errors("Develop RAW", errors)
            if (row, idx) not in loaded or pair.paths[idx] != path:
                return
            _path, base, pyramid = loaded[(row, idx)]
            pair.set_image(idx, path, base, pyramid)
            self._mark_dirty()
            self._schedule_render()
            settings = pair.develop[idx]
            self.set_status(f"{label} developed again: exposure {settings['exposure']:+.1f} EV, "
                            f"noise reduction {settings['noise']}.")

        self._load_images([((row, idx), path, pair.nr[idx], pair.develop[idx])], finished,
                          title="Developing RAW")

    def remove_reference_row(self):
        if not self.pairs[REFERENCE].has_any_image():
            self.show_reference_var.set(False)
            self._on_reference_toggle()
            return
        if not messagebox.askyesno(
                "Remove reference row",
                "Remove the reference row from this session?\n\n"
                "The reference images and its alignment to the current row are dropped; "
                "the reference session file itself is not changed.",
                parent=self.root):
            return
        self._new_pair(REFERENCE)
        self.reset_row_shift()
        self.show_reference_var.set(False)
        if self.tool_var.get() == "align_rows":
            self.set_tool("pan")
        self._mark_dirty()
        self._layout_panes()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    # Noise reduction
    # ------------------------------------------------------------------ #

    def apply_noise_reduction(self, idx, row=CURRENT):
        pair = self.pairs[row]
        base = pair.base_images[idx]
        label = self._image_label(idx, row)
        if base is None:
            self.set_status(f"{label}: no image loaded.")
            return
        nr = dict(pair.nr[idx])
        if nr["amount"] <= 0:
            pair.pyramids[idx] = Pyramid(base)
            self._mark_dirty()
            self._schedule_render()
            self.set_status(f"{label}: noise reduction cleared.")
            return

        def work():
            shown = denoise(base, nr["amount"], nr["color"], nr["edge"], nr["aggressive"])
            return Pyramid(shown)

        def finished(results):
            result = results[0]
            if isinstance(result, Exception):
                messagebox.showerror("Noise reduction", f"{label}: noise reduction failed.\n\n{result}",
                                     parent=self.root)
                return
            if pair.base_images[idx] is not base:
                return
            pair.pyramids[idx] = result
            self._mark_dirty()
            self._schedule_render()
            self.set_status(
                f"{label}: {'aggressive ' if nr['aggressive'] else ''}noise reduction applied "
                f"(amount {nr['amount']}, colour {nr['color']}, edge {nr['edge']}).")

        self._run_in_background(
            "Applying noise reduction",
            [(f"{label}: applying {'aggressive ' if nr['aggressive'] else ''}noise reduction "
              f"(amount {nr['amount']}).  This can take a minute on large images.", work)],
            finished)

    def clear_noise_reduction(self, idx, row=CURRENT):
        self.pairs[row].nr[idx]["amount"] = 0
        self._sync_controls()
        self.apply_noise_reduction(idx, row)

    # ------------------------------------------------------------------ #
    # Small helpers
    # ------------------------------------------------------------------ #

    def _dialog_dir(self):
        folder = self.config.get("last_dir")
        return folder if folder and os.path.isdir(folder) else None

    def _remember_dir(self, path):
        self.config.set("last_dir", os.path.dirname(os.path.abspath(path)))

    def _update_zoom_readout(self):
        self.zoom_readout_var.set(f"{self.zoom * 100:.0f}%" if self.zoom < 10 else f"{self.zoom:.0f}x")

    def level_angle(self, x0, y0, x1, y1):
        """Clockwise correction (deg) that makes the dragged line vertical."""
        dx, dy = x1 - x0, y1 - y0
        if dy < 0:
            dx, dy = -dx, -dy
        return math.degrees(math.atan2(dx, dy))
