"""The studio only answers requests that come from the studio itself."""
from __future__ import annotations

import http.client
import io
import threading
from pathlib import Path

import pytest
from PIL import Image

from kisscut.server import Handler, Server, Studio


@pytest.fixture()
def studio(tmp_path: Path):
    Handler.studio = Studio(tmp_path / "stickers")
    httpd = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def request(port: int, method: str, path: str, body: bytes = b"", **headers):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", headers.pop("Host", f"127.0.0.1:{port}"))
    for key, value in headers.items():
        conn.putheader(key.replace("_", "-"), value)
    conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 80, 40)).save(buffer, "PNG")
    return buffer.getvalue()


def test_same_origin_requests_work(studio):
    assert request(studio, "GET", "/api/meta")[0] == 200
    assert request(studio, "GET", "/api/meta", Host=f"localhost:{studio}")[0] == 200
    status, _ = request(studio, "POST", "/api/open", png_bytes(),
                        Origin=f"http://127.0.0.1:{studio}", Sec_Fetch_Site="same-origin")
    assert status == 200


def test_foreign_host_is_refused(studio):
    # DNS rebinding: a page on evil.example resolves its own name to 127.0.0.1.
    assert request(studio, "GET", "/api/meta", Host=f"evil.example:{studio}")[0] == 403
    assert request(studio, "POST", "/api/open", png_bytes(), Host="evil.example")[0] == 403


def test_cross_site_post_is_refused(studio):
    assert request(studio, "POST", "/api/open", png_bytes(),
                   Origin="https://evil.example")[0] == 403
    assert request(studio, "POST", "/api/open", png_bytes(), Sec_Fetch_Site="cross-site")[0] == 403
    assert request(studio, "POST", "/api/open", png_bytes(), Origin="null")[0] == 403


def test_asset_paths_stay_inside_the_web_folder(studio):
    assert request(studio, "GET", "/assets/app.js")[0] == 200
    assert request(studio, "GET", "/assets/../server.py")[0] == 404
    assert request(studio, "GET", "/assets/%2e%2e/server.py")[0] == 404
