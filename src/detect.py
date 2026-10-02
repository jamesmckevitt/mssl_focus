"""Find candidate pinholes: small bright spots on the dark background of a backlit image."""

import math

import numpy as np

from . import geometry as geo

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

# Every spot also gets a continuous score on which the faint, likely and clear
# thresholds are 1, 2 and 3.  The sensitivity setting (0-100) picks the lowest
# score offered: 50 = only clear spots, 75 = clear and likely, 100 = everything.
DEFAULT_SENSITIVITY = 75
_SIGMAS = [sigmas for _n, sigmas, _c in reversed(TIERS)]
_CONTRASTS = [contrast for _n, _s, contrast in reversed(TIERS)]


def minimum_score(sensitivity):
    return 1.0 + (100.0 - min(100.0, max(0.0, float(sensitivity)))) / 25.0


def _level(value, faint, likely, clear):
    """Where ``value`` falls on the scale on which the three thresholds are 1, 2 and 3."""
    if value <= 0:
        return 0.0
    if value < likely:
        return 1.0 + math.log(value / faint) / math.log(likely / faint)
    return 2.0 + math.log(value / likely) / math.log(clear / likely)

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
        # Scored on its third-brightest pixel: a tier needs a few pixels above its
        # threshold, so a single hot pixel, however bright, never counts as more than faint.
        third = float(np.sort(patch, axis=None)[-MIN_AREA])
        score = max(1.0, min(_level(third / local_noise, *_SIGMAS), _level(third, *_CONTRASTS)))
        candidates.append({
            "x": cx + 0.5,
            "y": cy + 0.5,
            "radius": max(1.5, math.sqrt(area / math.pi)),
            "peak": peak,
            "snr": peak / local_noise,
            "score": score,
            "tier": "clear" if score > 3.0 else "likely" if score > 2.0 else "faint",
        })
    candidates.sort(key=lambda c: -c["score"])
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


def match_markers_to_spots(markers, candidates, tolerance=12.0, reach=1.0):
    """Pair each marker (``(x, y, radius)``) with the spot it most plausibly marks.

    Returns ``{marker index: candidate}``.  A spot goes to one marker only, the
    nearest; a clear or likely spot wins over a faint one.  A spot counts if it is
    inside the marker's circle; ``reach`` widens that, in radii, for clear and
    likely spots (faint ones are too common to trust further out).
    """
    pairs = []
    for m, (x, y, radius) in enumerate(markers):
        near = max(radius, tolerance)
        for c, candidate in enumerate(candidates):
            distance = math.hypot(candidate["x"] - x, candidate["y"] - y)
            faint = candidate["tier"] == "faint"
            if distance <= near * (1.0 if faint else reach):
                pairs.append((faint, distance, m, c))
    pairs.sort()
    matched, used = {}, set()
    for _faint, _distance, m, c in pairs:
        if m not in matched and c not in used:
            matched[m] = candidates[c]
            used.add(c)
    return matched


def realign_markers(markers, candidates, tolerance=12.0):
    """Where each marker (``(x, y, radius)``) should sit so that it is on its spot.

    A marker is centred on the spot inside its circle.  Markers copied from an
    earlier inspection are often all off in the same way, further than their own
    radius, because the filter sat slightly differently in front of the camera.
    So the shift and rotation the markers have in common is worked out first,
    from the markers whose spot is plain to see, and a spot also counts if it is
    inside the circle once that correction is made.  A marker with no spot is
    left exactly where it is.

    Returns ``(positions, matched)``: the new ``(x, y)`` of each marker and the
    indices of those now sitting on a spot.
    """
    drift = geo.identity()
    seeds = match_markers_to_spots(markers, candidates, tolerance, reach=2.0)
    if len(seeds) >= 4:
        src = np.array([markers[m][:2] for m in seeds], dtype=float)
        dst = np.array([(c["x"], c["y"]) for c in seeds.values()], dtype=float)
        try:
            for _attempt in range(3):
                matrix, rms = geo.fit_similarity(src, dst, allow_scale=False)
                residual = np.hypot(*(geo.apply_many(matrix, src) - dst).T)
                keep = residual <= max(3.0, 2.5 * float(np.median(residual)))
                if keep.all() or keep.sum() < 4:
                    break
                src, dst = src[keep], dst[keep]     # a marker that grabbed the wrong spot
            # Only trust it if the markers really are off together: the common correction
            # must account for most of the distance between the markers and their spots.
            apart = math.sqrt(float(((src - dst) ** 2).sum(axis=1).mean()))
            if rms <= 0.5 * apart:
                drift = matrix
        except ValueError:
            pass

    pairs = []
    for m, (x, y, radius) in enumerate(markers):
        near = max(radius, tolerance)
        shifted_x, shifted_y = geo.apply(drift, x, y)
        for c, candidate in enumerate(candidates):
            distance = min(math.hypot(candidate["x"] - x, candidate["y"] - y),
                           math.hypot(candidate["x"] - shifted_x, candidate["y"] - shifted_y))
            if distance <= near:
                pairs.append((candidate["tier"] == "faint", distance, m, c))
    pairs.sort()
    matched, used = {}, set()
    for _faint, _distance, m, c in pairs:
        if m not in matched and c not in used:
            matched[m] = candidates[c]
            used.add(c)
    positions = [(float(matched[m]["x"]), float(matched[m]["y"])) if m in matched
                 else (float(markers[m][0]), float(markers[m][1])) for m in range(len(markers))]
    return positions, set(matched)

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


def inside_polygon(xs, ys, polygon):
    """``point_in_polygon`` for many points at once; returns a boolean array."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    inside = np.zeros(xs.shape, dtype=bool)
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        if y0 == y1:
            continue
        inside ^= ((y0 > ys) != (y1 > ys)) & (xs < (x1 - x0) * (ys - y0) / (y1 - y0) + x0)
    return inside


def point_in_polygon(x, y, polygon):
    inside = False
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside
