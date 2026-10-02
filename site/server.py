"""Сайт Кировсвет: статика и карта заявок из базы контейнера db."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import dbmap

ROOT = Path(__file__).resolve().parent / "dist"
PORT = 80

_SECURITY = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org; font-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
    ),
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=()",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "kirovsvet"

    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/health":
            self._bytes(200, b"ok\n", "text/plain; charset=utf-8", cache="no-store")
            return
        if path == "/api/map.json":
            self._map()
            return
        file_path = self._static(path)
        if file_path is None:
            missing = ROOT / "404.html"
            body = missing.read_bytes() if missing.is_file() else b"not found"
            self._bytes(404, body, "text/html; charset=utf-8", cache="no-store")
            return
        data = file_path.read_bytes()
        kind = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        cache = "public, max-age=31536000, immutable" if "/_astro/" in path else "public, max-age=300"
        self._bytes(200, data, kind, cache=cache)

    def _map(self):
        try:
            connection = dbmap.connect()
        except Exception:
            self._bytes(503, b'{"ok":false}', "application/json; charset=utf-8", cache="no-store")
            return
        try:
            items = dbmap.load_open_requests(connection)
        except Exception:
            self._bytes(503, b'{"ok":false}', "application/json; charset=utf-8", cache="no-store")
            return
        finally:
            connection.close()
        body = json.dumps({"ok": True, "items": items}, ensure_ascii=False).encode("utf-8")
        self._bytes(200, body, "application/json; charset=utf-8", cache="public, max-age=30")

    def _static(self, path: str) -> Path | None:
        if path != "/" and ".." in path:
            return None
        relative = path.lstrip("/")
        root = ROOT.resolve()

        def inside(candidate: Path) -> Path | None:
            try:
                candidate.resolve().relative_to(root)
            except ValueError:
                return None
            return candidate

        candidate = inside(ROOT / relative)
        if candidate is not None and candidate.is_dir():
            candidate = inside(candidate / "index.html")
        if candidate is not None and candidate.is_file():
            return candidate
        index = inside(ROOT / relative / "index.html")
        if index is not None and index.is_file():
            return index
        return None

    def _bytes(self, status: int, body: bytes, content_type: str, cache: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for name, value in _SECURITY.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
