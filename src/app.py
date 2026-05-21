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

        self.annotations = []
        self.annot_colour = "#ff0000"
        self.colour_labels = {}

        self._level_start = None
        self._align_pts_img1 = []
        self._align_pts_img2 = []
        self._align_guide_cursor = None
        self._crop_corner1 = None
        self._annotation_import = None
        self._drag_annotation_index = None

        self.annot_label_size_var = tk.IntVar(value=16)
        self.canvas_legend_size_var = tk.IntVar(value=13)

        self._base_images = [None, None]
        self.nr_amount_vars = [tk.IntVar(value=0), tk.IntVar(value=0)]

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

        self._build_ui()


__all__ = ["APP_VERSION", "ImageComparer", "__author__", "__email__", "__institution__"]