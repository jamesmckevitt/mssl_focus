"""The filter outline, the automatic pinhole search, and the review of what it finds."""

from tkinter import messagebox

import numpy as np
from PIL import Image, ImageDraw

from . import geometry as geo
from .detect import (
    TIER_ORDER,
    find_pinholes,
    flag_present_in,
    markers_without_a_spot,
    point_in_polygon,
    split_by_markers,
)
from .pair import BACKLIT
from .viewer import CURRENT, REFERENCE

REVIEW_ZOOM = 2.0
MARGIN = 40  # pixels of context around the searched region, for the background estimate


class DetectMixin:
    # ------------------------------------------------------------------ #
    # Filter outline
    # ------------------------------------------------------------------ #

    def effective_outline(self):
        """The filter outline in current-row backlit pixels: the row's own, or
        failing that the reference row's, carried across by the row alignment."""
        current, reference = self.pairs
        if len(current.outline) >= 3:
            return [tuple(p) for p in current.outline]
        if self._reference_ready() and len(reference.outline) >= 3:
            across = geo.invert(self.world_matrix(CURRENT, BACKLIT)) @ self.world_matrix(REFERENCE, BACKLIT)
            return [tuple(p) for p in geo.apply_many(across, reference.outline)]
        return []

    def _prepare_outline_tool(self):
        """Pick up an existing outline so its rounding and inset can be adjusted."""
        pair = self.pairs[CURRENT]
        self._outline_rect = None
        if len(pair.outline) >= 3:
            points = geo.apply_many(pair.matrix(BACKLIT), pair.outline)
            self._outline_rect = (float(points[:, 0].min()), float(points[:, 1].min()),
                                  float(points[:, 0].max()), float(points[:, 1].max()))
            self._syncing = True
            self.outline_inset_var.set("0")
            self._syncing = False

    def _set_outline_from_drag(self, pane, x0, y0, x1, y1):
        if pane.row != CURRENT:
            self.set_status("Draw the outline on the current (top) row; the reference row keeps its own.")
            return
        ax, ay = self.canvas_to_pair(CURRENT, x0, y0)
        bx, by = self.canvas_to_pair(CURRENT, x1, y1)
        self._outline_rect = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
        self._rebuild_outline()
        self.set_status("Outline set.  Adjust 'Corner radius' until the corners follow the filter edge, "
                        "and 'Inset' to pull the line just inside it.")

    def _rebuild_outline(self):
        if self._syncing or self._outline_rect is None:
            return
        try:
            radius = max(0.0, float(self.outline_radius_var.get()))
            inset = float(self.outline_inset_var.get())
        except ValueError:
            return
        x0, y0, x1, y1 = self._outline_rect
        x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        if x1 - x0 < 8 or y1 - y0 < 8:
            return
        pair = self.pairs[CURRENT]
        self._checkpoint("Set filter outline", coalesce="outline")
        points = geo.rounded_rectangle(x0, y0, x1, y1, radius)
        pair.outline = [[float(x), float(y)] for x, y in geo.apply_many(geo.invert(pair.matrix(BACKLIT)), points)]
        self._refresh_hint()
        self._draw_overlays()

    def clear_outline(self):
        if self.pairs[CURRENT].outline:
            self._checkpoint("Clear filter outline")
            self.pairs[CURRENT].outline = []
        self._outline_rect = None
        self._refresh_hint()
        self._draw_overlays()

    def _draw_outline(self, pane):
        if self.tool_var.get() not in ("outline", "detect", "review"):
            return
        outline = self.effective_outline() if pane.row == CURRENT else self.pairs[REFERENCE].outline
        if len(outline) < 3:
            return
        flat = []
        for x, y in outline:
            flat.extend(self.image_to_canvas(pane.row, BACKLIT, x, y))
        own = pane.row == REFERENCE or len(self.pairs[CURRENT].outline) >= 3
        pane.canvas.create_polygon(*flat, outline="#4fd0ff" if own else "#b48cff", fill="",
                                   width=self.px(2), dash=(8, 5), tags="world")

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #

    def _detect_in(self, row, world_polygon):
        """Spots of one row's backlit image inside a region given in world coordinates."""
        polygon = geo.apply_many(geo.invert(self.world_matrix(row, BACKLIT)), world_polygon)
        width, height = self.pairs[row].size(BACKLIT)
        left = int(max(0, np.floor(polygon[:, 0].min()) - MARGIN))
        top = int(max(0, np.floor(polygon[:, 1].min()) - MARGIN))
        right = int(min(width, np.ceil(polygon[:, 0].max()) + MARGIN))
        bottom = int(min(height, np.ceil(polygon[:, 1].max()) + MARGIN))
        if right - left < 8 or bottom - top < 8:
            return [], 0
        image = self.pairs[row].pyramids[BACKLIT].image.crop((left, top, right, bottom))
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).polygon([(float(x) - left, float(y) - top) for x, y in polygon], fill=255)
        found, total = find_pinholes(image, mask=np.asarray(mask))
        for candidate in found:
            candidate["x"] += left
            candidate["y"] += top
        return found, total

    def find_pinholes_in(self, canvas_rect=None):
        """Search the current backlit image -- inside the filter outline, or inside a
        canvas rectangle if one is given -- and start the review."""
        current, reference = self.pairs
        if not current.has_image(BACKLIT):
            self.set_status("Load a backlit image first.")
            return
        if canvas_rect is not None:
            x0, y0, x1, y1 = canvas_rect
            world_polygon = geo.apply_many(geo.invert(self.view_matrix()), [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        else:
            outline = self.effective_outline()
            if len(outline) < 3:
                self.set_status("Draw the filter outline first (Outline tool), or drag a rectangle to search.")
                return
            world_polygon = geo.apply_many(self.world_matrix(CURRENT, BACKLIT), outline)
        with_reference = self._reference_ready() and reference.has_image(BACKLIT)
        from_reference = (geo.invert(self.world_matrix(CURRENT, BACKLIT)) @ self.world_matrix(REFERENCE, BACKLIT)
                          if with_reference else None)
        region = [tuple(p) for p in geo.apply_many(geo.invert(self.world_matrix(CURRENT, BACKLIT)), world_polygon)]

        def work():
            found, _total = self._detect_in(CURRENT, world_polygon)
            earlier = []
            if with_reference:
                ref_found, _ = self._detect_in(REFERENCE, world_polygon)
                earlier = [geo.apply(from_reference, c["x"], c["y"]) for c in ref_found]
            return found, earlier

        def finished(results):
            result = results[0]
            if isinstance(result, Exception):
                messagebox.showerror("Find pinholes", f"The search failed.\n\n{result}", parent=self.root)
                self.set_tool("pan")
                return
            found, earlier = result
            inside = [a for a in current.annotations if point_in_polygon(a["img1_x"], a["img1_y"], region)]
            fresh, marked = split_by_markers(found, [(a["img1_x"], a["img1_y"], a["radius"])
                                                    for a in current.annotations])
            lonely = markers_without_a_spot([(a["img1_x"], a["img1_y"], a["radius"]) for a in inside], found)
            flag_present_in(fresh, earlier)
            # Surest first; with a reference row, spots absent from the earlier image before the rest.
            fresh.sort(key=lambda c: (c["in_reference"], TIER_ORDER[c["tier"]], -c["peak"]))
            self._candidates = fresh
            self._candidate_index = 0
            self._candidate_summary = {
                "marked": len(marked),
                "with_reference": with_reference,
                "new": sum(1 for c in fresh if not c["in_reference"] and c["tier"] != "faint"),
                "lonely": [inside[n].get("label") or "unlabelled" for n in lonely],
            }
            counts = {tier: sum(1 for c in fresh if c["tier"] == tier) for tier in TIER_ORDER}
            lonely_note = ""
            if lonely:
                names = ", ".join(self._candidate_summary["lonely"][:8]) + ("..." if len(lonely) > 8 else "")
                lonely_note = f"  {len(lonely)} existing marker(s) have no bright spot under them: {names}."
            if not self._review_candidates():
                self.set_tool("pan")
                self.set_status(
                    f"Nothing new: {len(marked)} spot(s) already have markers"
                    + (f", and {counts['faint']} faint spot(s) were left out" if counts["faint"] else "")
                    + "." + lonely_note)
                return
            self.tool_var.set("review")
            self._on_tool_changed()
            self._show_candidate()
            self.set_status(
                f"Found {counts['clear']} clear, {counts['likely']} likely and {counts['faint']} faint spot(s) "
                f"without a marker; {len(marked)} already marked." + lonely_note)

        self._run_in_background(
            "Finding pinholes", [("Searching the backlit image for small bright spots...", work)], finished)

    # ------------------------------------------------------------------ #
    # Review
    # ------------------------------------------------------------------ #

    def _review_candidates(self):
        """The candidates still awaiting a decision, honouring the 'faint' and 'new only' choices."""
        pending = self._candidates
        if not self.detect_faint_var.get():
            pending = [c for c in pending if c["tier"] != "faint"]
        if self.detect_new_only_var.get() and self._candidate_summary.get("with_reference"):
            pending = [c for c in pending if not c["in_reference"]]
        return pending

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

    def _decide(self, accept, unsure=False):
        candidate = self._current_candidate()
        if candidate is None:
            return
        if accept and not self._add_candidate_markers([candidate], unsure=unsure):
            return
        self._candidates.remove(candidate)
        self._show_candidate()

    def review_accept(self):
        self._decide(True)

    def review_unsure(self):
        """Accept the candidate, flagged with a question mark as one to look at again."""
        self._decide(True, unsure=True)

    def review_reject(self):
        self._decide(False)

    def review_skip(self, step=1):
        pending = self._review_candidates()
        if not pending or (step > 0 and self._candidate_index >= len(pending) - 1):
            self._finish_review()
            return
        self._candidate_index = max(0, self._candidate_index + step)
        self._show_candidate()

    def review_accept_clear(self):
        """Add markers for every remaining candidate the search is confident about."""
        clear = [c for c in self._review_candidates() if c["tier"] == "clear"]
        if clear and self._add_candidate_markers(clear):
            for candidate in clear:
                self._candidates.remove(candidate)
            self._candidate_index = 0
            self.set_status(f"Added {len(clear)} marker(s) for the clear spots.  Ctrl+Z removes them again.")
            self._show_candidate()

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
        self._draw_outline(pane)
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
