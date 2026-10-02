"""2D similarity transforms shared by rendering, click handling and alignment.

Everything is a 3x3 homogeneous matrix acting on column vectors in image-style
coordinates (x right, y down).  A positive rotation angle turns content
clockwise on screen, matching the convention saved in session files.
"""

import math

import numpy as np


def identity():
    return np.eye(3)


def translation(tx, ty):
    m = np.eye(3)
    m[0, 2] = tx
    m[1, 2] = ty
    return m


def scaling(factor):
    m = np.eye(3)
    m[0, 0] = factor
    m[1, 1] = factor
    return m


def about(centre, scale=1.0, deg=0.0):
    """Rotate by ``deg`` and scale by ``scale`` about ``centre``."""
    theta = math.radians(deg)
    c = math.cos(theta) * scale
    s = math.sin(theta) * scale
    cx, cy = centre
    return np.array([
        [c, -s, cx - c * cx + s * cy],
        [s, c, cy - s * cx - c * cy],
        [0.0, 0.0, 1.0],
    ])


def apply(matrix, x, y):
    return (
        matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2],
        matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2],
    )


def apply_many(matrix, points):
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    return pts @ matrix[:2, :2].T + matrix[:2, 2]


def invert(matrix):
    return np.linalg.inv(matrix)


def scale_of(matrix):
    return math.sqrt(abs(matrix[0, 0] * matrix[1, 1] - matrix[0, 1] * matrix[1, 0]))


def angle_of(matrix):
    return math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))


def wrap_angle(deg):
    """Wrap an angle to the range (-180, 180]."""
    deg = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if deg == -180.0 else deg


def fit_similarity(src, dst, allow_scale=True):
    """Least-squares similarity transform mapping ``src`` points onto ``dst``.

    Returns ``(matrix, rms_residual)``.  With ``allow_scale=False`` the fit is
    rigid (rotation and translation only).
    """
    src = np.asarray(src, dtype=float).reshape(-1, 2)
    dst = np.asarray(dst, dtype=float).reshape(-1, 2)
    if len(src) < 2 or len(src) != len(dst):
        raise ValueError("at least 2 matching point pairs are required")

    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_c = src - src_mean
    dst_c = dst - dst_mean
    src_energy = float((src_c ** 2).sum())
    if src_energy <= 1e-12:
        raise ValueError("the points are all in the same place")

    u, singular, vt = np.linalg.svd(src_c.T @ dst_c)
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0:
        vt[-1, :] *= -1
        singular = singular.copy()
        singular[-1] *= -1
        rot = vt.T @ u.T

    scale = float(singular.sum() / src_energy) if allow_scale else 1.0
    if scale <= 1e-9:
        raise ValueError("the points do not define a usable scale")

    matrix = np.eye(3)
    matrix[:2, :2] = scale * rot
    matrix[:2, 2] = dst_mean - scale * (rot @ src_mean)

    residual = apply_many(matrix, src) - dst
    rms = float(math.sqrt((residual ** 2).sum(axis=1).mean()))
    return matrix, rms


def decompose_about(matrix, centre):
    """Split a similarity into ``(scale, deg, tx, ty)`` such that
    ``matrix == translation(tx, ty) @ about(centre, scale, deg)``."""
    scale = scale_of(matrix)
    deg = angle_of(matrix)
    cx, cy = centre
    moved_cx, moved_cy = apply(matrix, cx, cy)
    return scale, deg, moved_cx - cx, moved_cy - cy
