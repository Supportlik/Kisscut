"""Kisscut - turn a photo into a WhatsApp sticker."""
from .workshop import OUTPUT_EDGE, Recipe, Workshop, add_border, as_png, as_webp
from . import cutout, photo, shapes

__version__ = "0.1.0"

__all__ = [
    "Recipe",
    "Workshop",
    "add_border",
    "as_png",
    "as_webp",
    "cutout",
    "photo",
    "shapes",
    "OUTPUT_EDGE",
    "__version__",
]
