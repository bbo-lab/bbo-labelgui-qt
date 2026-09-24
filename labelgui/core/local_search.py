"""Metric-independent pixel selection within a circular image neighborhood."""
import math

import numpy as np


def brightness(pixels):
    """Score grayscale intensity or mean RGB intensity (ignoring alpha)."""
    pixels = np.asarray(pixels, dtype=float)
    return pixels if pixels.ndim == 2 else pixels[..., :3].mean(axis=2)


def find_local_peak(image, center, radius, metric=brightness):
    """Return the highest-scoring (x, y) pixel within radius, or None.

    A metric accepts an image crop and returns a 2D score array; higher wins.
    Nonfinite scores are ignored. Equal scores prefer the pixel nearest center.
    Image coordinates, including the returned position, use (column, row).
    """
    x, y = map(float, center)
    radius = float(radius)
    if not all(map(math.isfinite, (x, y, radius))) or radius < 0:
        raise ValueError('Search center and radius must be finite; radius must be nonnegative')
    height, width = image.shape[:2]
    left, right = max(0, math.ceil(x - radius)), min(width, math.floor(x + radius) + 1)
    top, bottom = max(0, math.ceil(y - radius)), min(height, math.floor(y + radius) + 1)
    if left >= right or top >= bottom:
        return None
    scores = np.asarray(metric(image[top:bottom, left:right]), dtype=float)
    if scores.shape != (bottom - top, right - left):
        raise ValueError('Pixel metric must return one score per pixel')
    yy, xx = np.ogrid[top:bottom, left:right]
    distance = (xx - x) ** 2 + (yy - y) ** 2
    valid = (distance <= radius ** 2) & np.isfinite(scores)
    if not valid.any():
        return None
    best = valid & (scores == scores[valid].max())
    row, col = np.unravel_index(np.argmin(np.where(best, distance, np.inf)), scores.shape)
    return float(left + col), float(top + row)
