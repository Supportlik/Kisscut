"""Command line: run the studio, or cut a sticker straight from a file."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from . import __version__, cutout, photo, shapes
from .workshop import Recipe, Workshop, as_png, as_webp


def _add_recipe_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--look", default=None, choices=list(photo.LOOKS),
                        help="default: print for a photographed print, otherwise as-shot")
    parser.add_argument("--shape", default="silhouette", choices=list(shapes.SHAPES))
    parser.add_argument("--model", default="birefnet-portrait", choices=list(cutout.MODELS))
    parser.add_argument("--source", default="model", choices=["model", "full"],
                        help="what to keep: the subject the model finds, or the whole frame")
    parser.add_argument("--border", type=int, default=14, help="border width in pixels at 512")
    parser.add_argument("--border-color", default="#ffffff")
    parser.add_argument("--no-shadow", action="store_true")
    parser.add_argument("--no-pop-out", action="store_true",
                        help="keep the subject inside a geometric shape")
    parser.add_argument("--rotate", type=float, default=None,
                        help="degrees counter-clockwise; omit to auto-detect a tilted print")
    parser.add_argument("--sharpness", type=float, default=1.0)
    parser.add_argument("--saturation", type=float, default=1.0)
    parser.add_argument("--brightness", type=float, default=1.0)


def _recipe_from(args, shop: Workshop) -> Recipe:
    return Recipe(
        rotate=shop.suggested_angle if args.rotate is None else args.rotate,
        look=args.look or ("print" if shop.suggested_angle else "as-shot"),
        shape=args.shape,
        model=args.model,
        source=args.source,
        border=args.border,
        border_color=args.border_color,
        shadow=not args.no_shadow,
        pop_out=not args.no_pop_out,
        sharpness=args.sharpness,
        saturation=args.saturation,
        brightness=args.brightness,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kisscut",
        description="Turn a photo into a WhatsApp sticker: cut out, bordered, 512x512.",
    )
    parser.add_argument("--version", action="version", version=f"kisscut {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("serve", help="open the studio in a browser")
    run.add_argument("--port", type=int, default=8731)
    run.add_argument("--out", type=Path, default=None, help="where stickers are written")
    run.add_argument("--no-browser", action="store_true")

    make = sub.add_parser("make", help="cut one sticker without the interface")
    make.add_argument("image", type=Path)
    make.add_argument("-o", "--out", type=Path, default=Path("stickers"))
    make.add_argument("--name", default=None)
    _add_recipe_flags(make)

    args = parser.parse_args(argv)

    if args.command == "serve":
        from .server import serve
        serve(port=args.port, out_dir=args.out, open_browser=not args.no_browser)
        return 0

    if not args.image.is_file():
        print(f"No such file: {args.image}", file=sys.stderr)
        return 1

    shop = Workshop(Image.open(args.image), args.image.stem)
    sticker = shop.render(_recipe_from(args, shop))

    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.name or args.image.stem
    png_path = args.out / f"{stem}.png"
    webp_path = args.out / f"{stem}.webp"
    png = as_png(sticker)
    webp, quality = as_webp(sticker)
    png_path.write_bytes(png)
    webp_path.write_bytes(webp)

    print(f"{png_path}  {len(png) / 1024:.0f} KB")
    print(f"{webp_path}  {len(webp) / 1024:.0f} KB (quality {quality})")
    if len(webp) > 100_000:
        print("Warning: over WhatsApp's 100 KB limit for static stickers.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
