import json
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image


class SessionMixin:
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
                "glob_rot": self.glob_rot_var.get(),
            },
            "annotations": self.annotations,
            "colour_labels": self.colour_labels,
            "align_pts_img1": self._align_pts_img1,
            "align_pts_img2": self._align_pts_img2,
            "adjustments": [
                {k: v.get() for k, v in d.items()} for d in self.adj_vars
            ],
        }
        path = filedialog.asksaveasfilename(
            title="Save session",
            defaultextension=".json",
            filetypes=[("Session file", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2)
        self.status_var.set(f"Session saved -> {path}")

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
                         "*.jpg *.JPG *.jpeg *.JPEG *.bmp *.BMP"),
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
                    img = Image.open(loaded_path)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    self.images[i] = img
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
            self.annotations = session["annotations"]
        if "colour_labels" in session:
            self.colour_labels = session["colour_labels"]
        if "align_pts_img1" in session:
            self._align_pts_img1 = [tuple(p) for p in session["align_pts_img1"]]
        if "align_pts_img2" in session:
            self._align_pts_img2 = [tuple(p) for p in session["align_pts_img2"]]
        for i, d in enumerate(session.get("adjustments", [{}, {}])[:2]):
            for key in ("brightness", "contrast", "blacks", "whites"):
                if key in d:
                    self.adj_vars[i][key].set(float(d[key]))

        self._schedule_render()
        self.status_var.set(f"Session loaded from {path}")
