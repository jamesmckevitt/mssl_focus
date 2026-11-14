"""Session files: the session commands in the window.

Reading, writing and locating the files a session refers to live in
``session_data.py``, which has no user-interface dependency so the command line
can use it too; they are re-exported here so existing imports keep working.
"""

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import geometry as geo
from . import theme
from .camera import camera_differences, describe_camera, exposure_stops
from .imaging import IMAGE_FILETYPES, is_raw
from .metadata import APP_VERSION
from .pair import BACKLIT, FRONTLIT, ImagePair, normalise_annotation
from . import history as hist
from .session_data import (CURRENT, RAW_CROP_VERSION, REFERENCE, SESSION_VERSION,
                           SETTINGS_FILE_TYPE, alignment_key, describe_location,
                           describe_saved_reference, develop_record, fill_pair_from_session,
                           read_session, relative_to, resolve_frame_paths, resolve_image_path,
                           row_alignments_from_session, row_matrix_from_record,
                           session_has_reference, session_image_paths,
                           shift_legacy_raw_markers, write_session, _float, _pair_of)

SESSION_FILETYPES = [("Session or filter history", "*.json"), ("All files", "*.*")]
SETTINGS_FILETYPES = [("Image settings or session", "*.json"), ("All files", "*.*")]


def _same_file(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _is_history_file(path):
    try:
        return Path(path).is_file() and hist.is_history(read_session(path))
    except (OSError, ValueError):
        return False


class SessionMixin:
    def _session_record(self, session_path):
        """What a session file holds: the current row only.  A reference row is another
        inspection with a session of its own; all that is kept of it here is how the
        two line up, so that loading it again as the reference restores the alignment."""
        session_dir = Path(session_path).resolve().parent
        current = self.pairs[CURRENT]
        record = {
            "version": SESSION_VERSION,
            "app_version": APP_VERSION,
            "image_paths": list(current.paths),
            "image_paths_rel": [relative_to(p, session_dir) for p in current.paths],
            "mode": self.mode_var.get(),
            "opacity": float(self.opacity_var.get()),
            "zoom": self.zoom,
            "pan_x": self.pan_x,
            "pan_y": self.pan_y,
            "alignment": current.alignment_record(),
            "annotations": [normalise_annotation(a) for a in current.annotations],
            "colour_labels": dict(current.colour_labels),
            "label_prefixes": dict(current.label_prefixes),
            "filter_outline": [list(p) for p in current.outline],
            "align_pts_img1": [],
            "align_pts_img2": [],
            "adjustments": [dict(a) for a in current.adjust],
            "noise_reduction": [dict(n) for n in current.nr],
            "raw_develop": [develop_record(d, session_dir) for d in current.develop],
            "camera_settings": [dict(c) for c in current.camera],
            "row_alignments": self._row_alignments_to_save(session_dir),
        }
        if current.legend_colours:
            record["legend_colours"] = list(current.legend_colours)
        return record

    def _row_alignments_to_save(self, session_dir):
        """The current row's known alignments to other sessions, with the one to the
        reference row now shown brought up to date."""
        current, reference = self.pairs
        alignments = {key: dict(value) for key, value in current.row_alignments.items()}
        if reference.session_path and reference.has_image(BACKLIT) and current.has_image(BACKLIT):
            key = alignment_key(reference.session_path, session_dir)
            aligned = any(abs(self.row_shift[name] - rest) > 1e-9
                          for name, rest in (("x", 0.0), ("y", 0.0), ("rot", 0.0), ("scale", 1.0)))
            if aligned or key in alignments:
                alignments[key] = {
                    "off_x": round(self.row_shift["x"], 3),
                    "off_y": round(self.row_shift["y"], 3),
                    "rot": round(self.row_shift["rot"], 4),
                    "scale": round(self.row_shift["scale"], 5),
                    "current_rotation": round(current.glob_rot, 4),
                    "reference_rotation": round(reference.glob_rot, 4),
                }
        return alignments

    def _restore_row_alignment(self):
        """Line the rows up as they were when these two sessions were last saved together.
        Returns whether a saved alignment was found."""
        current, reference = self.pairs
        if not (current.session_path and reference.session_path
                and current.has_image(BACKLIT) and reference.has_image(BACKLIT)):
            return False
        record = current.row_alignments.get(
            alignment_key(reference.session_path, Path(current.session_path).resolve().parent))
        if record is not None:
            self.set_row_matrix(row_matrix_from_record(record, current, reference))
            return True
        # Saved the other way round, with today's reference row as the current one.
        record = reference.row_alignments.get(
            alignment_key(current.session_path, Path(reference.session_path).resolve().parent))
        if record is not None:
            self.set_row_matrix(geo.invert(row_matrix_from_record(record, reference, current)))
            return True
        return False

    # ------------------------------------------------------------------ #
    # Save
    # ------------------------------------------------------------------ #

    def save_session(self):
        if not self.session_path:
            return self.save_session_as()
        return self._write_session(self.session_path)

    def save_session_as(self):
        initial_dir = None
        if self.session_path:
            initial_dir = os.path.dirname(self.session_path)
        elif self.pairs[0].paths[BACKLIT] or self.pairs[0].paths[FRONTLIT]:
            initial_dir = os.path.dirname(self.pairs[0].paths[BACKLIT] or self.pairs[0].paths[FRONTLIT])
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save session",
            defaultextension=".json",
            initialdir=initial_dir or self._dialog_dir(),
            initialfile=os.path.basename(self.session_path) if self.session_path else "session.json",
            filetypes=SESSION_FILETYPES,
        )
        if not path:
            return None
        return self._write_session(path)

    def _write_session(self, path):
        current = self.pairs[CURRENT]
        if current.history_inspection and current.session_path and _same_file(path, current.session_path):
            return self._write_history(path)
        if _is_history_file(path):
            messagebox.showerror(
                "Save session",
                f"{os.path.basename(path)} is a filter history, not a session.  Choose another name; "
                "a history is only saved over from one of its own inspections.", parent=self.root)
            return None
        record = self._session_record(path)
        try:
            write_session(path, record)
        except OSError as exc:
            messagebox.showerror("Save session", f"Could not save the session:\n{path}\n\n{exc}",
                                 parent=self.root)
            return None
        self.pairs[0].row_alignments = record["row_alignments"]
        self.session_path = path
        self.pairs[0].session_path = path
        self.pairs[0].history_inspection = None     # saved as a session of its own now
        self.pairs[0].label = describe_location(path)
        self.dirty = False
        self.config.add_recent(path)
        self._remember_dir(path)
        self._refresh_recent_menu()
        self._update_title()
        self._draw_overlays()
        self.set_status(f"Session saved: {path}")
        return path

    def _write_history(self, path):
        """Save the current row back into the filter history it was opened from."""
        current = self.pairs[CURRENT]
        base = Path(path).resolve().parent
        try:
            history = hist.read_history(path)      # afresh: the command line may have changed it
            index = hist.inspection_index(history, current.history_inspection)
            summary = hist.apply_view(
                history, index, current.annotations,
                outline=current.outline,
                alignment=current.alignment_record(),
                adjustments=[dict(a) for a in current.adjust],
                noise_reduction=[dict(n) for n in current.nr],
                raw_develop=[develop_record(d, base) for d in current.develop])
            hist.write_history(path, history)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save to history", f"Could not save to the history:\n{path}\n\n{exc}",
                                 parent=self.root)
            return None
        # Show the markers as the history now has them: new IDs, rejected ones gone.
        view = hist.session_view(history, index, path)
        current.annotations = [normalise_annotation(a) for a in view["annotations"]]
        current.colour_labels = dict(view["colour_labels"])
        current.label_prefixes = dict(view["label_prefixes"])
        current.legend_colours = list(view["legend_colours"])
        self.session_path = path
        self.dirty = False
        self.config.add_recent(path)
        self._remember_dir(path)
        self._refresh_recent_menu()
        self._update_title()
        self._draw_overlays()
        changes = [f"{len(summary[key])} {key}" for key in ("added", "moved", "rejected", "recategorised")
                   if summary[key]]
        self.set_status(f"Saved to {os.path.basename(path)}, inspection {current.history_inspection}"
                        + (f": {', '.join(changes)}." if changes else "."))
        return path

    def _choose_inspection(self, history, title):
        """Ask which inspection of a history to open.  Returns its index, or None."""
        inspections = history["inspections"]
        if not inspections:
            messagebox.showinfo(title, "That history has no inspections yet.", parent=self.root)
            return None
        if len(inspections) == 1:
            return 0
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=theme.PANEL)
        dialog.transient(self.root)
        pad = self.px(14)
        ttk.Label(dialog, text=f"Filter {history.get('filter') or ''}: which inspection?\n"
                               "It opens with every pinhole known up to it.",
                  justify=tk.LEFT).pack(anchor=tk.W, padx=pad, pady=(pad, self.px(8)))
        listbox = tk.Listbox(dialog, height=min(12, len(inspections)), width=60, exportselection=False,
                             bg=theme.FIELD, fg=theme.TEXT, highlightthickness=0,
                             selectbackground=theme.ACCENT)
        for n, insp in enumerate(inspections):
            known = len(hist.known_at(history, n))
            listbox.insert(tk.END, f"{n + 1}.  {insp.get('name') or insp['id']}   {insp.get('date') or ''}"
                                   f"   ({known} pinholes known)")
        listbox.selection_set(len(inspections) - 1)
        listbox.see(len(inspections) - 1)
        listbox.pack(fill=tk.BOTH, expand=True, padx=pad)
        outcome = {"index": None}

        def accept(_event=None):
            chosen = listbox.curselection()
            if chosen:
                outcome["index"] = chosen[0]
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=pad, pady=pad)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Open", style="Accent.TButton", command=accept).pack(
            side=tk.RIGHT, padx=(0, self.px(8)))
        listbox.bind("<Double-Button-1>", accept)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        self._centre_dialog(dialog)
        dialog.grab_set()
        self.root.wait_window(dialog)
        return outcome["index"]

    def _confirm_discard(self, action):
        """Offer to save unsaved work before ``action``.  False means cancel the action."""
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            f"Save your changes before you {action}?",
            parent=self.root,
        )
        if answer is None:
            return False
        if answer:
            return self.save_session() is not None
        return True

    # ------------------------------------------------------------------ #
    # New / open
    # ------------------------------------------------------------------ #

    def new_session(self):
        if not self._confirm_discard("start a new session"):
            return
        self._reset_state()
        self.set_status("New session.  Load a backlit and a frontlit image to begin.")

    def _ask_session_file(self, title):
        path = filedialog.askopenfilename(
            parent=self.root, title=title, initialdir=self._dialog_dir(), filetypes=SESSION_FILETYPES)
        return path or None

    def _read_session_or_report(self, path, title):
        try:
            return read_session(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror(title, f"Could not read the session file:\n{path}\n\n{exc}",
                                 parent=self.root)
            return None

    def _locate_images(self, title, entries):
        """Resolve image paths, asking only about the ones that cannot be found.

        ``entries`` is a list of ``(label, resolved_path, saved_path)``.  Returns
        the final path list (``None`` for images to leave out), or ``None`` if
        the user cancelled.
        """
        missing = [i for i, (_label, resolved, saved) in enumerate(entries) if saved and not resolved]
        final = [resolved for _label, resolved, _saved in entries]
        if not missing:
            return final

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=theme.PANEL)
        dialog.transient(self.root)
        dialog.resizable(True, False)
        pad = self.px(14)
        ttk.Label(
            dialog,
            text="These images are not where the session expects them.\n"
                 "Choose each file, or leave a box empty to open the session without that image.",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=pad, pady=(pad, self.px(8)))

        path_vars = {}
        for i in missing:
            label, _resolved, saved = entries[i]
            block = ttk.Frame(dialog)
            block.pack(fill=tk.X, padx=pad, pady=self.px(4))
            ttk.Label(block, text=label, style="Panel.TLabel", font=self.fonts["bold"]).pack(anchor=tk.W)
            ttk.Label(block, text=f"Saved as: {saved}", style="Muted.TLabel",
                      wraplength=self.px(640), justify=tk.LEFT).pack(anchor=tk.W)
            line = ttk.Frame(block)
            line.pack(fill=tk.X, pady=(self.px(2), 0))
            var = tk.StringVar(value="")
            path_vars[i] = var
            ttk.Entry(line, textvariable=var, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True)

            def browse(v=var, name=label):
                chosen = filedialog.askopenfilename(
                    parent=dialog, title=f"Locate {name.lower()}",
                    initialdir=self._dialog_dir(), filetypes=IMAGE_FILETYPES)
                if chosen:
                    v.set(chosen)
                    self._remember_dir(chosen)

            ttk.Button(line, text="Browse...", command=browse).pack(side=tk.LEFT, padx=(self.px(6), 0))

        outcome = {"ok": False}

        def accept():
            outcome["ok"] = True
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=pad, pady=pad)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Open", style="Accent.TButton", command=accept).pack(
            side=tk.RIGHT, padx=(0, self.px(8)))
        dialog.bind("<Return>", lambda _e: accept())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        self._centre_dialog(dialog)
        dialog.grab_set()
        self.root.wait_window(dialog)
        if not outcome["ok"]:
            return None
        for i, var in path_vars.items():
            final[i] = var.get().strip() or None
        return final

    def _confirm_two_row_session(self, title, session, path, row):
        """An earlier version saved the reference row inside the session.  Say that only
        the session's own row is loaded now.  False cancels the load."""
        lines = [
            f"{os.path.basename(path)} was saved by an earlier version with two rows in it.",
            "",
            "A session now holds one inspection.  Only what was its current row will be loaded"
            + (", into the reference row." if row == REFERENCE else "."),
            "",
            f"Its reference row was:  {describe_saved_reference(session)}",
            "To compare with that inspection, load its own session into the reference row.",
        ]
        if session.get("compare_session_path_rel"):
            lines.append("The alignment between the two rows is kept and comes back when you do.")
        if row == CURRENT:
            lines += ["", "Saving will rewrite the file with the one row only."]
        return messagebox.askokcancel(title, "\n".join(lines), icon="warning", parent=self.root)

    def open_session(self, path=None, row=CURRENT, inspection=None):
        """Load a session -- one inspection's images, alignment and markers -- into the
        current row, or into the reference row to compare against.  The other row stays.

        ``path`` may also be a filter history; ``inspection`` then names the inspection
        to open (by ID, stage or number), else the user is asked."""
        title = "Load session into reference row" if row == REFERENCE else "Open session"
        if row == CURRENT and not self._confirm_discard("open another session"):
            return
        path = path or self._ask_session_file(title)
        if not path:
            return
        session = self._read_session_or_report(path, title)
        if session is None:
            return
        self._remember_dir(path)
        history_inspection = history_label = None
        if hist.is_history(session):
            try:
                history = hist.read_history(path)
                index = (hist.inspection_index(history, inspection) if inspection is not None
                         else self._choose_inspection(history, title))
            except (OSError, ValueError) as exc:
                messagebox.showerror(title, f"Could not open the history:\n{path}\n\n{exc}", parent=self.root)
                return
            if index is None:
                return
            insp = history["inspections"][index]
            if hist.to_filter(insp) is None:
                messagebox.showinfo(title, f"Inspection {insp['id']} has not been aligned yet, so its pinholes "
                                           "cannot be placed.  Align it from the command line first:\n\n"
                                           f"    python mssl_focus.py align {os.path.basename(path)} {insp['id']}",
                                    parent=self.root)
                return
            session = hist.session_view(history, index, path)
            history_inspection = insp["id"]
            history_label = f"{history.get('filter') or Path(path).stem} / {insp.get('name') or insp['id']}"
        if session_has_reference(session) and not self._confirm_two_row_session(title, session, path, row):
            return

        # Always the session's own row -- never the reference row an earlier version saved with it.
        resolved, saved = session_image_paths(session, path)
        entries = [(self._image_label(i, row), resolved[i], saved[i]) for i in (BACKLIT, FRONTLIT)]
        final = self._locate_images(title, entries)
        if final is None:
            return
        if row == REFERENCE and not any(final):
            messagebox.showinfo(title, "That session does not name any images to load.", parent=self.root)
            return

        pair = ImagePair()
        fill_pair_from_session(pair, session)
        missing_frames = resolve_frame_paths(pair, session.get("raw_develop"), Path(path).resolve().parent)
        pair.row_alignments = row_alignments_from_session(session)
        pair.label = history_label or describe_location(path)
        pair.session_path = path
        pair.history_inspection = history_inspection
        jobs = [((row, idx), image_path, pair.nr[idx], pair.develop[idx])
                for idx, image_path in enumerate(final) if image_path]

        def finished(loaded, errors):
            if errors:
                self._report_load_errors(title, errors)
                self.set_status("Session not opened: an image could not be loaded.")
                return
            for (_row, idx), (image_path, base, pyramid) in loaded.items():
                pair.set_image(idx, image_path, base, pyramid)
                if idx == BACKLIT:
                    shift_legacy_raw_markers(pair, session, base)
            other = self.pairs[REFERENCE if row == CURRENT else CURRENT]
            if row == CURRENT:
                reference_shown = self.show_reference_var.get() and other.has_any_image()
                self._reset_state()
                self.pairs = [pair, other]
                self.show_reference_var.set(reference_shown)
                self.mode_var.set("overlay" if session.get("mode") == "overlay" else "sidebyside")
                self.opacity_var.set(_float(session.get("opacity"), 0.5))
                self.session_path = path
                self.config.add_recent(path)
                self._refresh_recent_menu()
            else:
                was_dirty = self.dirty
                self.pairs[REFERENCE] = pair
                self.show_reference_var.set(True)
                self._clear_tool_points(redraw=False)
                if self.tool_var.get() in ("review", "detect"):
                    self.set_tool("pan")
                # Undo history refers to the row that was there before.
                self._undo_stack.clear()
                self._redo_stack.clear()
                self._last_checkpoint = (None, 0.0)
                self._update_undo_buttons()
                self.dirty = was_dirty
            self.reset_row_shift()
            restored = self._restore_row_alignment()
            self._update_title()
            self._layout_panes()
            self._sync_controls()
            saved_view = row == CURRENT and not other.has_any_image() and all(
                key in session for key in ("zoom", "pan_x", "pan_y"))
            if saved_view:
                self.zoom = max(0.02, min(100.0, _float(session["zoom"], 1.0)))
                self.pan_x = _float(session["pan_x"], 0.0)
                self.pan_y = _float(session["pan_y"], 0.0)
                self._view_is_fit = False
                self._update_zoom_readout()
                self._schedule_render()
            else:
                self.fit_view()
            where = "reference row" if row == REFERENCE else "current row"
            message = f"Session loaded into the {where}: {os.path.basename(path)} ({pair.label})."
            if self.pairs[CURRENT].has_any_image() and self.pairs[REFERENCE].has_any_image():
                message += ("  The alignment between the rows was restored from when they were last saved together."
                            if restored else "  Use Align rows to register the reference row to the current row.")
            if missing_frames:
                message += f"  ({missing_frames} extra or dark frame(s) could not be found and were left out.)"
            self.set_status(message)

        self._load_images(jobs, finished, title="Opening session" if row == CURRENT else "Loading reference session")

    def open_reference_session(self, path=None):
        """Load another inspection's session as the reference row."""
        self.open_session(path, row=REFERENCE)

    # ------------------------------------------------------------------ #
    # Image settings presets
    # ------------------------------------------------------------------ #

    def save_image_settings(self):
        """Save the selected image's tone, noise and RAW settings to a file of their own."""
        row, idx = self._adjust_target()
        pair = self.pairs[row]
        kind = "backlit" if idx == BACKLIT else "frontlit"
        path = filedialog.asksaveasfilename(
            parent=self.root, title=f"Save {kind} image settings", defaultextension=".json",
            initialdir=self._dialog_dir(), initialfile=f"{kind}_settings.json", filetypes=SETTINGS_FILETYPES)
        if not path:
            return None
        record = {
            "type": SETTINGS_FILE_TYPE,
            "version": 1,
            "image": kind,
            "adjust": dict(pair.adjust[idx]),
            "noise_reduction": dict(pair.nr[idx]),
            "raw_develop": {key: pair.develop[idx][key] for key in ("exposure", "noise")},
            "camera": dict(pair.camera[idx]),
            "saved_from": os.path.basename(pair.paths[idx]) if pair.paths[idx] else None,
        }
        try:
            write_session(path, record)
        except OSError as exc:
            messagebox.showerror("Save image settings", f"Could not save the settings:\n{path}\n\n{exc}",
                                 parent=self.root)
            return None
        self._remember_dir(path)
        self.set_status(f"Saved {kind} image settings: {path}")
        return path

    def _confirm_settings_camera(self, title, path, saved_for, saved_camera, row, idx):
        """Tell the user which camera settings the saved look was made for, and whether the
        image it is about to be applied to was taken differently.  False cancels the load."""
        pair = self.pairs[row]
        kind = "backlit" if idx == BACKLIT else "frontlit"
        saved_camera = saved_camera if isinstance(saved_camera, dict) else {}
        target_camera = pair.camera[idx]
        lines = [
            f"Settings from:  {os.path.basename(path)}",
            "",
            f"Saved from a {saved_for or 'previous'} image taken at:",
            f"    {describe_camera(saved_camera) or 'camera settings not recorded'}",
            f"Applying to the {self._image_label(idx, row).lower()}, taken at:",
            f"    {describe_camera(target_camera) or 'camera settings not known'}",
            "",
        ]
        differences = camera_differences(saved_camera, target_camera)
        warn = bool(differences) or saved_for not in (None, kind)
        if saved_for not in (None, kind):
            lines.append(f"Note: these settings were saved from a {saved_for} image, and this is a {kind} image.")
        if differences:
            lines.append("The camera settings are different:")
            lines.extend(f"    {difference}" for difference in differences)
            stops = exposure_stops(saved_camera, target_camera)
            if stops is not None and abs(stops) >= 0.05:
                lines.append(f"This image received about {abs(stops):.1f} stops "
                             f"{'more' if stops > 0 else 'less'} light, so the same brightness and "
                             "contrast may not give the same look.")
            elif stops is not None:
                lines.append("Overall the exposure is almost the same, so the look should carry over.")
        elif saved_camera and target_camera:
            lines.append("The aperture, exposure time and ISO are the same.")
        lines.extend(["", "Apply the settings anyway?" if warn else "Apply the settings?"])
        return messagebox.askokcancel(title, "\n".join(lines), icon="warning" if warn else "question",
                                      parent=self.root)

    def load_image_settings(self, path=None):
        """Apply saved settings -- from a settings file or a session -- to the selected image."""
        title = "Load image settings"
        row, idx = self._adjust_target()
        pair = self.pairs[row]
        kind = "backlit" if idx == BACKLIT else "frontlit"
        if not path:
            path = filedialog.askopenfilename(
                parent=self.root, title=f"Load settings for the {self._image_label(idx, row).lower()}",
                initialdir=self._dialog_dir(), filetypes=SETTINGS_FILETYPES)
        if not path:
            return
        data = self._read_session_or_report(path, title)
        if data is None:
            return
        self._remember_dir(path)
        if data.get("type") == SETTINGS_FILE_TYPE:
            adjust, noise, develop = data.get("adjust"), data.get("noise_reduction"), data.get("raw_develop")
            saved_for = data.get("image")
            saved_camera = data.get("camera")
        elif "adjustments" in data:
            # A session file: take the settings of its image of the same kind.
            def pick(key):
                values = data.get(key)
                return values[idx] if isinstance(values, list) and idx < len(values) else None
            adjust, noise, develop = pick("adjustments"), pick("noise_reduction"), pick("raw_develop")
            saved_for = kind
            saved_camera = pick("camera_settings")
        else:
            messagebox.showinfo(title, "That file does not contain image settings.", parent=self.root)
            return

        if not self._confirm_settings_camera(title, path, saved_for, saved_camera, row, idx):
            return

        def replaced(current, new):
            records = [dict(r) for r in current]
            if isinstance(new, dict):
                records[idx] = new
            return records

        old_noise, old_develop = dict(pair.nr[idx]), dict(pair.develop[idx])
        if isinstance(develop, dict):
            # A preset carries the look, never which files an image is built from.
            develop = dict(pair.develop[idx], exposure=develop.get("exposure", 0.0),
                           noise=develop.get("noise", "standard"))
        self._checkpoint("Load image settings")
        pair.apply_adjust_records(replaced(pair.adjust, adjust))
        pair.apply_nr_records(replaced(pair.nr, noise))
        pair.apply_develop_records(replaced(pair.develop, develop))
        self._sync_controls()
        self._schedule_render()
        note = "" if saved_for in (None, kind) else f"  Note: they were saved from a {saved_for} image."
        self.set_status(f"Loaded settings from {os.path.basename(path)} onto the "
                        f"{self._image_label(idx, row).lower()}.{note}")
        if not pair.has_image(idx):
            return
        if is_raw(pair.paths[idx]) and pair.develop[idx] != old_develop:
            self.redevelop_image(idx, row)          # also applies the extra noise reduction
        elif pair.nr[idx] != old_noise:
            self.apply_noise_reduction(idx, row)
