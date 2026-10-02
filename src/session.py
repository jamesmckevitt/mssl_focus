"""Session files: reading, writing, locating images, and the session commands."""

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import theme
from .camera import camera_differences, describe_camera, exposure_stops
from .imaging import IMAGE_FILETYPES, is_raw
from .metadata import APP_VERSION
from .pair import BACKLIT, FRONTLIT, ImagePair, normalise_annotation

SESSION_FILETYPES = [("Session file", "*.json"), ("All files", "*.*")]
SESSION_VERSION = 2
SETTINGS_FILE_TYPE = "mssl_focus_image_settings"
SETTINGS_FILETYPES = [("Image settings or session", "*.json"), ("All files", "*.*")]


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def read_session(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("this is not a MSSL FOCUS session file")
    return data


def write_session(path, data):
    """Write atomically so a crash or sync conflict cannot leave half a file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def describe_location(path):
    """Short human label from a file's folders, e.g. ``5_thermal_test / em2``."""
    if not path:
        return ""
    parent = Path(path).resolve().parent
    if parent.parent.name:
        return f"{parent.parent.name} / {parent.name}"
    return parent.name


def relative_to(path, base_dir):
    if not path:
        return None
    try:
        return os.path.relpath(path, base_dir).replace("\\", "/")
    except ValueError:  # different drive on Windows
        return None


def resolve_image_path(saved, relative, session_dir):
    """Find an image named in a session file, even after folders were moved or renamed."""
    session_dir = Path(session_dir)
    candidates = []
    if relative:
        candidates.append(session_dir / relative)
    if saved:
        candidates.append(Path(saved))
        parts = Path(str(saved).replace("\\", "/")).parts
        # Same file name beside the session, then progressively more of the old folder tail.
        for depth in range(1, min(4, len(parts)) + 1):
            base = session_dir
            for _ in range(depth - 1):
                base = base.parent
            candidates.append(base.joinpath(*parts[-depth:]))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _pair_of(values):
    values = list(values or [])[:2]
    while len(values) < 2:
        values.append(None)
    return values


def session_image_paths(session, session_path, reference=False):
    """Return ``(resolved, saved)`` image path pairs for a session's main or reference row."""
    key = "compare_image_paths" if reference else "image_paths"
    saved = _pair_of(session.get(key))
    relative = _pair_of(session.get(key + "_rel"))
    session_dir = Path(session_path).resolve().parent
    resolved = [resolve_image_path(s, r, session_dir) if (s or r) else None
                for s, r in zip(saved, relative)]
    saved = [s or r for s, r in zip(saved, relative)]
    return resolved, saved


def session_has_reference(session):
    return bool(session.get("compare_row_enabled")) or any(_pair_of(session.get("compare_image_paths")))


def fill_pair_from_session(pair, session, reference=False):
    """Copy a session's alignment, tone, noise and annotation records into ``pair``."""
    prefix = "compare_" if reference else ""
    pair.apply_alignment_record(session.get(prefix + "alignment"))
    pair.apply_adjust_records(session.get(prefix + "adjustments"))
    pair.apply_nr_records(session.get(prefix + "noise_reduction"))
    pair.apply_develop_records(session.get(prefix + "raw_develop"))
    pair.annotations = [normalise_annotation(a) for a in session.get(prefix + "annotations", [])]
    pair.colour_labels = dict(session.get(prefix + "colour_labels", {}))
    pair.label_prefixes = dict(session.get(prefix + "label_prefixes", {}))


def shift_legacy_raw_markers(pair, session, base_image):
    """Sessions from v1.x placed markers on the uncropped RAW frame; RAW files are now
    cropped to the camera's image area, so move those markers by the crop margin."""
    if int(_float(session.get("version"), 1)) >= SESSION_VERSION or not is_raw(pair.paths[BACKLIT]):
        return
    left, top = getattr(base_image, "info", {}).get("raw_crop_margins", (0, 0))
    for ann in pair.annotations:
        ann["img1_x"] -= left
        ann["img1_y"] -= top


def _float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Session commands
# --------------------------------------------------------------------------- #

class SessionMixin:
    def _session_record(self, session_path):
        session_dir = Path(session_path).resolve().parent
        current, reference = self.pairs
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
            "align_pts_img1": [],
            "align_pts_img2": [],
            "adjustments": [dict(a) for a in current.adjust],
            "noise_reduction": [dict(n) for n in current.nr],
            "raw_develop": [dict(d) for d in current.develop],
            "camera_settings": [dict(c) for c in current.camera],
            "compare_row_enabled": bool(self.show_reference_var.get() and reference.has_any_image()),
            "compare_image_paths": list(reference.paths),
            "compare_image_paths_rel": [relative_to(p, session_dir) for p in reference.paths],
            "compare_alignment": reference.alignment_record(),
            "compare_row_transform": {
                "off_x": round(self.row_shift["x"], 3),
                "off_y": round(self.row_shift["y"], 3),
                "rot": round(self.row_shift["rot"], 4),
                "scale": round(self.row_shift["scale"], 5),
            },
            "compare_adjustments": [dict(a) for a in reference.adjust],
            "compare_noise_reduction": [dict(n) for n in reference.nr],
            "compare_raw_develop": [dict(d) for d in reference.develop],
            "compare_camera_settings": [dict(c) for c in reference.camera],
            "compare_annotations": [normalise_annotation(a) for a in reference.annotations],
            "compare_colour_labels": dict(reference.colour_labels),
            "compare_label": reference.label,
            "compare_session_path_rel": relative_to(reference.session_path, session_dir),
        }
        return record

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
        try:
            write_session(path, self._session_record(path))
        except OSError as exc:
            messagebox.showerror("Save session", f"Could not save the session:\n{path}\n\n{exc}",
                                 parent=self.root)
            return None
        self.session_path = path
        self.pairs[0].session_path = path
        self.pairs[0].label = describe_location(path)
        self.dirty = False
        self.config.add_recent(path)
        self._remember_dir(path)
        self._refresh_recent_menu()
        self._update_title()
        self._draw_overlays()
        self.set_status(f"Session saved: {path}")
        return path

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

    def open_session(self, path=None):
        title = "Open session"
        if not self._confirm_discard("open another session"):
            return
        path = path or self._ask_session_file(title)
        if not path:
            return
        session = self._read_session_or_report(path, title)
        if session is None:
            return
        self._remember_dir(path)

        with_reference = session_has_reference(session)
        resolved, saved = session_image_paths(session, path)
        entries = [(self._image_label(i, 0), resolved[i], saved[i]) for i in (BACKLIT, FRONTLIT)]
        if with_reference:
            ref_resolved, ref_saved = session_image_paths(session, path, reference=True)
            entries += [(self._image_label(i, 1), ref_resolved[i], ref_saved[i]) for i in (BACKLIT, FRONTLIT)]
        final = self._locate_images(title, entries)
        if final is None:
            return

        current = ImagePair()
        fill_pair_from_session(current, session)
        current.label = describe_location(path)
        current.session_path = path
        reference = ImagePair()
        if with_reference:
            fill_pair_from_session(reference, session, reference=True)
            reference.label = session.get("compare_label") or ""
            rel = session.get("compare_session_path_rel")
            if rel:
                reference.session_path = str(Path(path).resolve().parent / rel)
        new_pairs = [current, reference]

        jobs = []
        for n, image_path in enumerate(final):
            if image_path:
                row, idx = divmod(n, 2)
                jobs.append(((row, idx), image_path, new_pairs[row].nr[idx], new_pairs[row].develop[idx]))

        def finished(loaded, errors):
            if errors:
                self._report_load_errors(title, errors)
                self.set_status("Session not opened: an image could not be loaded.")
                return
            for (row, idx), (image_path, base, pyramid) in loaded.items():
                new_pairs[row].set_image(idx, image_path, base, pyramid)
                if idx == BACKLIT and row == 0:
                    shift_legacy_raw_markers(new_pairs[row], session, base)
            if with_reference and not reference.label:
                reference.label = describe_location(reference.paths[BACKLIT] or reference.paths[FRONTLIT])
            self._reset_state()
            self.pairs = new_pairs
            transform = session.get("compare_row_transform") or {}
            self.row_shift = {
                "x": _float(transform.get("off_x"), 0.0),
                "y": _float(transform.get("off_y"), 0.0),
                "rot": _float(transform.get("rot"), 0.0),
                "scale": max(0.01, _float(transform.get("scale"), 1.0)),
            }
            self.show_reference_var.set(with_reference and reference.has_any_image())
            self.mode_var.set("overlay" if session.get("mode") == "overlay" else "sidebyside")
            self.opacity_var.set(_float(session.get("opacity"), 0.5))
            self.session_path = path
            self.dirty = False
            self.config.add_recent(path)
            self._refresh_recent_menu()
            self._update_title()
            self._layout_panes()
            self._sync_controls()
            if "zoom" in session and "pan_x" in session and "pan_y" in session:
                self.zoom = max(0.02, min(100.0, _float(session["zoom"], 1.0)))
                self.pan_x = _float(session["pan_x"], 0.0)
                self.pan_y = _float(session["pan_y"], 0.0)
                self._view_is_fit = False
                self._update_zoom_readout()
                self._schedule_render()
            else:
                self.fit_view()
            self.set_status(f"Session opened: {path}")

        self._load_images(jobs, finished, title="Opening session")

    def open_reference_session(self, path=None):
        """Load another session's image pair, alignment and annotations as the reference row."""
        title = "Load reference session"
        path = path or self._ask_session_file(title)
        if not path:
            return
        session = self._read_session_or_report(path, title)
        if session is None:
            return
        self._remember_dir(path)

        # Always the session's own (main) pair -- never whatever reference row it had.
        resolved, saved = session_image_paths(session, path)
        entries = [(self._image_label(i, 1), resolved[i], saved[i]) for i in (BACKLIT, FRONTLIT)]
        final = self._locate_images(title, entries)
        if final is None:
            return
        if not any(final):
            messagebox.showinfo(title, "That session does not name any images to load.", parent=self.root)
            return

        reference = ImagePair()
        fill_pair_from_session(reference, session)
        reference.label = describe_location(path)
        reference.session_path = path
        jobs = [((1, idx), image_path, reference.nr[idx], reference.develop[idx])
                for idx, image_path in enumerate(final) if image_path]

        def finished(loaded, errors):
            if errors:
                self._report_load_errors(title, errors)
                return
            for (_row, idx), (image_path, base, pyramid) in loaded.items():
                reference.set_image(idx, image_path, base, pyramid)
                if idx == BACKLIT:
                    shift_legacy_raw_markers(reference, session, base)
            was_empty = not self.pairs[0].has_any_image()
            self.pairs[1] = reference
            self.reset_row_shift()
            self.show_reference_var.set(True)
            self._clear_tool_points()
            self._mark_dirty()
            self._layout_panes()
            self._sync_controls()
            if was_empty or self._view_is_fit:
                self.fit_view()
            self.set_status(
                f"Reference row loaded from {os.path.basename(path)} ({reference.label}).  "
                "Use Align rows to register it to the current row.")

        self._load_images(jobs, finished, title="Loading reference session")

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
            "raw_develop": dict(pair.develop[idx]),
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
