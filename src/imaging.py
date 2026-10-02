"""Image loading, display rendering, tone adjustment and noise reduction."""

import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import geometry as geo
from .camera import RAW_EXTENSIONS, read_camera_info

# Inspection images are large on purpose.
Image.MAX_IMAGE_PIXELS = None

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


def is_raw(path):
    return bool(path) and os.path.splitext(path)[1].lower() in RAW_EXTENSIONS


# --------------------------------------------------------------------------- #
# Camera RAW development
# --------------------------------------------------------------------------- #

RAW_DEVELOP_DEFAULTS = {"exposure": 0.0, "noise": "standard"}

# name: (colour-noise blur sigma, brightness-noise blur sigma, black point in noise sigmas)
RAW_NOISE_LEVELS = {
    "off": (0.0, 0.0, 0.0),
    "light": (1.5, 0.0, 2.0),
    "standard": (2.5, 0.0, 3.0),
    "strong": (3.0, 0.8, 4.0),
}

# A frame counts as dark-field (backlit through an opaque filter) when its
# typical pixel is this close to black, as a fraction of full scale.
DARK_FIELD_MEDIAN = 0.03


def _srgb_curve(linear):
    linear = np.clip(linear, 0.0, 1.0, out=linear)
    low = linear <= 0.0031308
    out = np.empty_like(linear)
    out[low] = linear[low] * 12.92
    np.power(linear, 1.0 / 2.4, out=linear)
    out[~low] = 1.055 * linear[~low] - 0.055
    return out


def develop_raw(path, dark_field=False, exposure=0.0, noise="standard"):
    """Develop a camera RAW file into an 8-bit RGB image.

    The frame is cropped to the camera's own image area, so it matches the
    pixel grid of files converted with the manufacturer's software.

    ``dark_field`` asks for the treatment suited to backlit frames, where a
    few bright points sit on an otherwise black, noisy background: the black
    point is set just above the measured noise floor and the remaining range
    is stretched so those points are clearly visible.  It only takes effect
    if the frame really is dark.  ``exposure`` is an extra brightening in
    stops on top of that.
    """
    import cv2
    import rawpy

    chroma_sigma, luma_sigma, black_sigmas = RAW_NOISE_LEVELS.get(noise, RAW_NOISE_LEVELS["standard"])
    with rawpy.imread(path) as raw:
        linear = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16, gamma=(1, 1))
        sizes = raw.sizes
        left = int(getattr(sizes, "crop_left_margin", 0) or 0)
        top = int(getattr(sizes, "crop_top_margin", 0) or 0)
        crop_w = int(getattr(sizes, "crop_width", 0) or 0)
        crop_h = int(getattr(sizes, "crop_height", 0) or 0)
        flip = int(getattr(sizes, "flip", 0) or 0)
    margins = (0, 0)
    if flip == 0 and 0 < crop_w and 0 < crop_h and left + crop_w <= linear.shape[1] and top + crop_h <= linear.shape[0]:
        linear = linear[top:top + crop_h, left:left + crop_w]
        margins = (left, top)

    linear = linear.astype(np.float32)
    linear /= 65535.0
    luma = linear @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    sample = luma[::3, ::3]
    median = float(np.median(sample))
    sigma = float(np.median(np.abs(sample - median)) * 1.4826)
    is_dark = dark_field and median < DARK_FIELD_MEDIAN

    if chroma_sigma > 0:
        # Colour speckle is the most visible noise and carries no detail worth keeping.
        chroma = linear - luma[:, :, None]
        smooth = cv2.GaussianBlur(chroma, (0, 0), chroma_sigma if is_dark else chroma_sigma * 0.5)
        if is_dark:
            # Keep the true colour of anything standing clearly above the noise.
            keep = np.clip((luma - (median + 3.0 * sigma)) / max(6.0 * sigma, 1e-6), 0.0, 1.0)
            chroma -= smooth
            chroma *= keep[:, :, None]
            smooth += chroma
        if luma_sigma > 0:
            luma = cv2.GaussianBlur(luma, (0, 0), luma_sigma)
        linear = smooth
        linear += luma[:, :, None]
    elif luma_sigma > 0:
        linear = cv2.GaussianBlur(linear, (0, 0), luma_sigma)

    black = 0.0
    gain = 1.0
    if is_dark:
        black = median + black_sigmas * sigma
        # Stretch so genuine features are bright; the very brightest 0.01% may clip.
        peak = float(np.percentile(sample, 99.99)) - black
        gain = float(np.clip(1.6 / max(peak, 1e-6), 1.0, 64.0))
    gain *= 2.0 ** float(exposure)

    linear -= black
    linear *= gain
    out = _srgb_curve(linear)
    out *= 255.0
    out += 0.5
    image = Image.fromarray(out.astype(np.uint8))
    image.info["raw_crop_margins"] = margins
    return image


def open_image(path, develop=None, dark_field=False):
    """Open a standard or camera RAW image as a fully loaded 8-bit PIL image.

    ``develop`` holds the RAW development settings (see ``RAW_DEVELOP_DEFAULTS``);
    it is ignored for ordinary image files.  The camera's exposure settings, where
    the file records them, are returned in ``image.info["camera"]``.
    """
    image = _open_pixels(path, develop, dark_field)
    image.info["camera"] = read_camera_info(path)
    return image


def _open_pixels(path, develop, dark_field):
    if is_raw(path):
        settings = dict(RAW_DEVELOP_DEFAULTS)
        settings.update(develop or {})
        return develop_raw(path, dark_field=dark_field, exposure=settings["exposure"],
                           noise=settings["noise"])

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
        # While the view is moving, speed matters more than smoothness; the
        # pre-averaged level already keeps small bright spots from dropping out.
        resample = Image.Resampling.BICUBIC if quality else Image.Resampling.NEAREST
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
        # Not clipped again after brightening: lowering contrast must be able to
        # bring over-bright values back, or blown highlights would turn grey.
        return np.clip(out, 0, 255) * brightness

    x = curve(np.arange(256, dtype=np.float32))
    pivot = float(curve(np.array([mean], dtype=np.float32))[0])
    x = np.clip(pivot + (x - pivot) * contrast, 0, 255)
    return np.round(x).astype(np.uint8).tolist()


def match_tone(target, source, pivot):
    """Brightness and contrast that make one image look like another.

    ``target`` is the luminance (0-255) of the image to adjust, after its own
    blacks/whites levels but before brightness and contrast.  ``source`` is the
    luminance of the image to imitate, as displayed.  ``pivot`` is the level
    the target's contrast turns about (its mean after levels).

    Returns ``(brightness, contrast)``; contrast is ``None`` when the images are
    too dark for it to be estimated, in which case only brightness is matched,
    and both are ``None`` if an image holds nothing bright to compare.
    """
    target = np.asarray(target, dtype=np.float32).ravel()
    source = np.asarray(source, dtype=np.float32).ravel()

    def clamp(value):
        return float(min(3.0, max(0.1, value)))

    # Compare the two brightness distributions point by point, leaving out
    # values that are clipped to black or white in either image: those carry
    # no information about how much brighter one image is than the other.
    points = np.concatenate([np.linspace(2.0, 98.0, 49), [98.5, 99.0, 99.5, 99.8, 99.95]])
    t_points = np.percentile(target, points)
    s_points = np.percentile(source, points)
    usable = (t_points > 4.0) & (s_points > 4.0) & (t_points < 250.0) & (s_points < 250.0)
    t_mid, s_mid = float(np.median(target)), float(np.median(source))

    mostly_black = min(t_mid, s_mid, pivot) < 12.0
    if not mostly_black and usable.sum() >= 5 and np.ptp(t_points[usable]) >= 8.0:
        # Displayed value = b*pivot + c*b*(value - pivot): a straight line in the value.
        x, y = t_points[usable], s_points[usable]
        # Where both images have blown-out (or fully black) areas, those must stay
        # white (or black) rather than turn grey, so the line is pinned there.
        pinned = [level for level, clipped in ((255.0, lambda v: v >= 250.0), (0.0, lambda v: v <= 2.0))
                  if clipped(target).mean() >= 0.01 and clipped(source).mean() >= 0.01]
        if len(pinned) == 2:
            slope, intercept = 1.0, 0.0
        elif pinned:
            anchor = pinned[0]
            slope = float(((x - anchor) * (y - anchor)).sum() / ((x - anchor) ** 2).sum())
            intercept = anchor - slope * anchor
        else:
            slope, intercept = np.polyfit(x, y, 1)
        if slope > 0:
            brightness = clamp(intercept / pivot + slope)
            return brightness, clamp(slope / brightness)

    # Dark-field frames: nearly everything is black, so compare how far the
    # bright tail rises above each image's own background.
    tail = points >= 90.0
    t_tail = t_points[tail] - t_mid
    s_tail = s_points[tail] - s_mid
    usable_tail = usable[tail] & (t_tail > 4.0) & (s_tail > 4.0)
    if usable_tail.sum() >= 3:
        gain = float((s_tail[usable_tail] * t_tail[usable_tail]).sum() / (t_tail[usable_tail] ** 2).sum())
        return clamp(gain), None
    # Too few bright pixels for that: fall back to the brightest ones.
    for point in (99.9, 100.0):
        t_peak = float(np.percentile(target, point)) - t_mid
        s_peak = float(np.percentile(source, point)) - s_mid
        if t_peak > 4.0 and s_peak > 4.0:
            return clamp(s_peak / t_peak), None
    return None, None   # nothing bright in one of them: no basis for a match


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
