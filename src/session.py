import json
import math
import tkinter as tk
from tkinter import filedialog, messagebox

import numpy as np
from PIL import Image

from .viewer import _open_image


class SessionMixin:
    def _normalize_annotation_record(self, ann):
        normalized = dict(ann)
        normalized.pop("img2_x", None)
        normalized.pop("img2_y", None)
        normalized["img1_x"] = float(ann.get("img1_x", ann.get("img2_x", 0.0)))
        normalized["img1_y"] = float(ann.get("img1_y", ann.get("img2_y", 0.0)))
        normalized["radius"] = float(ann.get("radius", 20.0))
        normalized["colour"] = ann.get("colour", "#ff0000")
        normalized["label"] = ann.get("label", "")
        return normalized

    def _reset_session_state(self):
        if getattr(self, "_annotation_import", None) is not None:
            self._cancel_annotation_import()
        self._close_noise_reduction_progress()

        self.images = [None, None]
        self.image_paths = [None, None]
        self.preview_images = [None, None]
        self.preview_scales = [1.0, 1.0]
        self.photos = [None, None]
        self._base_images = [None, None]
        self._rotated_cache = [None, None]
        self._last_rot = [None, None]
        self._rotated_preview_cache = [None, None]
        self._last_rot_preview = [None, None]

        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.cursor_pos = (0, 0)
        self.last_pan = (0, 0)
        self._interacting = False

        self.annotations = []
        self.annot_colour = "#ff0000"
        self.colour_labels = {}
        if getattr(self, "annot_colour_btn", None) is not None:
            try:
                self.annot_colour_btn.config(bg=self.annot_colour)
            except Exception:
                pass

        self._level_start = None
        self._crop_corner1 = None
        self._drag_annotation_index = None
        self._align_guide_cursor = None
        self._clear_align_pts()

        self.mode_var.set("sidebyside")
        self.opacity_var.set(0.5)
        self.off_x_var.set("0")
        self.off_y_var.set("0")
        self.rot_var.set("0.0")
        self.img2_scale_var.set("1.000")
        self.glob_rot_var.set("0.0")

        self.level_mode_var.set(False)
        self.annot_mode_var.set(False)
        self.annot_radius_var.set(20)
        self.annot_label_var.set(False)
        self.move_annot_mode_var.set(False)
        self.align_mode_var.set(False)
        self.align_scale_mode_var.set(False)
        self.crop_mode_var.set(False)
        self.crop_pad_var.set(20)
        self.annot_label_size_var.set(16)
        self.canvas_legend_size_var.set(13)
        self.annot_width_var.set(2.0)

        for img_idx in range(2):
            self.nr_amount_vars[img_idx].set(0)
            self.nr_aggressive_vars[img_idx].set(False)
            self.nr_color_vars[img_idx].set(50)
            self.nr_edge_vars[img_idx].set(100)
            self.adj_vars[img_idx]["brightness"].set(1.0)
            self.adj_vars[img_idx]["contrast"].set(1.0)
            self.adj_vars[img_idx]["blacks"].set(0.0)
            self.adj_vars[img_idx]["whites"].set(255.0)

        self.canvas1.delete("level_line")
        self.canvas2.delete("level_line")
        self.canvas1.delete("crop_preview")
        self.canvas2.delete("crop_preview")
        self.canvas1.delete("annotations")
        self.canvas2.delete("annotations")
        self.canvas1.delete("legend")
        self.canvas2.delete("legend")

        self._on_mode_change()
        self._on_crop_mode_change()
        self._on_annot_mode_change()
        self._on_move_annot_mode_change()
        self._on_level_mode_change()
        self._schedule_render()
        self.status_var.set("New session started. Load two images to begin.")

    def _apply_adjustments_from_session(self, session):
        for i, d in enumerate(session.get("adjustments", [{}, {}])[:2]):
            for key in ("brightness", "contrast", "blacks", "whites"):
                if key in d:
                    self.adj_vars[i][key].set(float(d[key]))

    def _load_noise_reduction_settings_from_session(self, target, session):
        defaults = [
            {"amount": 0, "aggressive": False, "color": 50, "edge": 100},
            {"amount": 0, "aggressive": False, "color": 50, "edge": 100},
        ]
        saved = session.get("noise_reduction", defaults)
        for idx in range(2):
            cfg = saved[idx] if idx < len(saved) else defaults[idx]
            target.nr_amount_vars[idx].set(int(cfg.get("amount", defaults[idx]["amount"])))
            target.nr_aggressive_vars[idx].set(bool(cfg.get("aggressive", defaults[idx]["aggressive"])))
            target.nr_color_vars[idx].set(int(cfg.get("color", defaults[idx]["color"])))
            target.nr_edge_vars[idx].set(int(cfg.get("edge", defaults[idx]["edge"])))

    def _apply_saved_noise_reduction_from_session(self, target, session, on_complete=None):
        self._load_noise_reduction_settings_from_session(target, session)
        indices = []
        for idx in range(2):
            if target.images[idx] is not None and target.nr_amount_vars[idx].get() > 0:
                indices.append(idx)

        if not indices:
            if on_complete is not None:
                on_complete(False)
            return

        state = {"all_succeeded": True}

        def apply_next(pos=0):
            if pos >= len(indices):
                if on_complete is not None:
                    on_complete(state["all_succeeded"])
                return

            idx = indices[pos]

            def step_done(success):
                if not success:
                    state["all_succeeded"] = False
                apply_next(pos + 1)

            target._apply_noise_reduction(idx, on_complete=step_done)

        target.root.after(0, apply_next)

    def _new_session(self):
        answer = messagebox.askyesnocancel(
            "New session",
            "Save before starting a new session?\n\n"
            "Yes: choose where to save the current session first, then start a new blank session.\n"
            "No: start a new blank session now without saving.\n"
            "Cancel: keep working in the current session.",
            parent=self.root,
        )
        if answer is None:
            return
        if answer:
            saved_path = self._save_session()
            if not saved_path:
                return
        self._reset_session_state()

    def _import_image_settings_from_session(self):
        path = filedialog.askopenfilename(
            title="Import image settings from session",
            filetypes=[("Session file", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
        except Exception as exc:
            messagebox.showerror(
                "Import image settings",
                f"Could not read session file:\n{exc}",
                parent=self.root,
            )
            return

        if "adjustments" not in session:
            messagebox.showinfo(
                "Import image settings",
                "That session does not contain saved image adjustment settings.",
                parent=self.root,
            )
            return

        self._apply_adjustments_from_session(session)
        self._schedule_render()
        self.status_var.set(f"Imported image settings from {path}.")

    def _fit_similarity_transform(self, source_points, target_points):
        src = np.array(source_points, dtype=float)
        dst = np.array(target_points, dtype=float)
        if src.shape[0] < 2 or dst.shape[0] < 2:
            raise ValueError("at least 2 point pairs are required")

        src_mean = src.mean(axis=0)
        dst_mean = dst.mean(axis=0)
        src_centered = src - src_mean
        dst_centered = dst - dst_mean

        src_energy = float((src_centered ** 2).sum())
        if src_energy <= 0.0:
            raise ValueError("source points are degenerate")

        covariance = src_centered.T @ dst_centered
        u, singular_vals, vt = np.linalg.svd(covariance)
        rot = vt.T @ u.T
        if np.linalg.det(rot) < 0:
            vt[-1, :] *= -1
            rot = vt.T @ u.T

        scale = float(singular_vals.sum() / src_energy)

        def transform_point(point):
            point_arr = np.array(point, dtype=float)
            return scale * ((point_arr - src_mean) @ rot) + dst_mean

        return transform_point, scale

    def _save_session(self):
        session = {
            "version": 1,
            "image_paths": self.image_paths,
            "mode": self.mode_var.get(),
            "opacity": self.opacity_var.get(),
            "zoom": self.zoom,
            "pan_x": self.pan_x,
            "pan_y": self.pan_y,
            "alignment": {
                "off_x": self.off_x_var.get(),
                "off_y": self.off_y_var.get(),
                "rot": self.rot_var.get(),
                "img2_scale": self.img2_scale_var.get(),
                "glob_rot": self.glob_rot_var.get(),
            },
            "annotations": [self._normalize_annotation_record(ann) for ann in self.annotations],
            "colour_labels": self.colour_labels,
            "align_pts_img1": self._align_pts_img1,
            "align_pts_img2": self._align_pts_img2,
            "adjustments": [
                {k: v.get() for k, v in d.items()} for d in self.adj_vars
            ],
            "noise_reduction": [
                {
                    "amount": self.nr_amount_vars[i].get(),
                    "aggressive": bool(self.nr_aggressive_vars[i].get()),
                    "color": self.nr_color_vars[i].get(),
                    "edge": self.nr_edge_vars[i].get(),
                }
                for i in range(2)
            ],
        }
        path = filedialog.asksaveasfilename(
            title="Save session",
            defaultextension=".json",
            filetypes=[("Session file", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return None
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2)
        self.status_var.set(f"Session saved -> {path}")
        return path

    def _load_session(self):
        path = filedialog.askopenfilename(
            title="Load session",
            filetypes=[("Session file", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
        except Exception as exc:
            messagebox.showerror("Load error", f"Could not read session file:\n{exc}",
                                 parent=self.root)
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Load Session - Verify image paths")
        dlg.configure(bg="#2b2b2b")
        dlg.resizable(True, False)
        dlg.transient(self.root)
        dlg.grab_set()

        saved_paths = list(session.get("image_paths", [None, None]))
        while len(saved_paths) < 2:
            saved_paths.append(None)
        path_vars = [tk.StringVar(value=p or "") for p in saved_paths]

        tk.Label(dlg, text="Image files to load  (edit or Browse to choose different files):",
                 bg="#2b2b2b", fg="#ccc",
                 font=("TkDefaultFont", 9, "bold")).pack(padx=12, pady=(10, 4), anchor=tk.W)

        for i, (pv, label) in enumerate(zip(path_vars, ["Image 1:", "Image 2:"])):
            row = tk.Frame(dlg, bg="#2b2b2b")
            row.pack(fill=tk.X, padx=10, pady=3)
            tk.Label(row, text=label, bg="#2b2b2b", fg="#aaa",
                     width=8, anchor=tk.W).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=pv, bg="#444", fg="white",
                     insertbackground="white", relief=tk.FLAT,
                     width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

            def browse(var=pv):
                selected = filedialog.askopenfilename(
                    filetypes=[
                        ("Image files",
                         "*.tif *.tiff *.TIF *.TIFF *.png *.PNG "
                         "*.jpg *.JPG *.jpeg *.JPEG *.bmp *.BMP "
                         "*.arw *.ARW *.nef *.NEF *.cr2 *.CR2 *.cr3 *.CR3 "
                         "*.dng *.DNG *.orf *.ORF *.rw2 *.RW2 *.raf *.RAF"),
                        ("All files", "*.*"),
                    ]
                )
                if selected:
                    var.set(selected)

            tk.Button(row, text="Browse...", command=browse,
                      bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                      cursor="hand2").pack(side=tk.LEFT, padx=4)

        btn_row = tk.Frame(dlg, bg="#2b2b2b")
        btn_row.pack(pady=10)
        confirmed = [False]

        def on_ok():
            confirmed[0] = True
            dlg.destroy()

        tk.Button(btn_row, text="Load", command=on_ok,
                  bg="#336633", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg="#555", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)

        self.root.wait_window(dlg)
        if not confirmed[0]:
            return

        final_paths = [pv.get().strip() or None for pv in path_vars]
        for i, loaded_path in enumerate(final_paths):
            if loaded_path:
                try:
                    img = _open_image(loaded_path)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    self.images[i] = img
                    self._base_images[i] = img
                    self.image_paths[i] = loaded_path
                    self.preview_images[i], self.preview_scales[i] = self._make_preview(img)
                    self._rotated_cache[i] = None
                    self._last_rot[i] = None
                    self._rotated_preview_cache[i] = None
                    self._last_rot_preview[i] = None
                except Exception as exc:
                    messagebox.showerror("Load error",
                                         f"Could not load image {i + 1}:\n{loaded_path}\n\n{exc}",
                                         parent=self.root)

        alignment = session.get("alignment", {})
        self.off_x_var.set(str(alignment.get("off_x", "0")))
        self.off_y_var.set(str(alignment.get("off_y", "0")))
        self.rot_var.set(str(alignment.get("rot", "0.0")))
        self.img2_scale_var.set(str(alignment.get("img2_scale", "1.000")))
        self.glob_rot_var.set(str(alignment.get("glob_rot", "0.0")))
        if "mode" in session:
            self.mode_var.set(session["mode"])
            self._on_mode_change()
        if "opacity" in session:
            self.opacity_var.set(float(session["opacity"]))
        if "zoom" in session:
            self.zoom = float(session["zoom"])
        if "pan_x" in session:
            self.pan_x = float(session["pan_x"])
        if "pan_y" in session:
            self.pan_y = float(session["pan_y"])
        if "annotations" in session:
            self.annotations = [self._normalize_annotation_record(ann) for ann in session["annotations"]]
        if "colour_labels" in session:
            self.colour_labels = session["colour_labels"]
        if "align_pts_img1" in session:
            self._align_pts_img1 = [tuple(p) for p in session["align_pts_img1"]]
        if "align_pts_img2" in session:
            self._align_pts_img2 = [tuple(p) for p in session["align_pts_img2"]]
        self._apply_adjustments_from_session(session)

        def finish_load(applied_nr):
            self._schedule_render()
            if applied_nr:
                self.status_var.set(f"Session loaded from {path} and saved NR was applied.")
            else:
                self.status_var.set(f"Session loaded from {path}")

        self._apply_saved_noise_reduction_from_session(self, session, on_complete=finish_load)

    def _apply_session_to_viewer(self, viewer, session, image_paths, loaded_images=None,
                                 force_sidebyside=False):
        while len(image_paths) < 2:
            image_paths.append(None)
        if loaded_images is None:
            loaded_images = [None, None]
        while len(loaded_images) < 2:
            loaded_images.append(None)

        viewer.images = [None, None]
        viewer._base_images = [None, None]
        viewer.image_paths = [None, None]
        viewer.preview_images = [None, None]
        viewer.preview_scales = [1.0, 1.0]
        viewer.photos = [None, None]
        viewer._rotated_cache = [None, None]
        viewer._last_rot = [None, None]
        viewer._rotated_preview_cache = [None, None]
        viewer._last_rot_preview = [None, None]

        for i, loaded_path in enumerate(image_paths[:2]):
            img = loaded_images[i]
            if img is None and loaded_path:
                img = _open_image(loaded_path)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
            if img is None:
                continue
            viewer.images[i] = img
            viewer._base_images[i] = img
            viewer.image_paths[i] = loaded_path
            viewer.preview_images[i], viewer.preview_scales[i] = viewer._make_preview(img)

        alignment = session.get("alignment", {})
        viewer.off_x_var.set(str(alignment.get("off_x", "0")))
        viewer.off_y_var.set(str(alignment.get("off_y", "0")))
        viewer.rot_var.set(str(alignment.get("rot", "0.0")))
        viewer.img2_scale_var.set(str(alignment.get("img2_scale", "1.000")))
        viewer.glob_rot_var.set(str(alignment.get("glob_rot", "0.0")))
        viewer.mode_var.set("sidebyside" if force_sidebyside else session.get("mode", "sidebyside"))
        viewer._on_mode_change()
        if "opacity" in session:
            viewer.opacity_var.set(float(session["opacity"]))
        viewer.zoom = float(session.get("zoom", 1.0))
        viewer.pan_x = float(session.get("pan_x", 0.0))
        viewer.pan_y = float(session.get("pan_y", 0.0))
        viewer.annotations = [self._normalize_annotation_record(ann) for ann in session.get("annotations", [])]
        viewer.colour_labels = dict(session.get("colour_labels", {}))
        viewer._align_pts_img1 = [tuple(p) for p in session.get("align_pts_img1", [])]
        viewer._align_pts_img2 = [tuple(p) for p in session.get("align_pts_img2", [])]
        for i, d in enumerate(session.get("adjustments", [{}, {}])[:2]):
            for key in ("brightness", "contrast", "blacks", "whites"):
                if key in d:
                    viewer.adj_vars[i][key].set(float(d[key]))
        self._load_noise_reduction_settings_from_session(viewer, session)

        viewer.annot_mode_var.set(False)
        viewer.align_mode_var.set(False)
        viewer.level_mode_var.set(False)
        viewer.crop_mode_var.set(False)
        viewer._schedule_render()

    def _set_widget_states_by_text(self, root, disabled_texts):
        for child in root.winfo_children():
            try:
                text = child.cget("text")
            except Exception:
                text = None
            if text in disabled_texts:
                try:
                    child.configure(state=tk.DISABLED)
                except Exception:
                    pass
            self._set_widget_states_by_text(child, disabled_texts)

    def _create_annotation_import_viewer(self, session, source_paths, source_images, path):
        from .app import ImageComparer

        win = tk.Toplevel(self.root)
        viewer = ImageComparer(win)
        viewer.root.title(f"Source session view - {path}")
        viewer.root.geometry("1400x900")
        viewer.root.transient(self.root)
        self._apply_session_to_viewer(
            viewer,
            session,
            list(source_paths),
            loaded_images=list(source_images),
            force_sidebyside=True,
        )
        self._set_widget_states_by_text(
            viewer.root,
            {
                "Load Image 1",
                "Load Image 2",
                " Annotate  (click=place  | right-click=delete)",
                "Clear all",
                "Edit labels",
                " Point align  (click pts on img 1, then same pts on img 2  | 2 pairs needed)",
                " Point align + scale  (final click free; 2 pairs needed)",
                "Apply align",
                "Apply align+scale",
                "Clear pts",
                "Move ann",
                "_|_ Level line  (drag a line that should be vertical -> auto-corrects rotation)",
                " Crop export  (click 2 corners on either canvas)",
                "Save session",
                "Load session",
                "Import annotations",
            },
        )

        original_render = viewer._render

        def wrapped_render():
            original_render()
            state = self._annotation_import
            if state is not None and state.get("source_viewer") is viewer:
                self._draw_annotation_import_viewer_overlays()

        viewer._render = wrapped_render

        controls = tk.Frame(viewer.root, bg="#1b2030", pady=4)
        controls.pack(side=tk.TOP, fill=tk.X, before=viewer.canvas_frame)
        help_var = tk.StringVar(
            value=(
                "Click an old annotation in this window, then click the matching point in the main window. "
                "Only Image 1 needs matching; Image 2 is shown for reference."
            )
        )
        count_vars = [tk.StringVar(value="Image 1: 0 pair(s)"),
                      tk.StringVar(value="Image 2: reference only")]
        tk.Label(controls, textvariable=help_var, bg="#1b2030", fg="#ddd",
                 justify=tk.LEFT, wraplength=850,
                 font=("TkDefaultFont", 9)).pack(side=tk.LEFT, padx=8)
        tk.Label(controls, textvariable=count_vars[0], bg="#1b2030", fg="#ffcc88").pack(side=tk.LEFT, padx=8)
        tk.Label(controls, textvariable=count_vars[1], bg="#1b2030", fg="#88ddff").pack(side=tk.LEFT, padx=8)
        tk.Button(controls, text="Clear pairs", command=self._clear_annotation_import_pairs,
                  bg="#555", fg="white", relief=tk.FLAT, padx=10, pady=3,
                  cursor="hand2").pack(side=tk.RIGHT, padx=4)
        apply_btn = tk.Button(controls, text="Import", command=self._apply_annotation_import,
                              bg="#336633", fg="white", relief=tk.FLAT, padx=14, pady=3,
                              cursor="hand2", state=tk.DISABLED)
        apply_btn.pack(side=tk.RIGHT, padx=4)
        tk.Button(controls, text="Cancel", command=self._cancel_annotation_import,
                  bg="#555", fg="white", relief=tk.FLAT, padx=10, pady=3,
                  cursor="hand2").pack(side=tk.RIGHT, padx=4)

        for idx, canvas in enumerate((viewer.canvas1, viewer.canvas2)):
            canvas.bind("<ButtonPress-1>", lambda event, i=idx: self._on_annotation_import_source_press(i, event))
            canvas.bind("<B1-Motion>", lambda event, i=idx: self._on_annotation_import_source_motion(i, event))
            canvas.bind("<ButtonRelease-1>", lambda event, i=idx: self._on_annotation_import_source_release(i, event))
            canvas.bind("<Button-3>", lambda _event: "break")

        def on_close():
            self._cancel_annotation_import()

        viewer.root.protocol("WM_DELETE_WINDOW", on_close)
        viewer.status_var.set(
            "Import annotations: use this window to choose source annotations; use the main window to place their matches."
        )
        viewer._schedule_render()
        return viewer, help_var, count_vars, apply_btn

    def _import_annotations_from_session(self):
        if self.images[0] is None or self.images[1] is None:
            messagebox.showinfo(
                "Import annotations",
                "Load the current Image 1 and Image 2 first, then import annotations.",
                parent=self.root,
            )
            return
        if self._annotation_import is not None:
            win = self._annotation_import.get("win")
            if win is not None and win.winfo_exists():
                win.lift()
                return
            self._annotation_import = None

        confirmed = messagebox.askyesno(
            "Import annotations",
            "Have you already aligned the current Image 1 and Image 2?\n\n"
            "Imported annotations assume the current pair is already aligned before import.",
            parent=self.root,
        )
        if not confirmed:
            self.status_var.set("Import annotations cancelled: align the current image pair first.")
            return

        path = filedialog.askopenfilename(
            title="Import annotations from session",
            filetypes=[("Session file", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
        except Exception as exc:
            messagebox.showerror(
                "Import error",
                f"Could not read session file:\n{exc}",
                parent=self.root,
            )
            return

        annotations = session.get("annotations", [])
        if not annotations:
            messagebox.showinfo(
                "Import annotations",
                "That session does not contain any annotations.",
                parent=self.root,
            )
            return

        saved_paths = list(session.get("image_paths", [None, None]))
        while len(saved_paths) < 2:
            saved_paths.append(None)

        dlg = tk.Toplevel(self.root)
        dlg.title("Import Annotations - Verify source image paths")
        dlg.configure(bg="#2b2b2b")
        dlg.resizable(True, False)
        dlg.transient(self.root)
        dlg.grab_set()

        path_vars = [tk.StringVar(value=p or "") for p in saved_paths[:2]]
        tk.Label(
            dlg,
            text="Source images from the saved session  (edit or Browse if paths changed):",
            bg="#2b2b2b",
            fg="#ccc",
            font=("TkDefaultFont", 9, "bold"),
        ).pack(padx=12, pady=(10, 4), anchor=tk.W)

        for pv, label in zip(path_vars, ["Source Image 1:", "Source Image 2:"]):
            row = tk.Frame(dlg, bg="#2b2b2b")
            row.pack(fill=tk.X, padx=10, pady=3)
            tk.Label(row, text=label, bg="#2b2b2b", fg="#aaa",
                     width=14, anchor=tk.W).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=pv, bg="#444", fg="white",
                     insertbackground="white", relief=tk.FLAT,
                     width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

            def browse(var=pv):
                selected = filedialog.askopenfilename(
                    filetypes=[
                        ("Image files",
                         "*.tif *.tiff *.TIF *.TIFF *.png *.PNG "
                         "*.jpg *.JPG *.jpeg *.JPEG *.bmp *.BMP "
                         "*.arw *.ARW *.nef *.NEF *.cr2 *.CR2 *.cr3 *.CR3 "
                         "*.dng *.DNG *.orf *.ORF *.rw2 *.RW2 *.raf *.RAF"),
                        ("All files", "*.*"),
                    ]
                )
                if selected:
                    var.set(selected)

            tk.Button(row, text="Browse...", command=browse,
                      bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                      cursor="hand2").pack(side=tk.LEFT, padx=4)

        confirmed = [False]

        def on_ok():
            confirmed[0] = True
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg="#2b2b2b")
        btn_row.pack(pady=10)
        tk.Button(btn_row, text="Open", command=on_ok,
                  bg="#336633", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg="#555", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)

        self.root.wait_window(dlg)
        if not confirmed[0]:
            return

        source_paths = [pv.get().strip() or None for pv in path_vars]
        source_images = [None, None]
        for i, source_path in enumerate(source_paths):
            if not source_path:
                messagebox.showerror(
                    "Import annotations",
                    f"Please choose the source file for Image {i + 1}.",
                    parent=self.root,
                )
                return
            try:
                img = _open_image(source_path)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                source_images[i] = img
            except Exception as exc:
                messagebox.showerror(
                    "Import annotations",
                    f"Could not load source image {i + 1}:\n{source_path}\n\n{exc}",
                    parent=self.root,
                )
                return

        self.mode_var.set("sidebyside")
        self._on_mode_change()
        self.annot_mode_var.set(False)
        self.align_mode_var.set(False)
        self.level_mode_var.set(False)
        self.crop_mode_var.set(False)

        viewer, help_var, count_vars, apply_btn = self._create_annotation_import_viewer(
            session,
            source_paths,
            source_images,
            path,
        )

        self._annotation_import = {
            "path": path,
            "win": viewer.root,
            "help_var": help_var,
            "count_vars": count_vars,
            "source_viewer": viewer,
            "source_images": source_images,
            "source_annotations": viewer.annotations,
            "source_colour_labels": session.get("colour_labels", {}),
            "source_pairs": [[], []],
            "target_pairs": [[], []],
            "matched_ann_indices": [[], []],
            "source_press": None,
            "pending": None,
            "apply_btn": apply_btn,
        }
        self._update_annotation_import_ui()
        self.status_var.set(
            "Import annotations: select a source annotation in the import window, then click the matching point on the current image."
        )

    def _draw_annotation_import_viewer_overlays(self):
        state = self._annotation_import
        if state is None:
            return
        viewer = state.get("source_viewer")
        if viewer is None:
            return
        _, _, _, glob_rot = viewer._get_alignment_values()
        pending = state["pending"]
        for image_idx, canvas in enumerate((viewer.canvas1, viewer.canvas2)):
            canvas.delete("import_selection")
            if image_idx == 1 and viewer.images[1] is None:
                continue
            matched = set(state["matched_ann_indices"][0])
            for ann_index, ann in enumerate(state["source_annotations"]):
                cx, cy = viewer._annotation_canvas_position(
                    ann,
                    canvas_is_2=bool(image_idx),
                    glob_rot=glob_rot,
                )
                radius = max(8, float(ann.get("radius", 20)) * viewer.zoom + 4)
                if ann_index in matched:
                    canvas.create_oval(
                        cx - radius,
                        cy - radius,
                        cx + radius,
                        cy + radius,
                        outline="#88ffff",
                        width=3,
                        tags="import_selection",
                    )
                if pending is not None and pending["image_idx"] == image_idx and pending["ann_index"] == ann_index:
                    canvas.create_oval(
                        cx - radius - 4,
                        cy - radius - 4,
                        cx + radius + 4,
                        cy + radius + 4,
                        outline="#ffaa00",
                        width=3,
                        dash=(4, 4),
                        tags="import_selection",
                    )
            canvas.tag_raise("import_selection")

    def _update_annotation_import_ui(self):
        state = self._annotation_import
        if state is None:
            return
        state["count_vars"][0].set(f"Image 1: {len(state['source_pairs'][0])} pair(s)")
        state["count_vars"][1].set("Image 2: reference only")
        pending = state["pending"]
        if pending is None:
            state["help_var"].set(
                "Click an old annotation in the source-session window on Image 1, then click the matching point on the current Image 1. "
                "Do this at least twice. Image 2 is shown for reference only."
            )
        else:
            state["help_var"].set(
                f"Selected source annotation {pending['ann_index'] + 1} on Image 1. "
                "Now click the matching point on the current Image 1."
            )
        can_apply = len(state["source_pairs"][0]) >= 2
        state["apply_btn"].config(state=tk.NORMAL if can_apply else tk.DISABLED)
        viewer = state.get("source_viewer")
        if viewer is not None:
            viewer.status_var.set(state["help_var"].get())
        self._draw_annotation_import_viewer_overlays()

    def _on_annotation_import_source_press(self, image_idx, event):
        state = self._annotation_import
        if state is None:
            return "break"
        state["source_press"] = {
            "image_idx": image_idx,
            "x": event.x,
            "y": event.y,
            "dragged": False,
        }
        return "break"

    def _on_annotation_import_source_motion(self, image_idx, event):
        state = self._annotation_import
        if state is None:
            return "break"
        press = state.get("source_press")
        if press is None or press["image_idx"] != image_idx:
            return "break"
        viewer = state.get("source_viewer")
        if viewer is None:
            return "break"
        if (not press["dragged"]
                and (abs(event.x - press["x"]) > 4 or abs(event.y - press["y"]) > 4)):
            press["dragged"] = True
            viewer._interacting = True
            viewer.last_pan = (press["x"], press["y"])
        if press["dragged"]:
            viewer._on_pan(event)
        return "break"

    def _on_annotation_import_source_release(self, image_idx, event):
        state = self._annotation_import
        if state is None:
            return "break"
        press = state.get("source_press")
        state["source_press"] = None
        if press is None or press["image_idx"] != image_idx:
            return "break"
        if not press["dragged"]:
            self._select_annotation_from_source_viewer(image_idx, event)
        return "break"

    def _select_annotation_from_source_viewer(self, image_idx, event):
        state = self._annotation_import
        if state is None:
            return
        if image_idx != 0:
            self.status_var.set(
                "Import annotations: only source Image 1 is used for matching. Image 2 is for reference."
            )
            return
        if state["pending"] is not None:
            self.status_var.set(
                "Import annotations: finish the current match on the main image first."
            )
            return

        viewer = state.get("source_viewer")
        if viewer is None:
            return
        _, _, _, glob_rot = viewer._get_alignment_values()

        closest = None
        min_dist = float("inf")
        for ann_index, ann in enumerate(state["source_annotations"]):
            cx, cy = viewer._annotation_canvas_position(
                ann,
                canvas_is_2=bool(image_idx),
                glob_rot=glob_rot,
            )
            dist = math.hypot(event.x - cx, event.y - cy)
            if dist < min_dist:
                min_dist = dist
                closest = ann_index
        if closest is None or min_dist > 30:
            self.status_var.set(
                "Import annotations: click closer to a source annotation on Image 1."
            )
            return
        if closest in state["matched_ann_indices"][0]:
            self.status_var.set(
                f"Import annotations: source annotation {closest + 1} on Image 1 is already used."
            )
            return

        ann = state["source_annotations"][closest]
        state["pending"] = {
            "image_idx": 0,
            "ann_index": closest,
            "point": (float(ann["img1_x"]), float(ann["img1_y"])),
        }
        self.status_var.set(
            f"Import annotations: selected source annotation {closest + 1} on Image 1; "
            "click the matching point on the current Image 1."
        )
        self._update_annotation_import_ui()

    def _handle_annotation_import_target_click(self, event):
        state = self._annotation_import
        if state is None:
            return
        pending = state["pending"]
        if pending is None:
            self.status_var.set(
                "Import annotations: select a source annotation in the import window first."
            )
            return

        if event.widget != self.canvas1:
            self.status_var.set(
                "Import annotations: place the matching point on current Image 1 only."
            )
            return
        image_idx = 0
        target_point = self._canvas_to_img1(event.x, event.y)

        if image_idx != pending["image_idx"]:
            self.status_var.set(
                f"Import annotations: the next target click must be on current Image {pending['image_idx'] + 1}."
            )
            return

        state["source_pairs"][image_idx].append(pending["point"])
        state["target_pairs"][image_idx].append((float(target_point[0]), float(target_point[1])))
        state["matched_ann_indices"][0].append(pending["ann_index"])
        state["pending"] = None
        self.status_var.set(
            f"Import annotations: stored pair {len(state['source_pairs'][0])} for Image 1."
        )
        self._update_annotation_import_ui()

    def _clear_annotation_import_pairs(self):
        state = self._annotation_import
        if state is None:
            return
        state["source_pairs"] = [[], []]
        state["target_pairs"] = [[], []]
        state["matched_ann_indices"] = [[], []]
        state["pending"] = None
        self.status_var.set("Import annotations: cleared all matching pairs.")
        self._update_annotation_import_ui()

    def _cancel_annotation_import(self):
        state = self._annotation_import
        self._annotation_import = None
        if state is None:
            return
        win = state.get("win")
        if win is not None and win.winfo_exists():
            win.destroy()
        self.status_var.set("Import annotations cancelled.")

    def _apply_annotation_import(self):
        state = self._annotation_import
        if state is None:
            return
        try:
            transform, scale = self._fit_similarity_transform(
                state["source_pairs"][0],
                state["target_pairs"][0],
            )
        except Exception as exc:
            messagebox.showerror(
                "Import annotations",
                f"Could not compute the annotation transform:\n{exc}",
                parent=state.get("win"),
            )
            return

        imported = []
        radius_scale = float(scale)
        for ann in state["source_annotations"]:
            ann_copy = self._normalize_annotation_record(ann)
            p1 = transform((ann_copy["img1_x"], ann_copy["img1_y"]))
            ann_copy["img1_x"] = float(p1[0])
            ann_copy["img1_y"] = float(p1[1])
            ann_copy["radius"] = max(2.0, float(ann_copy.get("radius", 20.0)) * radius_scale)
            imported.append(ann_copy)

        for colour, label in state["source_colour_labels"].items():
            self.colour_labels.setdefault(colour, label)
        self.annotations.extend(imported)
        imported_count = len(imported)

        win = state.get("win")
        self._annotation_import = None
        if win is not None and win.winfo_exists():
            win.destroy()
        self._schedule_render()
        self.status_var.set(
            f"Imported {imported_count} annotation(s) from {state['path']}."
        )
