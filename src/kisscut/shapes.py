"""Die shapes - the outline a sticker is cut to.

``silhouette`` follows the subject itself; everything else is a geometric die
the photo is cut with. Masks are drawn at 4x and scaled down, which is what
keeps a 12-point star from looking like a staircase.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

#: Shape name -> label for the interface.
SHAPES: dict[str, str] = {
    "silhouette": "Silhouette",
    "circle": "Circle",
    "rounded": "Rounded",
    "square": "Square",
    "bubble": "Speech bubble",
    "seal": "Seal",
    "heart": "Heart",
    "burst": "Burst",
}

SUPERSAMPLE = 4


def die(shape: str, size: int, inset: int = 0) -> Image.Image:
    """Grayscale mask of one shape, centred in a square of ``size`` pixels."""
    scale = SUPERSAMPLE
    edge = size * scale
    mask = Image.new("L", (edge, edge), 0)
    draw = ImageDraw.Draw(mask)

    pad = inset * scale
    box = (pad, pad, edge - pad - 1, edge - pad - 1)
    centre = edge / 2
    radius = (edge - 2 * pad) / 2

    if shape == "circle":
        draw.ellipse(box, fill=255)
    elif shape == "square":
        draw.rounded_rectangle(box, radius=int(edge * 0.04), fill=255)
    elif shape == "rounded":
        draw.rounded_rectangle(box, radius=int(edge * 0.14), fill=255)
    elif shape == "bubble":
        body = (pad, pad, edge - pad - 1, int(edge * 0.80) - pad)
        draw.rounded_rectangle(body, radius=int(edge * 0.13), fill=255)
        draw.polygon([(int(edge * 0.26), int(edge * 0.76)),
                      (int(edge * 0.30), edge - pad - 1),
                      (int(edge * 0.50), int(edge * 0.76))], fill=255)
    elif shape == "seal":
        points, depth = 18, 0.075
        draw.polygon(_rosette(centre, radius, points, depth), fill=255)
    elif shape == "burst":
        spikes = 12
        pts = []
        for i in range(spikes * 2):
            r = radius if i % 2 == 0 else radius * 0.62
            t = -math.pi / 2 + i * math.pi / spikes
            pts.append((centre + r * math.cos(t), centre + r * math.sin(t)))
        draw.polygon(pts, fill=255)
    elif shape == "heart":
        draw.polygon(_heart(centre, radius), fill=255)
    else:
        draw.rectangle(box, fill=255)

    return mask.resize((size, size), Image.LANCZOS)


def _rosette(centre: float, radius: float, points: int, depth: float):
    steps = points * 48
    return [
        (centre + radius * (1 - depth + depth * math.cos(points * t)) * math.cos(t),
         centre + radius * (1 - depth + depth * math.cos(points * t)) * math.sin(t))
        for t in (i / steps * 2 * math.pi for i in range(steps))
    ]


def _heart(centre: float, radius: float):
    pts = []
    for i in range(400):
        t = i / 400 * 2 * math.pi
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((centre + x / 17 * radius, centre + y / 17 * radius * 0.95))
    return pts
