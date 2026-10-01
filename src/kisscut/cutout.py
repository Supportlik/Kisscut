"""Deciding what belongs on the sticker.

Three ways to get there: let a segmentation model find the subject, trace it by
hand, or hand in a photo with a line drawn around the subject in red pen.
"""
from __future__ import annotations

import threading

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as ndi

#: Models rembg can fetch, with what each is good for.
#: The time is what one cutout costs on a normal CPU - worth knowing before
#: picking, since everything else in the studio reacts instantly.
MODELS: dict[str, str] = {
    "birefnet-portrait": "People, cleanest edges (~6 s)",
    "birefnet-general-lite": "Anything, keeps surroundings (~4 s)",
    "u2net_human_seg": "People, generous (~2 s)",
    "isnet-general-use": "Objects, hard edges (~2 s)",
    "u2net": "General purpose (~2 s)",
}

_sessions: dict[str, object] = {}
_session_lock = threading.Lock()


def _session(model: str):
    """One rembg session per model, created once and shared."""
    with _session_lock:
        if model not in _sessions:
            from rembg import new_session
            _sessions[model] = new_session(model)
        return _sessions[model]


def by_model(img: Image.Image, model: str = "birefnet-portrait") -> Image.Image:
    """Raw alpha channel from a segmentation model."""
    from rembg import remove
    return remove(img, session=_session(model), post_process_mask=False).split()[3]


def tidy(alpha: Image.Image, min_fraction: float = 0.06, feather: float = 3.0,
         shrink: int = 1, cut_below: int | None = None) -> Image.Image:
    """Turn a raw model mask into something that can carry a border.

    Drops stray fragments, fills holes, pulls the edge in by a hair to avoid a
    halo of background, and feathers what is left.
    """
    m = np.asarray(alpha).astype(np.float32) / 255.0
    solid = m > 0.5

    labels, count = ndi.label(solid)
    if count > 1:
        sizes = ndi.sum(solid, labels, range(1, count + 1))
        keep = np.zeros_like(solid)
        for index, size in enumerate(sizes, start=1):
            if size >= sizes.max() * min_fraction:
                keep |= labels == index
        solid = keep

    solid = ndi.binary_fill_holes(solid)
    if shrink:
        solid = ndi.binary_erosion(solid, iterations=shrink)
    if cut_below is not None:
        solid[cut_below:, :] = False

    # Binary on purpose: keeping the model's own values here would undo the
    # hole filling and leave half-transparent patches inside the subject. The
    # soft edge is rebuilt by the blur below.
    out = solid.astype(np.float32)
    out = np.asarray(
        Image.fromarray((out * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(feather)),
        dtype=np.float32,
    ) / 255.0
    out = np.clip((out - 0.35) / 0.4, 0, 1)      # tighten the feathered edge again
    if cut_below is not None:
        out[cut_below:, :] = 0.0
    return Image.fromarray((out * 255).astype(np.uint8))


def by_lasso(size: tuple[int, int], points, feather: float = 4.0) -> Image.Image:
    """Mask from a freehand outline. ``points`` are (x, y) in pixels."""
    mask = Image.new("L", size, 0)
    points = [tuple(p) for p in points]
    if len(points) >= 3:
        ImageDraw.Draw(mask).polygon(points, fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
        a = np.asarray(mask).astype(np.float32) / 255.0
        mask = Image.fromarray((np.clip((a - 0.4) / 0.35, 0, 1) * 255).astype(np.uint8))
    return mask


def by_red_line(annotated: Image.Image) -> Image.Image:
    """Mask from a line drawn on the photo in pure red (255, 0, 0).

    Floods inward from the image border rather than filling holes, so an
    outline that runs close to the edge still works, then grows back to the
    middle of the drawn stroke.
    """
    a = np.asarray(annotated.convert("RGB")).astype(int)
    line = (a[..., 0] > 200) & (a[..., 1] < 60) & (a[..., 2] < 60)
    if not line.any():
        return Image.new("L", annotated.size, 0)

    half_width = max(float(ndi.distance_transform_edt(line).max()), 1.0)
    free = ~ndi.binary_dilation(line, np.ones((7, 7)))       # close pen gaps
    labels, _ = ndi.label(free)
    border = set(labels[0].tolist()) | set(labels[-1].tolist())
    border |= set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    border.discard(0)

    inside = free & ~np.isin(labels, list(border))
    inside = ndi.binary_dilation(inside, np.ones((3, 3)), iterations=int(half_width) + 3)
    inside = ndi.binary_fill_holes(inside)

    labels, count = ndi.label(inside)
    if count > 1:
        sizes = ndi.sum(inside, labels, range(1, count + 1))
        inside = labels == (int(np.argmax(sizes)) + 1)

    soft = np.asarray(
        Image.fromarray((inside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5)),
        dtype=np.float32,
    ) / 255.0
    return Image.fromarray((np.clip((soft - 0.4) / 0.35, 0, 1) * 255).astype(np.uint8))
