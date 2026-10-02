"""Annotation markers, their legend, and everything drawn on top of the images."""

import math
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, messagebox, ttk

from . import geometry as geo
from . import theme
from .constants import _PRESET_COLOURS
from .pair import BACKLIT, FRONTLIT, marker_text
from .viewer import CURRENT, REFERENCE

PICK_TOLERANCE = 14  # screen pixels beyond the marker's edge


class AnnotationMixin:
    # ------------------------------------------------------------------ #
    # Geometry
    # ------------------------------------------------------------------ #

    def _annotation_canvas_circle(self, row, ann):
        """Centre and radius of a marker on screen.  Markers live in backlit-image
        pixels, and every canvas shares one view, so this holds for all panes of a row."""
        x, y = self.image_to_canvas(row, BACKLIT, ann["img1_x"], ann["img1_y"])
        scale = self.zoom * (self.row_shift["scale"] if row == REFERENCE else 1.0)
        return x, y, max(3.0, ann["radius"] * scale)

    def _annotation_at(self, x, y):
        closest, best = None, float("inf")
        for i, ann in enumerate(self.pairs[CURRENT].annotations):
            cx, cy, radius = self._annotation_canvas_circle(CURRENT, ann)
            distance = math.hypot(x - cx, y - cy)
            if distance <= radius + self.px(PICK_TOLERANCE) and distance < best:
                closest, best = i, distance
        return closest

    # ------------------------------------------------------------------ #
    # Editing
    # ------------------------------------------------------------------ #

    def _click_annotate(self, pane, x, y):
        if pane.row != CURRENT:
            self.set_status("Markers belong to the current (top) row.  The reference row is read-only.")
            return
        pair = self.pairs[CURRENT]
        colour = self.annot_colour
        if colour not in pair.colour_labels or pair.prefix_for(colour) is None:
            details = self._ask_colour_details(colour)
            if details is None:
                return
            pair.colour_labels[colour], pair.label_prefixes[colour] = details
            self._sync_controls()
        self._checkpoint("Add marker")
        img_x, img_y = self.canvas_to_image(CURRENT, BACKLIT, x, y)
        label = pair.next_label(colour) if self.annot_autolabel_var.get() else ""
        pair.annotations.append({
            "img1_x": img_x,
            "img1_y": img_y,
            "radius": self._marker_radius(),
            "colour": colour,
            "label": label,
        })
        self._refresh_hint()
        self._draw_overlays()
        self.set_status(f"Marker {label or len(pair.annotations)} added.  Ctrl+Z undoes.")

    def _ask_colour_details(self, colour):
        """First use of a colour: ask what it means and how its markers are numbered."""
        pair = self.pairs[CURRENT]
        dialog = tk.Toplevel(self.root)
        dialog.title("New marker colour")
        dialog.configure(bg=theme.PANEL)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        pad = self.px(14)

        top = ttk.Frame(dialog)
        top.pack(fill=tk.X, padx=pad, pady=(pad, self.px(8)))
        tk.Frame(top, bg=colour, width=self.px(22), height=self.px(22)).pack(side=tk.LEFT, padx=(0, self.px(10)))
        ttk.Label(top, text="This colour has not been used in this session yet.",
                  font=self.fonts["bold"]).pack(side=tk.LEFT)

        form = ttk.Frame(dialog)
        form.pack(fill=tk.X, padx=pad)
        name_var = tk.StringVar(value=pair.colour_labels.get(colour, ""))
        prefix_var = tk.StringVar(value=pair.prefix_for(colour) or "")
        ttk.Label(form, text="Legend name").grid(row=0, column=0, sticky="w", pady=self.px(3))
        name_entry = ttk.Entry(form, textvariable=name_var, width=32)
        name_entry.grid(row=0, column=1, sticky="we", padx=(self.px(10), 0))
        ttk.Label(form, text="e.g. Thermal Test", style="Muted.TLabel").grid(row=1, column=1, sticky="w",
                                                                              padx=(self.px(10), 0))
        ttk.Label(form, text="Label prefix").grid(row=2, column=0, sticky="w", pady=(self.px(8), self.px(3)))
        ttk.Entry(form, textvariable=prefix_var, width=8).grid(row=2, column=1, sticky="w",
                                                               padx=(self.px(10), 0), pady=(self.px(8), 0))
        ttk.Label(form, text="Markers are numbered automatically: T1, T2, ...  Leave empty for no labels.",
                  style="Muted.TLabel").grid(row=3, column=1, sticky="w", padx=(self.px(10), 0))

        outcome = {"value": None}

        def accept():
            outcome["value"] = (name_var.get().strip(), prefix_var.get().strip())
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=pad, pady=pad)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="OK", style="Accent.TButton", command=accept).pack(
            side=tk.RIGHT, padx=(0, self.px(8)))
        dialog.bind("<Return>", lambda _e: accept())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        self._centre_dialog(dialog)
        dialog.grab_set()
        name_entry.focus_set()
        self.root.wait_window(dialog)
        return outcome["value"]

    def _show_annotation_menu(self, index, event):
        ann = self.pairs[CURRENT].annotations[index]
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label=f"Delete marker {ann.get('label') or index + 1}",
                         command=lambda: self._delete_annotation(index))
        menu.add_command(label="Edit label...", command=lambda: self._edit_annotation_label(index))
        menu.add_command(label="Mark as confirmed" if ann.get("unsure") else "Mark as unsure (?)",
                         command=lambda: self._toggle_annotation_unsure(index))
        menu.add_command(label="Change to current colour", command=lambda: self._recolour_annotation(index))
        menu.add_command(label="Set radius to current size", command=lambda: self._resize_annotation(index))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _delete_annotation(self, index):
        annotations = self.pairs[CURRENT].annotations
        if 0 <= index < len(annotations):
            self._checkpoint("Delete marker")
            removed = annotations.pop(index)
            self._refresh_hint()
            self._draw_overlays()
            self.set_status(f"Marker {removed.get('label') or index + 1} deleted.  Ctrl+Z brings it back.")

    def _edit_annotation_label(self, index):
        ann = self.pairs[CURRENT].annotations[index]
        value = self._ask_text("Edit label", "Marker label (leave empty for none):", ann.get("label", ""))
        if value is None:
            return
        self._checkpoint("Edit label")
        ann["label"] = value.strip()
        self._refresh_hint()
        self._draw_overlays()

    def _toggle_annotation_unsure(self, index):
        ann = self.pairs[CURRENT].annotations[index]
        self._checkpoint("Mark as confirmed" if ann.get("unsure") else "Mark as unsure")
        if ann.get("unsure"):
            ann.pop("unsure", None)
        else:
            ann["unsure"] = True
        self._draw_overlays()

    def _recolour_annotation(self, index):
        self._checkpoint("Recolour marker")
        self.pairs[CURRENT].annotations[index]["colour"] = self.annot_colour
        self._draw_overlays()

    def _resize_annotation(self, index):
        self._checkpoint("Resize marker")
        self.pairs[CURRENT].annotations[index]["radius"] = self._marker_radius()
        self._draw_overlays()

    def _marker_radius(self):
        try:
            return max(2.0, float(self.annot_radius_var.get()))
        except (tk.TclError, ValueError):  # the box is empty or mid-edit
            return 20.0

    def clear_annotations(self):
        pair = self.pairs[CURRENT]
        if not pair.annotations:
            return
        if not messagebox.askyesno("Clear all markers",
                                   f"Delete all {len(pair.annotations)} markers?\n\n"
                                   "You can undo this with Ctrl+Z.", parent=self.root):
            return
        self._checkpoint("Clear markers")
        pair.annotations.clear()
        self._refresh_hint()
        self._draw_overlays()

    def copy_reference_annotations(self):
        """Bring the reference row's markers into the current row, through the row alignment."""
        current, reference = self.pairs
        if not reference.annotations:
            messagebox.showinfo(
                "Copy markers from reference",
                "The reference row has no markers.\n\nLoad it from a saved session "
                "(File > Load reference session) to bring that session's markers with it.",
                parent=self.root)
            return
        if not messagebox.askyesno(
                "Copy markers from reference",
                f"Copy {len(reference.annotations)} markers from the reference row into the current row?\n\n"
                "They are placed using the row alignment, so use Align rows first: a marker should sit "
                "on the same feature in both rows.  Markers already present are skipped.",
                parent=self.root):
            return
        to_current = (geo.invert(current.matrix(BACKLIT)) @ self.row_matrix()
                      @ reference.matrix(BACKLIT))
        scale = geo.scale_of(to_current)
        self._checkpoint("Copy markers from reference")
        added = 0
        for ann in reference.annotations:
            x, y = geo.apply(to_current, ann["img1_x"], ann["img1_y"])
            radius = max(2.0, ann["radius"] * scale)
            duplicate = any(
                other["colour"] == ann["colour"] and other.get("label", "") == ann.get("label", "")
                and math.hypot(other["img1_x"] - x, other["img1_y"] - y) <= radius
                for other in current.annotations)
            if duplicate:
                continue
            copied = {
                "img1_x": float(x), "img1_y": float(y), "radius": float(radius),
                "colour": ann["colour"], "label": ann.get("label", ""),
            }
            if ann.get("unsure"):
                copied["unsure"] = True
            current.annotations.append(copied)
            added += 1
        for colour, name in reference.colour_labels.items():
            current.colour_labels.setdefault(colour, name)
        for colour, prefix in reference.label_prefixes.items():
            current.label_prefixes.setdefault(colour, prefix)
        self._sync_controls()
        self._refresh_hint()
        self._draw_overlays()
        skipped = len(reference.annotations) - added
        self.set_status(f"Copied {added} markers from the reference row"
                        + (f" ({skipped} already present)." if skipped else "."))

    # ------------------------------------------------------------------ #
    # Colour and legend
    # ------------------------------------------------------------------ #

    def set_annotation_colour(self, colour):
        self.annot_colour = colour
        self._sync_controls()
        self._refresh_hint()

    def pick_custom_colour(self):
        result = colorchooser.askcolor(color=self.annot_colour, title="Custom marker colour", parent=self.root)
        if result and result[1]:
            self.set_annotation_colour(result[1].lower())

    def _on_legend_fields_changed(self):
        """Legend name / prefix entries edit the entry for the current colour."""
        if self._syncing:
            return
        pair = self.pairs[CURRENT]
        colour = self.annot_colour
        name = self.legend_name_var.get().strip()
        prefix = self.label_prefix_var.get().strip()
        if pair.colour_labels.get(colour, "") == name and (pair.prefix_for(colour) or "") == prefix:
            return
        self._checkpoint("Edit legend", coalesce="legend-" + colour)
        pair.colour_labels[colour] = name
        pair.label_prefixes[colour] = prefix
        self._refresh_hint()
        self._draw_overlays()

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #

    def _draw_overlays(self):
        visible = self.visible_panes()
        last_in_row = {}
        for pane in visible:
            last_in_row[pane.row] = pane
        for pane in visible:
            canvas = pane.canvas
            canvas.delete("world")
            canvas.delete("hud")
            width, height = canvas.winfo_width(), canvas.winfo_height()
            if width < 2 or height < 2:
                continue
            if self._pane_is_empty(pane):
                self._draw_empty_state(pane, width, height)
            else:
                self._draw_markers(pane)
                self._draw_tool_points(pane)
                self._draw_candidates(pane)
                if last_in_row[pane.row] is pane:
                    self._draw_legend(pane, width, height)
            self._draw_badge(pane)
            canvas.tag_raise("cursor")

    def _draw_empty_state(self, pane, width, height):
        canvas = pane.canvas
        overlay = self.mode_var.get() == "overlay"
        colour = theme.BACKLIT if pane.idx == BACKLIT else theme.FRONTLIT
        name = "images" if overlay else self._image_label(pane.idx, pane.row).lower()
        if pane.row == REFERENCE:
            lines = (f"No {name}", "Click to choose a file, or use\nFile > Load reference session")
        else:
            lines = (f"No {name}", "Click to choose a file")
        canvas.create_text(width / 2, height / 2 - self.px(14), text=lines[0], fill=colour,
                           font=self.fonts["title"], tags="hud")
        canvas.create_text(width / 2, height / 2 + self.px(16), text=lines[1], fill=theme.MUTED,
                           font=self.fonts["base"], justify=tk.CENTER, tags="hud")

    def _draw_markers(self, pane):
        canvas = pane.canvas
        pair = self.pairs[pane.row]
        line_width = float(self.annot_width_var.get())
        dash = (5, 3) if pane.row == REFERENCE else None
        font = (self.fonts["base"][0], int(self.annot_label_size_var.get()), "bold")
        for ann in pair.annotations:
            cx, cy, radius = self._annotation_canvas_circle(pane.row, ann)
            options = {"outline": ann["colour"], "width": line_width, "tags": "world"}
            if dash:
                options["dash"] = dash
            canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, **options)
            text = marker_text(ann)
            if text:
                canvas.create_text(cx + radius + self.px(4), cy, text=text, fill=ann["colour"],
                                   anchor=tk.W, font=font, tags="world")

    def _draw_tool_points(self, pane):
        tool = self.tool_var.get()
        state = self._tool_state
        if tool == "align" and state["row"] == pane.row:
            points = state["a"] if pane.idx == BACKLIT else state["b"]
            for i, (x, y) in enumerate(points):
                self._draw_point(pane.canvas, *self.image_to_canvas(pane.row, pane.idx, x, y),
                                 i + 1, theme.ALIGN_POINT)
        elif tool == "align_rows":
            points = state["cur"] if pane.row == CURRENT else state["ref"]
            for i, (x, y) in enumerate(points):
                self._draw_point(pane.canvas, *self.pair_to_canvas(pane.row, x, y), i + 1, theme.ROW_POINT)

    def _draw_point(self, canvas, x, y, number, colour):
        r = self.px(9)
        arm = self.px(4)
        canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=self.px(2), tags="world")
        canvas.create_line(x - arm, y, x + arm, y, fill=colour, tags="world")
        canvas.create_line(x, y - arm, x, y + arm, fill=colour, tags="world")
        canvas.create_text(x + r + self.px(3), y - r, text=str(number), fill=colour, anchor=tk.W,
                           font=self.fonts["bold"], tags="world")

    def _draw_legend(self, pane, width, height):
        data = self.pairs[pane.row].legend()
        if not data:
            return
        canvas = pane.canvas
        size = int(self.canvas_legend_size_var.get())
        font = self._legend_fonts.get(size)
        if font is None:
            font = tkfont.Font(root=self.root, family=self.fonts["base"][0], size=size)
            self._legend_fonts[size] = font
        pad = max(self.px(5), font.metrics("linespace") // 3)
        row_h = int(font.metrics("linespace") * 1.25)
        swatch = int(font.metrics("linespace") * 0.6)
        texts = [text for _colour, text in data]
        box_w = max(font.measure(t) for t in texts) + pad * 3 + swatch
        box_h = pad * 2 + len(data) * row_h
        x0 = width - pad - box_w
        y0 = height - pad - box_h
        canvas.create_rectangle(x0, y0, x0 + box_w, y0 + box_h, fill="#1e1e1e", outline="#555555", tags="hud")
        for i, (colour, text) in enumerate(data):
            cy = y0 + pad + i * row_h + row_h // 2
            canvas.create_rectangle(x0 + pad, cy - swatch // 2, x0 + pad + swatch, cy + swatch // 2,
                                    fill=colour, outline="", tags="hud")
            canvas.create_text(x0 + pad * 2 + swatch, cy, text=text, fill=colour, anchor=tk.W,
                               font=font, tags="hud")

    def _draw_badge(self, pane):
        canvas = pane.canvas
        pair = self.pairs[pane.row]
        overlay = self.mode_var.get() == "overlay"
        if overlay:
            title, colour = "Overlay", theme.TEXT
            files = [os.path.basename(p) for p in pair.paths if p]
        else:
            title = "Backlit" if pane.idx == BACKLIT else "Frontlit"
            colour = theme.BACKLIT if pane.idx == BACKLIT else theme.FRONTLIT
            files = [os.path.basename(pair.paths[pane.idx])] if pair.paths[pane.idx] else []
        parts = [("Reference  " if pane.row == REFERENCE else "") + title]
        if pair.label:
            parts.append(pair.label)
        parts.extend(files[:1] if not overlay else [" + ".join(files)] if files else [])
        text = "   |   ".join(parts)
        pad = self.px(5)
        item = canvas.create_text(self.px(8) + pad, self.px(8) + pad, anchor=tk.NW, text=text, fill=colour,
                                  font=self.fonts["bold"], tags="hud")
        x0, y0, x1, y1 = canvas.bbox(item)
        back = canvas.create_rectangle(x0 - pad, y0 - pad, x1 + pad, y1 + pad, fill="#101010",
                                       outline="#333333", tags="hud")
        canvas.tag_lower(back, item)

    def _move_crosshair(self, x, y):
        """Mirror the pointer on every panel so the same spot is marked in each image."""
        for pane in self.visible_panes():
            canvas = pane.canvas
            width, height = canvas.winfo_width(), canvas.winfo_height()
            h_line, v_line, ring = pane.cursor_items
            r = self.px(6)
            canvas.coords(h_line, 0, y, width, y)
            canvas.coords(v_line, x, 0, x, height)
            canvas.coords(ring, x - r, y - r, x + r, y + r)
            canvas.itemconfigure("cursor", state=tk.NORMAL)
            canvas.tag_raise("cursor")

    # ------------------------------------------------------------------ #
    # Small dialogs
    # ------------------------------------------------------------------ #

    def _ask_text(self, title, prompt, initial=""):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=theme.PANEL)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        pad = self.px(14)
        ttk.Label(dialog, text=prompt).pack(anchor=tk.W, padx=pad, pady=(pad, self.px(6)))
        var = tk.StringVar(value=initial)
        entry = ttk.Entry(dialog, textvariable=var, width=36)
        entry.pack(fill=tk.X, padx=pad)
        outcome = {"value": None}

        def accept():
            outcome["value"] = var.get()
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=pad, pady=pad)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="OK", style="Accent.TButton", command=accept).pack(
            side=tk.RIGHT, padx=(0, self.px(8)))
        dialog.bind("<Return>", lambda _e: accept())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        self._centre_dialog(dialog)
        dialog.grab_set()
        entry.focus_set()
        entry.select_range(0, tk.END)
        self.root.wait_window(dialog)
        return outcome["value"]


PRESET_COLOURS = list(_PRESET_COLOURS)
