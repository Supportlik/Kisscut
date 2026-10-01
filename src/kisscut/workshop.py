"""The bench: a recipe, a cached workshop, and the border that makes it a sticker."""
from __future__ import annotations

import hashlib
import io
import json
import threading
from dataclasses import asdict, dataclass, field

import numpy as np
from PIL import Image, ImageChops, ImageFilter
from scipy import ndimage as ndi

from . import cutout, photo, shapes

WORK_EDGE = 900         # longest edge we compute on; preview and export share it
THUMB_EDGE = 360        # cheaper resolution for the suggestion strip
SOURCE_EDGE = 2400      # incoming photos are capped here; 512 px output needs no more
OUTPUT_EDGE = 512       # WhatsApp sticker edge
WEBP_LIMIT = 99_000     # WhatsApp rejects static stickers over 100 KB


@dataclass
class Recipe:
    """Everything the interface can change, in one serialisable object."""

    rotate: float = 0.0
    crop: list[float] | None = None          # [x0, y0, x1, y1], relative 0..1
    look: str = "warm"
    sharpness: float = 1.0
    saturation: float = 1.0
    brightness: float = 1.0
    shape: str = "silhouette"
    source: str = "model"                    # model | lasso | full
    model: str = "birefnet-portrait"
    lasso: list[list[float]] = field(default_factory=list)   # relative 0..1
    pop_out: bool = True                     # subject may overlap a geometric die
    border: int = 14
    border_color: str = "#ffffff"
    shadow: bool = True
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "Recipe":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)

    def _digest(self, keys: tuple[str, ...]) -> str:
        payload = {k: getattr(self, k) for k in keys}
        return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    @property
    def frame_key(self) -> str:
        return self._digest(("rotate", "crop"))

    @property
    def image_key(self) -> str:
        return self._digest(("rotate", "crop", "look", "sharpness", "saturation", "brightness"))

    @property
    def mask_key(self) -> str:
        return self._digest(("rotate", "crop", "source", "model", "lasso"))


def _rgb(value: str) -> tuple[int, int, int]:
    text = str(value).lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))      # type: ignore[return-value]
    except (ValueError, IndexError):
        return (255, 255, 255)


def add_border(rgba: Image.Image, width: int, color=(255, 255, 255),
               shadow: tuple[int, int, float] | None = None) -> Image.Image:
    """Lay an even border around whatever is opaque, plus an optional shadow.

    Uses a distance transform rather than repeated dilation, so the border is
    exactly as wide in a sharp corner as along a straight edge.
    """
    if width <= 0 and not shadow:
        return rgba

    pad = int(width * 2 + (shadow[0] + shadow[1] * 3 if shadow else 0)) + 8
    padded = Image.new("RGBA", (rgba.width + 2 * pad, rgba.height + 2 * pad), (0, 0, 0, 0))
    padded.alpha_composite(rgba, (pad, pad))
    rgba = padded

    alpha = np.asarray(rgba.split()[3]).astype(np.float32) / 255.0
    distance = ndi.distance_transform_edt(~(alpha > 0.5))
    ring = np.maximum(np.clip(width + 1.0 - distance, 0, 1), alpha)

    height, width_px = alpha.shape
    canvas = Image.new("RGBA", (width_px, height), (0, 0, 0, 0))

    if shadow:
        offset, blur, opacity = shadow
        blurred = Image.fromarray((ring * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur))
        layer = Image.new("RGBA", (width_px, height), (0, 0, 0, 0))
        layer.putalpha(Image.fromarray((np.asarray(blurred).astype(np.float32) * opacity).astype(np.uint8)))
        canvas.alpha_composite(layer.crop((-offset, -offset, width_px - offset, height - offset)))

    edge = Image.new("RGBA", (width_px, height), tuple(color) + (0,))
    edge.putalpha(Image.fromarray((ring * 255).astype(np.uint8)))
    canvas.alpha_composite(edge)
    canvas.alpha_composite(rgba)
    return canvas


def _trim(rgba: Image.Image, threshold: int = 4) -> Image.Image:
    box = rgba.split()[3].point(lambda v: 255 if v > threshold else 0).getbbox()
    return rgba.crop(box) if box else rgba


def _fit(rgba: Image.Image, room: int) -> Image.Image:
    rgba = _trim(rgba)
    scale = min(room / rgba.width, room / rgba.height)
    return rgba.resize((max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))),
                       Image.LANCZOS)


def _cover(img: Image.Image, edge: int, zoom: float, dx: float, dy: float) -> Image.Image:
    """Fill a square with the image, cropping the overflow. Keeps RGBA transparent."""
    scale = max(edge / img.width, edge / img.height) * max(zoom, 0.2)
    scaled = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                        Image.LANCZOS)
    canvas = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    canvas.paste(scaled, (round((edge - scaled.width) / 2 + dx * edge),
                          round((edge - scaled.height) / 2 + dy * edge)))
    return canvas


class Workshop:
    """Holds one source photo and remembers the expensive intermediate steps.

    Segmenting costs seconds, developing costs a moment, assembling costs
    nothing - so each is cached under the recipe fields that actually affect it.
    A border change re-renders instantly; only a crop forces a new cutout.
    """

    def __init__(self, image: Image.Image, name: str = "sticker"):
        image = image.convert("RGB")
        scale = SOURCE_EDGE / max(image.size)
        if scale < 1.0:
            image = image.resize((round(image.width * scale), round(image.height * scale)),
                                 Image.LANCZOS)
        self.source = image
        self.name = name
        self.suggested_angle = photo.tilt_angle(self.source)
        self._cache: dict[str, Image.Image] = {}
        self._lock = threading.RLock()

    def _framed(self, recipe: Recipe, work_edge: int) -> Image.Image:
        """Rotated, cropped and scaled to working resolution."""
        key = f"frame:{recipe.frame_key}:{work_edge}"
        if key not in self._cache:
            img = self.source
            if recipe.rotate:
                img = img.rotate(recipe.rotate, resample=Image.BICUBIC, expand=True,
                                 fillcolor=(255, 255, 255))
            if recipe.crop:
                x0, y0, x1, y1 = recipe.crop
                box = (int(x0 * img.width), int(y0 * img.height),
                       int(x1 * img.width), int(y1 * img.height))
                if box[2] - box[0] > 10 and box[3] - box[1] > 10:
                    img = img.crop(box)
            scale = work_edge / max(img.width, img.height)
            if not 0.95 < scale < 1.05:
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                                 Image.LANCZOS)
            self._cache[key] = img
        return self._cache[key]

    def _developed(self, recipe: Recipe, work_edge: int) -> Image.Image:
        key = f"image:{recipe.image_key}:{work_edge}"
        if key not in self._cache:
            self._cache[key] = photo.develop(self._framed(recipe, work_edge), recipe.look,
                                             recipe.sharpness, recipe.saturation, recipe.brightness)
        return self._cache[key]

    def _mask(self, recipe: Recipe, size: tuple[int, int]) -> Image.Image:
        """Segment once at full working resolution; thumbnails reuse it scaled."""
        key = "mask:" + recipe.mask_key
        if key not in self._cache:
            img = self._developed(recipe, WORK_EDGE)
            if recipe.source == "lasso" and len(recipe.lasso) >= 3:
                points = [(p[0] * img.width, p[1] * img.height) for p in recipe.lasso]
                mask = cutout.by_lasso(img.size, points)
            elif recipe.source == "full":
                mask = Image.new("L", img.size, 255)
            else:
                mask = cutout.tidy(cutout.by_model(img, recipe.model))
            self._cache[key] = mask
        mask = self._cache[key]
        return mask if mask.size == size else mask.resize(size, Image.LANCZOS)

    def render(self, recipe: Recipe, edge: int = OUTPUT_EDGE, margin: int = 8,
               work_edge: int | None = None) -> Image.Image:
        """The finished sticker, square, transparent around the die."""
        with self._lock:
            image = self._developed(recipe, work_edge or WORK_EDGE)
            scale = edge / OUTPUT_EDGE
            border = max(0, round(recipe.border * scale))
            shadow = (round(6 * scale), round(7 * scale), 0.5) if recipe.shadow else None
            depth = (shadow[0] + shadow[1]) if shadow else 0
            room = max(32, edge - 2 * (round(margin * scale) + border) - depth)

            if recipe.shape == "silhouette":
                subject = image.convert("RGBA")
                subject.putalpha(self._mask(recipe, image.size))
                motif = _fit(subject, room)
            else:
                die = shapes.die(recipe.shape, room)
                motif = _cover(image.convert("RGBA"), room, recipe.zoom, recipe.offset_x, recipe.offset_y)
                motif.putalpha(ImageChops.multiply(motif.split()[3], die))
                if recipe.pop_out and recipe.source != "full":
                    subject = image.convert("RGBA")
                    subject.putalpha(self._mask(recipe, image.size))
                    motif.alpha_composite(_cover(subject, room, recipe.zoom,
                                                 recipe.offset_x, recipe.offset_y))

            sticker = _trim(add_border(motif, border, _rgb(recipe.border_color), shadow), threshold=3)
            if max(sticker.size) > edge:
                shrink = edge / max(sticker.size)
                sticker = sticker.resize((max(1, round(sticker.width * shrink)),
                                          max(1, round(sticker.height * shrink))), Image.LANCZOS)

            canvas = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
            canvas.alpha_composite(sticker, ((edge - sticker.width) // 2, (edge - sticker.height) // 2))
            return canvas


def as_png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def as_webp(img: Image.Image, limit: int = WEBP_LIMIT) -> tuple[bytes, int]:
    """Best quality WebP that still fits WhatsApp's size limit."""
    data = b""
    quality = 92
    for quality in range(92, 39, -6):
        buffer = io.BytesIO()
        img.save(buffer, "WEBP", quality=quality, method=6, exact=True)
        data = buffer.getvalue()
        if len(data) <= limit:
            break
    return data, quality
