"""Window layout: menu, toolbar, guidance bar, image panels, sidebar and status bar."""

import os
import tkinter as tk
from tkinter import ttk

from . import theme
from .annotations import PRESET_COLOURS
from .help import show_about, show_guide, show_shortcuts
from .pair import BACKLIT, FRONTLIT
from .theme import Tooltip
from .tools import TOOLS
from .viewer import CURRENT, REFERENCE, Pane

ADJUST_TARGETS = [
    ("Backlit image", CURRENT, BACKLIT),
    ("Frontlit image", CURRENT, FRONTLIT),
    ("Reference backlit image", REFERENCE, BACKLIT),
    ("Reference frontlit image", REFERENCE, FRONTLIT),
]

ADJUST_SLIDERS = [
    ("brightness", "Brightness", 0.1, 3.0, "{:.2f}"),
    ("contrast", "Contrast", 0.1, 3.0, "{:.2f}"),
    ("blacks", "Blacks", 0.0, 200.0, "{:.0f}"),
    ("whites", "Whites", 55.0, 255.0, "{:.0f}"),
]


class UIBuilderMixin:
    def px(self, value):
        return int(round(value * self.ui_scale))

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        self._build_variables()
        self._build_menu()
        self._build_toolbar()
        self._build_hint_bar()
        self._build_status_bar()

        body = ttk.Frame(self.root, style="Window.TFrame")
        body.pack(fill=tk.BOTH, expand=True)
        self.sidebar_holder = ttk.Frame(body, width=self.px(350))
        self.sidebar_holder.pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar_holder.pack_propagate(False)
        self.canvas_area = tk.Frame(body, bg=theme.BG)
        self.canvas_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_panes()
        self._build_sidebar()
        self._bind_keys()

    def _build_variables(self):
        self.tool_var = tk.StringVar(value="pan")
        self.mode_var = tk.StringVar(value="sidebyside")
        self.opacity_var = tk.DoubleVar(value=0.5)
        self.show_reference_var = tk.BooleanVar(value=False)
        self.show_sidebar_var = tk.BooleanVar(value=True)
        self.align_scale_var = tk.BooleanVar(value=False)
        self.control_row_var = tk.IntVar(value=CURRENT)

        self.annot_radius_var = tk.IntVar(value=20)
        self.annot_autolabel_var = tk.BooleanVar(value=True)
        self.annot_width_var = tk.DoubleVar(value=2.0)
        self.annot_label_size_var = tk.IntVar(value=12)
        self.canvas_legend_size_var = tk.IntVar(value=10)
        self.legend_name_var = tk.StringVar()
        self.label_prefix_var = tk.StringVar()
        self.crop_pad_var = tk.IntVar(value=20)

        self.align_fields = {name: tk.StringVar() for name in ("off_x", "off_y", "rot", "scale", "glob_rot")}
        self.row_fields = {name: tk.StringVar() for name in ("x", "y", "rot", "scale")}

        self.adjust_target_var = tk.StringVar(value=ADJUST_TARGETS[0][0])
        self.adjust_vars = {key: tk.DoubleVar() for key, *_rest in ADJUST_SLIDERS}
        self.adjust_readouts = {key: tk.StringVar() for key, *_rest in ADJUST_SLIDERS}
        self.nr_vars = {"amount": tk.IntVar(), "color": tk.IntVar(), "edge": tk.IntVar()}
        self.nr_aggressive_var = tk.BooleanVar()

        self.hint_title_var = tk.StringVar()
        self.hint_text_var = tk.StringVar()
        self.status_var = tk.StringVar(value="")
        self.coords_var = tk.StringVar(value="")
        self.zoom_readout_var = tk.StringVar(value="100%")
        self.image_name_vars = {(row, idx): tk.StringVar() for row in (0, 1) for idx in (0, 1)}
        self.row_label_vars = {row: tk.StringVar() for row in (0, 1)}

    # ------------------------------------------------------------------ #
    # Menu
    # ------------------------------------------------------------------ #

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New session", accelerator="Ctrl+N", command=self.new_session)
        file_menu.add_command(label="Open session...", accelerator="Ctrl+O", command=self.open_session)
        self.recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Open recent", menu=self.recent_menu)
        file_menu.add_command(label="Save session", accelerator="Ctrl+S", command=self.save_session)
        file_menu.add_command(label="Save session as...", accelerator="Ctrl+Shift+S",
                              command=self.save_session_as)
        file_menu.add_separator()
        file_menu.add_command(label="Load backlit image...", command=lambda: self.load_image(BACKLIT))
        file_menu.add_command(label="Load frontlit image...", command=lambda: self.load_image(FRONTLIT))
        file_menu.add_separator()
        file_menu.add_command(label="Load reference session...", command=self.open_reference_session)
        file_menu.add_command(label="Load reference backlit image...",
                              command=lambda: self.load_image(BACKLIT, REFERENCE))
        file_menu.add_command(label="Load reference frontlit image...",
                              command=lambda: self.load_image(FRONTLIT, REFERENCE))
        file_menu.add_command(label="Remove reference row", command=self.remove_reference_row)
        file_menu.add_separator()
        file_menu.add_command(label="Import image settings from session...", command=self.import_image_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Export crop...", accelerator="C", command=lambda: self.set_tool("crop"))
        file_menu.add_command(label="Export current view...", command=self.export_view)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy markers from reference row...", command=self.copy_reference_annotations)
        edit_menu.add_command(label="Clear all markers...", command=self.clear_annotations)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        self.edit_menu = edit_menu

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_radiobutton(label="Side by side", variable=self.mode_var, value="sidebyside",
                                  command=self._on_mode_change)
        view_menu.add_radiobutton(label="Overlay", accelerator="O", variable=self.mode_var, value="overlay",
                                  command=self._on_mode_change)
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Show reference row", variable=self.show_reference_var,
                                  command=self._on_reference_toggle)
        view_menu.add_checkbutton(label="Show sidebar", variable=self.show_sidebar_var,
                                  command=self._on_sidebar_toggle)
        view_menu.add_separator()
        view_menu.add_command(label="Fit to window", accelerator="F", command=self.fit_view)
        view_menu.add_command(label="Actual size (100%)", accelerator="1", command=self.zoom_actual)
        view_menu.add_command(label="Zoom in", accelerator="+", command=lambda: self.zoom_step(1.25))
        view_menu.add_command(label="Zoom out", accelerator="-", command=lambda: self.zoom_step(0.8))
        menubar.add_cascade(label="View", menu=view_menu)

        tools_menu = tk.Menu(menubar, tearoff=False)
        for tool, label, key, _tip in TOOLS:
            tools_menu.add_radiobutton(label=label, accelerator=key.upper(), variable=self.tool_var,
                                       value=tool, command=self._on_tool_changed)
        tools_menu.add_separator()
        tools_menu.add_command(label="Reset frontlit alignment", command=self.reset_frontlit_alignment)
        tools_menu.add_command(label="Reset rotation of both images", command=self.reset_global_rotation)
        tools_menu.add_command(label="Reset row alignment", command=self.reset_row_alignment)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Step-by-step guide", accelerator="F1", command=lambda: show_guide(self))
        help_menu.add_command(label="Keyboard and mouse shortcuts", command=lambda: show_shortcuts(self))
        help_menu.add_separator()
        help_menu.add_command(label="About MSSL FOCUS", command=lambda: show_about(self))
        menubar.add_cascade(label="Help", menu=help_menu)

        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self.recent_menu.delete(0, tk.END)
        recent = self.config.recent()
        if not recent:
            self.recent_menu.add_command(label="(no recent sessions)", state=tk.DISABLED)
            return
        for path in recent:
            folder = os.path.basename(os.path.dirname(path))
            self.recent_menu.add_command(
                label=f"{folder}/{os.path.basename(path)}    -  {os.path.dirname(path)}",
                command=lambda p=path: self.open_session(p))

    # ------------------------------------------------------------------ #
    # Toolbar, guidance bar, status bar
    # ------------------------------------------------------------------ #

    def _toolbar_separator(self, parent):
        ttk.Separator(parent, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y,
                                                        padx=self.px(8), pady=self.px(6))

    def _build_toolbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(side=tk.TOP, fill=tk.X)
        pad = self.px(2)

        def button(text, command, tip, style="Tool.Toolbutton"):
            widget = ttk.Button(bar, text=text, command=command, style=style, takefocus=False)
            widget.pack(side=tk.LEFT, padx=pad, pady=self.px(4))
            Tooltip(widget, tip)
            return widget

        ttk.Frame(bar, width=self.px(4)).pack(side=tk.LEFT)
        button("Open", self.open_session, "Open a saved session (Ctrl+O)")
        button("Save", self.save_session, "Save the session (Ctrl+S)")
        self._toolbar_separator(bar)

        for tool, label, _key, tip in TOOLS:
            widget = ttk.Radiobutton(bar, text=label, value=tool, variable=self.tool_var,
                                     command=self._on_tool_changed, style="Tool.Toolbutton", takefocus=False)
            widget.pack(side=tk.LEFT, padx=pad, pady=self.px(4))
            Tooltip(widget, tip)
        self._toolbar_separator(bar)

        for value, label, tip in (
            ("sidebyside", "Side by side", "Show the backlit and frontlit images next to each other"),
            ("overlay", "Overlay", "Blend the frontlit image over the backlit image (O)\n"
                                   "Best way to check an alignment."),
        ):
            widget = ttk.Radiobutton(bar, text=label, value=value, variable=self.mode_var,
                                     command=self._on_mode_change, style="Tool.Toolbutton", takefocus=False)
            widget.pack(side=tk.LEFT, padx=pad, pady=self.px(4))
            Tooltip(widget, tip)
        widget = ttk.Checkbutton(bar, text="Reference row", variable=self.show_reference_var,
                                 command=self._on_reference_toggle, style="Tool.Toolbutton", takefocus=False)
        widget.pack(side=tk.LEFT, padx=pad, pady=self.px(4))
        Tooltip(widget, "Show a second row with another inspection of the same filter,\n"
                        "for a before / after comparison.")
        button("Fit", self.fit_view, "Fit the images to the window (F)")
        self._toolbar_separator(bar)

        self.undo_button = button("Undo", self.undo, "Undo (Ctrl+Z)")
        self.redo_button = button("Redo", self.redo, "Redo (Ctrl+Y)")

        guide = ttk.Button(bar, text="Guide", command=lambda: show_guide(self), style="Tool.Toolbutton",
                           takefocus=False)
        guide.pack(side=tk.RIGHT, padx=self.px(6), pady=self.px(4))
        Tooltip(guide, "Step-by-step guide to an inspection (F1)")

    def _build_hint_bar(self):
        bar = ttk.Frame(self.root, style="Hint.TFrame")
        bar.pack(side=tk.TOP, fill=tk.X)
        self.hint_bar = bar
        pad_y = self.px(6)
        ttk.Label(bar, textvariable=self.hint_title_var, style="HintTitle.TLabel").pack(
            side=tk.LEFT, padx=(self.px(12), self.px(10)), pady=pad_y)

        self.hint_actions = ttk.Frame(bar, style="Hint.TFrame")
        self.hint_actions.pack(side=tk.RIGHT, padx=self.px(8))
        self.hint_scale_check = ttk.Checkbutton(self.hint_actions, text="Allow scale change",
                                                variable=self.align_scale_var, style="Hint.TCheckbutton",
                                                takefocus=False, command=self._draw_align_guide)
        Tooltip(self.hint_scale_check,
                "Off: only shift and rotate (use when both images were taken at the same distance).\n"
                "On: also resize, for images taken at slightly different magnification.")
        self.hint_undo_point = ttk.Button(self.hint_actions, text="Remove last point",
                                          command=self._undo_tool_point, takefocus=False)
        self.hint_clear_points = ttk.Button(self.hint_actions, text="Clear points",
                                            command=self._clear_tool_points, takefocus=False)
        self.hint_apply = ttk.Button(self.hint_actions, text="Apply", style="Accent.TButton",
                                     command=self.apply_tool_points, takefocus=False)
        self.hint_done = ttk.Button(self.hint_actions, text="Done", command=lambda: self.set_tool("pan"),
                                    takefocus=False)

        self.hint_label = ttk.Label(bar, textvariable=self.hint_text_var, style="Hint.TLabel",
                                    justify=tk.LEFT, anchor=tk.W)
        self.hint_label.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=pad_y)
        self.hint_label.bind("<Configure>",
                             lambda e: self.hint_label.configure(wraplength=max(200, e.width - self.px(8))))

    def _set_hint_buttons(self, show_points, can_apply):
        for widget in (self.hint_scale_check, self.hint_undo_point, self.hint_clear_points,
                       self.hint_apply, self.hint_done):
            widget.pack_forget()
        tool = self.tool_var.get()
        if show_points:
            pad = self.px(3)
            self.hint_scale_check.pack(side=tk.LEFT, padx=(pad, self.px(10)))
            self.hint_undo_point.pack(side=tk.LEFT, padx=pad)
            self.hint_clear_points.pack(side=tk.LEFT, padx=pad)
            self.hint_apply.pack(side=tk.LEFT, padx=pad)
            self.hint_apply.state(["!disabled"] if can_apply else ["disabled"])
        if tool != "pan":
            self.hint_done.pack(side=tk.LEFT, padx=self.px(3))

    def _build_status_bar(self):
        bar = ttk.Frame(self.root, style="Window.TFrame")
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bar, textvariable=self.zoom_readout_var, style="Status.TLabel", width=7,
                  anchor=tk.E).pack(side=tk.RIGHT, padx=(0, self.px(10)), pady=self.px(3))
        ttk.Label(bar, textvariable=self.coords_var, style="Status.TLabel", width=44,
                  anchor=tk.E).pack(side=tk.RIGHT, padx=self.px(10))
        ttk.Label(bar, textvariable=self.status_var, style="StatusMsg.TLabel", anchor=tk.W).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=self.px(10))

    def set_status(self, message):
        self.status_var.set(message)

    # ------------------------------------------------------------------ #
    # Image panels
    # ------------------------------------------------------------------ #

    def _build_panes(self):
        self.panes = []
        for row in (CURRENT, REFERENCE):
            for idx in (BACKLIT, FRONTLIT):
                canvas = tk.Canvas(self.canvas_area, bg=theme.CANVAS_BG, highlightthickness=0,
                                   cursor="fleur", takefocus=True)
                pane = Pane(row, idx, canvas)
                pane.cursor_items = (
                    canvas.create_line(0, 0, 0, 0, fill=theme.CURSOR, tags="cursor", state=tk.HIDDEN),
                    canvas.create_line(0, 0, 0, 0, fill=theme.CURSOR, tags="cursor", state=tk.HIDDEN),
                    canvas.create_oval(0, 0, 0, 0, outline=theme.CURSOR, tags="cursor", state=tk.HIDDEN),
                )
                canvas.bind("<Motion>", self._on_mouse_move)
                canvas.bind("<MouseWheel>", self._on_wheel)
                canvas.bind("<Button-4>", self._on_wheel)
                canvas.bind("<Button-5>", self._on_wheel)
                canvas.bind("<ButtonPress-1>", self._on_press)
                canvas.bind("<B1-Motion>", self._on_drag)
                canvas.bind("<ButtonRelease-1>", self._on_release)
                canvas.bind("<ButtonPress-2>", self._on_middle_press)
                canvas.bind("<B2-Motion>", self._on_middle_drag)
                canvas.bind("<Button-3>", self._on_right_click)
                canvas.bind("<Configure>", self._on_canvas_resized)
                canvas.bind("<Leave>", self._on_leave)
                self.panes.append(pane)

    # ------------------------------------------------------------------ #
    # Sidebar
    # ------------------------------------------------------------------ #

    def _on_sidebar_toggle(self):
        if self.show_sidebar_var.get():
            self.sidebar_holder.pack(side=tk.RIGHT, fill=tk.Y, before=self.canvas_area)
        else:
            self.sidebar_holder.pack_forget()

    def _build_sidebar(self):
        holder = self.sidebar_holder
        scroll = ttk.Scrollbar(holder, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        view = tk.Canvas(holder, bg=theme.PANEL, highlightthickness=0, yscrollcommand=scroll.set)
        view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=view.yview)
        inner = ttk.Frame(view)
        window = view.create_window(0, 0, anchor=tk.NW, window=inner)
        inner.bind("<Configure>", lambda _e: view.configure(scrollregion=view.bbox("all")))
        view.bind("<Configure>", lambda e: view.itemconfigure(window, width=e.width))

        def on_wheel(event):
            if inner.winfo_height() > view.winfo_height():
                view.yview_scroll(-1 if event.delta > 0 else 1, "units")

        holder.bind("<Enter>", lambda _e: holder.bind_all("<MouseWheel>", on_wheel))
        holder.bind("<Leave>", lambda _e: holder.unbind_all("<MouseWheel>"))

        self._sections = {}
        self._build_images_section(self._section(inner, "images", "Images"))
        self._build_view_section(self._section(inner, "view", "View"))
        self._build_alignment_section(self._section(inner, "alignment", "Alignment"))
        self._build_annotation_section(self._section(inner, "annotations", "Annotations"))
        self._build_adjust_section(self._section(inner, "adjust", "Brightness, contrast and noise",
                                                 open_by_default=False))
        self._build_export_section(self._section(inner, "export", "Export", open_by_default=False))

    def _section(self, parent, key, title, open_by_default=True):
        """A titled block that collapses when its header is clicked."""
        states = self.config.get("sections", {})
        is_open = bool(states.get(key, open_by_default))
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill=tk.X, pady=(0, self.px(2)))
        header = ttk.Button(wrapper, style="Section.TButton", takefocus=False)
        header.pack(fill=tk.X)
        body = ttk.Frame(wrapper)
        section = {"open": is_open, "body": body, "header": header, "title": title}
        self._sections[key] = section

        def refresh():
            header.configure(text=("▾  " if section["open"] else "▸  ") + title)
            if section["open"]:
                body.pack(fill=tk.X, padx=self.px(12), pady=(self.px(8), self.px(10)))
            else:
                body.pack_forget()

        def toggle():
            section["open"] = not section["open"]
            saved = dict(self.config.get("sections", {}))
            saved[key] = section["open"]
            self.config.set("sections", saved)
            refresh()

        header.configure(command=toggle)
        refresh()
        return body

    def _row(self, parent, pady=2):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=self.px(pady))
        return row

    def _subheading(self, parent, text, style="Group.TLabel"):
        ttk.Label(parent, text=text.upper(), style=style).pack(anchor=tk.W, pady=(self.px(8), self.px(2)))

    def _note(self, parent, text):
        label = ttk.Label(parent, text=text, style="Muted.TLabel", justify=tk.LEFT, wraplength=self.px(300))
        label.pack(anchor=tk.W, pady=(self.px(2), self.px(4)))
        return label

    def _number_field(self, parent, label, var, low, high, step, command, width=8, fmt="%.2f"):
        ttk.Label(parent, text=label).pack(side=tk.LEFT)
        box = ttk.Spinbox(parent, textvariable=var, from_=low, to=high, increment=step, width=width,
                          format=fmt, command=command)
        box.pack(side=tk.LEFT, padx=(self.px(4), self.px(10)))
        box.bind("<Return>", lambda _e: (command(), self.panes[0].canvas.focus_set()))
        box.bind("<FocusOut>", lambda _e: command())
        return box

    def _slider(self, parent, label, var, low, high, command, readout=None, label_width=11):
        row = self._row(parent, 3)
        ttk.Label(row, text=label, width=label_width).pack(side=tk.LEFT)
        if readout is not None:
            ttk.Label(row, textvariable=readout, style="Value.TLabel", width=5, anchor=tk.E).pack(side=tk.RIGHT)
        scale = ttk.Scale(row, from_=low, to=high, variable=var, command=command)
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=self.px(6))
        return scale

    # -- Images --------------------------------------------------------- #

    def _build_images_section(self, body):
        def image_rows(row):
            for idx, style in ((BACKLIT, "Backlit.TLabel"), (FRONTLIT, "Frontlit.TLabel")):
                line = self._row(body)
                ttk.Label(line, text="Backlit" if idx == BACKLIT else "Frontlit", style=style,
                          width=8).pack(side=tk.LEFT)
                ttk.Button(line, text="Load...", style="Small.TButton", takefocus=False,
                           command=lambda i=idx, r=row: self.load_image(i, r)).pack(side=tk.RIGHT)
                ttk.Label(line, textvariable=self.image_name_vars[(row, idx)], style="Value.TLabel",
                          anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=self.px(4))

        ttk.Label(body, text="CURRENT ROW", style="Group.TLabel").pack(anchor=tk.W)
        ttk.Label(body, textvariable=self.row_label_vars[CURRENT], style="Muted.TLabel").pack(anchor=tk.W)
        image_rows(CURRENT)

        self._subheading(body, "Reference row")
        ttk.Label(body, textvariable=self.row_label_vars[REFERENCE], style="Muted.TLabel").pack(anchor=tk.W)
        image_rows(REFERENCE)
        line = self._row(body, 4)
        ttk.Button(line, text="Load session...", takefocus=False,
                   command=self.open_reference_session).pack(side=tk.LEFT)
        ttk.Button(line, text="Remove", takefocus=False,
                   command=self.remove_reference_row).pack(side=tk.LEFT, padx=self.px(6))
        self._note(body, "The reference row shows an earlier inspection of the same filter, "
                         "with its markers, so you can see what a test changed.")

    # -- View ----------------------------------------------------------- #

    def _build_view_section(self, body):
        line = self._row(body)
        ttk.Radiobutton(line, text="Side by side", value="sidebyside", variable=self.mode_var,
                        command=self._on_mode_change, takefocus=False).pack(side=tk.LEFT)
        ttk.Radiobutton(line, text="Overlay", value="overlay", variable=self.mode_var,
                        command=self._on_mode_change, takefocus=False).pack(side=tk.LEFT, padx=self.px(12))
        self._slider(body, "Frontlit mix", self.opacity_var, 0.0, 1.0,
                     lambda _v: self._schedule_render(interactive=True))
        self._note(body, "In Overlay, slide the mix back and forth: features that jump are not aligned.")

    # -- Alignment ------------------------------------------------------ #

    def _build_alignment_section(self, body):
        line = self._row(body)
        ttk.Label(line, text="Row").pack(side=tk.LEFT)
        ttk.Radiobutton(line, text="Current", value=CURRENT, variable=self.control_row_var,
                        command=self._sync_controls, takefocus=False).pack(side=tk.LEFT, padx=self.px(10))
        self.control_row_reference = ttk.Radiobutton(
            line, text="Reference", value=REFERENCE, variable=self.control_row_var,
            command=self._sync_controls, takefocus=False)
        self.control_row_reference.pack(side=tk.LEFT)

        self._subheading(body, "Frontlit image onto backlit image")
        fields = self.align_fields
        line = self._row(body)
        self._number_field(line, "X", fields["off_x"], -99999, 99999, 1, self._on_alignment_fields, fmt="%.1f")
        self._number_field(line, "Y", fields["off_y"], -99999, 99999, 1, self._on_alignment_fields, fmt="%.1f")
        line = self._row(body)
        self._number_field(line, "Rotation", fields["rot"], -180, 180, 0.05, self._on_alignment_fields)
        self._number_field(line, "Scale", fields["scale"], 0.1, 10, 0.001, self._on_alignment_fields,
                           fmt="%.4f")
        line = self._row(body, 4)
        ttk.Button(line, text="Align by points...", takefocus=False,
                   command=lambda: self.set_tool("align")).pack(side=tk.LEFT)
        ttk.Button(line, text="Reset", takefocus=False,
                   command=self.reset_frontlit_alignment).pack(side=tk.LEFT, padx=self.px(6))

        self._subheading(body, "Both images (make the filter upright)")
        line = self._row(body)
        self._number_field(line, "Rotation", fields["glob_rot"], -360, 360, 0.05, self._on_alignment_fields)
        line = self._row(body, 4)
        ttk.Button(line, text="Level by drawing a line...", takefocus=False,
                   command=lambda: self.set_tool("level")).pack(side=tk.LEFT)
        ttk.Button(line, text="Reset", takefocus=False,
                   command=self.reset_global_rotation).pack(side=tk.LEFT, padx=self.px(6))

        self._subheading(body, "Reference row onto current row")
        self.row_align_frame = ttk.Frame(body)
        self.row_align_frame.pack(fill=tk.X)
        fields = self.row_fields
        line = self._row(self.row_align_frame)
        self._number_field(line, "X", fields["x"], -99999, 99999, 1, self._on_row_fields, fmt="%.1f")
        self._number_field(line, "Y", fields["y"], -99999, 99999, 1, self._on_row_fields, fmt="%.1f")
        line = self._row(self.row_align_frame)
        self._number_field(line, "Rotation", fields["rot"], -180, 180, 0.05, self._on_row_fields)
        self._number_field(line, "Scale", fields["scale"], 0.1, 10, 0.001, self._on_row_fields, fmt="%.4f")
        line = self._row(self.row_align_frame, 4)
        ttk.Button(line, text="Align rows by points...", takefocus=False,
                   command=lambda: self.set_tool("align_rows")).pack(side=tk.LEFT)
        ttk.Button(line, text="Reset", takefocus=False,
                   command=self.reset_row_alignment).pack(side=tk.LEFT, padx=self.px(6))
        self.row_align_note = self._note(body, "Load a reference row to use this.")

    # -- Annotations ---------------------------------------------------- #

    def _build_annotation_section(self, body):
        ttk.Label(body, text="MARKER COLOUR", style="Group.TLabel").pack(anchor=tk.W)
        grid = ttk.Frame(body)
        grid.pack(anchor=tk.W, pady=self.px(4))
        self.colour_swatches = {}
        size = self.px(26)
        for i, colour in enumerate(PRESET_COLOURS):
            swatch = tk.Frame(grid, width=size, height=size, bg=colour, highlightthickness=self.px(2),
                              highlightbackground=theme.PANEL, cursor="hand2")
            swatch.grid(row=i // 8, column=i % 8, padx=self.px(2), pady=self.px(2))
            swatch.bind("<Button-1>", lambda _e, c=colour: self.set_annotation_colour(c))
            self.colour_swatches[colour] = swatch
        line = self._row(body)
        self.current_colour_swatch = tk.Frame(line, width=size, height=size, bg=self.annot_colour,
                                              highlightthickness=self.px(2), highlightbackground="#ffffff")
        self.current_colour_swatch.pack(side=tk.LEFT)
        ttk.Label(line, text="in use").pack(side=tk.LEFT, padx=self.px(8))
        ttk.Button(line, text="Custom colour...", style="Small.TButton", takefocus=False,
                   command=self.pick_custom_colour).pack(side=tk.RIGHT)

        form = ttk.Frame(body)
        form.pack(fill=tk.X, pady=(self.px(6), 0))
        form.grid_columnconfigure(1, weight=1)
        ttk.Label(form, text="Legend name").grid(row=0, column=0, sticky="w", pady=self.px(2))
        name_entry = ttk.Entry(form, textvariable=self.legend_name_var)
        name_entry.grid(row=0, column=1, sticky="we", padx=(self.px(8), 0))
        ttk.Label(form, text="Label prefix").grid(row=1, column=0, sticky="w", pady=self.px(2))
        prefix_entry = ttk.Entry(form, textvariable=self.label_prefix_var, width=8)
        prefix_entry.grid(row=1, column=1, sticky="w", padx=(self.px(8), 0))
        for entry in (name_entry, prefix_entry):
            entry.bind("<Return>", lambda _e: (self._on_legend_fields_changed(), self.panes[0].canvas.focus_set()))
            entry.bind("<FocusOut>", lambda _e: self._on_legend_fields_changed())
        ttk.Checkbutton(body, text="Number new markers (T1, T2, ...)", variable=self.annot_autolabel_var,
                        command=self._refresh_hint, takefocus=False).pack(anchor=tk.W, pady=(self.px(4), 0))
        self._note(body, "The legend name and prefix belong to the colour in use.")

        line = self._row(body)
        ttk.Label(line, text="Radius (px)").pack(side=tk.LEFT)
        ttk.Spinbox(line, textvariable=self.annot_radius_var, from_=2, to=2000, increment=1,
                    width=7).pack(side=tk.LEFT, padx=self.px(8))
        redraw = lambda _v=None: self._draw_overlays()
        self._slider(body, "Line width", self.annot_width_var, 0.5, 6.0,
                     lambda v: (self.annot_width_var.set(round(float(v) * 2) / 2), redraw()))
        self._slider(body, "Label size", self.annot_label_size_var, 6, 48,
                     lambda v: (self.annot_label_size_var.set(int(round(float(v)))), redraw()))
        self._slider(body, "Legend size", self.canvas_legend_size_var, 6, 36,
                     lambda v: (self.canvas_legend_size_var.set(int(round(float(v)))), redraw()))

        line = self._row(body, 6)
        ttk.Button(line, text="Place markers", style="Accent.TButton", takefocus=False,
                   command=lambda: self.set_tool("annotate")).pack(side=tk.LEFT)
        ttk.Button(line, text="Clear all...", style="Danger.TButton", takefocus=False,
                   command=self.clear_annotations).pack(side=tk.RIGHT)
        self.copy_reference_button = ttk.Button(body, text="Copy markers from reference row...",
                                                takefocus=False, command=self.copy_reference_annotations)
        self.copy_reference_button.pack(anchor=tk.W)

    # -- Brightness / contrast / noise ---------------------------------- #

    def _build_adjust_section(self, body):
        line = self._row(body)
        ttk.Label(line, text="Image").pack(side=tk.LEFT)
        self.adjust_target_box = ttk.Combobox(line, textvariable=self.adjust_target_var, state="readonly",
                                              values=[name for name, _r, _i in ADJUST_TARGETS], takefocus=False)
        self.adjust_target_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(self.px(8), 0))
        self.adjust_target_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_controls())

        for key, label, low, high, _fmt in ADJUST_SLIDERS:
            self._slider(body, label, self.adjust_vars[key], low, high,
                         lambda _v, k=key: self._on_adjust_changed(k), readout=self.adjust_readouts[key])
        line = self._row(body, 4)
        ttk.Button(line, text="Reset", takefocus=False, command=self.reset_adjustments).pack(side=tk.LEFT)

        self._subheading(body, "Noise reduction")
        for key, label in (("amount", "Amount"), ("color", "Colour"), ("edge", "Edges")):
            self._slider(body, label, self.nr_vars[key], 0, 100,
                         lambda v, k=key: self._on_nr_changed(k, v))
        ttk.Checkbutton(body, text="Aggressive", variable=self.nr_aggressive_var, takefocus=False,
                        command=lambda: self._on_nr_changed(None, None)).pack(anchor=tk.W)
        line = self._row(body, 4)
        ttk.Button(line, text="Apply noise reduction", takefocus=False,
                   command=self._apply_nr_from_panel).pack(side=tk.LEFT)
        ttk.Button(line, text="Clear", takefocus=False,
                   command=self._clear_nr_from_panel).pack(side=tk.LEFT, padx=self.px(6))
        self._note(body, "Noise reduction is slow on full-size images and only changes the display; "
                         "the files on disk are never modified.")

    # -- Export --------------------------------------------------------- #

    def _build_export_section(self, body):
        line = self._row(body)
        ttk.Label(line, text="Padding (px)").pack(side=tk.LEFT)
        ttk.Spinbox(line, textvariable=self.crop_pad_var, from_=0, to=500, increment=5,
                    width=7).pack(side=tk.LEFT, padx=self.px(8))
        line = self._row(body, 4)
        ttk.Button(line, text="Crop a region...", takefocus=False,
                   command=lambda: self.set_tool("crop")).pack(side=tk.LEFT)
        ttk.Button(line, text="Export current view...", takefocus=False,
                   command=self.export_view).pack(side=tk.LEFT, padx=self.px(6))
        self._note(body, "Exports are saved at the full resolution of the backlit image, "
                         "with markers, legend and a date stamp.")

    # ------------------------------------------------------------------ #
    # Sidebar <-> state
    # ------------------------------------------------------------------ #

    def _control_row(self):
        """Which row the Alignment panel edits."""
        if self.control_row_var.get() == REFERENCE and self._reference_ready():
            return REFERENCE
        return CURRENT

    def _adjust_target(self):
        for name, row, idx in ADJUST_TARGETS:
            if name == self.adjust_target_var.get():
                return row, idx
        return CURRENT, BACKLIT

    def _sync_controls(self):
        """Push the current state into every sidebar control."""
        self._syncing = True
        try:
            reference_ready = self._reference_ready()
            if not reference_ready and self.control_row_var.get() == REFERENCE:
                self.control_row_var.set(CURRENT)
            self.control_row_reference.state(["!disabled"] if reference_ready else ["disabled"])

            for row in (CURRENT, REFERENCE):
                pair = self.pairs[row]
                self.row_label_vars[row].set(pair.label or ("not loaded" if row == REFERENCE else "untitled"))
                for idx in (BACKLIT, FRONTLIT):
                    path = pair.paths[idx]
                    self.image_name_vars[(row, idx)].set(os.path.basename(path) if path else "none")

            pair = self.pairs[self._control_row()]
            self.align_fields["off_x"].set(f"{pair.off_x:.1f}")
            self.align_fields["off_y"].set(f"{pair.off_y:.1f}")
            self.align_fields["rot"].set(f"{pair.rot:.2f}")
            self.align_fields["scale"].set(f"{pair.scale:.4f}")
            self.align_fields["glob_rot"].set(f"{pair.glob_rot:.2f}")
            self.row_fields["x"].set(f"{self.row_shift['x']:.1f}")
            self.row_fields["y"].set(f"{self.row_shift['y']:.1f}")
            self.row_fields["rot"].set(f"{self.row_shift['rot']:.2f}")
            self.row_fields["scale"].set(f"{self.row_shift['scale']:.4f}")
            self._set_children_state(self.row_align_frame, reference_ready)
            self.row_align_note.configure(
                text="Aligns the reference row to the current row, so the cursor marks the same spot "
                     "on the filter in both." if reference_ready else "Load a reference row to use this.")
            self.copy_reference_button.state(["!disabled"] if reference_ready else ["disabled"])

            current = self.pairs[CURRENT]
            self.legend_name_var.set(current.colour_labels.get(self.annot_colour, ""))
            self.label_prefix_var.set(current.prefix_for(self.annot_colour) or "")
            self.current_colour_swatch.configure(bg=self.annot_colour)
            for colour, swatch in self.colour_swatches.items():
                swatch.configure(highlightbackground="#ffffff" if colour == self.annot_colour else theme.PANEL)

            row, idx = self._adjust_target()
            target = self.pairs[row]
            for key, _label, _low, _high, fmt in ADJUST_SLIDERS:
                value = target.adjust[idx][key]
                self.adjust_vars[key].set(value)
                self.adjust_readouts[key].set(fmt.format(value))
            for key, var in self.nr_vars.items():
                var.set(target.nr[idx][key])
            self.nr_aggressive_var.set(target.nr[idx]["aggressive"])
        finally:
            self._syncing = False
        self._update_undo_buttons()
        self._refresh_hint()

    def _set_children_state(self, frame, enabled):
        for child in frame.winfo_children():
            if isinstance(child, (ttk.Frame, tk.Frame)):
                self._set_children_state(child, enabled)
            else:
                try:
                    child.state(["!disabled"] if enabled else ["disabled"])
                except (AttributeError, tk.TclError):
                    pass

    def _on_alignment_fields(self):
        if self._syncing:
            return
        pair = self.pairs[self._control_row()]
        try:
            off_x = float(self.align_fields["off_x"].get())
            off_y = float(self.align_fields["off_y"].get())
            rot = float(self.align_fields["rot"].get())
            scale = max(0.01, float(self.align_fields["scale"].get()))
            glob_rot = float(self.align_fields["glob_rot"].get())
        except ValueError:
            self._sync_controls()
            return
        shown = (round(pair.off_x, 1), round(pair.off_y, 1), round(pair.rot, 2), round(pair.scale, 4),
                 round(pair.glob_rot, 2))
        if (off_x, off_y, rot, scale, glob_rot) == shown:
            return
        self._checkpoint("Edit alignment", coalesce="align-fields")
        if (off_x, off_y, rot, scale) != shown[:4]:
            pair.off_x, pair.off_y, pair.rot, pair.scale = off_x, off_y, rot, scale
        if glob_rot != shown[4]:
            pair.set_global_rotation(glob_rot)
        self._sync_controls()
        self._schedule_render(interactive=True)

    def _on_row_fields(self):
        if self._syncing:
            return
        try:
            new = {
                "x": float(self.row_fields["x"].get()),
                "y": float(self.row_fields["y"].get()),
                "rot": float(self.row_fields["rot"].get()),
                "scale": max(0.01, float(self.row_fields["scale"].get())),
            }
        except ValueError:
            self._sync_controls()
            return
        shift = self.row_shift
        shown = {"x": round(shift["x"], 1), "y": round(shift["y"], 1), "rot": round(shift["rot"], 2),
                 "scale": round(shift["scale"], 4)}
        if new == shown:
            return
        self._checkpoint("Edit row alignment", coalesce="row-fields")
        self.row_shift = new
        self._sync_controls()
        self._schedule_render(interactive=True)

    def _on_adjust_changed(self, key):
        if self._syncing:
            return
        row, idx = self._adjust_target()
        value = float(self.adjust_vars[key].get())
        fmt = next(f for k, _l, _lo, _hi, f in ADJUST_SLIDERS if k == key)
        self.adjust_readouts[key].set(fmt.format(value))
        self._checkpoint("Adjust image", coalesce=f"adjust-{row}-{idx}-{key}")
        self.pairs[row].adjust[idx][key] = value
        self._schedule_render(interactive=True)

    def reset_adjustments(self):
        row, idx = self._adjust_target()
        self._checkpoint("Reset image adjustments")
        self.pairs[row].apply_adjust_records(
            [None if i == idx else dict(a) for i, a in enumerate(self.pairs[row].adjust)])
        self._sync_controls()
        self._schedule_render()

    def _on_nr_changed(self, key, value):
        if self._syncing:
            return
        row, idx = self._adjust_target()
        if key is not None:
            # Snap to steps of 10, as the processing presets are tuned for those.
            self.nr_vars[key].set(int(round(float(value) / 10.0)) * 10)
        settings = self.pairs[row].nr[idx]
        for name, var in self.nr_vars.items():
            settings[name] = int(var.get())
        settings["aggressive"] = bool(self.nr_aggressive_var.get())

    def _apply_nr_from_panel(self):
        row, idx = self._adjust_target()
        self.apply_noise_reduction(idx, row)

    def _clear_nr_from_panel(self):
        row, idx = self._adjust_target()
        self.clear_noise_reduction(idx, row)

    # ------------------------------------------------------------------ #
    # Keys and small helpers
    # ------------------------------------------------------------------ #

    def _bind_keys(self):
        root = self.root
        root.bind("<Key>", self._on_key)
        root.bind("<Control-s>", lambda _e: self.save_session())
        root.bind("<Control-S>", lambda _e: self.save_session_as())
        root.bind("<Control-o>", lambda _e: self.open_session())
        root.bind("<Control-n>", lambda _e: self.new_session())
        root.bind("<Control-z>", lambda _e: None if self._typing() else self.undo())
        root.bind("<Control-y>", lambda _e: None if self._typing() else self.redo())
        root.bind("<Control-Z>", lambda _e: None if self._typing() else self.redo())
        root.bind("<F1>", lambda _e: show_guide(self))

    def _centre_dialog(self, dialog):
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 3)
        dialog.geometry(f"+{x}+{y}")
