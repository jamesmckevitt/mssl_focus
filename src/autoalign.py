"""Automatic alignment of an inspection from its photographs alone.

Three things are worked out, all from the filter's frame rather than from any
pinholes, so that they work on a filter never seen before:

* where the frontlit photograph sits on the backlit one (``register_frontlit``),
* how far the filter is tilted, so it can be turned upright, and
* the outline of the membrane: the rounded-rectangle opening in the frame
  (``find_aperture``).

The opening is easiest to see in the frontlit photograph, where the membrane
and the frame differ strongly (which is the darker depends on the lighting, so
either way round is accepted).  The backlit photograph is used if there is no
frontlit one, or if the frame cannot be found in it.

Angles follow ``geometry.py``: positive turns content clockwise on screen.  A
filter whose edges run ``tilt`` degrees clockwise of the image axes is made
upright by a global rotation of ``-tilt``.
"""

import math

import numpy as np

from . import geometry as geo

WORK_SIDE = 1200          # long side of the reduced image the coarse search runs on
BAND = (0.35, 0.65)       # middle part of the image that the opening is assumed to span
MIN_SIDE = 0.2            # the opening is at least this fraction of the image's short side
ASPECT = (0.6, 1.6)       # plausible width / height of the opening
STRONG_SIGMAS = 10.0      # every side of the opening is at least this many noise levels strong ...
STRONG_FRACTION = 0.2     # ... and this fraction as strong as the strongest rectangle in the image
SUPPORT_SIGMAS = 4.0      # a point on a side counts as edge above this many noise levels
MIN_SUPPORT = 0.7         # and at least this fraction of each side must be edge
CORNER_FRACTION = 0.15    # each end of a side left out when fitting it, for the rounded corners
SIZE_TOLERANCE = 0.06     # a known opening is looked for within this fraction of its size
# The opening sits centred in the frame plate, each side of it this fraction of
# the plate's (0.81-0.82 on every filter photographed so far).  When the plate's
# outside edge is found, the opening is looked for there first.
OPENING_IN_PLATE = (0.75, 0.90)
CENTRED = 0.03            # off-centre allowed, as a fraction of the plate's size
MOVED_GAIN = 0.03         # the frontlit photograph is taken to have moved only if that fits
MOVED_RATIO = 0.2         # the edges better by this much (absolute, and relative to not moving)


class AlignmentError(RuntimeError):
    """The frame could not be found well enough to align on."""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _grey(image):
    """Brightness of a PIL image or array as float32, kept dark-aware: the square
    root lifts a dark backlit frame enough for its edges to count."""
    arr = np.asarray(image)
    grey = arr.mean(axis=2) if arr.ndim == 3 else arr
    return np.sqrt(grey.astype(np.float32) * 255.0)


def _reduce(grey, side):
    import cv2
    height, width = grey.shape
    factor = max(1.0, max(width, height) / float(side))
    if factor == 1.0:
        return grey.copy(), 1.0
    size = (max(1, int(round(width / factor))), max(1, int(round(height / factor))))
    return cv2.resize(grey, size, interpolation=cv2.INTER_AREA), factor


def _gradients(grey, sigma):
    import cv2
    blur = cv2.GaussianBlur(grey, (0, 0), sigma)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    return gx, gy


def _warp(grey, matrix, size):
    import cv2
    return cv2.warpAffine(grey, np.asarray(matrix, dtype=np.float64)[:2], size,
                          flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def estimate_tilt(grey, limit=15.0):
    """The dominant direction of straight edges, folded to (-45, 45] degrees.

    Gradient directions are averaged with their angle multiplied by four, so
    horizontal and vertical edges agree and round things (screws, reflections
    of the camera lens) cancel out.
    """
    gx, gy = _gradients(grey, 1.5)
    magnitude = np.hypot(gx, gy)
    strong = magnitude > np.percentile(magnitude, 95)
    if not strong.any():
        return 0.0
    theta = np.arctan2(gy[strong], gx[strong])
    weight = magnitude[strong]
    tilt = math.degrees(math.atan2(float((weight * np.sin(4 * theta)).sum()),
                                   float((weight * np.cos(4 * theta)).sum()))) / 4.0
    return tilt if abs(tilt) <= limit else 0.0


def _peaks(profile, lo, hi, count, spacing):
    """Indices of the strongest local maxima of ``|profile|`` in ``[lo, hi)``."""
    values = np.abs(profile)
    order = np.argsort(values[lo:hi])[::-1] + lo
    chosen = []
    for index in order:
        if values[index] <= 0:
            break
        if all(abs(index - other) >= spacing for other in chosen):
            chosen.append(int(index))
            if len(chosen) == count:
                break
    return chosen


# --------------------------------------------------------------------------- #
# The opening in the frame
# --------------------------------------------------------------------------- #

class Aperture:
    """A rounded rectangle: centre, size, tilt and corner radius, in the pixel
    space of the image it was found in."""

    def __init__(self, cx, cy, width, height, tilt, radius, score=0.0, polarity=1):
        self.cx, self.cy = float(cx), float(cy)
        self.width, self.height = float(width), float(height)
        self.tilt = float(tilt)
        self.radius = float(radius)
        self.score = float(score)
        self.polarity = int(polarity)      # +1: membrane darker than the frame around it

    def upright(self):
        """Matrix taking image pixels to a frame where the opening is upright about its centre."""
        return geo.about((self.cx, self.cy), 1.0, -self.tilt)

    def points(self, steps=10):
        """The outline, in image pixels."""
        half_w, half_h = self.width / 2.0, self.height / 2.0
        shape = geo.rounded_rectangle(self.cx - half_w, self.cy - half_h, self.cx + half_w,
                                      self.cy + half_h, self.radius, steps)
        return [tuple(map(float, p)) for p in geo.apply_many(geo.invert(self.upright()), shape)]

    def transformed(self, matrix):
        """The same opening seen through a similarity ``matrix`` (image -> other image)."""
        cx, cy = geo.apply(matrix, self.cx, self.cy)
        scale = geo.scale_of(matrix)
        return Aperture(cx, cy, self.width * scale, self.height * scale,
                        geo.wrap_angle(self.tilt + geo.angle_of(matrix)), self.radius * scale,
                        self.score, self.polarity)

    def as_record(self):
        return {"cx": round(self.cx, 2), "cy": round(self.cy, 2), "width": round(self.width, 2),
                "height": round(self.height, 2), "tilt": round(self.tilt, 4),
                "radius": round(self.radius, 1), "score": round(self.score, 3)}

    def __repr__(self):
        return (f"Aperture(centre=({self.cx:.1f}, {self.cy:.1f}), size={self.width:.1f}x{self.height:.1f}, "
                f"tilt={self.tilt:.3f}, radius={self.radius:.0f}, score={self.score:.2f})")


def _rectangle_candidates(grey):
    """Rectangles in an upright, reduced image whose four sides are all edges of the
    same sense, best first: ``[(score, (x0, y0, x1, y1), polarity), ...]``."""
    height, width = grey.shape
    gx, gy = _gradients(grey, 1.5)
    band_y = slice(int(height * BAND[0]), int(height * BAND[1]))
    band_x = slice(int(width * BAND[0]), int(width * BAND[1]))
    # Medians, so only an edge that runs the whole band counts, not a reflection crossing it.
    columns = np.median(gx[band_y, :], axis=0)
    rows = np.median(gy[:, band_x], axis=1)
    spacing = max(3, int(min(width, height) * 0.01))
    lefts = _peaks(columns, 2, width // 2, 8, spacing)
    rights = _peaks(columns, width // 2, width - 2, 8, spacing)
    tops = _peaks(rows, 2, height // 2, 8, spacing)
    bottoms = _peaks(rows, height // 2, height - 2, 8, spacing)
    shortest = MIN_SIDE * min(width, height)
    noise = 1.4826 * float(np.median(np.abs(np.concatenate([gx.ravel(), gy.ravel()])))) or 1e-3

    found = []
    for x0 in lefts:
        for x1 in rights:
            w = x1 - x0
            if w < shortest:
                continue
            for y0 in tops:
                for y1 in bottoms:
                    h = y1 - y0
                    if h < shortest or not ASPECT[0] <= w / h <= ASPECT[1]:
                        continue
                    ys = slice(int(y0 + CORNER_FRACTION * h), int(y1 - CORNER_FRACTION * h) + 1)
                    xs = slice(int(x0 + CORNER_FRACTION * w), int(x1 - CORNER_FRACTION * w) + 1)
                    # Gradient pointing out of the rectangle on each side.
                    outward = np.array([
                        float(np.median(-gx[ys, x0])), float(np.median(gx[ys, x1])),
                        float(np.median(-gy[y0, xs])), float(np.median(gy[y1, xs])),
                    ])
                    polarity = 1 if outward.sum() >= 0 else -1
                    score = float((outward * polarity).min())
                    if score <= 0:
                        continue
                    # How much of each side is an edge at all: a real opening is edged all along.
                    support = min(
                        float(np.mean(-gx[ys, x0] * polarity > SUPPORT_SIGMAS * noise)),
                        float(np.mean(gx[ys, x1] * polarity > SUPPORT_SIGMAS * noise)),
                        float(np.mean(-gy[y0, xs] * polarity > SUPPORT_SIGMAS * noise)),
                        float(np.mean(gy[y1, xs] * polarity > SUPPORT_SIGMAS * noise)),
                    )
                    found.append((score, (x0, y0, x1, y1), polarity, support))
    found.sort(key=lambda item: -item[0])
    return found, noise


def _choose(candidates, noise, expect=None):
    """The membrane's opening rather than the outside of the frame or the mount.

    ``expect``, the size the opening is known to have (``(width, height)`` in the
    same pixels), picks the strongest rectangle of about that size.  Otherwise,
    if the strongest rectangle is the frame plate, the opening is the strongest
    one centred inside it at about four-fifths of its size.  Failing both, of
    the rectangles edged strongly all the way round the innermost is taken;
    reflections inside the opening are not edged all the way round.
    """
    # Edged all the way round, well above the noise.  The opening's edge can be
    # far fainter than the plate's outside edge (on FM1 the membrane and plate
    # are both dark grey), so this is judged against the noise, not the plate.
    edged = [c for c in candidates if c[0] >= STRONG_SIGMAS * noise and c[3] >= MIN_SUPPORT]
    if expect is not None:
        sized = [c for c in edged if _matches_size(c[1], expect)]
        if sized:
            return max(sized, key=lambda c: c[0])
    if edged:
        plate = max(edged, key=lambda c: c[0])[1]
        inside = [c for c in edged if _centred_in(c[1], plate)]
        if inside:
            return max(inside, key=lambda c: c[0])
    best_score = candidates[0][0]
    strong = [c for c in edged if c[0] >= STRONG_FRACTION * best_score]
    if not strong:
        return candidates[0]
    return _innermost(strong)


def _centred_in(box, plate):
    """Whether ``box`` sits centred in ``plate`` at the opening's share of its size."""
    pw, ph = plate[2] - plate[0], plate[3] - plate[1]
    w, h = box[2] - box[0], box[3] - box[1]
    low, high = OPENING_IN_PLATE
    if not (low <= w / pw <= high and low <= h / ph <= high):
        return False
    return (abs((box[0] + box[2]) - (plate[0] + plate[2])) / 2.0 <= CENTRED * pw
            and abs((box[1] + box[3]) - (plate[1] + plate[3])) / 2.0 <= CENTRED * ph)


def _innermost(candidates):
    smallest = min(_area(c[1]) for c in candidates)
    # Of near-identical smallest boxes (a side found at two neighbouring places), the strongest.
    return max((c for c in candidates if _area(c[1]) <= smallest * 1.02), key=lambda c: c[0])


def _matches_size(box, expect, tolerance=SIZE_TOLERANCE):
    width, height = box[2] - box[0], box[3] - box[1]
    return (abs(width / expect[0] - 1.0) <= tolerance and abs(height / expect[1] - 1.0) <= tolerance
            and abs((width / height) / (expect[0] / expect[1]) - 1.0) <= tolerance / 2.0)


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _sample(grey, xs, ys):
    """Bilinear samples of ``grey`` at float pixel positions (arrays of any shape)."""
    import cv2
    xs = np.asarray(xs, dtype=np.float32)
    ys = np.asarray(ys, dtype=np.float32)
    shape = xs.shape
    out = cv2.remap(grey, xs.reshape(1, -1), ys.reshape(1, -1), cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE)
    return out.reshape(shape)


def _edge_points(grey, to_image, side, position, start, stop, polarity, reach, samples=80):
    """Points on one side of the rectangle, located to sub-pixel precision in the
    full-resolution image.  ``to_image`` maps the upright frame to image pixels;
    ``side`` is 'left', 'right', 'top' or 'bottom'; ``position`` is the side's
    coarse place along its normal and ``start``/``stop`` its extent."""
    along = np.linspace(start, stop, samples)
    offsets = np.arange(-reach, reach + 1, 1.0)
    normal_sign = -1.0 if side in ("left", "top") else 1.0     # pointing out of the rectangle
    across = position + normal_sign * offsets                   # inner -> outer
    if side in ("left", "right"):
        ux, uy = np.meshgrid(across, along)
    else:
        uy, ux = np.meshgrid(across, along)
    pts = geo.apply_many(to_image, np.column_stack([ux.ravel(), uy.ravel()]))
    values = _sample(grey, pts[:, 0], pts[:, 1]).reshape(len(along), len(offsets))
    rise = np.gradient(values, axis=1) * polarity               # positive where it gets brighter outward
    points = []
    for n in range(len(along)):
        k = int(np.argmax(rise[n]))
        if rise[n, k] <= 0 or k == 0 or k == len(offsets) - 1:
            continue
        a, b, c = rise[n, k - 1], rise[n, k], rise[n, k + 1]
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if denom != 0 else 0.0
        place = across[k] + normal_sign * shift
        points.append((place, along[n], rise[n, k]) if side in ("left", "right")
                      else (along[n], place, rise[n, k]))
    return np.array(points, dtype=float).reshape(-1, 3)


def _robust_line(u, v):
    """Fit ``v = a*u + b`` ignoring outliers; returns ``(a, b, kept)``."""
    keep = np.ones(len(u), dtype=bool)
    a, b = 0.0, float(np.median(v)) if len(v) else 0.0
    for _ in range(4):
        if keep.sum() < 4:
            break
        a, b = np.polyfit(u[keep], v[keep], 1)
        residual = np.abs(v - (a * u + b))
        spread = max(0.5, 2.5 * 1.4826 * float(np.median(residual[keep])))
        new_keep = residual <= spread
        if (new_keep == keep).all():
            break
        keep = new_keep
    return float(a), float(b), keep


def _corner_radius(grey, to_image, box, polarity, reach):
    """The corner rounding that best follows the edge, from the four corner arcs."""
    x0, y0, x1, y1 = box
    largest = 0.25 * min(x1 - x0, y1 - y0)
    best, best_score = 0.0, -np.inf
    for radius in np.linspace(0.0, largest, 26):
        score = 0.0
        for cx, cy, start in ((x0 + radius, y0 + radius, 180.0), (x1 - radius, y0 + radius, 270.0),
                              (x1 - radius, y1 - radius, 0.0), (x0 + radius, y1 - radius, 90.0)):
            angles = np.radians(start + np.linspace(15.0, 75.0, 9))
            dx, dy = np.cos(angles), np.sin(angles)
            inner = geo.apply_many(to_image, np.column_stack([cx + (radius - reach) * dx, cy + (radius - reach) * dy]))
            outer = geo.apply_many(to_image, np.column_stack([cx + (radius + reach) * dx, cy + (radius + reach) * dy]))
            # An edge right on the arc: a step in brightness across it.
            step = (_sample(grey, outer[:, 0], outer[:, 1]) - _sample(grey, inner[:, 0], inner[:, 1])) * polarity
            score += float(np.median(step))
        if score > best_score:
            best, best_score = float(radius), score
    return best


def _coarse_box(small, tilt, expect=None):
    """The opening's box in a reduced image levelled by ``tilt``:
    ``(score, box, polarity)``, the box in that levelled frame."""
    height, width = small.shape
    upright = _warp(small, geo.about((width / 2.0, height / 2.0), 1.0, -tilt), (width, height))
    candidates, noise = _rectangle_candidates(upright)
    if not candidates:
        raise AlignmentError("no rectangular opening found in the image")
    score, box, polarity, _support = _choose(candidates, noise, expect)
    return score, box, polarity


def _refine(smooth, factor, tilt, box, polarity):
    """Trace each side of a coarse box at full resolution and fit it as a line.
    Returns ``(tilt, (x0, y0, x1, y1))`` in the frame levelled by the new tilt."""
    full_h, full_w = smooth.shape
    centre = (full_w / 2.0, full_h / 2.0)
    x0, y0, x1, y1 = ((v + 0.5) * factor - 0.5 for v in box)
    reach = max(4, int(math.ceil(2.5 * factor)))
    for _round in range(2):
        to_image = geo.invert(geo.about(centre, 1.0, -tilt))
        w, h = x1 - x0, y1 - y0
        sides = {}
        for side, position, start, stop in (
                ("left", x0, y0 + CORNER_FRACTION * h, y1 - CORNER_FRACTION * h),
                ("right", x1, y0 + CORNER_FRACTION * h, y1 - CORNER_FRACTION * h),
                ("top", y0, x0 + CORNER_FRACTION * w, x1 - CORNER_FRACTION * w),
                ("bottom", y1, x0 + CORNER_FRACTION * w, x1 - CORNER_FRACTION * w)):
            pts = _edge_points(smooth, to_image, side, position, start, stop, polarity, reach)
            if len(pts) < 10:
                raise AlignmentError(f"the {side} edge of the opening could not be traced")
            sides[side] = pts
        # What is left of the tilt, from the four side lines.
        angles, weights = [], []
        for side, pts in sides.items():
            if side in ("left", "right"):
                a, _b, keep = _robust_line(pts[:, 1], pts[:, 0])
                angles.append(-math.degrees(math.atan(a)))
            else:
                a, _b, keep = _robust_line(pts[:, 0], pts[:, 1])
                angles.append(math.degrees(math.atan(a)))
            weights.append(max(1, int(keep.sum())))
        tilt += float(np.average(angles, weights=weights))
        # Place each side again in the newly levelled frame.
        level = geo.about(centre, 1.0, -tilt) @ to_image
        placed = {}
        for side, pts in sides.items():
            upright = geo.apply_many(level, pts[:, :2])
            placed[side] = float(np.median(upright[:, 0] if side in ("left", "right") else upright[:, 1]))
        x0, x1, y0, y1 = placed["left"], placed["right"], placed["top"], placed["bottom"]
        reach = max(4, int(math.ceil(0.8 * factor)))
    return tilt, (x0, y0, x1, y1)


def find_aperture(image, expect=None):
    """Find the membrane's opening in the frame.  Returns an :class:`Aperture` in
    the image's pixel space, or raises :class:`AlignmentError`.

    ``expect`` is the opening's size, ``(width, height)`` in this image's pixels,
    when it is known from an earlier inspection of the same filter."""
    import cv2
    full = _grey(image)
    small, factor = _reduce(full, WORK_SIDE)
    smooth = cv2.GaussianBlur(full, (0, 0), 1.2)
    full_h, full_w = full.shape
    centre = (full_w / 2.0, full_h / 2.0)

    # The first guess at the tilt can be pulled off by other straight things in the
    # picture (the mount, the bench); once the opening's sides have been traced the
    # tilt is known well, and the search is run once more with it.
    tilt = estimate_tilt(small)
    for attempt in range(2):
        hint = None if expect is None else (expect[0] / factor, expect[1] / factor)
        score, box, polarity = _coarse_box(small, tilt, hint)
        refined_tilt, (x0, y0, x1, y1) = _refine(smooth, factor, tilt, box, polarity)
        settled = abs(refined_tilt - tilt) < 0.1
        tilt = refined_tilt
        if settled:
            break

    to_image = geo.invert(geo.about(centre, 1.0, -tilt))
    radius = _corner_radius(smooth, to_image, (x0, y0, x1, y1), polarity, max(3.0, factor))
    cx, cy = geo.apply(to_image, (x0 + x1) / 2.0, (y0 + y1) / 2.0)
    return Aperture(cx, cy, x1 - x0, y1 - y0, tilt, radius, score, polarity)


# --------------------------------------------------------------------------- #
# Frontlit onto backlit
# --------------------------------------------------------------------------- #

def _structure(grey):
    """What the two photographs have in common: where the edges are, not how bright
    they are (the lighting is opposite).  The noise floor is taken off, so that the
    grain of a dark, boosted backlit image does not drown the frame's edges."""
    import cv2
    gx, gy = _gradients(np.log1p(grey), 1.5)
    magnitude = np.hypot(gx, gy)
    magnitude = np.maximum(magnitude - 3.0 * float(np.median(magnitude)), 0.0)
    top = float(np.percentile(magnitude, 99.5)) or 1.0
    return cv2.GaussianBlur(np.clip(magnitude / top, 0.0, 1.0), (0, 0), 1.5).astype(np.float32)


def _correlation(a, b, valid=None):
    """Normalised correlation of two equal-sized arrays (over ``valid`` if given)."""
    if valid is not None:
        a, b = a[valid], b[valid]
    a = a - a.mean()
    b = b - b.mean()
    denom = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum()) / denom if denom > 0 else 0.0


def _structures(backlit, frontlit, level):
    import cv2
    out = []
    for image in (backlit, frontlit):
        height, width = image.shape
        size = (max(1, int(round(width / level))), max(1, int(round(height / level))))
        out.append(_structure(cv2.resize(image, size, interpolation=cv2.INTER_AREA)))
    back, front = out
    return back, _fit_to(front, back)


def _level_matrix(level):
    """Reduced pixels (at ``level``) -> full-resolution pixels."""
    return geo.translation(-0.5, -0.5) @ geo.scaling(level) @ geo.translation(0.5, 0.5)


def _agreement(back, front, front_to_back, level):
    """How well the edge maps agree with the frontlit one placed by ``front_to_back``
    (full-resolution pixels), judged at 1/``level`` scale."""
    scale = _level_matrix(level)
    matrix = geo.invert(scale) @ front_to_back @ scale
    height, width = back.shape
    moved = _warp(front, matrix, (width, height))
    valid = _warp(np.ones_like(front), matrix, (width, height)) > 0.99
    return _correlation(back, moved, valid) if valid.mean() > 0.5 else -1.0


def _refine_ecc(maps, front_to_back, levels=(16, 8)):
    """Refine a frontlit -> backlit matrix with ECC, coarse to fine.  A scale at
    which ECC does not converge is skipped and the estimate so far kept."""
    import cv2
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
    for level in levels:
        back, front = maps[level]
        scale = _level_matrix(level)
        warp = (geo.invert(scale) @ geo.invert(front_to_back) @ scale)[:2].astype(np.float32)
        try:
            _q, warp = cv2.findTransformECC(back, front, warp, cv2.MOTION_EUCLIDEAN, criteria, None, 5)
        except cv2.error:
            continue
        back_to_front = scale @ np.vstack([warp, [0.0, 0.0, 1.0]]).astype(float) @ geo.invert(scale)
        front_to_back = geo.invert(back_to_front)
    return front_to_back


def register_frontlit(backlit, frontlit, max_turn=3.0):
    """The similarity matrix taking frontlit pixels to backlit pixels, found from
    the frame and mount, which appear in both.  Returns ``(matrix, quality)``,
    quality being the correlation of the two edge maps once aligned (0-1).

    The photographs are usually taken without moving the camera, so the search
    starts from no movement, from the overall shift, and from the best of a range
    of small turns; each start is refined by ECC and the one whose edges agree
    best is kept.
    """
    import cv2
    back_full = _grey(backlit)
    front_full = _grey(frontlit)
    maps = {level: _structures(back_full, front_full, level) for level in (16, 8)}

    starts = [geo.identity()]
    back, front = maps[16]
    height, width = back.shape
    window = cv2.createHanningWindow((width, height), cv2.CV_64F)
    centre = (width / 2.0, height / 2.0)
    best_turn = (-2.0, None)
    for turn in np.arange(-max_turn, max_turn + 1e-9, 0.5):
        rotate = geo.about(centre, 1.0, float(turn))
        turned = _warp(front, rotate, (width, height))
        (dx, dy), _response = cv2.phaseCorrelate(turned.astype(np.float64), back.astype(np.float64), window)
        matrix = geo.translation(dx, dy) @ rotate
        if turn == 0:
            starts.append(_level_matrix(16) @ matrix @ geo.invert(_level_matrix(16)))
        score = _agreement(back, front, _level_matrix(16) @ matrix @ geo.invert(_level_matrix(16)), 16)
        if score > best_turn[0]:
            best_turn = (score, matrix)
    if best_turn[1] is not None:
        starts.append(_level_matrix(16) @ best_turn[1] @ geo.invert(_level_matrix(16)))

    # Judged at 1/8 scale: finer than that, the grain of a dark backlit image
    # outweighs its edges.
    back8, front8 = maps[8]
    unmoved = _agreement(back8, front8, geo.identity(), 8)
    best = (unmoved, geo.identity())
    for start in starts:
        for matrix in (start, _refine_ecc(maps, start)):
            score = _agreement(back8, front8, matrix, 8)
            if score > best[0]:
                best = (score, matrix)
    quality, front_to_back = best
    # Edges lit from opposite sides never agree perfectly, so a small gain is not
    # evidence that the camera moved: only a clear one is.
    if quality < unmoved + max(MOVED_GAIN, MOVED_RATIO * unmoved):
        quality, front_to_back = unmoved, geo.identity()
    if quality <= 0.05:
        raise AlignmentError("the frontlit image could not be matched to the backlit one")
    return front_to_back, float(quality)


def _fit_to(image, like):
    """``image`` cropped or padded to the shape of ``like``."""
    out = np.zeros_like(like)
    h = min(image.shape[0], like.shape[0])
    w = min(image.shape[1], like.shape[1])
    out[:h, :w] = image[:h, :w]
    return out
