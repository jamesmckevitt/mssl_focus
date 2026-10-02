import os
import time
import tkinter as tk

from .annotations import AnnotationMixin
from .config import Config
from .detection_ui import DetectMixin
from .export import ExportMixin
from .help import show_guide
from .metadata import APP_AUTHOR, APP_EMAIL, APP_INSTITUTION, APP_VERSION
from .pair import ImagePair
from .session import SessionMixin
from .theme import apply_theme
from .tools import ToolsMixin
from .ui import UIBuilderMixin
from .viewer import ViewerMixin
from .window_icon import set_app_icon


__author__ = APP_AUTHOR
__institution__ = APP_INSTITUTION
__email__ = APP_EMAIL

APP_TITLE = "MSSL FOCUS"
UNDO_LIMIT = 200
COALESCE_SECONDS = 1.5


class ImageComparer(ExportMixin, SessionMixin, DetectMixin, AnnotationMixin, ToolsMixin, ViewerMixin,
                    UIBuilderMixin):
    def __init__(self, root, config=None):
        self.root = root
        self.config = config if config is not None else Config()
        self.fonts, self.ui_scale = apply_theme(root)
        set_app_icon(root)

        # Row 0 is the inspection being worked on; row 1 an optional reference inspection.
        self.pairs = [ImagePair(), ImagePair()]
        self.row_shift = {"x": 0.0, "y": 0.0, "rot": 0.0, "scale": 1.0}
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        self.session_path = None
        self.dirty = False
        self.annot_colour = "#ff0000"

        self._undo_stack = []
        self._redo_stack = []
        self._last_checkpoint = (None, 0.0)

        self._busy = False
        self._syncing = False
        self._interacting = False
        self._render_job = None
        self._quality_job = None
        self._refit_job = None
        self._view_is_fit = True
        self._press = None
        self._hover = None
        self._tool_point_order = []
        self._legend_fonts = {}
        self._badge_font = None
        self._candidates = []
        self._candidate_index = 0
        self._candidate_summary = {}
        self._tool_state = {"row": None, "a": [], "b": [], "cur": [], "ref": []}

        self._restore_window()
        self._build_ui()
        self._layout_panes()
        self._sync_controls()
        self._update_title()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.config.get("show_guide_at_start", True):
            self.root.after(400, lambda: show_guide(self))

    # ------------------------------------------------------------------ #
    # Window
    # ------------------------------------------------------------------ #

    def _restore_window(self):
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = min(int(1500 * self.ui_scale), screen_w - 80)
        height = min(int(950 * self.ui_scale), screen_h - 120)
        self.root.geometry(f"{width}x{height}+{(screen_w - width) // 2}+{max(0, (screen_h - height) // 3)}")
        self.root.minsize(int(900 * self.ui_scale), int(560 * self.ui_scale))
        if self.config.get("maximised", False):
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass

    def _update_title(self):
        name = os.path.basename(self.session_path) if self.session_path else "Untitled session"
        label = self.pairs[0].label
        where = f"  ({label})" if label and self.session_path else ""
        self.root.title(f"{'* ' if self.dirty else ''}{name}{where}  -  {APP_TITLE}")

    def _on_close(self):
        if self._busy:
            return
        if not self._confirm_discard("exit"):
            return
        try:
            self.config.set("maximised", self.root.state() == "zoomed")
        except tk.TclError:
            pass
        self.root.destroy()

    # ------------------------------------------------------------------ #
    # State changes, undo and redo
    # ------------------------------------------------------------------ #

    def _new_pair(self, row):
        self.pairs[row] = ImagePair()

    def _reset_state(self):
        """Back to an empty session."""
        self.pairs = [ImagePair(), ImagePair()]
        self.reset_row_shift()
        self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
        self._view_is_fit = True
        self.session_path = None
        self.dirty = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.show_reference_var.set(False)
        self.mode_var.set("sidebyside")
        self.opacity_var.set(0.5)
        self.control_row_var.set(0)
        self.tool_var.set("pan")
        self._on_tool_changed()
        self._update_zoom_readout()
        self._update_title()
        self._layout_panes()
        self._sync_controls()

    def _snapshot(self):
        return {
            "pairs": [pair.snapshot() for pair in self.pairs],
            "row_shift": dict(self.row_shift),
        }

    def _restore(self, snap):
        for pair, pair_snap in zip(self.pairs, snap["pairs"]):
            pair.restore(pair_snap)
        self.row_shift = dict(snap["row_shift"])

    def _mark_dirty(self):
        if not self.dirty:
            self.dirty = True
            self._update_title()

    def _checkpoint(self, label, coalesce=None):
        """Record the state before a change so it can be undone.

        Rapid repeats of the same adjustment (a slider drag, held arrow key)
        collapse into a single undo step.
        """
        now = time.monotonic()
        last_key, last_time = self._last_checkpoint
        self._last_checkpoint = (coalesce, now)
        self._mark_dirty()
        if coalesce is not None and coalesce == last_key and now - last_time < COALESCE_SECONDS:
            return
        self._undo_stack.append((label, self._snapshot()))
        del self._undo_stack[:-UNDO_LIMIT]
        self._redo_stack.clear()
        self._update_undo_buttons()

    def _step_history(self, source, target, verb):
        if not source or self._busy:
            return
        label, snap = source.pop()
        target.append((label, self._snapshot()))
        self._restore(snap)
        self._last_checkpoint = (None, 0.0)
        self._mark_dirty()
        self._clear_tool_points(redraw=False)
        self._sync_controls()
        self._schedule_render()
        self.set_status(f"{verb}: {label}")

    def undo(self):
        self._step_history(self._undo_stack, self._redo_stack, "Undid")

    def redo(self):
        self._step_history(self._redo_stack, self._undo_stack, "Redid")

    def _update_undo_buttons(self):
        self.undo_button.state(["!disabled"] if self._undo_stack else ["disabled"])
        self.redo_button.state(["!disabled"] if self._redo_stack else ["disabled"])


__all__ = ["APP_VERSION", "ImageComparer", "__author__", "__email__", "__institution__"]
