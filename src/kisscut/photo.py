"""Repairing photos of photos.

A picture taken of a print on a table arrives tilted, hazy and blue: the paper
sits at an angle to the lens, the room light bounces off the gloss, and evening
light drags everything toward blue. These are the three corrections that matter
before anything is cut out.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

#: Preset names map to the knobs below. ``raw`` only sharpens.
LOOKS: dict[str, dict] = {
    "natural": dict(gamma=0.85, local=(40, 0.55), saturation=1.28, contrast=1.05,
                    sharpen=(2.0, 125, 4), warmth=None),
    "warm": dict(gamma=0.83, local=(40, 0.60), saturation=1.35, contrast=1.08,
                 sharpen=(1.8, 150, 3), warmth=(0.86, 1.08)),
    "punchy": dict(gamma=0.82, local=(35, 0.70), saturation=1.50, contrast=1.14,
                   sharpen=(1.6, 170, 3), warmth=None),
    "raw": dict(gamma=1.00, local=(40, 0.00), saturation=1.00, contrast=1.00,
                sharpen=(1.5, 60, 4), warmth=None),
}


def _gray_world(a: np.ndarray) -> np.ndarray:
    """Neutralise a colour cast by pulling all channel means together."""
    mean = a.reshape(-1, 3).mean(0)
    return a * (mean.mean() / np.maximum(mean, 1e-3))


def _black_point(a: np.ndarray, percentile: float = 0.5) -> np.ndarray:
    """Lift the veil: map the darkest percentile to true black."""
    lo = np.percentile(a, percentile)
    return (a - lo) * 255.0 / max(255.0 - lo, 1e-3)


def _lift_shadows(a: np.ndarray, gamma: float) -> np.ndarray:
    if gamma == 1.0:
        return a
    return 255.0 * np.power(np.clip(a, 0, 255) / 255.0, gamma)


def _warm_shadows(a: np.ndarray, blue: float, red: float) -> np.ndarray:
    """Pull blue out of the dark areas, where an evening cast sits worst."""
    weight = np.clip(1.0 - a.mean(2, keepdims=True) / 255.0, 0, 1) ** 1.2
    out = a.copy()
    out[..., 2] *= (1 - weight[..., 0]) + weight[..., 0] * blue
    out[..., 0] *= (1 - weight[..., 0]) + weight[..., 0] * red
    return out


def _local_contrast(img: Image.Image, radius: float, amount: float) -> Image.Image:
    """Large-radius unsharp mask - this is what clears reflection haze."""
    if amount <= 0:
        return img
    a = np.asarray(img).astype(np.float32)
    blurred = np.asarray(img.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32)
    return Image.fromarray(np.clip(a + (a - blurred) * amount, 0, 255).astype(np.uint8))


def develop(img: Image.Image, look: str = "warm", sharpness: float = 1.0,
            saturation: float = 1.0, brightness: float = 1.0) -> Image.Image:
    """Run a photo through the full correction chain.

    ``sharpness``, ``saturation`` and ``brightness`` are multipliers on top of
    the preset, so 1.0 means "exactly the preset".
    """
    preset = LOOKS.get(look, LOOKS["warm"])
    img = img.convert("RGB").filter(ImageFilter.MedianFilter(3))

    a = np.asarray(img).astype(np.float32)
    a = _gray_world(a)
    a = _black_point(a, 0.5)
    a = _lift_shadows(a, preset["gamma"] / max(brightness, 0.05))
    if preset["warmth"]:
        a = _warm_shadows(a, *preset["warmth"])

    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    out = _local_contrast(out, *preset["local"])
    out = ImageEnhance.Color(out).enhance(preset["saturation"] * saturation)
    out = ImageEnhance.Contrast(out).enhance(preset["contrast"])

    radius, percent, threshold = preset["sharpen"]
    if sharpness > 0:
        out = out.filter(ImageFilter.UnsharpMask(radius, int(percent * sharpness), threshold))
    return out


def tilt_angle(img: Image.Image) -> float:
    """Estimate how far a photographed print is rotated, in degrees.

    Follows the top edge of the print (bright paper above, image below) across
    the frame and measures its slope. Returns 0.0 when no straight edge is
    found, so a normal photo is never rotated by accident.
    """
    small = img.convert("L").resize((max(img.width // 2, 2), max(img.height // 2, 2)))
    g = np.asarray(small).astype(float)
    height, width = g.shape

    # The top of the frame has to look like paper: bright and even. Otherwise
    # this is an ordinary photo and nothing should be rotated.
    margin = g[: max(3, height // 30)]
    paper = float(np.median(margin))
    if paper < 170 or float(np.std(margin)) > 18:
        return 0.0
    threshold = paper - max(22.0, paper * 0.12)

    xs: list[int] = []
    ys: list[int] = []
    for x in range(width // 10, width - width // 10, max(width // 40, 1)):
        column = g[: int(height * 0.6), x]
        if column[:5].min() <= threshold:  # must start on paper
            continue
        below = np.where(column <= threshold)[0]
        if len(below) and below[0] > 3:
            xs.append(x)
            ys.append(int(below[0]))

    if len(xs) < 8:
        return 0.0

    # Some columns hit the side edge of the print instead of the top one, which
    # would drag a least-squares fit off completely. Theil-Sen takes the median
    # slope over all point pairs and shrugs those outliers off.
    px = np.asarray(xs, dtype=float)
    py = np.asarray(ys, dtype=float)
    i, j = np.triu_indices(len(px), k=1)
    spread = px[j] - px[i]
    usable = spread != 0
    if not usable.any():
        return 0.0
    slope = float(np.median((py[j] - py[i])[usable] / spread[usable]))
    intercept = float(np.median(py - slope * px))

    close = np.abs(py - (slope * px + intercept)) < max(4.0, height * 0.01)
    if close.sum() < 8 or close.mean() < 0.5:   # no straight edge - leave it alone
        return 0.0
    slope, _ = np.polyfit(px[close], py[close], 1)
    return round(math.degrees(math.atan(slope)), 2)


def deskew(img: Image.Image, angle: float | None = None) -> tuple[Image.Image, float]:
    """Rotate a photographed print upright. Returns the image and the angle used."""
    if angle is None:
        angle = tilt_angle(img)
    if not angle:
        return img, 0.0
    return img.rotate(angle, resample=Image.BICUBIC, expand=True,
                      fillcolor=(255, 255, 255)), angle
