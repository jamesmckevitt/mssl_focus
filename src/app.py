import tkinter as tk

from .annotations import AnnotationMixin
from .crop import CropMixin
from .metadata import APP_AUTHOR, APP_EMAIL, APP_INSTITUTION, APP_VERSION
from .session import SessionMixin
from .ui import UIBuilderMixin
from .viewer import ViewerMixin


__author__ = APP_AUTHOR
__institution__ = APP_INSTITUTION
__email__ = APP_EMAIL


class ImageComparer(CropMixin, SessionMixin, AnnotationMixin, ViewerMixin, UIBuilderMixin):
    def __init__(self, root):
        self.root = root
        self.root.title("MSSL thin-film filter inspector")
        self.root.geometry("1400x900")
        self.root.configure(bg="#2b2b2b")
        self._set_app_icon()

        self.images = [None, None]
        self.image_paths = [None, None]
        self.preview_images = [None, None]
        self.preview_scales = [1.0, 1.0]
        self.photos = [None, None]

        self.compare_row_images = [None, None]
        self.compare_row_image_paths = [None, None]
        self.compare_row_preview_images = [None, None]
        self.compare_row_preview_scales = [1.0, 1.0]
        self.compare_row_photos = [None, None]

        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.offset_x = 0
        self.offset_y = 0
        self.rotation = 0.0
        self.opacity = 0.5
        self.cursor_pos = (0, 0)
        self.last_pan = (0, 0)
        self._render_pending = False
        self._interacting = False
        self._quality_timer = None
        self._rotated_cache = [None, None]
        self._last_rot = [None, None]
        self._rotated_preview_cache = [None, None]
        self._last_rot_preview = [None, None]
        self._compare_row_rotated_cache = [None, None]
        self._compare_row_last_rot = [None, None]
        self._compare_row_rotated_preview_cache = [None, None]
        self._compare_row_last_rot_preview = [None, None]

        self.annotations = []
        self.annot_colour = "#ff0000"
        self.colour_labels = {}

        self._level_start = None
        self._align_pts_img1 = []
        self._align_pts_img2 = []
        self._compare_row_align_pts_img1 = []
        self._compare_row_align_pts_img2 = []
        self._row_align_pts_top = []
        self._row_align_pts_bottom = []
        self._align_guide_cursor = None
        self._compare_row_align_guide_cursor = None
        self._crop_corner1 = None
        self._annotation_import = None
        self._drag_annotation_index = None
        self._nr_progress_dialog = None

        self.annot_label_size_var = tk.IntVar(value=16)
        self.canvas_legend_size_var = tk.IntVar(value=13)

        self._base_images = [None, None]
        self._compare_row_base_images = [None, None]
        self.nr_amount_vars = [tk.IntVar(value=0), tk.IntVar(value=0)]
        self.nr_aggressive_vars = [tk.BooleanVar(value=False), tk.BooleanVar(value=False)]
        self.nr_color_vars = [tk.IntVar(value=50), tk.IntVar(value=50)]
        self.nr_edge_vars = [tk.IntVar(value=100), tk.IntVar(value=100)]
        self.compare_row_nr_amount_vars = [tk.IntVar(value=0), tk.IntVar(value=0)]
        self.compare_row_nr_aggressive_vars = [tk.BooleanVar(value=False), tk.BooleanVar(value=False)]
        self.compare_row_nr_color_vars = [tk.IntVar(value=50), tk.IntVar(value=50)]
        self.compare_row_nr_edge_vars = [tk.IntVar(value=100), tk.IntVar(value=100)]

        self.adj_vars = [
            {
                "brightness": tk.DoubleVar(value=1.0),
                "contrast": tk.DoubleVar(value=1.0),
                "blacks": tk.DoubleVar(value=0.0),
                "whites": tk.DoubleVar(value=255.0),
            },
            {
                "brightness": tk.DoubleVar(value=1.0),
                "contrast": tk.DoubleVar(value=1.0),
                "blacks": tk.DoubleVar(value=0.0),
                "whites": tk.DoubleVar(value=255.0),
            },
        ]

        self.compare_row_adj_vars = [
            {
                "brightness": tk.DoubleVar(value=1.0),
                "contrast": tk.DoubleVar(value=1.0),
                "blacks": tk.DoubleVar(value=0.0),
                "whites": tk.DoubleVar(value=255.0),
            },
            {
                "brightness": tk.DoubleVar(value=1.0),
                "contrast": tk.DoubleVar(value=1.0),
                "blacks": tk.DoubleVar(value=0.0),
                "whites": tk.DoubleVar(value=255.0),
            },
        ]

        self.show_compare_row_var = tk.BooleanVar(value=False)
        self.compare_row_off_x_var = tk.StringVar(value="0")
        self.compare_row_off_y_var = tk.StringVar(value="0")
        self.compare_row_rot_var = tk.StringVar(value="0.0")
        self.compare_row_img2_scale_var = tk.StringVar(value="1.000")
        self.compare_row_glob_rot_var = tk.StringVar(value="0.0")
        self.compare_row_shift_x_var = tk.StringVar(value="0")
        self.compare_row_shift_y_var = tk.StringVar(value="0")
        self.compare_row_shift_rot_var = tk.StringVar(value="0.0")
        self.compare_row_shift_scale_var = tk.StringVar(value="1.000")
        self.compare_row_align_mode_var = tk.BooleanVar(value=False)
        self.compare_row_align_scale_mode_var = tk.BooleanVar(value=False)
        self.row_align_mode_var = tk.BooleanVar(value=False)
        self.row_align_scale_mode_var = tk.BooleanVar(value=False)

        self._build_ui()


__all__ = ["APP_VERSION", "ImageComparer", "__author__", "__email__", "__institution__"]