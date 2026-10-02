"""Image loading, display rendering, tone adjustment and noise reduction."""

import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import geometry as geo

# Inspection images are large on purpose.
Image.MAX_IMAGE_PIXELS = None

RAW_EXTENSIONS = {'.arw', '.nef', '.cr2', '.cr3', '.orf', '.rw2', '.dng', '.raf', '.pef', '.srw'}

IMAGE_FILETYPES = [
    ("Image files",
     "*.tif *.tiff *.TIF *.TIFF *.png *.PNG "
     "*.jpg *.JPG *.jpeg *.JPEG *.bmp *.BMP *.webp *.WEBP "
     "*.arw *.ARW *.nef *.NEF *.cr2 *.CR2 *.cr3 *.CR3 "
     "*.dng *.DNG *.orf *.ORF *.rw2 *.RW2 *.raf *.RAF"),
    ("All files", "*.*"),
]

# Neutral so it does not bias the eye when judging faint features.
CANVAS_BACKGROUND = (24, 24, 24)


def open_image(path):
    """Open a standard or camera RAW image as a fully loaded 8-bit PIL image."""
    if os.path.splitext(path)[1].lower() in RAW_EXTENSIONS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True)
        return Image.fromarray(rgb)

    with Image.open(path) as handle:
        handle.load()
        img = handle.copy()
    if img.mode in ("I;16", "I;16L", "I;16B", "I"):
        # Pillow clips rather than rescales when converting these to 8-bit.
        arr = np.asarray(img).astype(np.float32)
        peak = float(arr.max()) if arr.size else 0.0
        divisor = 256.0 if peak > 255.0 else 1.0
        return Image.fromarray(np.clip(arr / divisor, 0, 255).astype(np.uint8))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


class Pyramid:
    """An image plus pre-averaged half-size copies, for alias-free zoomed-out views."""

    MIN_LEVEL_SIZE = 600

    def __init__(self, image):
        self.levels = [image]
        while max(self.levels[-1].size) > self.MIN_LEVEL_SIZE * 2 and len(self.levels) < 6:
            self.levels.append(self.levels[-1].reduce(2))
        smallest = self.levels[-1]
        grey = smallest if smallest.mode == "L" else smallest.convert("L")
        self.mean = float(np.asarray(grey).mean())

    @property
    def image(self):
        return self.levels[0]

    @property
    def size(self):
        return self.levels[0].size

    def corners(self, matrix):
        w, h = self.size
        return geo.apply_many(matrix, [(0, 0), (w, 0), (w, h), (0, h)])

    def render(self, matrix, size, quality=True, lut=None):
        """Draw the image into an RGB frame of ``size`` pixels.

        ``matrix`` maps full-resolution image pixels to frame pixels.
        """
        width, height = max(1, int(size[0])), max(1, int(size[1]))
        scale = geo.scale_of(matrix)
        level_index = 0
        if scale < 1.0:
            level_index = min(len(self.levels) - 1, int(math.floor(math.log2(1.0 / scale) + 1e-9)))
        level = self.levels[level_index]
        level_matrix = matrix @ geo.scaling(2 ** level_index)
        inv = geo.invert(level_matrix)
        coefficients = (inv[0, 0], inv[0, 1], inv[0, 2], inv[1, 0], inv[1, 1], inv[1, 2])
        resample = Image.Resampling.BICUBIC if quality else Image.Resampling.BILINEAR
        fill = CANVAS_BACKGROUND[0] if level.mode == "L" else CANVAS_BACKGROUND
        frame = level.transform(
            (width, height), Image.Transform.AFFINE, coefficients,
            resample=resample, fillcolor=fill,
        )
        if lut is not None:
            frame = frame.point(lut if frame.mode == "L" else lut * 3)
        if frame.mode != "RGB":
            frame = frame.convert("RGB")
        if lut is not None:
            # The tone curve also hit the empty surround; put the background back.
            quad = [tuple(p) for p in self.corners(matrix)]
            if not _quad_covers(quad, width, height):
                mask = Image.new("L", (width, height), 0)
                ImageDraw.Draw(mask).polygon(quad, fill=255)
                frame = Image.composite(frame, Image.new("RGB", (width, height), CANVAS_BACKGROUND), mask)
        return frame


def _quad_covers(quad, width, height):
    """True if the convex quad contains the whole (0, 0)-(width, height) frame."""
    corners = [(0, 0), (width, 0), (width, height), (0, height)]
    sign = 0
    for i in range(4):
        x0, y0 = quad[i]
        x1, y1 = quad[(i + 1) % 4]
        for px, py in corners:
            cross = (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0)
            if abs(cross) < 1e-9:
                continue
            side = 1 if cross > 0 else -1
            if sign == 0:
                sign = side
            elif side != sign:
                return False
    return True


def blank_frame(size):
    return Image.new("RGB", (max(1, int(size[0])), max(1, int(size[1]))), CANVAS_BACKGROUND)


def build_lut(brightness, contrast, blacks, whites, mean):
    """256-entry tone curve: levels, then brightness, then contrast.

    Contrast pivots on the whole image's mean so the look does not change as
    the view is panned.  Returns ``None`` when the settings are neutral.
    """
    if (blacks == 0.0 and whites == 255.0
            and abs(brightness - 1.0) < 1e-3 and abs(contrast - 1.0) < 1e-3):
        return None

    def curve(values):
        out = (values - blacks) * (255.0 / max(whites - blacks, 1.0))
        out = np.clip(out, 0, 255)
        return np.clip(out * brightness, 0, 255)

    x = curve(np.arange(256, dtype=np.float32))
    pivot = float(curve(np.array([mean], dtype=np.float32))[0])
    x = np.clip(pivot + (x - pivot) * contrast, 0, 255)
    return np.round(x).astype(np.uint8).tolist()


# --------------------------------------------------------------------------- #
# Noise reduction
# --------------------------------------------------------------------------- #

def _denoise_gray_nlm(cv2, gray, amount, aggressive):
    frac = max(0.0, min(1.0, float(amount) / 100.0))
    h = frac * (34.0 if aggressive else 24.0)
    search = 21 if aggressive else (17 if frac >= 0.6 else 13)
    denoised = cv2.fastNlMeansDenoising(gray, None, h, 7, search)
    if aggressive and frac >= 0.65:
        second_h = max(6.0, h * 0.8)
        denoised = cv2.fastNlMeansDenoising(denoised, None, second_h, 7, 21)
    return denoised


def _edge_blend_gray(cv2, original_gray, denoised_gray, edge_amount):
    edge_frac = max(0.0, min(1.0, float(edge_amount) / 100.0))
    original = original_gray.astype(np.float32)
    denoised = denoised_gray.astype(np.float32)
    gx = cv2.Sobel(original, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(original, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    scale = float(np.percentile(mag, 95)) if mag.size else 0.0
    edge_mask = np.clip(mag / max(scale, 1e-6), 0.0, 1.0)
    denoise_weight = 1.0 - edge_mask * (1.0 - edge_frac)
    blended = original * (1.0 - denoise_weight) + denoised * denoise_weight
    return np.clip(blended, 0, 255).astype(np.uint8)


def _denoise_color_nlm(cv2, rgb, amount, color_amount, edge_amount, aggressive):
    frac = max(0.0, min(1.0, float(amount) / 100.0))
    color_frac = max(0.0, min(1.0, float(color_amount) / 100.0))
    h = frac * (34.0 if aggressive else 24.0)
    h_color = h * 1.6 * color_frac
    search = 21 if aggressive else (17 if frac >= 0.6 else 13)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    denoised = cv2.fastNlMeansDenoisingColored(bgr, None, h, h_color, 7, search)
    if aggressive and frac >= 0.65:
        second_h = max(6.0, h * 0.8)
        denoised = cv2.fastNlMeansDenoisingColored(
            denoised, None, second_h, second_h * 1.6 * color_frac, 7, 21
        )
    denoised_rgb = cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB)
    original_ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    denoised_ycc = cv2.cvtColor(denoised_rgb, cv2.COLOR_RGB2YCrCb)
    denoised_ycc[:, :, 0] = _edge_blend_gray(
        cv2,
        original_ycc[:, :, 0],
        denoised_ycc[:, :, 0],
        edge_amount,
    )
    return cv2.cvtColor(denoised_ycc, cv2.COLOR_YCrCb2RGB)


def _denoise_blur_fallback(base, amount, color_amount, edge_amount, aggressive):
    edge_frac = max(0.0, min(1.0, float(edge_amount) / 100.0))
    color_frac = max(0.0, min(1.0, float(color_amount) / 100.0))
    luma_r = amount / 100.0 * (2.0 + edge_frac * (3.0 if aggressive else 2.0))
    chroma_r = amount / 100.0 * ((3.0 if aggressive else 2.0) + color_frac * (9.0 if aggressive else 6.0))
    if base.mode == "L":
        img = base.filter(ImageFilter.GaussianBlur(radius=luma_r))
        if aggressive and amount >= 65:
            img = img.filter(ImageFilter.GaussianBlur(radius=max(1.0, luma_r * 0.8)))
        return img
    y, cb, cr = base.convert("YCbCr").split()
    y = y.filter(ImageFilter.GaussianBlur(radius=luma_r))
    cb = cb.filter(ImageFilter.GaussianBlur(radius=chroma_r))
    cr = cr.filter(ImageFilter.GaussianBlur(radius=chroma_r))
    if aggressive and amount >= 65:
        y = y.filter(ImageFilter.GaussianBlur(radius=max(1.0, luma_r * 0.8)))
        cb = cb.filter(ImageFilter.GaussianBlur(radius=max(1.5, chroma_r * 0.8)))
        cr = cr.filter(ImageFilter.GaussianBlur(radius=max(1.5, chroma_r * 0.8)))
    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def denoise(base, amount, color_amount, edge_amount, aggressive):
    """Non-local-means noise reduction (OpenCV), with a blur fallback."""
    try:
        import cv2
    except ImportError:
        return _denoise_blur_fallback(base, amount, color_amount, edge_amount, aggressive)
    if base.mode == "L":
        gray = np.array(base)
        denoised = _denoise_gray_nlm(cv2, gray, amount, aggressive)
        return Image.fromarray(_edge_blend_gray(cv2, gray, denoised, edge_amount))
    rgb = np.array(base.convert("RGB"))
    return Image.fromarray(_denoise_color_nlm(cv2, rgb, amount, color_amount, edge_amount, aggressive))
