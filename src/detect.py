"""Find candidate pinholes: small bright spots on the dark background of a backlit image."""

import math

import numpy as np

# name: (threshold in local noise sigmas, minimum contrast in 8-bit levels)
SENSITIVITY = {
    "low": (12.0, 45.0),
    "normal": (7.0, 25.0),
    "high": (4.5, 14.0),
}

MIN_AREA = 3          # pixels; smaller is indistinguishable from sensor noise
MAX_AREA = 900        # larger is a tear, an edge or stray light, not a pinhole
MAX_BACKGROUND = 90   # ignore regions flooded with light (frame edges, leaks)
COARSE = 8            # background and noise are estimated at 1/8 scale


def find_pinholes(image, sensitivity="normal", limit=400):
    """Return candidate pinholes in ``image`` (a PIL image), strongest first.

    Each candidate is a dict with ``x``, ``y`` (pixel coordinates of the
    centre), ``radius`` (pixels), ``peak`` (brightness above the local
    background) and ``snr``.
    """
    import cv2

    arr = np.asarray(image)
    grey = (arr.max(axis=2) if arr.ndim == 3 else arr).astype(np.float32)
    height, width = grey.shape
    sigmas, min_contrast = SENSITIVITY.get(sensitivity, SENSITIVITY["normal"])

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

    mask = (residual > np.maximum(sigmas * noise_after_blur, min_contrast)) & (background < MAX_BACKGROUND)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)

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
        cy, cx = centroids[i][1], centroids[i][0]
        local_noise = float(noise_after_blur[min(height - 1, int(cy)), min(width - 1, int(cx))])
        candidates.append({
            "x": float(cx) + 0.5,
            "y": float(cy) + 0.5,
            "radius": max(1.5, math.sqrt(area / math.pi)),
            "peak": peak,
            "snr": peak / local_noise,
        })
    candidates.sort(key=lambda c: -c["peak"])
    total = len(candidates)
    return candidates[:limit], total


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
