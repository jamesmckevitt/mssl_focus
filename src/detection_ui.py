"""The automatic pinhole search: its search area (the filter outline), the live
preview of what it finds, the one-by-one review, and centring markers on spots."""

import math
import tkinter as tk
from tkinter import messagebox

import numpy as np

from . import geometry as geo
from .detect import (
    DEFAULT_SENSITIVITY,
    find_pinholes,
    flag_present_in,
    inside_polygon,
    markers_without_a_spot,
    match_markers_to_spots,
    minimum_score,
    realign_markers,
    split_by_markers,
)
from .pair import BACKLIT
from .viewer import CURRENT, REFERENCE

REVIEW_ZOOM = 2.0
SEARCH_PAD = 80        # pixels searched beyond the outline, so adjusting it needs no new search
SPOT_LIMIT = 12000
DRAW_LIMIT = 4000
CENTRE_REACH = 12.0    # a marker is centred on a spot inside its circle, or at least this close
QUICK_AREA = 1_500_000  # pixels; smaller searches run at once, without a progress window
ROUNDED_POINTS = len(geo.rounded_rectangle(0, 0, 100, 100, 10))
TIER_COLOURS = {"clear": "#6ee67a", "likely": "#ffe14d", "faint": "#ff9d5c"}


def _padded_box(points, size, pad):
    """Bounding box of ``points`` grown by ``pad`` and clipped to an image of ``size``."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    width, height = size
    return (int(max(0, math.floor(points[:, 0].min()) - pad)), int(max(0, math.floor(points[:, 1].min()) - pad)),
            int(min(width, math.ceil(points[:, 0].max()) + pad)), int(min(height, math.ceil(points[:, 1].max()) + pad)))


def _spots_in(image, box):
    """Every spot the search finds in a region of an image, in that image's pixel coordinates."""
    left, top, right, bottom = box
    if right - left < 8 or bottom - top < 8:
        return []
    found, _total = find_pinholes(image.crop(box), limit=SPOT_LIMIT)
    for candidate in found:
        candidate["x"] += left
        candidate["y"] += top
    return found


class DetectMixin:
    # ------------------------------------------------------------------ #
    # Search area (the filter outline)
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

    def _outline_numbers(self):
        """Corner radius and inset as typed, or None while a box is empty or mid-edit."""
        try:
            return max(0.0, float(self.outline_radius_var.get())), float(self.outline_inset_var.get())
        except ValueError:
            return None

    def _prepare_detect_tool(self):
        """Pick up the existing search area so its rounding and inset can be adjusted."""
        self._outline_rect = None
        self._outline_built = None
        self._outline_redraw = False
        outline = self.effective_outline()
        if len(outline) < 3:
            return
        points = geo.apply_many(self.pairs[CURRENT].matrix(BACKLIT), outline)
        rect = (float(points[:, 0].min()), float(points[:, 1].min()),
                float(points[:, 0].max()), float(points[:, 1].max()))
        self._outline_rect = rect
        self._syncing = True
        if len(outline) == 4:
            self.outline_radius_var.set("0")
        elif len(outline) == ROUNDED_POINTS:   # the first point is where the top-left corner starts to curve
            self.outline_radius_var.set(str(int(round(max(0.0, points[0][1] - rect[1])))))
        self.outline_inset_var.set("0")
        self._syncing = False
        self._outline_built = (rect, self._outline_numbers())

    def _outline_drawing(self):
        """Whether a drag in the Find pinholes tool draws the search area (rather than pans)."""
        return self._outline_redraw or self._outline_rect is None

    def redraw_outline(self):
        self._outline_redraw = True
        self._update_cursor()
        self._refresh_hint()

    def _outline_rubber(self, x0, y0, x1, y1):
        """Canvas points of the rounded shape a drag between two corners would give."""
        numbers = self._outline_numbers()
        radius = (numbers[0] if numbers else 0.0) * self.zoom
        return geo.rounded_rectangle(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), radius)

    def _set_outline_from_drag(self, pane, x0, y0, x1, y1):
        if pane.row != CURRENT:
            self.set_status("Draw the search area on the current (top) row; the reference row keeps its own.")
            return
        ax, ay = self.canvas_to_pair(CURRENT, x0, y0)
        bx, by = self.canvas_to_pair(CURRENT, x1, y1)
        self._outline_rect = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
        self._outline_redraw = False
        self._last_checkpoint = (None, 0.0)   # a new drag is its own undo step
        self._update_cursor()
        self._rebuild_outline()

    def _rebuild_outline(self):
        numbers = self._outline_numbers()
        if self._syncing or self._outline_rect is None or numbers is None:
            return
        if self._outline_built == (self._outline_rect, numbers):
            return
        radius, inset = numbers
        x0, y0, x1, y1 = self._outline_rect
        x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        if x1 - x0 < 8 or y1 - y0 < 8:
            return
        pair = self.pairs[CURRENT]
        self._checkpoint("Set search area", coalesce="outline")
        points = geo.rounded_rectangle(x0, y0, x1, y1, radius)
        pair.outline = [[float(x), float(y)] for x, y in geo.apply_many(geo.invert(pair.matrix(BACKLIT)), points)]
        self._outline_built = (self._outline_rect, numbers)
        self._ensure_search()

    def clear_outline(self):
        if self.pairs[CURRENT].outline:
            self._checkpoint("Clear search area")
            self.pairs[CURRENT].outline = []
        self._prepare_detect_tool()
        self._update_cursor()
        self._ensure_search()

    def _draw_outline(self, pane):
        if self.tool_var.get() not in ("detect", "review"):
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

    def _forget_detection(self):
        self._detection = None
        self._rejected = set()
        self._pending_key = None
        self._candidates = []
        self._candidate_summary = {}
        self._candidate_index = 0

    def _to_reference(self):
        """Current backlit pixels -> reference backlit pixels."""
        return geo.invert(self.world_matrix(REFERENCE, BACKLIT)) @ self.world_matrix(CURRENT, BACKLIT)

    def _detection_covers(self, outline):
        """Whether the last search still holds for the images shown and takes in ``outline``."""
        detection = self._detection
        current, reference = self.pairs
        if detection is None or len(outline) < 3 or not current.has_image(BACKLIT):
            return False
        if detection["image"] is not current.pyramids[BACKLIT].image:
            return False
        with_reference = self._reference_ready() and reference.has_image(BACKLIT)
        if with_reference != (detection["ref_image"] is not None):
            return False
        if with_reference and (detection["ref_image"] is not reference.pyramids[BACKLIT].image
                               or not np.allclose(detection["to_reference"], self._to_reference(), atol=1e-6)):
            return False
        left, top, right, bottom = _padded_box(outline, detection["image"].size, 0)
        box = detection["box"]
        return box[0] <= left and box[1] <= top and box[2] >= right and box[3] >= bottom

    def _ensure_search(self):
        """Search again if the search area or the images have changed; otherwise just redraw."""
        if self.tool_var.get() not in ("detect", "review"):
            return
        outline = self.effective_outline()
        if len(outline) >= 3 and self.pairs[CURRENT].has_image(BACKLIT) and not self._detection_covers(outline):
            self.search_pinholes()
            return
        self._refresh_hint()
        self._draw_overlays()

    def search_pinholes(self):
        """Find every small bright spot in and around the search area, in both rows."""
        current, reference = self.pairs
        outline = self.effective_outline()
        if not current.has_image(BACKLIT):
            self.set_status("Load a backlit image first.")
            return
        if len(outline) < 3:
            self.set_status("Drag across the filter first, to say where to look.")
            return
        image = current.pyramids[BACKLIT].image
        box = _padded_box(outline, image.size, SEARCH_PAD)
        ref_image = ref_box = to_reference = None
        if self._reference_ready() and reference.has_image(BACKLIT):
            ref_image = reference.pyramids[BACKLIT].image
            to_reference = self._to_reference()
            ref_box = _padded_box(geo.apply_many(to_reference, outline), ref_image.size, SEARCH_PAD)

        def work():
            found = _spots_in(image, box)
            earlier = _spots_in(ref_image, ref_box) if ref_image is not None else []
            return found, [(c["x"], c["y"]) for c in earlier]

        def finished(results):
            result = results[0]
            if isinstance(result, Exception):
                messagebox.showerror("Find pinholes", f"The search failed.\n\n{result}", parent=self.root)
                self.set_tool("pan")
                return
            self._forget_detection()
            self._detection = {"found": result[0], "earlier": result[1], "box": box, "image": image,
                               "ref_image": ref_image, "to_reference": to_reference}
            if self.tool_var.get() == "review":
                self._show_candidate()
            self._refresh_hint()
            self._draw_overlays()
            pending = self._pending()
            counts = {tier: sum(1 for c in pending if c["tier"] == tier) for tier in TIER_COLOURS}
            self.set_status(
                f"Found {counts['clear']} clear, {counts['likely']} likely and {counts['faint']} faint spot(s) "
                f"without a marker; {self._candidate_summary.get('marked', 0)} already marked.  "
                "Move the Sensitivity slider to choose how many are offered.")

        self._run_in_background(
            "Finding pinholes", [("Searching the backlit image for small bright spots...", work)], finished)

    def _pending(self):
        """Spots inside the search area with no marker that have not been rejected, best first.

        Worked out again only when the search area, the markers or the alignment change.
        """
        detection = self._detection
        current = self.pairs[CURRENT]
        if detection is None or not current.has_image(BACKLIT) \
                or detection["image"] is not current.pyramids[BACKLIT].image:
            return []
        outline = self.effective_outline()
        with_reference = detection["ref_image"] is not None and self._reference_ready()
        from_reference = geo.invert(self._to_reference()) if with_reference else None
        markers = [(a["img1_x"], a["img1_y"], a["radius"]) for a in current.annotations]
        key = (id(detection), tuple(outline), tuple(markers), len(self._rejected),
               tuple(from_reference.ravel()) if with_reference else None)
        if key == self._pending_key:
            return self._candidates

        found = detection["found"]
        if len(outline) >= 3 and found:
            keep = inside_polygon([c["x"] for c in found], [c["y"] for c in found], outline)
            found = [c for c, inside in zip(found, keep) if inside]
        else:
            found = []
        labels = [a.get("label") or "unlabelled" for a in current.annotations]
        if markers and len(outline) >= 3:
            keep = inside_polygon([m[0] for m in markers], [m[1] for m in markers], outline)
            lonely = markers_without_a_spot([m for m, inside in zip(markers, keep) if inside], found)
            inside_labels = [label for label, inside in zip(labels, keep) if inside]
            lonely = [inside_labels[n] for n in lonely]
        else:
            lonely = []
        fresh, marked = split_by_markers([c for c in found if id(c) not in self._rejected], markers)
        earlier = detection["earlier"]
        flag_present_in(fresh, [tuple(p) for p in geo.apply_many(from_reference, earlier)]
                        if with_reference and earlier else [])
        # Surest first; with a reference row, spots absent from the earlier image before the rest.
        fresh.sort(key=lambda c: (c["in_reference"], -c["score"]))
        self._candidates = fresh
        self._candidate_summary = {
            "marked": len(marked),
            "with_reference": with_reference,
            "new": sum(1 for c in fresh if not c["in_reference"] and c["tier"] != "faint"),
            "lonely": lonely,
        }
        self._pending_key = key
        return fresh

    def _sensitivity(self):
        try:
            return min(100.0, max(0.0, float(self.detect_sensitivity_var.get())))
        except (ValueError, TypeError, tk.TclError):
            return float(DEFAULT_SENSITIVITY)

    def _review_candidates(self):
        """The spots on offer: those awaiting a decision that pass the Sensitivity
        setting and the 'only new' choice."""
        floor = minimum_score(self._sensitivity())
        pending = [c for c in self._pending() if c["score"] >= floor]
        if self.detect_new_only_var.get() and self._candidate_summary.get("with_reference"):
            pending = [c for c in pending if not c["in_reference"]]
        return pending

    def _on_detect_filter_changed(self, _value=None):
        """The Sensitivity slider or the 'only new' box changed."""
        self.detect_sensitivity_var.set(round(self._sensitivity()))
        self._candidate_index = 0
        if self.tool_var.get() == "review":
            self._show_candidate()
        else:
            self._refresh_hint()
            self._draw_overlays()

    # ------------------------------------------------------------------ #
    # Adding what was found
    # ------------------------------------------------------------------ #

    def start_review(self):
        if not self._review_candidates():
            self.set_status("There is nothing to review at this sensitivity.")
            return
        self._candidate_index = 0
        self.tool_var.set("review")
        self._on_tool_changed()
        self._show_candidate()

    def add_all_shown(self):
        """Add a marker for every spot currently on offer."""
        shown = self._review_candidates()
        if not shown:
            return
        faint = sum(1 for c in shown if c["tier"] == "faint")
        if faint and not messagebox.askyesno(
                "Add all",
                f"{faint} of the {len(shown)} spots shown are faint, and most faint spots are noise "
                "rather than pinholes.\n\nAdd markers for all of them anyway?\n\n"
                "(Lower the Sensitivity to leave the faint ones out.)", parent=self.root):
            return
        if self._add_candidate_markers(shown):
            self.set_status(f"Added {len(shown)} marker(s).  Ctrl+Z removes them again.")
            self._refresh_hint()
            self._draw_overlays()

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
        if accept:
            if not self._add_candidate_markers([candidate], unsure=unsure):
                return
        else:
            self._rejected.add(id(candidate))
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
        """Leave the one-by-one review, back to the overview of what was found."""
        self._candidate_index = 0
        if self.tool_var.get() == "review":
            self.set_tool("detect")
        else:
            self._refresh_hint()
            self._draw_overlays()

    def _draw_candidates(self, pane):
        self._draw_outline(pane)
        tool = self.tool_var.get()
        if tool not in ("detect", "review") or pane.row != CURRENT:
            return
        current = self._current_candidate() if tool == "review" else None
        smallest = self.px(9 if tool == "review" else 6)
        canvas = pane.canvas
        for candidate in self._review_candidates()[:DRAW_LIMIT]:
            x, y = self.image_to_canvas(CURRENT, BACKLIT, candidate["x"], candidate["y"])
            radius = max(smallest, candidate["radius"] * self.zoom * 2.5)
            colour = TIER_COLOURS[candidate["tier"]]
            if candidate is current:
                radius += self.px(4)
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                                   outline=colour, width=self.px(3), dash=(4, 3), tags="world")
            else:
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                                   outline=colour, width=self.px(1), tags="world")

    # ------------------------------------------------------------------ #
    # Centring markers on the spots they mark
    # ------------------------------------------------------------------ #

    def centre_markers(self, indices=None):
        """Move markers onto the bright spots they mark.

        With no ``indices``, every marker of the current row, using the spots that
        pass the Sensitivity setting, and allowing for the markers all being off in
        the same way (see ``realign_markers``).  Otherwise just the markers listed,
        each to the best spot near it.  A marker with no spot is left alone.
        """
        pair = self.pairs[CURRENT]
        if not pair.has_image(BACKLIT) or not pair.annotations:
            self.set_status("There are no markers to centre.")
            return
        everything = indices is None
        chosen = list(range(len(pair.annotations))) if everything else list(indices)
        floor = minimum_score(self._sensitivity()) if everything else 0.0
        markers = [(a["img1_x"], a["img1_y"], a["radius"]) for a in (pair.annotations[i] for i in chosen)]
        image = pair.pyramids[BACKLIT].image
        reach = 2.0 * max(max(radius, CENTRE_REACH) for _x, _y, radius in markers)
        box = _padded_box([(x, y) for x, y, _r in markers], image.size, reach + SEARCH_PAD)

        def finished(results):
            found = results[0]
            if isinstance(found, Exception):
                messagebox.showerror("Centre markers", f"The search failed.\n\n{found}", parent=self.root)
                return
            spots = [c for c in found if c["score"] >= floor]
            if everything:
                positions, matched = realign_markers(markers, spots, CENTRE_REACH)
            else:
                hits = match_markers_to_spots(markers, spots, CENTRE_REACH, reach=2.0)
                matched = set(hits)
                positions = [(hits[m]["x"], hits[m]["y"]) if m in hits else markers[m][:2]
                             for m in range(len(markers))]
            moves = [math.hypot(x - markers[m][0], y - markers[m][1]) for m, (x, y) in enumerate(positions)]
            moved = [m for m, distance in enumerate(moves) if distance > 0.25]
            if moved:
                self._checkpoint("Centre markers on pinholes")
                for m in moved:
                    ann = pair.annotations[chosen[m]]
                    ann["img1_x"], ann["img1_y"] = float(positions[m][0]), float(positions[m][1])
            missing = [pair.annotations[chosen[m]].get("label") or "unlabelled"
                       for m in range(len(markers)) if m not in matched]
            parts = []
            if moved:
                parts.append(f"Centred {len(moved)} marker(s) on the bright spot they mark "
                             f"(largest move {max(moves[m] for m in moved):.0f} px).  Ctrl+Z undoes.")
            if len(matched) > len(moved):
                parts.append(f"{len(matched) - len(moved)} already centred.")
            if missing:
                names = ", ".join(missing[:8]) + ("..." if len(missing) > 8 else "")
                parts.append(f"{len(missing)} have no bright spot" + (" at this sensitivity" if everything else "")
                             + f" and were left where they are: {names}.")
            self.set_status("  ".join(parts))
            self._refresh_hint()
            self._draw_overlays()

        if (box[2] - box[0]) * (box[3] - box[1]) <= QUICK_AREA:
            try:
                finished([_spots_in(image, box)])
            except Exception as exc:  # reported in a dialog, like a failure in the background
                finished([exc])
        else:
            self._run_in_background(
                "Centring markers", [("Looking for the bright spot under each marker...",
                                      lambda: _spots_in(image, box))], finished)
