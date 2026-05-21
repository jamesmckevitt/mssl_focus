import tkinter as tk
from tkinter import ttk


class UIBuilderMixin:
    def _build_ui(self):
        toolbar = tk.Frame(self.root, bg="#3c3c3c", pady=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        btn_style = {"bg": "#555", "fg": "white", "relief": tk.FLAT,
                     "padx": 8, "pady": 3, "cursor": "hand2"}

        tk.Button(toolbar, text="Load Image 1", command=lambda: self.load_image(0),
                  **btn_style).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="Load Image 2", command=lambda: self.load_image(1),
                  **btn_style).pack(side=tk.LEFT, padx=4)

        sep = tk.Frame(toolbar, bg="#666", width=2, height=28)
        sep.pack(side=tk.LEFT, padx=8, fill=tk.Y)

        tk.Label(toolbar, text="Mode:", bg="#3c3c3c", fg="white").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="sidebyside")
        tk.Radiobutton(toolbar, text="Side by Side", variable=self.mode_var,
                       value="sidebyside", command=self._on_mode_change,
                       bg="#3c3c3c", fg="white", selectcolor="#555",
                       activebackground="#3c3c3c").pack(side=tk.LEFT, padx=2)
        tk.Radiobutton(toolbar, text="Overlay", variable=self.mode_var,
                       value="overlay", command=self._on_mode_change,
                       bg="#3c3c3c", fg="white", selectcolor="#555",
                       activebackground="#3c3c3c").pack(side=tk.LEFT, padx=2)

        sep2 = tk.Frame(toolbar, bg="#666", width=2, height=28)
        sep2.pack(side=tk.LEFT, padx=8, fill=tk.Y)

        tk.Label(toolbar, text="Opacity (img 2):", bg="#3c3c3c", fg="white").pack(side=tk.LEFT)
        self.opacity_var = tk.DoubleVar(value=0.5)
        opacity_slider = ttk.Scale(toolbar, from_=0.0, to=1.0, length=160,
                                   orient=tk.HORIZONTAL, variable=self.opacity_var,
                                   command=lambda v: self._schedule_render())
        opacity_slider.pack(side=tk.LEFT, padx=4)

        sep3 = tk.Frame(toolbar, bg="#666", width=2, height=28)
        sep3.pack(side=tk.LEFT, padx=8, fill=tk.Y)

        toolbar2 = tk.Frame(self.root, bg="#2f2f2f", pady=4)
        toolbar2.pack(side=tk.TOP, fill=tk.X)

        tk.Label(toolbar2, text="Image 2 alignment  -  Offset X:",
                 bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(8, 2))
        self.off_x_var = tk.StringVar(value="0")
        self._make_spinbox(toolbar2, self.off_x_var, -9999, 9999)

        tk.Label(toolbar2, text="Y:", bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(6, 2))
        self.off_y_var = tk.StringVar(value="0")
        self._make_spinbox(toolbar2, self.off_y_var, -9999, 9999)

        tk.Label(toolbar2, text="  Rotation (deg):", bg="#2f2f2f", fg="#ccc").pack(side=tk.LEFT, padx=(12, 2))
        self.rot_var = tk.StringVar(value="0.0")
        self._make_spinbox(toolbar2, self.rot_var, -180, 180, inc=0.1, width=6)

        tk.Label(toolbar2, text="  [Arrow keys nudge X/Y  | Shift+Arrow nudges rotation]",
                 bg="#2f2f2f", fg="#888", font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=12)

        tk.Button(toolbar2, text="Reset alignment",
                  command=self._reset_alignment,
                  bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

        toolbar3 = tk.Frame(self.root, bg="#282828", pady=4)
        toolbar3.pack(side=tk.TOP, fill=tk.X)

        tk.Label(toolbar3, text="Global rotation (both images, deg):",
                 bg="#282828", fg="#aaffaa").pack(side=tk.LEFT, padx=(8, 2))
        self.glob_rot_var = tk.StringVar(value="0.0")
        self._make_spinbox(toolbar3, self.glob_rot_var, -360, 360, inc=0.1, width=7)

        tk.Label(toolbar3, text="  [Ctrl+<> to nudge  | rotates both images together]",
                 bg="#282828", fg="#666", font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=6)

        tk.Frame(toolbar3, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        self.level_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar3, text="_|_ Level line  (drag a line that should be vertical -> auto-corrects rotation)",
                       variable=self.level_mode_var, command=self._on_level_mode_change,
                       bg="#282828", fg="#aaffaa", selectcolor="#444",
                       activebackground="#282828").pack(side=tk.LEFT, padx=4)

        tk.Button(toolbar3, text="Reset global rot",
                  command=lambda: (self.glob_rot_var.set("0.0"), self._schedule_render()),
                  bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

        toolbar4 = tk.Frame(self.root, bg="#1e1e2e", pady=4)
        toolbar4.pack(side=tk.TOP, fill=tk.X)

        self.annot_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar4, text=" Annotate  (click=place  | right-click=delete)",
                       variable=self.annot_mode_var, command=self._on_annot_mode_change,
                       bg="#1e1e2e", fg="#ffff88", selectcolor="#444",
                       activebackground="#1e1e2e").pack(side=tk.LEFT, padx=(8, 4))

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=6, fill=tk.Y)

        self.annot_colour_btn = tk.Button(toolbar4, text="  Colour  ",
                                          bg=self.annot_colour, fg="white",
                                          relief=tk.FLAT, padx=6, pady=2,
                                          cursor="hand2", command=self._pick_colour)
        self.annot_colour_btn.pack(side=tk.LEFT, padx=4)

        tk.Label(toolbar4, text="Radius (px):", bg="#1e1e2e", fg="#ccc").pack(side=tk.LEFT, padx=(8, 2))
        self.annot_radius_var = tk.IntVar(value=20)
        tk.Spinbox(toolbar4, textvariable=self.annot_radius_var, from_=2, to=2000,
                   increment=1, width=5, bg="#444", fg="white",
                   insertbackground="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=6, fill=tk.Y)

        self.annot_label_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar4, text="Floating label",
                       variable=self.annot_label_var,
                       bg="#1e1e2e", fg="#ccc", selectcolor="#444",
                       activebackground="#1e1e2e").pack(side=tk.LEFT, padx=4)

        tk.Button(toolbar4, text="Clear all", command=self._clear_annotations,
                  bg="#663333", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)

        tk.Button(toolbar4, text="Edit labels", command=self._edit_colour_labels,
                  bg="#444466", fg="#ccccff", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=2)

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=6, fill=tk.Y)

        self.align_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar4,
                       text=" Point align  (click pts on img 1, then same pts on img 2  | 2 pairs needed)",
                       variable=self.align_mode_var, command=self._on_align_mode_change,
                       bg="#1e1e2e", fg="#88ffff", selectcolor="#444",
                       activebackground="#1e1e2e").pack(side=tk.LEFT, padx=(4, 2))

        self._align_apply_btn = tk.Button(
            toolbar4, text="Apply align",
            command=self._apply_point_alignment,
            bg="#224444", fg="#88ffff", relief=tk.FLAT, padx=6, pady=2,
            cursor="hand2", state=tk.DISABLED)
        self._align_apply_btn.pack(side=tk.LEFT, padx=2)

        tk.Button(toolbar4, text="Clear pts", command=self._clear_align_pts,
                  bg="#224444", fg="#88ffff", relief=tk.FLAT, padx=4, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=2)

        tk.Frame(toolbar4, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=6, fill=tk.Y)
        tk.Label(toolbar4, text="Label pt:", bg="#1e1e2e", fg="#ccc",
                 font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=(4, 1))
        tk.Scale(toolbar4, variable=self.annot_label_size_var, from_=6, to=48,
                 orient=tk.HORIZONTAL, length=100, bg="#1e1e2e", fg="#ccc",
                 troughcolor="#444", highlightthickness=0, sliderlength=10,
                 command=lambda _: self._schedule_render()).pack(side=tk.LEFT, padx=1)
        tk.Label(toolbar4, text="Legend pt:", bg="#1e1e2e", fg="#ccc",
                 font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=(6, 1))
        tk.Scale(toolbar4, variable=self.canvas_legend_size_var, from_=6, to=36,
                 orient=tk.HORIZONTAL, length=100, bg="#1e1e2e", fg="#ccc",
                 troughcolor="#444", highlightthickness=0, sliderlength=10,
                 command=lambda _: self._schedule_render()).pack(side=tk.LEFT, padx=1)
        tk.Label(toolbar4, text="Ann. width:", bg="#1e1e2e", fg="#ccc",
                 font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=(6, 1))
        self.annot_width_var = tk.DoubleVar(value=2.0)
        tk.Scale(toolbar4, variable=self.annot_width_var, from_=0.5, to=3.5,
                 resolution=0.5, orient=tk.HORIZONTAL, length=80, bg="#1e1e2e", fg="#ccc",
                 troughcolor="#444", highlightthickness=0, sliderlength=10,
                 command=lambda _: self._schedule_render()).pack(side=tk.LEFT, padx=1)

        toolbar5 = tk.Frame(self.root, bg="#12121a", pady=4)
        toolbar5.pack(side=tk.TOP, fill=tk.X)

        adj_defs = [("brightness", 0.1, 3.0, "Bright"),
                    ("contrast",   0.1, 3.0, "Contr"),
                    ("blacks",     0.0, 200.0, "Blacks"),
                    ("whites",    55.0, 255.0, "Whites")]

        for img_idx, (img_label, label_col) in enumerate([("Image 1", "#ffcc00"),
                                                           ("Image 2", "#00ccff")]):
            if img_idx > 0:
                tk.Frame(toolbar5, bg="#555", width=2, height=20).pack(
                    side=tk.LEFT, padx=8, fill=tk.Y)
            tk.Label(toolbar5, text=img_label + ":", bg="#12121a", fg=label_col,
                     font=("TkDefaultFont", 8, "bold")).pack(side=tk.LEFT, padx=(8, 4))
            for key, lo, hi, lbl in adj_defs:
                tk.Label(toolbar5, text=lbl + ":", bg="#12121a", fg="#aaa",
                         font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=(4, 0))
                ttk.Scale(toolbar5, from_=lo, to=hi, length=75, orient=tk.HORIZONTAL,
                          variable=self.adj_vars[img_idx][key],
                          command=lambda _v: self._schedule_render()).pack(side=tk.LEFT, padx=2)

            tk.Button(toolbar5, text="Reset",
                      command=lambda index=img_idx: self._reset_image_adjustments(index),
                      bg="#444", fg="white", relief=tk.FLAT, padx=5, pady=2,
                      cursor="hand2").pack(side=tk.LEFT, padx=(6, 2))

            tk.Frame(toolbar5, bg="#444", width=1, height=20).pack(side=tk.LEFT, padx=(6, 0), fill=tk.Y)
            tk.Label(toolbar5, text="NR:", bg="#12121a", fg="#aaa",
                     font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=(4, 0))
            tk.Scale(toolbar5, variable=self.nr_amount_vars[img_idx],
                     from_=0, to=100, resolution=1, orient=tk.HORIZONTAL, length=80,
                     bg="#12121a", fg="#ccc", troughcolor="#444",
                     highlightthickness=0, sliderlength=12).pack(side=tk.LEFT, padx=2)
            tk.Button(toolbar5, text="Apply",
                      command=lambda i=img_idx: self._apply_noise_reduction(i),
                      bg="#334455", fg="#aaccff", relief=tk.FLAT, padx=5, pady=2,
                      cursor="hand2").pack(side=tk.LEFT, padx=2)

        tk.Button(toolbar5, text="Reset all", command=self._reset_adjustments,
                  bg="#555", fg="white", relief=tk.FLAT, padx=6, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

        toolbar6 = tk.Frame(self.root, bg="#0d0d1a", pady=4)
        toolbar6.pack(side=tk.TOP, fill=tk.X)

        self.crop_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar6,
                       text=" Crop export  (click 2 corners on either canvas)",
                       variable=self.crop_mode_var, command=self._on_crop_mode_change,
                       bg="#0d0d1a", fg="#ffcc88", selectcolor="#444",
                       activebackground="#0d0d1a").pack(side=tk.LEFT, padx=(8, 4))

        tk.Label(toolbar6, text="Padding (px):", bg="#0d0d1a", fg="#ccc").pack(side=tk.LEFT, padx=(8, 2))
        self.crop_pad_var = tk.IntVar(value=20)
        tk.Spinbox(toolbar6, textvariable=self.crop_pad_var, from_=0, to=500,
                   increment=5, width=5, bg="#444", fg="white",
                   insertbackground="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Frame(toolbar6, bg="#666", width=2, height=20).pack(side=tk.LEFT, padx=12, fill=tk.Y)

        tk.Button(toolbar6, text="Save session", command=self._save_session,
                  bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        tk.Button(toolbar6, text="Load session", command=self._load_session,
                  bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        self.canvas_frame = tk.Frame(self.root, bg="#1e1e1e")
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas1 = tk.Canvas(self.canvas_frame, bg="#1e1e1e",
                                 cursor="crosshair", highlightthickness=0)
        self.canvas2 = tk.Canvas(self.canvas_frame, bg="#1e1e1e",
                                 cursor="crosshair", highlightthickness=0)
        self.canvas1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas1.create_text(8, 8, anchor=tk.NW, text="IMAGE 1",
                                 fill="#ffcc00", font=("TkDefaultFont", 9, "bold"),
                                 tags="badge1")
        self.canvas2.create_text(8, 8, anchor=tk.NW, text="IMAGE 2",
                                 fill="#00ccff", font=("TkDefaultFont", 9, "bold"),
                                 tags="badge2")

        self.status_var = tk.StringVar(value="Load two images to begin.")
        tk.Label(self.root, textvariable=self.status_var, anchor=tk.W,
                 bg="#1a1a1a", fg="#aaa", font=("TkDefaultFont", 8),
                 padx=6).pack(side=tk.BOTTOM, fill=tk.X)

        for canvas in (self.canvas1, self.canvas2):
            canvas.bind("<Motion>", self._on_mouse_move)
            canvas.bind("<MouseWheel>", self._on_zoom)
            canvas.bind("<Button-4>", self._on_zoom)
            canvas.bind("<Button-5>", self._on_zoom)
            canvas.bind("<ButtonPress-1>", self._on_left_press)
            canvas.bind("<B1-Motion>", self._on_b1_motion)
            canvas.bind("<ButtonRelease-1>", self._on_left_release)
            canvas.bind("<Button-3>", self._on_right_click)
            canvas.bind("<Configure>", lambda e: self._schedule_render())
            canvas.bind("<Leave>", self._on_canvas_leave)

        self.root.bind("<Left>", lambda e: self._nudge(-1, 0, 0))
        self.root.bind("<Right>", lambda e: self._nudge(1, 0, 0))
        self.root.bind("<Up>", lambda e: self._nudge(0, -1, 0))
        self.root.bind("<Down>", lambda e: self._nudge(0, 1, 0))
        self.root.bind("<Shift-Left>", lambda e: self._nudge(0, 0, -0.1))
        self.root.bind("<Shift-Right>", lambda e: self._nudge(0, 0, 0.1))
        self.root.bind("<Control-Left>", lambda e: self._nudge_global(-0.5))
        self.root.bind("<Control-Right>", lambda e: self._nudge_global(0.5))

    def _make_spinbox(self, parent, var, from_, to, inc=1, width=5):
        sb = tk.Spinbox(parent, textvariable=var, from_=from_, to=to,
                        increment=inc, width=width, bg="#444", fg="white",
                        insertbackground="white", relief=tk.FLAT,
                        command=self._on_alignment_change)
        sb.bind("<Return>", lambda e: self._on_alignment_change())
        sb.bind("<FocusOut>", lambda e: self._on_alignment_change())
        sb.pack(side=tk.LEFT, padx=2)
        return sb
