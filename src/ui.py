import tkinter as tk
from tkinter import ttk


class UIBuilderMixin:
    def _build_ui(self):
        self.mode_var = tk.StringVar(value="sidebyside")
        self.opacity_var = tk.DoubleVar(value=0.5)
        self.off_x_var = tk.StringVar(value="0")
        self.off_y_var = tk.StringVar(value="0")
        self.rot_var = tk.StringVar(value="0.0")
        self.img2_scale_var = tk.StringVar(value="1.000")
        self.glob_rot_var = tk.StringVar(value="0.0")

        self.level_mode_var = tk.BooleanVar(value=False)
        self.annot_mode_var = tk.BooleanVar(value=False)
        self.annot_radius_var = tk.IntVar(value=20)
        self.annot_label_var = tk.BooleanVar(value=False)
        self.move_annot_mode_var = tk.BooleanVar(value=False)
        self.align_mode_var = tk.BooleanVar(value=False)
        self.align_scale_mode_var = tk.BooleanVar(value=False)
        self.annot_width_var = tk.DoubleVar(value=2.0)
        self.crop_mode_var = tk.BooleanVar(value=False)
        self.crop_pad_var = tk.IntVar(value=20)

        self._align_apply_menu_ref = None
        self._align_scale_apply_menu_ref = None
        self._control_panel = None
        self._control_notebook = None
        self._control_tabs = {}

        self._build_menu_bar()
        self._build_control_panel()
        self._hide_control_panel()

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

    def _build_menu_bar(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Session...", command=self._new_session)
        file_menu.add_separator()
        file_menu.add_command(label="Load Image 1...", command=lambda: self.load_image(0))
        file_menu.add_command(label="Load Image 2...", command=lambda: self.load_image(1))
        file_menu.add_separator()
        file_menu.add_command(label="Save Session...", command=self._save_session)
        file_menu.add_command(label="Load Session...", command=self._load_session)
        file_menu.add_command(label="Import Image Settings...", command=self._import_image_settings_from_session)
        file_menu.add_command(label="Import Annotations...", command=self._import_annotations_from_session)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_radiobutton(label="Side by Side", variable=self.mode_var,
                                  value="sidebyside", command=self._on_mode_change)
        view_menu.add_radiobutton(label="Overlay", variable=self.mode_var,
                                  value="overlay", command=self._on_mode_change)
        view_menu.add_separator()
        view_menu.add_command(label="Show View Controls", command=lambda: self._show_control_panel("view"))
        view_menu.add_command(label="Show All Controls", command=self._show_control_panel)
        menubar.add_cascade(label="View", menu=view_menu)

        align_menu = tk.Menu(menubar, tearoff=False)
        align_menu.add_command(label="Show Alignment Controls", command=lambda: self._show_control_panel("alignment"))
        align_menu.add_separator()
        align_menu.add_checkbutton(label="Level Line", variable=self.level_mode_var,
                                   command=self._on_level_mode_change)
        align_menu.add_checkbutton(label="Point Align", variable=self.align_mode_var,
                                   command=self._on_align_mode_change)
        align_menu.add_command(label="Apply Point Align", command=self._apply_point_alignment,
                               state=tk.DISABLED)
        self._align_apply_menu_ref = (align_menu, align_menu.index(tk.END))
        align_menu.add_checkbutton(label="Point Align + Scale", variable=self.align_scale_mode_var,
                                   command=self._on_align_scale_mode_change)
        align_menu.add_command(label="Apply Align + Scale", command=self._apply_point_alignment_with_scale,
                               state=tk.DISABLED)
        self._align_scale_apply_menu_ref = (align_menu, align_menu.index(tk.END))
        align_menu.add_command(label="Clear Alignment Points", command=self._clear_align_pts)
        align_menu.add_separator()
        align_menu.add_command(label="Reset Alignment", command=self._reset_alignment)
        align_menu.add_command(
            label="Reset Global Rotation",
            command=lambda: (self.glob_rot_var.set("0.0"), self._schedule_render()),
        )
        menubar.add_cascade(label="Align", menu=align_menu)

        annot_menu = tk.Menu(menubar, tearoff=False)
        annot_menu.add_command(label="Show Annotation Controls", command=lambda: self._show_control_panel("annotations"))
        annot_menu.add_separator()
        annot_menu.add_checkbutton(label="Annotate", variable=self.annot_mode_var,
                                   command=self._on_annot_mode_change)
        annot_menu.add_checkbutton(label="Move Annotations", variable=self.move_annot_mode_var,
                                   command=self._on_move_annot_mode_change)
        annot_menu.add_checkbutton(label="Floating Labels", variable=self.annot_label_var)
        annot_menu.add_separator()
        annot_menu.add_command(label="Pick Marker Colour...", command=self._pick_colour)
        annot_menu.add_command(label="Edit Legend Labels...", command=self._edit_colour_labels)
        annot_menu.add_command(label="Clear All Annotations", command=self._clear_annotations)
        menubar.add_cascade(label="Annotations", menu=annot_menu)

        image1_menu = tk.Menu(menubar, tearoff=False)
        image1_menu.add_command(label="Show Image 1 Controls", command=lambda: self._show_control_panel("image1"))
        image1_menu.add_command(label="Load Image 1...", command=lambda: self.load_image(0))
        image1_menu.add_separator()
        image1_menu.add_command(label="Apply Noise Reduction", command=lambda: self._apply_noise_reduction(0))
        image1_menu.add_command(label="Clear Noise Reduction", command=lambda: self._clear_noise_reduction(0))
        image1_menu.add_command(label="Reset Image 1 Adjustments", command=lambda: self._reset_image_adjustments(0))
        menubar.add_cascade(label="Image 1", menu=image1_menu)

        image2_menu = tk.Menu(menubar, tearoff=False)
        image2_menu.add_command(label="Show Image 2 Controls", command=lambda: self._show_control_panel("image2"))
        image2_menu.add_command(label="Load Image 2...", command=lambda: self.load_image(1))
        image2_menu.add_separator()
        image2_menu.add_command(label="Apply Noise Reduction", command=lambda: self._apply_noise_reduction(1))
        image2_menu.add_command(label="Clear Noise Reduction", command=lambda: self._clear_noise_reduction(1))
        image2_menu.add_command(label="Reset Image 2 Adjustments", command=lambda: self._reset_image_adjustments(1))
        menubar.add_cascade(label="Image 2", menu=image2_menu)

        export_menu = tk.Menu(menubar, tearoff=False)
        export_menu.add_command(label="Show Export / Session Controls", command=lambda: self._show_control_panel("session"))
        export_menu.add_separator()
        export_menu.add_checkbutton(label="Crop Export Mode", variable=self.crop_mode_var,
                                    command=self._on_crop_mode_change)
        export_menu.add_command(label="Reset All Adjustments", command=self._reset_adjustments)
        menubar.add_cascade(label="Export", menu=export_menu)

    def _build_control_panel(self):
        panel = tk.Toplevel(self.root)
        panel.title("Controls")
        panel.geometry("460x760")
        panel.configure(bg="#202028")
        panel.protocol("WM_DELETE_WINDOW", self._hide_control_panel)
        panel.withdraw()
        self._control_panel = panel

        header = tk.Frame(panel, bg="#17171f", pady=8)
        header.pack(fill=tk.X)
        tk.Label(header, text="Controls", bg="#17171f", fg="#f0f0f0",
                 font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=10)
        tk.Button(header, text="Hide", command=self._hide_control_panel,
                  bg="#444", fg="white", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

        notebook = ttk.Notebook(panel)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._control_notebook = notebook

        self._control_tabs = {
            "view": self._create_control_tab(notebook, "View"),
            "alignment": self._create_control_tab(notebook, "Alignment"),
            "annotations": self._create_control_tab(notebook, "Annotations"),
            "image1": self._create_control_tab(notebook, "Image 1"),
            "image2": self._create_control_tab(notebook, "Image 2"),
            "session": self._create_control_tab(notebook, "Session / Export"),
        }

        self._populate_view_tab(self._control_tabs["view"])
        self._populate_alignment_tab(self._control_tabs["alignment"])
        self._populate_annotations_tab(self._control_tabs["annotations"])
        self._populate_image_tab(self._control_tabs["image1"], 0, "#ffcc00")
        self._populate_image_tab(self._control_tabs["image2"], 1, "#00ccff")
        self._populate_session_tab(self._control_tabs["session"])

    def _create_control_tab(self, notebook, title):
        frame = tk.Frame(notebook, bg="#202028")
        notebook.add(frame, text=title)
        return frame

    def _make_control_section(self, parent, title):
        section = tk.LabelFrame(parent, text=title, bg="#202028", fg="#dddddd",
                                bd=1, relief=tk.GROOVE, padx=8, pady=8)
        section.pack(fill=tk.X, padx=8, pady=6)
        return section

    def _populate_view_tab(self, parent):
        files = self._make_control_section(parent, "Images")
        tk.Button(files, text="Load Image 1", command=lambda: self.load_image(0),
                  bg="#555", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(files, text="Load Image 2", command=lambda: self.load_image(1),
                  bg="#555", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        display = self._make_control_section(parent, "Display")
        mode_row = tk.Frame(display, bg="#202028")
        mode_row.pack(fill=tk.X, pady=2)
        tk.Label(mode_row, text="Mode:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        tk.Radiobutton(mode_row, text="Side by Side", variable=self.mode_var,
                       value="sidebyside", command=self._on_mode_change,
                       bg="#202028", fg="white", selectcolor="#444",
                       activebackground="#202028").pack(side=tk.LEFT, padx=6)
        tk.Radiobutton(mode_row, text="Overlay", variable=self.mode_var,
                       value="overlay", command=self._on_mode_change,
                       bg="#202028", fg="white", selectcolor="#444",
                       activebackground="#202028").pack(side=tk.LEFT, padx=6)

        opacity_row = tk.Frame(display, bg="#202028")
        opacity_row.pack(fill=tk.X, pady=6)
        tk.Label(opacity_row, text="Overlay opacity (Image 2):",
                 bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        ttk.Scale(opacity_row, from_=0.0, to=1.0, length=220,
                  orient=tk.HORIZONTAL, variable=self.opacity_var,
                  command=lambda _v: self._schedule_render()).pack(side=tk.LEFT, padx=8)

    def _populate_alignment_tab(self, parent):
        align = self._make_control_section(parent, "Image 2 Alignment")
        row1 = tk.Frame(align, bg="#202028")
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="Offset X:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        self._make_spinbox(row1, self.off_x_var, -9999, 9999)
        tk.Label(row1, text="Y:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT, padx=(8, 0))
        self._make_spinbox(row1, self.off_y_var, -9999, 9999)

        row2 = tk.Frame(align, bg="#202028")
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="Rotation (deg):", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        self._make_spinbox(row2, self.rot_var, -180, 180, inc=0.1, width=6)
        tk.Label(row2, text="Scale:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT, padx=(8, 0))
        self._make_spinbox(row2, self.img2_scale_var, 0.1, 10.0, inc=0.01, width=6)
        tk.Button(row2, text="Reset Alignment", command=self._reset_alignment,
                  bg="#555", fg="white", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=4)

        global_section = self._make_control_section(parent, "Global Rotation")
        grow = tk.Frame(global_section, bg="#202028")
        grow.pack(fill=tk.X, pady=2)
        tk.Label(grow, text="Both images (deg):", bg="#202028", fg="#aaffaa").pack(side=tk.LEFT)
        self._make_spinbox(grow, self.glob_rot_var, -360, 360, inc=0.1, width=7)
        tk.Button(grow, text="Reset Global Rot",
                  command=lambda: (self.glob_rot_var.set("0.0"), self._schedule_render()),
                  bg="#555", fg="white", relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2").pack(side=tk.RIGHT, padx=4)

        tools = self._make_control_section(parent, "Alignment Tools")
        tk.Checkbutton(tools, text="Level line mode",
                       variable=self.level_mode_var, command=self._on_level_mode_change,
                       bg="#202028", fg="#aaffaa", selectcolor="#444",
                       activebackground="#202028").pack(anchor=tk.W, pady=2)
        tk.Checkbutton(tools, text="Point align",
                       variable=self.align_mode_var, command=self._on_align_mode_change,
                       bg="#202028", fg="#88ffff", selectcolor="#444",
                       activebackground="#202028").pack(anchor=tk.W, pady=2)
        tk.Checkbutton(tools, text="Point align + scale",
                       variable=self.align_scale_mode_var, command=self._on_align_scale_mode_change,
                       bg="#202028", fg="#88ffbb", selectcolor="#444",
                       activebackground="#202028").pack(anchor=tk.W, pady=2)
        btns = tk.Frame(tools, bg="#202028")
        btns.pack(fill=tk.X, pady=(6, 2))
        self._align_apply_btn = tk.Button(
            btns, text="Apply align", command=self._apply_point_alignment,
            bg="#224444", fg="#88ffff", relief=tk.FLAT, padx=8, pady=3,
            cursor="hand2", state=tk.DISABLED)
        self._align_apply_btn.pack(side=tk.LEFT, padx=4)
        self._align_scale_apply_btn = tk.Button(
            btns, text="Apply align + scale", command=self._apply_point_alignment_with_scale,
            bg="#225544", fg="#88ffbb", relief=tk.FLAT, padx=8, pady=3,
            cursor="hand2", state=tk.DISABLED)
        self._align_scale_apply_btn.pack(side=tk.LEFT, padx=4)
        tk.Button(btns, text="Clear pts", command=self._clear_align_pts,
                  bg="#444", fg="white", relief=tk.FLAT, padx=8, pady=3,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Label(tools,
                 text="Arrow keys nudge X/Y, Shift+Arrow nudges rotation, Ctrl+Left/Right nudges global rotation.",
                 bg="#202028", fg="#888888", justify=tk.LEFT,
                 wraplength=380, font=("TkDefaultFont", 8)).pack(anchor=tk.W, pady=(4, 0))

    def _populate_annotations_tab(self, parent):
        tools = self._make_control_section(parent, "Annotation Tools")
        tk.Checkbutton(tools, text="Annotate",
                       variable=self.annot_mode_var, command=self._on_annot_mode_change,
                       bg="#202028", fg="#ffff88", selectcolor="#444",
                       activebackground="#202028").pack(anchor=tk.W, pady=2)
        tk.Checkbutton(tools, text="Move annotations",
                       variable=self.move_annot_mode_var, command=self._on_move_annot_mode_change,
                       bg="#202028", fg="#ffbb88", selectcolor="#444",
                       activebackground="#202028").pack(anchor=tk.W, pady=2)
        tk.Checkbutton(tools, text="Floating labels",
                       variable=self.annot_label_var,
                       bg="#202028", fg="#dddddd", selectcolor="#444",
                       activebackground="#202028").pack(anchor=tk.W, pady=2)

        style = self._make_control_section(parent, "Marker Style")
        colour_row = tk.Frame(style, bg="#202028")
        colour_row.pack(fill=tk.X, pady=2)
        tk.Label(colour_row, text="Colour:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        self.annot_colour_btn = tk.Button(colour_row, text="  Colour  ",
                                          bg=self.annot_colour, fg="white",
                                          relief=tk.FLAT, padx=8, pady=2,
                                          cursor="hand2", command=self._pick_colour)
        self.annot_colour_btn.pack(side=tk.LEFT, padx=8)

        radius_row = tk.Frame(style, bg="#202028")
        radius_row.pack(fill=tk.X, pady=2)
        tk.Label(radius_row, text="Radius (px):", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        tk.Spinbox(radius_row, textvariable=self.annot_radius_var, from_=2, to=2000,
                   increment=1, width=6, bg="#444", fg="white",
                   insertbackground="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=8)

        text_section = self._make_control_section(parent, "Label and Legend")
        label_row = tk.Frame(text_section, bg="#202028")
        label_row.pack(fill=tk.X, pady=4)
        tk.Label(label_row, text="Label size:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        tk.Scale(label_row, variable=self.annot_label_size_var, from_=6, to=48,
                 orient=tk.HORIZONTAL, length=220, bg="#202028", fg="#dddddd",
                 troughcolor="#444", highlightthickness=0, sliderlength=10,
                 command=lambda _: self._schedule_render()).pack(side=tk.LEFT, padx=8)

        legend_row = tk.Frame(text_section, bg="#202028")
        legend_row.pack(fill=tk.X, pady=4)
        tk.Label(legend_row, text="Legend size:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        tk.Scale(legend_row, variable=self.canvas_legend_size_var, from_=6, to=36,
                 orient=tk.HORIZONTAL, length=220, bg="#202028", fg="#dddddd",
                 troughcolor="#444", highlightthickness=0, sliderlength=10,
                 command=lambda _: self._schedule_render()).pack(side=tk.LEFT, padx=8)

        width_row = tk.Frame(text_section, bg="#202028")
        width_row.pack(fill=tk.X, pady=4)
        tk.Label(width_row, text="Annotation width:", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        tk.Scale(width_row, variable=self.annot_width_var, from_=0.5, to=3.5,
                 resolution=0.5, orient=tk.HORIZONTAL, length=220, bg="#202028", fg="#dddddd",
                 troughcolor="#444", highlightthickness=0, sliderlength=10,
                 command=lambda _: self._schedule_render()).pack(side=tk.LEFT, padx=8)

        actions = tk.Frame(parent, bg="#202028")
        actions.pack(fill=tk.X, padx=12, pady=8)
        tk.Button(actions, text="Edit labels", command=self._edit_colour_labels,
                  bg="#444466", fg="#ccccff", relief=tk.FLAT, padx=8, pady=3,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Clear all", command=self._clear_annotations,
                  bg="#663333", fg="white", relief=tk.FLAT, padx=8, pady=3,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

    def _populate_image_tab(self, parent, img_idx, accent_colour):
        adj_defs = [
            ("brightness", 0.1, 3.0, "Brightness"),
            ("contrast", 0.1, 3.0, "Contrast"),
            ("blacks", 0.0, 200.0, "Blacks"),
            ("whites", 55.0, 255.0, "Whites"),
        ]

        actions = self._make_control_section(parent, f"Image {img_idx + 1} Actions")
        tk.Button(actions, text=f"Load Image {img_idx + 1}", command=lambda i=img_idx: self.load_image(i),
                  bg="#555", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Reset adjustments",
                  command=lambda i=img_idx: self._reset_image_adjustments(i),
                  bg="#444", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        tone = self._make_control_section(parent, "Tone and Levels")
        for key, lo, hi, label in adj_defs:
            row = tk.Frame(tone, bg="#202028")
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label + ":", bg="#202028", fg=accent_colour,
                     width=11, anchor=tk.W).pack(side=tk.LEFT)
            ttk.Scale(row, from_=lo, to=hi, length=240, orient=tk.HORIZONTAL,
                      variable=self.adj_vars[img_idx][key],
                      command=lambda _v: self._schedule_render()).pack(side=tk.LEFT, padx=6)

        noise = self._make_control_section(parent, "Noise Reduction")
        nr_row = tk.Frame(noise, bg="#202028")
        nr_row.pack(fill=tk.X, pady=4)
        tk.Label(nr_row, text="NR:", bg="#202028", fg="#dddddd", width=11, anchor=tk.W).pack(side=tk.LEFT)
        tk.Scale(nr_row, variable=self.nr_amount_vars[img_idx],
                 from_=0, to=100, resolution=10, orient=tk.HORIZONTAL, length=220,
                 bg="#202028", fg="#dddddd", troughcolor="#444",
                 highlightthickness=0, sliderlength=12).pack(side=tk.LEFT, padx=6)

        cnr_row = tk.Frame(noise, bg="#202028")
        cnr_row.pack(fill=tk.X, pady=4)
        tk.Label(cnr_row, text="Color NR:", bg="#202028", fg="#7fd7ff", width=11, anchor=tk.W).pack(side=tk.LEFT)
        tk.Scale(cnr_row, variable=self.nr_color_vars[img_idx],
                 from_=0, to=100, resolution=10, orient=tk.HORIZONTAL, length=220,
                 bg="#202028", fg="#dddddd", troughcolor="#444",
                 highlightthickness=0, sliderlength=12).pack(side=tk.LEFT, padx=6)

        edge_row = tk.Frame(noise, bg="#202028")
        edge_row.pack(fill=tk.X, pady=4)
        tk.Label(edge_row, text="Edge NR:", bg="#202028", fg="#9fffb0", width=11, anchor=tk.W).pack(side=tk.LEFT)
        tk.Scale(edge_row, variable=self.nr_edge_vars[img_idx],
                 from_=0, to=100, resolution=10, orient=tk.HORIZONTAL, length=220,
                 bg="#202028", fg="#dddddd", troughcolor="#444",
                 highlightthickness=0, sliderlength=12).pack(side=tk.LEFT, padx=6)

        tk.Checkbutton(noise, text="Aggressive",
                       variable=self.nr_aggressive_vars[img_idx],
                       bg="#202028", fg="#aaccff", selectcolor="#334455",
                       activebackground="#202028", activeforeground="#aaccff").pack(anchor=tk.W, pady=4)

        noise_btns = tk.Frame(noise, bg="#202028")
        noise_btns.pack(fill=tk.X, pady=(6, 2))
        tk.Button(noise_btns, text="Apply", command=lambda i=img_idx: self._apply_noise_reduction(i),
                  bg="#334455", fg="#aaccff", relief=tk.FLAT, padx=8, pady=3,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(noise_btns, text="Clear NR", command=lambda i=img_idx: self._clear_noise_reduction(i),
                  bg="#444", fg="white", relief=tk.FLAT, padx=8, pady=3,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

    def _populate_session_tab(self, parent):
        sessions = self._make_control_section(parent, "Session")
        btns = tk.Frame(sessions, bg="#202028")
        btns.pack(fill=tk.X)
        tk.Button(btns, text="New session", command=self._new_session,
                  bg="#663333", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(btns, text="Save session", command=self._save_session,
                  bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(btns, text="Load session", command=self._load_session,
                  bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        import_row = tk.Frame(sessions, bg="#202028")
        import_row.pack(fill=tk.X, pady=(8, 0))
        tk.Button(import_row, text="Import image settings", command=self._import_image_settings_from_session,
              bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=10, pady=4,
              cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(import_row, text="Import annotations", command=self._import_annotations_from_session,
                  bg="#2a3a5a", fg="#aaccff", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

        crop = self._make_control_section(parent, "Crop Export")
        tk.Checkbutton(crop, text="Crop export mode",
                       variable=self.crop_mode_var, command=self._on_crop_mode_change,
                       bg="#202028", fg="#ffcc88", selectcolor="#444",
                       activebackground="#202028").pack(anchor=tk.W, pady=2)
        pad_row = tk.Frame(crop, bg="#202028")
        pad_row.pack(fill=tk.X, pady=4)
        tk.Label(pad_row, text="Padding (px):", bg="#202028", fg="#dddddd").pack(side=tk.LEFT)
        tk.Spinbox(pad_row, textvariable=self.crop_pad_var, from_=0, to=500,
                   increment=5, width=6, bg="#444", fg="white",
                   insertbackground="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=8)
        tk.Label(crop,
                 text="Enable crop mode, then click two corners on either canvas to export a crop preview.",
                 bg="#202028", fg="#888888", justify=tk.LEFT,
                 wraplength=380, font=("TkDefaultFont", 8)).pack(anchor=tk.W, pady=(4, 0))

        reset_row = tk.Frame(parent, bg="#202028")
        reset_row.pack(fill=tk.X, padx=12, pady=8)
        tk.Button(reset_row, text="Reset all adjustments", command=self._reset_adjustments,
                  bg="#555", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=4)

    def _show_control_panel(self, tab_name=None):
        if self._control_panel is None or not self._control_panel.winfo_exists():
            self._build_control_panel()
        self._control_panel.deiconify()
        self._position_control_panel()
        self._control_panel.lift()
        self._control_panel.focus_force()
        if tab_name is not None and tab_name in self._control_tabs:
            self._control_notebook.select(self._control_tabs[tab_name])

    def _hide_control_panel(self):
        if self._control_panel is not None and self._control_panel.winfo_exists():
            self._control_panel.withdraw()

    def _position_control_panel(self):
        if self._control_panel is None or not self._control_panel.winfo_exists():
            return
        self.root.update_idletasks()
        self._control_panel.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width() + 16
        y = self.root.winfo_rooty() + 48
        self._control_panel.geometry(f"+{x}+{y}")

    def _clear_noise_reduction(self, idx):
        self.nr_amount_vars[idx].set(0)
        self._apply_noise_reduction(idx)

    def _set_menu_entry_state(self, menu_ref, state):
        if menu_ref is None:
            return
        menu, index = menu_ref
        try:
            menu.entryconfig(index, state=state)
        except Exception:
            pass

    def _make_spinbox(self, parent, var, from_, to, inc=1, width=5):
        sb = tk.Spinbox(parent, textvariable=var, from_=from_, to=to,
                        increment=inc, width=width, bg="#444", fg="white",
                        insertbackground="white", relief=tk.FLAT,
                        command=self._on_alignment_change)
        sb.bind("<Return>", lambda e: self._on_alignment_change())
        sb.bind("<FocusOut>", lambda e: self._on_alignment_change())
        sb.pack(side=tk.LEFT, padx=2)
        return sb
