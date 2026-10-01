"""Local web interface. Standard library only - no framework to install.

The browser does the pointing: crop box, freehand outline, sliders. Every
render runs here, in the same code the command line uses, so what the preview
shows is the file you get.
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import threading
import time
import webbrowser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

from . import cutout, photo, shapes
from .workshop import THUMB_EDGE, Recipe, Workshop, as_png, as_webp

WEB_DIR = Path(__file__).parent / "web"
MAX_UPLOAD = 40 * 1024 * 1024
MAX_WORKSHOPS = 8
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

#: Thumbnails offered under the canvas: a name and the fields it overrides.
SUGGESTIONS = [
    ("Classic", dict(shape="silhouette", border=14, shadow=False, look="natural")),
    ("Drop shadow", dict(shape="silhouette", border=18, shadow=True, look="warm")),
    ("Punchy", dict(shape="silhouette", border=14, shadow=True, look="punchy")),
    ("Circle", dict(shape="circle", border=16, shadow=True, look="warm")),
    ("Speech bubble", dict(shape="bubble", border=16, shadow=True, look="warm")),
    ("Seal", dict(shape="seal", border=14, shadow=True, look="warm")),
    ("Heart", dict(shape="heart", border=16, shadow=True, look="warm")),
    ("Hairline", dict(shape="silhouette", border=5, shadow=False, look="natural")),
]


class Studio:
    """Keeps the open photos of this session."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self._shops: OrderedDict[str, Workshop] = OrderedDict()
        self._lock = threading.Lock()
        self._counter = 0

    def add(self, image: Image.Image, name: str) -> tuple[str, Workshop]:
        with self._lock:
            self._counter += 1
            key = f"p{self._counter}-{int(time.time())}"
            shop = Workshop(image, name)
            self._shops[key] = shop
            while len(self._shops) > MAX_WORKSHOPS:
                self._shops.popitem(last=False)
            return key, shop

    def get(self, key: str) -> Workshop | None:
        with self._lock:
            shop = self._shops.get(key)
            if shop is not None:
                self._shops.move_to_end(key)
            return shop


class Handler(BaseHTTPRequestHandler):
    server_version = "Kisscut"
    studio: Studio

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):            # quieter console
        if "/api/" in str(args[0] if args else ""):
            return
        super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _fail(self, code: int, message: str):
        self._json({"error": message}, code)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise ValueError("file too large")
        return self.rfile.read(length)

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self._file(WEB_DIR / "index.html")
        if path == "/api/meta":
            return self._json({
                "models": cutout.MODELS,
                "shapes": shapes.SHAPES,
                "looks": list(photo.LOOKS),
                "suggestions": [name for name, _ in SUGGESTIONS],
                "out_dir": str(self.studio.out_dir),
            })
        if path.startswith("/source/"):
            return self._source(path.rsplit("/", 1)[-1])
        if path.startswith("/assets/"):
            target = (WEB_DIR / path[len("/assets/"):]).resolve()
            if WEB_DIR.resolve() in target.parents and target.is_file():
                return self._file(target)
        return self._fail(404, "not found")

    def _file(self, path: Path):
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith(("javascript", "json")):
            kind += "; charset=utf-8"
        self._send(200, path.read_bytes(), kind)

    def _source(self, key: str):
        shop = self.studio.get(key)
        if not shop:
            return self._fail(404, "photo not open")
        img = shop.source
        scale = min(1.0, 1600 / max(img.size))
        if scale < 1.0:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, "JPEG", quality=88)
        self._send(200, buffer.getvalue(), "image/jpeg")

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/open":
                return self._open()
            if path == "/api/preview":
                return self._preview()
            if path == "/api/suggestions":
                return self._suggestions()
            if path == "/api/trace":
                return self._trace()
            if path == "/api/save":
                return self._save()
        except ValueError as err:
            return self._fail(400, str(err))
        except Exception as err:                   # noqa: BLE001 - surface it in the UI
            return self._fail(500, f"{type(err).__name__}: {err}")
        return self._fail(404, "not found")

    def _open(self):
        raw = self._body()
        if not raw:
            raise ValueError("no image received")
        try:
            image = Image.open(io.BytesIO(raw))
            image.load()
        except Exception as err:                   # noqa: BLE001
            raise ValueError(f"cannot read that file ({err})") from err
        name = Path(unquote(self.headers.get("X-Filename", "sticker"))).stem or "sticker"
        key, shop = self.studio.add(image, SAFE_NAME.sub("-", name))
        self._json({
            "id": key,
            "name": shop.name,
            "width": shop.source.width,
            "height": shop.source.height,
            "angle": shop.suggested_angle,
            "source": f"/source/{key}",
        })

    def _recipe(self) -> tuple[Workshop, Recipe, dict]:
        data = json.loads(self._body() or b"{}")
        shop = self.studio.get(data.get("id", ""))
        if not shop:
            raise ValueError("photo not open - load it again")
        return shop, Recipe.from_dict(data.get("recipe", {})), data

    def _preview(self):
        shop, recipe, _ = self._recipe()
        self._send(200, as_png(shop.render(recipe)), "image/png")

    def _suggestions(self):
        shop, recipe, _ = self._recipe()
        out = []
        for name, override in SUGGESTIONS:
            variant = Recipe.from_dict({**recipe.to_dict(), **override})
            thumb = shop.render(variant, edge=176, work_edge=THUMB_EDGE)
            out.append({
                "name": name,
                "recipe": override,
                "png": "data:image/png;base64," + base64.b64encode(as_png(thumb)).decode(),
            })
        self._json({"suggestions": out})

    def _trace(self):
        """Read a red pen outline off an uploaded copy of the photo."""
        shop, recipe, data = self._recipe()
        raw = base64.b64decode(data.get("image", "").split(",")[-1])
        marked = Image.open(io.BytesIO(raw)).convert("RGB")
        mask = cutout.by_red_line(marked)
        box = mask.getbbox()
        if not box:
            raise ValueError("no red outline found - draw one in pure red")
        points = _mask_to_polygon(mask)
        self._json({"lasso": points})

    def _save(self):
        shop, recipe, data = self._recipe()
        sticker = shop.render(recipe)
        stem = SAFE_NAME.sub("-", str(data.get("name") or shop.name)) or "sticker"
        self.studio.out_dir.mkdir(parents=True, exist_ok=True)

        target = self.studio.out_dir / f"{stem}.png"
        index = 2
        while target.exists():
            target = self.studio.out_dir / f"{stem}-{index}.png"
            index += 1

        png = as_png(sticker)
        target.write_bytes(png)
        webp_bytes, quality = as_webp(sticker)
        webp = target.with_suffix(".webp")
        webp.write_bytes(webp_bytes)

        self._json({
            "files": [
                {"name": target.name, "bytes": len(png)},
                {"name": webp.name, "bytes": len(webp_bytes), "quality": quality},
            ],
            "dir": str(self.studio.out_dir),
            "within_limit": len(webp_bytes) <= 100_000,
        })


def _mask_to_polygon(mask: Image.Image, step: int = 6) -> list[list[float]]:
    """Trace the outer boundary of a mask as relative points for the lasso tool."""
    import numpy as np
    from scipy import ndimage as ndi

    solid = np.asarray(mask) > 127
    edge = solid & ~ndi.binary_erosion(solid)
    ys, xs = np.where(edge)
    if not len(xs):
        return []
    centre = (xs.mean(), ys.mean())
    angles = np.arctan2(ys - centre[1], xs - centre[0])
    order = np.argsort(angles)
    xs, ys, angles = xs[order], ys[order], angles[order]

    points: list[list[float]] = []
    for lo in np.linspace(-np.pi, np.pi, 180, endpoint=False):
        band = (angles >= lo) & (angles < lo + 2 * np.pi / 180)
        if not band.any():
            continue
        radius = np.hypot(xs[band] - centre[0], ys[band] - centre[1])
        pick = int(np.argmax(radius))
        points.append([float(xs[band][pick] / mask.width), float(ys[band][pick] / mask.height)])
    return points[::1] if step <= 1 else points


class Server(ThreadingHTTPServer):
    # Windows hands out a port that is already listening when SO_REUSEADDR is
    # set, which would silently leave two studios running. Better to refuse.
    allow_reuse_address = False
    daemon_threads = True


def serve(port: int = 8731, out_dir: Path | None = None, open_browser: bool = True):
    Handler.studio = Studio(Path(out_dir or Path.cwd() / "stickers"))
    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError as err:
        print(f"Port {port} is busy - is Kisscut already running? "
              f"Use --port to pick another one.\n  ({err})")
        raise SystemExit(1) from err
    url = f"http://127.0.0.1:{port}/"
    print(f"Kisscut is running at {url}")
    print(f"Stickers are written to {Handler.studio.out_dir}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
