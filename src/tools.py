"""The single active tool: mouse and keyboard handling, alignment and on-screen guidance."""

import tkinter as tk
from tkinter import messagebox, ttk

from . import geometry as geo
from .pair import BACKLIT, FRONTLIT
from .viewer import CURRENT, REFERENCE

# id, toolbar label, shortcut key, tooltip
TOOLS = [
    ("pan", "Pan", "v",
     "Navigate (V)\nDrag to pan, scroll to zoom."),
    ("annotate", "Annotate", "a",
     "Annotate (A)\nClick a feature to mark it with a circle."),
    ("move", "Move", "m",
     "Move markers (M)\nDrag an existing marker to a new position."),
    ("level", "Level", "l",
     "Level (L)\nDrag along an edge that should be vertical; both images rotate to make it so."),
    ("align", "Align", "g",
     "Align frontlit to backlit (G)\nClick matching features on the two images of a row."),
    ("align_rows", "Align rows", "r",
     "Align reference row to current row (R)\nClick matching features in the top and bottom rows."),
    ("crop", "Crop export", "c",
     "Crop export (C)\nDrag a rectangle to export that region as an image."),
]
TOOL_KEYS = {key: tool for tool, _label, key, _tip in TOOLS}
CLICK_TOOLS = {"pan", "annotate", "align", "align_rows"}   # dragging pans in these
DRAG_THRESHOLD = 4

_TEXT_WIDGETS = (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Text, tk.Spinbox)


class ToolsMixin:
    # ------------------------------------------------------------------ #
    # Tool selection
    # ------------------------------------------------------------------ #

    def set_tool(self, tool):
        if tool == "align_rows" and not self._reference_ready():
            messagebox.showinfo(
                "Align rows",
                "Load a reference row first (File > Load reference session, or the Images panel).\n\n"
                "Align rows lines the reference row up with the current row so the same spot "
                "on the filter sits under the cursor in both.",
                parent=self.root)
            tool = "pan"
        if tool == "align" and self.mode_var.get() == "overlay":
            self.mode_var.set("sidebyside")
            self._layout_panes()
        if self.tool_var.get() != tool:
            self.tool_var.set(tool)
        self._on_tool_changed()

    def _on_tool_changed(self):
        tool = self.tool_var.get()
        if tool == "align_rows" and not self._reference_ready():
            self.set_tool("pan")
            return
        if tool == "align" and self.mode_var.get() == "overlay":
            self.mode_var.set("sidebyside")
            self._layout_panes()
        self._press = None
        self._clear_tool_points(redraw=False)
        cursor = {"pan": "fleur", "move": "hand2"}.get(tool, "crosshair")
        for pane in self.panes:
            pane.canvas.config(cursor=cursor)
            pane.canvas.delete("rubber")
        self._refresh_hint()
        self._draw_overlays()

    def _reference_ready(self):
        return self.show_reference_var.get() and self.pairs[REFERENCE].has_any_image()

    def _clear_tool_points(self, redraw=True):
        self._tool_state = {"row": None, "a": [], "b": [], "cur": [], "ref": []}
        if redraw:
            self._refresh_hint()
            self._draw_overlays()

    def _point_counts(self):
        state = self._tool_state
        if self.tool_var.get() == "align":
            return len(state["a"]), len(state["b"])
        return len(state["cur"]), len(state["ref"])

    def _undo_tool_point(self):
        state = self._tool_state
        first, second = ("a", "b") if self.tool_var.get() == "align" else ("cur", "ref")
        if not state[first] and not state[second]:
            return
        # Remove whichever point was placed last.
        key = self._tool_point_order.pop() if self._tool_point_order else (
            first if len(state[first]) > len(state[second]) else second)
        if state[key]:
            state[key].pop()
        if not state["a"] and not state["b"]:
            state["row"] = None
        self._refresh_hint()
        self._draw_overlays()

    # ------------------------------------------------------------------ #
    # Guidance
    # ------------------------------------------------------------------ #

    def _refresh_hint(self):
        tool = self.tool_var.get()
        have_images = self.pairs[CURRENT].has_any_image()
        can_apply = False
        show_point_buttons = False
        if not have_images and tool == "pan":
            title = "Start here"
            text = ("Click an empty panel to load the backlit and frontlit images of a filter, "
                    "or open a saved session (Ctrl+O).  Press F1 for a step-by-step guide.")
        elif tool == "pan":
            title = "Navigate"
            text = ("Drag to pan and scroll to zoom; every panel moves together.  "
                    "Pick a tool above to level, align, annotate or export.")
        elif tool == "annotate":
            title = "Annotate"
            label = self.pairs[CURRENT].next_label(self.annot_colour) if self.annot_autolabel_var.get() else ""
            name = self.pairs[CURRENT].colour_labels.get(self.annot_colour, "")
            what = f"'{name}' marker" if name else "marker"
            text = (f"Click a feature to place a {what}"
                    + (f" (next label {label})" if label else "")
                    + ".  Drag still pans.  Right-click a marker to relabel or delete it.  "
                    "Change colour and size in the Annotations panel.")
        elif tool == "move":
            title = "Move markers"
            text = "Drag a marker to reposition it.  Drag empty space to pan."
        elif tool == "level":
            title = "Level"
            text = ("Find an edge that should be vertical, such as a mesh bar or the frame edge, "
                    "and drag along it.  Both images of that row rotate so the line you drew becomes "
                    "vertical.  Fine-tune with Ctrl+Left / Ctrl+Right.")
        elif tool == "align":
            title = "Align frontlit to backlit"
            n_a, n_b = self._point_counts()
            pairs = min(n_a, n_b)
            show_point_buttons = True
            can_apply = pairs >= 2
            if n_a == n_b:
                step = (f"Click feature {n_a + 1} on either image"
                        if pairs else "Click a small, sharp feature on the backlit image")
            elif n_a > n_b:
                step = f"Now click the same feature (point {n_b + 1}) on the frontlit image"
            else:
                step = f"Now click the same feature (point {n_a + 1}) on the backlit image"
            ready = "  Ready: press Apply (Enter), or add more pairs for a better fit." if can_apply else ""
            text = (f"{step}.  Mark at least 2 features, far apart.  {pairs} pair(s) so far.{ready}  "
                    "Arrow keys nudge the frontlit image by 1 px; Shift+Left/Right rotate it.")
        elif tool == "align_rows":
            title = "Align reference row to current row"
            n_cur, n_ref = self._point_counts()
            pairs = min(n_cur, n_ref)
            show_point_buttons = True
            can_apply = pairs >= 2
            if n_cur == n_ref:
                step = (f"Click feature {n_cur + 1} in either row"
                        if pairs else "Click a feature of the filter in the current (top) row")
            elif n_cur > n_ref:
                step = f"Now click the same feature (point {n_ref + 1}) in the reference (bottom) row"
            else:
                step = f"Now click the same feature (point {n_cur + 1}) in the current (top) row"
            ready = "  Ready: press Apply (Enter)." if can_apply else ""
            text = (f"{step}.  Mark at least 2 features, far apart.  {pairs} pair(s) so far.{ready}  "
                    "Align each row's frontlit image to its backlit image first.")
        else:
            title = "Crop export"
            text = ("Drag a rectangle around the region to export.  A preview opens where you can "
                    "adjust label sizes and save the image.")
        self.hint_title_var.set(title)
        self.hint_text_var.set(text)
        self._set_hint_buttons(show_point_buttons, can_apply)

    # ------------------------------------------------------------------ #
    # Mouse
    # ------------------------------------------------------------------ #

    def _pane_is_empty(self, pane):
        pair = self.pairs[pane.row]
        if self.mode_var.get() == "overlay":
            return not pair.has_any_image()
        return not pair.has_image(pane.idx)

    def _on_press(self, event):
        pane = self.pane_for_widget(event.widget)
        if pane is None or self._busy:
            return
        event.widget.focus_set()
        tool = self.tool_var.get()
        mode = "pan"
        ann_index = None
        if tool == "move" and pane.row == CURRENT:
            ann_index = self._annotation_at(event.x, event.y)
            if ann_index is not None:
                mode = "move_ann"
        elif tool in ("level", "crop") and not self._pane_is_empty(pane):
            mode = tool
        self._press = {
            "pane": pane, "x": event.x, "y": event.y, "last": (event.x, event.y),
            "dragging": False, "mode": mode, "ann": ann_index,
        }

    def _on_drag(self, event):
        press = self._press
        if press is None:
            return
        if not press["dragging"]:
            if (abs(event.x - press["x"]) < DRAG_THRESHOLD
                    and abs(event.y - press["y"]) < DRAG_THRESHOLD):
                return
            press["dragging"] = True
            if press["mode"] == "move_ann":
                self._checkpoint("Move marker")
        mode = press["mode"]
        if mode == "pan":
            self._pan_by(event.x - press["last"][0], event.y - press["last"][1])
            press["last"] = (event.x, event.y)
        elif mode == "move_ann":
            x, y = self.canvas_to_image(CURRENT, BACKLIT, event.x, event.y)
            ann = self.pairs[CURRENT].annotations[press["ann"]]
            ann["img1_x"], ann["img1_y"] = x, y
            self._draw_overlays()
        elif mode == "level":
            canvas = press["pane"].canvas
            canvas.delete("rubber")
            canvas.create_line(press["x"], press["y"], event.x, event.y,
                               fill="#ffff44", width=self.px(2), dash=(6, 4), tags="rubber")
        elif mode == "crop":
            for pane in self.visible_panes():
                pane.canvas.delete("rubber")
                pane.canvas.create_rectangle(press["x"], press["y"], event.x, event.y,
                                             outline="#ffcc88", width=self.px(1), dash=(6, 4),
                                             tags="rubber")
        self._move_crosshair(event.x, event.y)

    def _on_release(self, event):
        press, self._press = self._press, None
        if press is None:
            return
        pane = press["pane"]
        for p in self.panes:
            p.canvas.delete("rubber")
        if press["dragging"]:
            mode = press["mode"]
            if mode == "level":
                self._apply_level(pane.row, press["x"], press["y"], event.x, event.y)
            elif mode == "crop":
                x0, x1 = sorted((press["x"], event.x))
                y0, y1 = sorted((press["y"], event.y))
                if x1 - x0 >= 8 and y1 - y0 >= 8:
                    self.show_export_preview(x0, y0, x1, y1)
            elif mode == "move_ann":
                self._schedule_render()
            return

        # A plain click.
        if self._pane_is_empty(pane):
            self.load_image(pane.idx, pane.row)
            return
        tool = self.tool_var.get()
        if tool == "annotate":
            self._click_annotate(pane, event.x, event.y)
        elif tool == "align":
            self._click_align(pane, event.x, event.y)
        elif tool == "align_rows":
            self._click_align_rows(pane, event.x, event.y)

    def _on_middle_press(self, event):
        self._middle_last = (event.x, event.y)

    def _on_middle_drag(self, event):
        last = getattr(self, "_middle_last", None)
        if last is None:
            return
        self._pan_by(event.x - last[0], event.y - last[1])
        self._middle_last = (event.x, event.y)
        self._move_crosshair(event.x, event.y)

    def _on_right_click(self, event):
        pane = self.pane_for_widget(event.widget)
        if pane is None or self._busy:
            return
        if self.tool_var.get() in ("align", "align_rows"):
            self._undo_tool_point()
            return
        if pane.row != CURRENT:
            return
        index = self._annotation_at(event.x, event.y)
        if index is not None:
            self._show_annotation_menu(index, event)

    def _on_mouse_move(self, event):
        pane = self.pane_for_widget(event.widget)
        if pane is None:
            return
        self._move_crosshair(event.x, event.y)
        idx = BACKLIT if self.mode_var.get() == "overlay" else pane.idx
        if self.pairs[pane.row].has_image(idx):
            x, y = self.canvas_to_image(pane.row, idx, event.x, event.y)
            self.coords_var.set(f"{self._image_label(idx, pane.row)}:  x {x:.1f}   y {y:.1f}")
        else:
            self.coords_var.set("")
        if self.tool_var.get() in ("align", "align_rows"):
            self._hover = (pane, event.x, event.y)
            self._draw_align_guide()

    def _on_leave(self, _event):
        self._hover = None
        for pane in self.panes:
            pane.canvas.itemconfigure("cursor", state=tk.HIDDEN)
            pane.canvas.delete("guide")
        self.coords_var.set("")

    # ------------------------------------------------------------------ #
    # Keyboard
    # ------------------------------------------------------------------ #

    def _typing(self):
        try:
            return isinstance(self.root.focus_get(), _TEXT_WIDGETS)
        except (KeyError, tk.TclError):
            return False

    def _on_key(self, event):
        if self._busy or self._typing():
            return None
        key = event.keysym
        ctrl = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)
        if key == "Escape":
            return self._on_escape()
        if key in ("Return", "KP_Enter"):
            if self.tool_var.get() in ("align", "align_rows"):
                self.apply_tool_points()
                return "break"
            return None
        if key in ("Left", "Right", "Up", "Down"):
            return self._on_arrow(key, ctrl, shift)
        if ctrl:
            return None
        lowered = key.lower()
        if lowered in TOOL_KEYS:
            self.set_tool(TOOL_KEYS[lowered])
            return "break"
        if lowered == "f":
            self.fit_view()
        elif key in ("plus", "equal", "KP_Add"):
            self.zoom_step(1.25)
        elif key in ("minus", "KP_Subtract"):
            self.zoom_step(0.8)
        elif key == "1":
            self.zoom_actual()
        elif lowered == "o":
            self.toggle_mode()
        return None

    def _on_escape(self):
        if self._press is not None:
            self._press = None
            for pane in self.panes:
                pane.canvas.delete("rubber")
            return "break"
        n_first, n_second = self._point_counts()
        if self.tool_var.get() in ("align", "align_rows") and (n_first or n_second):
            self._clear_tool_points()
        else:
            self.set_tool("pan")
        return "break"

    def toggle_mode(self):
        self.mode_var.set("sidebyside" if self.mode_var.get() == "overlay" else "overlay")
        self._on_mode_change()

    def _on_arrow(self, key, ctrl, shift):
        tool = self.tool_var.get()
        if tool not in ("align", "level"):
            return None
        row = self._tool_state["row"] if self._tool_state["row"] is not None else self._control_row()
        pair = self.pairs[row]
        if ctrl and key in ("Left", "Right"):
            self._checkpoint("Rotate both images", coalesce="nudge-glob")
            pair.set_global_rotation(pair.glob_rot + (-0.1 if key == "Left" else 0.1))
        elif tool != "align":
            return None
        elif shift and key in ("Left", "Right"):
            self._checkpoint("Rotate frontlit image", coalesce="nudge-rot")
            matrix = geo.about(geo.apply(pair.matrix(FRONTLIT), *pair.centre(FRONTLIT)), 1.0,
                               -0.1 if key == "Left" else 0.1) @ pair.matrix(FRONTLIT)
            pair.set_frontlit_matrix(matrix)
        elif not shift and not ctrl:
            self._checkpoint("Nudge frontlit image", coalesce="nudge-offset")
            dx = {"Left": -1, "Right": 1}.get(key, 0)
            dy = {"Up": -1, "Down": 1}.get(key, 0)
            pair.off_x += dx
            pair.off_y += dy
        else:
            return None
        self._sync_controls()
        self._schedule_render(interactive=True)
        return "break"

    # ------------------------------------------------------------------ #
    # Level
    # ------------------------------------------------------------------ #

    def _apply_level(self, row, x0, y0, x1, y1):
        if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
            return
        angle = self.level_angle(x0, y0, x1, y1)
        pair = self.pairs[row]
        self._checkpoint("Level")
        pair.set_global_rotation(pair.glob_rot + angle)
        self._sync_controls()
        self._schedule_render()
        self.set_status(
            f"Levelled the {self._row_name(row)}: rotated by {angle:+.2f} deg "
            f"(now {pair.glob_rot:.2f} deg).  Ctrl+Z undoes.")

    # ------------------------------------------------------------------ #
    # Point alignment
    # ------------------------------------------------------------------ #

    def _click_align(self, pane, x, y):
        state = self._tool_state
        pair = self.pairs[pane.row]
        if not (pair.has_image(BACKLIT) and pair.has_image(FRONTLIT)):
            self.set_status("Load both the backlit and frontlit image of this row before aligning.")
            return
        if state["row"] is None:
            state["row"] = pane.row
            self._tool_point_order = []
        elif state["row"] != pane.row:
            self.set_status(
                f"You are aligning the {self._row_name(state['row'])}.  "
                "Finish there, or press Esc to clear the points and start on this row.")
            return
        n_a, n_b = len(state["a"]), len(state["b"])
        key = "a" if pane.idx == BACKLIT else "b"
        if n_a != n_b and key != ("a" if n_a < n_b else "b"):
            wanted = self._image_label(BACKLIT if n_a < n_b else FRONTLIT).lower()
            self.set_status(f"Next click should be on the {wanted}.")
            return
        state[key].append(self.canvas_to_image(pane.row, pane.idx, x, y))
        self._tool_point_order.append(key)
        self._refresh_hint()
        self._draw_overlays()

    def _click_align_rows(self, pane, x, y):
        state = self._tool_state
        n_cur, n_ref = len(state["cur"]), len(state["ref"])
        key = "cur" if pane.row == CURRENT else "ref"
        if n_cur != n_ref and key != ("cur" if n_cur < n_ref else "ref"):
            wanted = "current (top)" if n_cur < n_ref else "reference (bottom)"
            self.set_status(f"Next click should be in the {wanted} row.")
            return
        if not state["cur"] and not state["ref"]:
            self._tool_point_order = []
        state[key].append(self.canvas_to_pair(pane.row, x, y))
        self._tool_point_order.append(key)
        self._refresh_hint()
        self._draw_overlays()

    def apply_tool_points(self):
        tool = self.tool_var.get()
        if tool == "align":
            self._apply_frontlit_alignment()
        elif tool == "align_rows":
            self._apply_row_alignment()

    def _apply_frontlit_alignment(self):
        state = self._tool_state
        n = min(len(state["a"]), len(state["b"]))
        if n < 2 or state["row"] is None:
            self.set_status("Mark at least 2 matching features on both images first.")
            return
        row = state["row"]
        pair = self.pairs[row]
        allow_scale = bool(self.align_scale_var.get())
        target = geo.apply_many(pair.matrix(BACKLIT), state["a"][:n])
        try:
            matrix, rms = geo.fit_similarity(state["b"][:n], target, allow_scale=allow_scale)
        except ValueError as exc:
            messagebox.showerror("Align", f"Could not work out the alignment: {exc}.", parent=self.root)
            return
        self._checkpoint("Align frontlit image")
        pair.set_frontlit_matrix(matrix)
        self._clear_tool_points(redraw=False)
        self._sync_controls()
        self._refresh_hint()
        self._schedule_render()
        self.set_status(
            f"Aligned the frontlit image from {n} point pairs: offset ({pair.off_x:.1f}, {pair.off_y:.1f}) px, "
            f"rotation {pair.rot:.2f} deg, scale {pair.scale:.4f}.  {self._fit_quality(rms, n, allow_scale)}  "
            "Check it in Overlay view (O).")

    def _apply_row_alignment(self):
        state = self._tool_state
        n = min(len(state["cur"]), len(state["ref"]))
        if n < 2:
            self.set_status("Mark at least 2 matching features in both rows first.")
            return
        allow_scale = bool(self.align_scale_var.get())
        try:
            matrix, rms = geo.fit_similarity(state["ref"][:n], state["cur"][:n], allow_scale=allow_scale)
        except ValueError as exc:
            messagebox.showerror("Align rows", f"Could not work out the alignment: {exc}.", parent=self.root)
            return
        self._checkpoint("Align rows")
        self.set_row_matrix(matrix)
        self._clear_tool_points(redraw=False)
        self._sync_controls()
        self._refresh_hint()
        self._schedule_render()
        shift = self.row_shift
        self.set_status(
            f"Rows aligned from {n} point pairs: shift ({shift['x']:.1f}, {shift['y']:.1f}) px, "
            f"rotation {shift['rot']:.2f} deg, scale {shift['scale']:.4f}.  "
            f"{self._fit_quality(rms, n, allow_scale)}")

    @staticmethod
    def _fit_quality(rms, n, allow_scale):
        # Two pairs always fit exactly when scale is free, so the residual says nothing.
        if n == 2 and allow_scale:
            return "Add a third pair to get an error estimate."
        return f"Residual {rms:.1f} px."

    def _draw_align_guide(self):
        """While aligning without scale, show where the next frontlit point should fall:
        on a circle around the previous one, at the distance measured on the backlit image."""
        for pane in self.panes:
            pane.canvas.delete("guide")
        state = self._tool_state
        if self.tool_var.get() != "align" or self.align_scale_var.get() or self._hover is None:
            return
        n_a, n_b = len(state["a"]), len(state["b"])
        if n_a < 2 or n_a != n_b + 1 or n_b < 1 or state["row"] is None:
            return
        row = state["row"]
        hover_pane, hx, hy = self._hover
        if hover_pane.row != row or hover_pane.idx != FRONTLIT:
            return
        ax0, ay0 = state["a"][-2]
        ax1, ay1 = state["a"][-1]
        radius = ((ax1 - ax0) ** 2 + (ay1 - ay0) ** 2) ** 0.5 * self.zoom * (
            self.row_shift["scale"] if row == REFERENCE else 1.0)
        gx, gy = self.image_to_canvas(row, FRONTLIT, *state["b"][-1])
        canvas = hover_pane.canvas
        canvas.create_oval(gx - radius, gy - radius, gx + radius, gy + radius,
                           outline="#ffaa00", width=1, dash=(4, 4), tags="guide")
        canvas.create_line(gx, gy, hx, hy, fill="#ffaa00", width=1, dash=(4, 4), tags="guide")

    # ------------------------------------------------------------------ #
    # Sidebar numeric controls
    # ------------------------------------------------------------------ #

    def reset_frontlit_alignment(self):
        pair = self.pairs[self._control_row()]
        self._checkpoint("Reset alignment")
        pair.reset_alignment()
        self._sync_controls()
        self._schedule_render()

    def reset_global_rotation(self):
        pair = self.pairs[self._control_row()]
        self._checkpoint("Reset rotation")
        pair.set_global_rotation(0.0)
        self._sync_controls()
        self._schedule_render()

    def reset_row_alignment(self):
        self._checkpoint("Reset row alignment")
        self.reset_row_shift()
        self._sync_controls()
        self._schedule_render()
