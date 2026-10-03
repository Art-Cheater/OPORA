"""Сайт Кировсвет: статика и карта заявок из базы контейнера db."""

from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import cabinet
import content
import dbmap

_NEWS_SLUG = re.compile(r"^/novosti/([a-z0-9-]{1,80})/?$")
_UPLOAD = re.compile(r"^/uploads/news/([a-f0-9]{32}\.(?:jpg|png|webp))$")

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
        # Раньше этот хост открывал вход в Опору. Для удаления из поиска нужен 404, не редирект.
        if path == "/auth" or path.startswith("/auth/"):
            self._bytes(404, b"not found\n", "text/plain; charset=utf-8", cache="no-store", robots="noindex, nofollow")
            return
        if path == "/api/map.json":
            self._map()
            return
        if path == "/api/content.json":
            self._content()
            return
        if path.startswith("/admin"):
            cabinet.handle_get(self, path)
            return
        upload = _UPLOAD.match(path)
        if upload:
            self._upload(upload.group(1))
            return
        news = _NEWS_SLUG.match(path)
        if news and self._news(news.group(1)):
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

    def do_POST(self):
        path = unquote(self.path.split("?", 1)[0])
        if path.startswith("/admin"):
            cabinet.handle_post(self, path)
            return
        self._bytes(405, b"method", "text/plain; charset=utf-8", cache="no-store")

    def _content(self):
        try:
            connection = dbmap.connect()
            try:
                payload = content.public_content(connection)
            finally:
                connection.close()
        except Exception:
            payload = {"phones": {}, "schedule": {"on_after_sunset": 15, "off_before_sunrise": 15, "days": []}, "news": []}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._bytes(200, body, "application/json; charset=utf-8", cache="public, max-age=10")

    def _news(self, slug: str) -> bool:
        try:
            connection = dbmap.connect()
            try:
                article = content.news_article(connection, slug)
            finally:
                connection.close()
        except Exception:
            return False
        if article is None:
            return False
        styles = []
        folder = ROOT / "_astro"
        if folder.is_dir():
            styles.extend(f'<link rel="stylesheet" href="/_astro/{item.name}">' for item in sorted(folder.glob("*.css")))
        self._bytes(200, cabinet.news_page(article, "\n".join(styles)), "text/html; charset=utf-8", cache="public, max-age=30")
        return True

    def _upload(self, name: str):
        file_path = cabinet.UPLOADS / "news" / name
        if not file_path.is_file():
            self._bytes(404, b"not found", "text/plain; charset=utf-8", cache="no-store")
            return
        kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._bytes(200, file_path.read_bytes(), kind, cache="public, max-age=86400")

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

    def _bytes(self, status: int, body: bytes, content_type: str, cache: str, robots: str | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if robots:
            self.send_header("X-Robots-Tag", robots)
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
