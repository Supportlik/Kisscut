"""Draw the sample photos that ship with Kisscut.

Everything here is generated, so the repository carries no photographs of
anyone. The point is to reproduce the problems a real snapshot has - a print
lying at an angle under a lamp, a subject against a busy background, a red pen
outline - so the whole pipeline can be exercised offline.

    python examples/make_samples.py
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
RNG = np.random.default_rng(7)


# --------------------------------------------------------------- scenery

def _sky(size: tuple[int, int], top=(86, 140, 196), bottom=(226, 206, 172)) -> Image.Image:
    width, height = size
    ramp = np.linspace(0, 1, height)[:, None]
    bands = [np.full((height, width), t * (1 - ramp) + b * ramp).astype(np.uint8)
             for t, b in zip(top, bottom)]
    return Image.fromarray(np.dstack(bands), "RGB")


def _clouds(img: Image.Image, count: int = 14) -> None:
    layer = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(layer)
    for _ in range(count):
        cx = RNG.uniform(0, img.width)
        cy = RNG.uniform(0, img.height * 0.55)
        for _ in range(7):
            rx, ry = RNG.uniform(30, 90), RNG.uniform(14, 34)
            ox, oy = RNG.uniform(-60, 60), RNG.uniform(-14, 14)
            draw.ellipse((cx + ox - rx, cy + oy - ry, cx + ox + rx, cy + oy + ry), fill=170)
    layer = layer.filter(ImageFilter.GaussianBlur(14))
    img.paste(Image.new("RGB", img.size, (252, 250, 245)), (0, 0), layer)


def _hills(img: Image.Image) -> None:
    draw = ImageDraw.Draw(img)
    width, height = img.size
    for index, (shade, base, amp) in enumerate([
        ((122, 136, 118), 0.70, 46),
        ((92, 110, 96), 0.78, 62),
        ((63, 82, 72), 0.88, 38),
    ]):
        points = [(x, height * base + math.sin(x / (120 + index * 70) + index) * amp
                   + math.sin(x / 37.0 + index * 2) * 6) for x in range(0, width + 8, 8)]
        draw.polygon([(0, height), *points, (width, height)], fill=shade)


def balloon_layer(scale: float) -> Image.Image:
    """A hot air balloon on its own transparent layer: a clear, closed silhouette."""
    rx, ry = 92 * scale, 108 * scale
    width = int(rx * 2) + 8
    height = int(ry * 2.05 + 60 * scale) + 8
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cx = width / 2
    cy = ry + 4

    panels = [(214, 73, 61), (242, 196, 85), (238, 240, 236), (73, 124, 168)]
    stripes = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    stripe_draw = ImageDraw.Draw(stripes)
    for index in range(8):
        x0 = cx - rx + index * (2 * rx / 8)
        stripe_draw.rectangle((x0, cy - ry - 2, x0 + 2 * rx / 8, cy + ry * 1.05 + 2),
                              fill=panels[index % len(panels)] + (255,))

    envelope = Image.new("L", (width, height), 0)
    ImageDraw.Draw(envelope).ellipse((cx - rx, cy - ry, cx + rx, cy + ry * 1.05), fill=255)
    layer.paste(stripes, (0, 0), envelope)

    draw = ImageDraw.Draw(layer)
    shade = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse((cx - rx, cy - ry, cx + rx * 0.2, cy + ry), fill=(20, 24, 40, 46))
    layer.paste(Image.alpha_composite(layer.crop((0, 0, width, height)), shade), (0, 0), envelope)

    basket_w, basket_h = 26 * scale, 22 * scale
    top = cy + ry * 1.02
    rope = max(2, int(3 * scale))
    draw = ImageDraw.Draw(layer)
    draw.line([(cx - rx * 0.45, top), (cx - basket_w, top + 34 * scale)], fill=(70, 56, 44, 255), width=rope)
    draw.line([(cx + rx * 0.45, top), (cx + basket_w, top + 34 * scale)], fill=(70, 56, 44, 255), width=rope)
    draw.rounded_rectangle((cx - basket_w, top + 32 * scale, cx + basket_w, top + 32 * scale + basket_h),
                           radius=int(5 * scale), fill=(146, 103, 58, 255),
                           outline=(104, 72, 40, 255), width=2)
    return layer


def scene_balloon(size=(1000, 1250)) -> Image.Image:
    img = _sky(size)
    _clouds(img)
    _hills(img)
    layer = balloon_layer(1.35)
    img.paste(layer, (int(size[0] * 0.5 - layer.width / 2), int(size[1] * 0.17)), layer)
    return img


def scene_mug(size=(1100, 900)) -> Image.Image:
    """A mug on a busy shelf - a normal snapshot, nothing to straighten."""
    img = Image.new("RGB", size, (198, 184, 162))
    draw = ImageDraw.Draw(img)
    for y in range(0, size[1], 7):                      # wood grain
        shade = 176 + int(14 * math.sin(y / 9.0) + RNG.integers(-6, 6))
        draw.line([(0, y), (size[0], y)], fill=(shade, shade - 18, shade - 44), width=5)
    draw.rectangle((0, 0, size[0], size[1] * 0.42), fill=(118, 122, 128))
    for index in range(9):                              # books on the shelf
        x = 40 + index * 118 + int(RNG.integers(-10, 10))
        height = int(RNG.integers(170, 300))
        colour = tuple(int(c) for c in RNG.integers(60, 210, 3))
        draw.rectangle((x, size[1] * 0.42 - height, x + 92, size[1] * 0.42), fill=colour)
        draw.rectangle((x + 10, size[1] * 0.42 - height + 22, x + 82,
                        size[1] * 0.42 - height + 34), fill=(245, 242, 236))

    cx, cy = size[0] * 0.52, size[1] * 0.62
    body = (cx - 150, cy - 130, cx + 150, cy + 190)
    draw.ellipse((cx + 120, cy - 60, cx + 250, cy + 90), outline=(236, 238, 240), width=34)
    draw.rounded_rectangle(body, radius=40, fill=(238, 240, 242))
    draw.ellipse((cx - 150, cy - 160, cx + 150, cy - 100), fill=(250, 251, 252))
    draw.ellipse((cx - 128, cy - 152, cx + 128, cy - 108), fill=(92, 62, 44))
    draw.rounded_rectangle((cx - 110, cy - 10, cx + 110, cy + 60), radius=18, fill=(214, 76, 62))
    return img


# ------------------------------------------------------- print simulation

def photograph_print(scene: Image.Image, angle: float = 8.0, haze: float = 0.30,
                     blue: float = 1.14, blur: float = 1.6) -> Image.Image:
    """Lay a scene on paper and take a mediocre phone photo of it."""
    paper = Image.new("RGB", (int(scene.width * 1.25), int(scene.height * 1.3)), (246, 243, 236))
    paper.paste(scene, ((paper.width - scene.width) // 2, int(scene.height * 0.22)))
    tilted = paper.rotate(-angle, resample=Image.BICUBIC, expand=True, fillcolor=(243, 240, 233))

    a = np.asarray(tilted).astype(np.float32)
    gloss = np.zeros(a.shape[:2], np.float32)           # reflection of a window
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    gloss += np.exp(-(((xx - a.shape[1] * 0.62) / (a.shape[1] * 0.45)) ** 2
                      + ((yy - a.shape[0] * 0.30) / (a.shape[0] * 0.55)) ** 2))
    a = a * (1 - haze * gloss[..., None]) + 255.0 * haze * gloss[..., None] * 0.92
    a[..., 2] *= blue                                   # evening colour cast
    a[..., 0] *= 0.97
    a += RNG.normal(0, 3.2, a.shape)
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return out.filter(ImageFilter.GaussianBlur(blur))


def mark_outline(img: Image.Image, points) -> Image.Image:
    """Draw the red pen line a person would draw around the subject."""
    marked = img.copy()
    draw = ImageDraw.Draw(marked)
    draw.line([*points, points[0]], fill=(255, 0, 0),
              width=max(6, img.width // 110), joint="curve")
    return marked


def main() -> None:
    balloon_scene = scene_balloon()
    print_photo = photograph_print(balloon_scene)
    print_photo.save(HERE / "balloon-print.jpg", quality=78)

    width, height = print_photo.size
    ring = [(width * x, height * y) for x, y in [
        (0.33, 0.30), (0.46, 0.22), (0.60, 0.25), (0.69, 0.36), (0.70, 0.50),
        (0.63, 0.62), (0.60, 0.74), (0.47, 0.76), (0.40, 0.66), (0.33, 0.52), (0.30, 0.40),
    ]]
    mark_outline(print_photo, ring).save(HERE / "balloon-print-marked.png")

    scene_mug().filter(ImageFilter.GaussianBlur(0.4)).save(HERE / "mug-shelf.jpg", quality=86)

    for name in ("balloon-print.jpg", "balloon-print-marked.png", "mug-shelf.jpg"):
        path = HERE / name
        print(f"{name:28s} {Image.open(path).size}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
