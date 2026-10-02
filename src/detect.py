"""Find candidate pinholes: small bright spots on the dark background of a backlit image."""

import math

import numpy as np

# How sure the search is about a spot, strictest first.  A spot gets the first
# tier whose test it passes: (name, threshold in local noise sigmas, minimum
# contrast in 8-bit levels).  Checked against hand-made maps, "clear" spots were
# almost always marked by the inspector and "faint" ones almost never.
TIERS = [
    ("clear", 12.0, 45.0),
    ("likely", 7.0, 25.0),
    ("faint", 4.5, 14.0),
]
TIER_ORDER = {name: n for n, (name, _s, _c) in enumerate(TIERS)}

MIN_AREA = 3          # pixels; smaller is indistinguishable from sensor noise
MAX_AREA = 900        # larger is a tear, an edge or stray light, not a pinhole
MAX_BACKGROUND = 90   # ignore regions flooded with light (frame edges, leaks)
COARSE = 8            # background and noise are estimated at 1/8 scale


def find_pinholes(image, mask=None, limit=4000):
    """Return ``(candidates, total)`` for ``image`` (a PIL image), surest and brightest first.

    ``mask``, if given, is an array the size of the image; only spots where it is
    non-zero are reported.  Each candidate is a dict with ``x``, ``y`` (pixel
    coordinates of the centre), ``radius`` (pixels), ``peak`` (brightness above the
    local background), ``snr`` and ``tier`` (see ``TIERS``).
    """
    import cv2

    arr = np.asarray(image)
    grey = (arr.max(axis=2) if arr.ndim == 3 else arr).astype(np.float32)
    height, width = grey.shape

    # Slowly varying background, robust to the spots themselves.
    small = cv2.resize(grey, (max(1, width // COARSE), max(1, height // COARSE)), interpolation=cv2.INTER_AREA)
    background_small = cv2.medianBlur(np.clip(small, 0, 255).astype(np.uint8), 15).astype(np.float32)
    background = cv2.resize(background_small, (width, height), interpolation=cv2.INTER_LINEAR)

    # A spot a few pixels wide survives a slight blur; single-pixel noise does not.
    smooth = cv2.GaussianBlur(grey, (0, 0), 1.2)
    residual = smooth - background

    # Local noise level, so grainy or glowing regions need a stronger signal.
    deviation = np.abs(grey - background)
    deviation_small = cv2.resize(deviation, (background_small.shape[1], background_small.shape[0]),
                                 interpolation=cv2.INTER_AREA)
    deviation_small = cv2.medianBlur(np.clip(deviation_small * 8, 0, 255).astype(np.uint8), 9).astype(np.float32) / 8
    noise = cv2.resize(cv2.GaussianBlur(deviation_small, (0, 0), 4.0), (width, height),
                       interpolation=cv2.INTER_LINEAR) * 1.2533
    # The blur above cuts pixel noise to roughly a quarter.
    noise_after_blur = np.maximum(noise * 0.25, 0.4)

    _name, faint_sigmas, faint_contrast = TIERS[-1]
    found = (residual > np.maximum(faint_sigmas * noise_after_blur, faint_contrast)) & (background < MAX_BACKGROUND)
    if mask is not None:
        found &= np.asarray(mask) > 0
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(found.astype(np.uint8), connectivity=8)

    candidates = []
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if not MIN_AREA <= area <= MAX_AREA:
            continue
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        if max(w, h) > 3.5 * min(w, h) or area < 0.35 * w * h:
            continue  # a streak or a ragged fragment, not a round spot
        x0, y0 = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        patch = residual[y0:y0 + h, x0:x0 + w]
        peak = float(patch.max())
        cx, cy = float(centroids[i][0]), float(centroids[i][1])
        local_noise = float(noise_after_blur[min(height - 1, int(cy)), min(width - 1, int(cx))])
        # A tier needs a few pixels above its own threshold, so a single hot
        # pixel, however bright, never counts as more than faint.
        tier = next((name for name, sigmas, contrast in TIERS[:-1]
                     if int((patch > max(sigmas * local_noise, contrast)).sum()) >= MIN_AREA), TIERS[-1][0])
        candidates.append({
            "x": cx + 0.5,
            "y": cy + 0.5,
            "radius": max(1.5, math.sqrt(area / math.pi)),
            "peak": peak,
            "snr": peak / local_noise,
            "tier": tier,
        })
    candidates.sort(key=lambda c: (TIER_ORDER[c["tier"]], -c["peak"]))
    return candidates[:limit], len(candidates)


def split_by_markers(candidates, markers, tolerance=12.0):
    """Separate candidates that already have a marker from those that do not.

    ``markers`` is a list of ``(x, y, radius)`` in the same pixel space.
    """
    fresh, marked = [], []
    for candidate in candidates:
        hit = any(math.hypot(candidate["x"] - x, candidate["y"] - y) <= max(radius, tolerance)
                  for x, y, radius in markers)
        (marked if hit else fresh).append(candidate)
    return fresh, marked


def markers_without_a_spot(markers, candidates, tolerance=12.0):
    """Indices of ``markers`` (``(x, y, radius)``) with no candidate under them."""
    lonely = []
    for n, (x, y, radius) in enumerate(markers):
        if not any(math.hypot(c["x"] - x, c["y"] - y) <= max(radius, tolerance) for c in candidates):
            lonely.append(n)
    return lonely


def flag_present_in(candidates, others, tolerance=10.0):
    """Mark each candidate with whether a spot in ``others`` (a list of ``(x, y)``
    in the same pixel space) lies at the same place."""
    if not others:
        for candidate in candidates:
            candidate["in_reference"] = False
        return candidates
    points = np.asarray(others, dtype=np.float32)
    for candidate in candidates:
        distances = np.hypot(points[:, 0] - candidate["x"], points[:, 1] - candidate["y"])
        candidate["in_reference"] = bool(distances.min() <= tolerance)
    return candidates


def point_in_polygon(x, y, polygon):
    inside = False
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside
