"""Публичный JSON карты. Без сессии, без корзины полей и без записи."""

from __future__ import annotations

import threading
import time
from collections import deque

from flask import jsonify, request

from app.modules.public_site.blueprint import public_site_bp
from app.modules.public_site.service import PUBLIC_FIELDS, public_open_requests

_ALLOWED_HOSTS = frozenset({"kirovsvet.truthqwark.ru", "localhost", "127.0.0.1"})
_WINDOW_SECONDS = 60
_MAX_PER_WINDOW = 60
_hits: dict[str, deque[float]] = {}
_hits_lock = threading.Lock()


@public_site_bp.get("/map.json")
def map_json():
    host = (request.host or "").split(":")[0].lower()
    if host not in _ALLOWED_HOSTS:
        return jsonify({"ok": False}), 404
    if not _allow(request.remote_addr or "unknown"):
        response = jsonify({"ok": False})
        response.status_code = 429
        response.headers["Retry-After"] = str(_WINDOW_SECONDS)
        response.headers["Cache-Control"] = "no-store"
        return response
    items = [
        {key: item[key] for key in PUBLIC_FIELDS if key in item}
        for item in public_open_requests()
    ]
    response = jsonify({"ok": True, "items": items})
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["X-Robots-Tag"] = "noindex"
    return response


def _allow(ip: str) -> bool:
    now = time.monotonic()
    with _hits_lock:
        bucket = _hits.setdefault(ip, deque())
        while bucket and now - bucket[0] > _WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= _MAX_PER_WINDOW:
            return False
        bucket.append(now)
        return True
