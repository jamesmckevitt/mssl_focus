"""Automatic pinhole search and the review of what it finds."""

from tkinter import messagebox

import numpy as np

from . import geometry as geo
from .detect import find_pinholes, flag_present_in, split_by_markers
from .pair import BACKLIT
from .viewer import CURRENT, REFERENCE

REVIEW_ZOOM = 2.0
MARGIN = 40  # pixels of context searched around the chosen region


class DetectMixin:
    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #

    def _search_region(self, row, canvas_rect):
        """Canvas rectangle -> (crop box in backlit pixels, canvas-to-image test)."""
        x0, y0, x1, y1 = canvas_rect
        to_image = geo.invert(self.canvas_matrix(row, BACKLIT))
        corners = geo.apply_many(to_image, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        width, height = self.pairs[row].size(BACKLIT)
        left = int(max(0, np.floor(corners[:, 0].min()) - MARGIN))
        top = int(max(0, np.floor(corners[:, 1].min()) - MARGIN))
        right = int(min(width, np.ceil(corners[:, 0].max()) + MARGIN))
        bottom = int(min(height, np.ceil(corners[:, 1].max()) + MARGIN))
        return (left, top, right, bottom)

    def _detect_in(self, row, canvas_rect, sensitivity):
        """Candidates of one row's backlit image inside a canvas rectangle, in image pixels."""
        box = self._search_region(row, canvas_rect)
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            return [], 0
        image = self.pairs[row].pyramids[BACKLIT].image.crop(box)
        found, total = find_pinholes(image, sensitivity)
        to_canvas = self.canvas_matrix(row, BACKLIT)
        x0, y0, x1, y1 = canvas_rect
        inside = []
        for candidate in found:
            candidate["x"] += box[0]
            candidate["y"] += box[1]
            cx, cy = geo.apply(to_canvas, candidate["x"], candidate["y"])
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                inside.append(candidate)
        return inside, total

    def find_pinholes_in(self, canvas_rect):
        """Search the current backlit image inside a canvas rectangle and start the review."""
        current, reference = self.pairs
        if not current.has_image(BACKLIT):
            self.set_status("Load a backlit image first.")
            return
        sensitivity = self.detect_sensitivity_var.get().lower()
        with_reference = self._reference_ready() and reference.has_image(BACKLIT)
        to_canvas = self.canvas_matrix(CURRENT, BACKLIT)
        from_reference = geo.invert(self.world_matrix(CURRENT, BACKLIT)) @ self.world_matrix(REFERENCE, BACKLIT) \
            if with_reference else None

        def work():
            found, total = self._detect_in(CURRENT, canvas_rect, sensitivity)
            earlier = []
            if with_reference:
                ref_found, _ = self._detect_in(REFERENCE, canvas_rect, sensitivity)
                earlier = [geo.apply(from_reference, c["x"], c["y"]) for c in ref_found]
            return found, total, earlier

        def finished(results):
            result = results[0]
            if isinstance(result, Exception):
                messagebox.showerror("Find pinholes", f"The search failed.\n\n{result}", parent=self.root)
                self.set_tool("pan")
                return
            found, total, earlier = result
            markers = [(a["img1_x"], a["img1_y"], a["radius"]) for a in current.annotations]
            fresh, marked = split_by_markers(found, markers)
            flag_present_in(fresh, earlier)
            if with_reference:
                # Spots absent from the earlier inspection are the interesting ones: show them first.
                fresh.sort(key=lambda c: (c["in_reference"], -c["peak"]))
            self._candidates = fresh
            self._candidate_index = 0
            self._candidate_summary = {
                "found": len(found), "marked": len(marked),
                "new": sum(1 for c in fresh if not c["in_reference"]), "with_reference": with_reference,
            }
            if not fresh:
                self.set_tool("pan")
                self.set_status(
                    f"Found {len(found)} bright spots in that region; all {len(marked)} already have markers."
                    if found else "No bright spots found in that region.  Try a higher sensitivity.")
                return
            self.tool_var.set("review")
            self._on_tool_changed()
            self._show_candidate()

        self._run_in_background(
            "Finding pinholes", [("Searching the backlit image for small bright spots...", work)], finished)

    # ------------------------------------------------------------------ #
    # Review
    # ------------------------------------------------------------------ #

    def _review_candidates(self):
        """The candidates still awaiting a decision, honouring the 'new only' filter."""
        if self.detect_new_only_var.get() and self._candidate_summary.get("with_reference"):
            return [c for c in self._candidates if not c["in_reference"]]
        return self._candidates

    def _current_candidate(self):
        pending = self._review_candidates()
        if not pending:
            return None
        self._candidate_index = max(0, min(self._candidate_index, len(pending) - 1))
        return pending[self._candidate_index]

    def _show_candidate(self):
        candidate = self._current_candidate()
        if candidate is None:
            self._finish_review()
            return
        # Centre it in the panel at a zoom where a pinhole is easy to judge.
        canvas = self.panes[0].canvas
        if self.zoom < REVIEW_ZOOM:
            self.zoom = REVIEW_ZOOM
        wx, wy = geo.apply(self.world_matrix(CURRENT, BACKLIT), candidate["x"], candidate["y"])
        self.pan_x = canvas.winfo_width() / 2.0 - self.zoom * wx
        self.pan_y = canvas.winfo_height() / 2.0 - self.zoom * wy
        self._view_is_fit = False
        self._update_zoom_readout()
        self._refresh_hint()
        self._schedule_render()

    def review_accept(self):
        candidate = self._current_candidate()
        if candidate is None:
            return
        if not self._add_candidate_markers([candidate]):
            return
        self._candidates.remove(candidate)
        self._show_candidate()

    def review_unsure(self):
        """Accept the candidate, flagged with a question mark as one to look at again."""
        candidate = self._current_candidate()
        if candidate is None:
            return
        if not self._add_candidate_markers([candidate], unsure=True):
            return
        self._candidates.remove(candidate)
        self._show_candidate()

    def review_skip(self, step=1):
        pending = self._review_candidates()
        if not pending:
            self._finish_review()
            return
        if step > 0 and self._candidate_index >= len(pending) - 1:
            self._finish_review()
            return
        self._candidate_index = max(0, self._candidate_index + step)
        self._show_candidate()

    def review_reject(self):
        candidate = self._current_candidate()
        if candidate is None:
            return
        self._candidates.remove(candidate)
        self._show_candidate()

    def review_accept_all(self):
        pending = list(self._review_candidates())
        if not pending:
            return
        if not messagebox.askyesno(
                "Find pinholes",
                f"Add a marker for all {len(pending)} remaining candidates?\n\n"
                "Each becomes a marker in the colour in use.  Ctrl+Z removes them again.",
                parent=self.root):
            return
        if self._add_candidate_markers(pending):
            for candidate in pending:
                self._candidates.remove(candidate)
            self._finish_review()

    def _add_candidate_markers(self, candidates, unsure=False):
        pair = self.pairs[CURRENT]
        colour = self.annot_colour
        if colour not in pair.colour_labels or pair.prefix_for(colour) is None:
            details = self._ask_colour_details(colour)
            if details is None:
                return False
            pair.colour_labels[colour], pair.label_prefixes[colour] = details
            self._sync_controls()
        self._checkpoint("Add detected markers" if len(candidates) > 1 else "Add detected marker")
        radius = self._marker_radius()
        for candidate in candidates:
            marker = {
                "img1_x": candidate["x"],
                "img1_y": candidate["y"],
                "radius": max(radius, candidate["radius"] * 2.0),
                "colour": colour,
                "label": pair.next_label(colour) if self.annot_autolabel_var.get() else "",
            }
            if unsure:
                marker["unsure"] = True
            pair.annotations.append(marker)
        return True

    def _finish_review(self):
        self._candidates = []
        self._candidate_index = 0
        if self.tool_var.get() == "review":
            self.set_tool("pan")
        self._draw_overlays()

    def _draw_candidates(self, pane):
        if self.tool_var.get() != "review" or pane.row != CURRENT:
            return
        current = self._current_candidate()
        for candidate in self._review_candidates():
            x, y = self.image_to_canvas(CURRENT, BACKLIT, candidate["x"], candidate["y"])
            is_current = candidate is current
            radius = max(self.px(9), candidate["radius"] * self.zoom * 2.5) + (self.px(4) if is_current else 0)
            pane.canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                outline="#ffe14d" if is_current else "#ffffff", width=self.px(2 if is_current else 1),
                dash=(4, 3), tags="world")
