"""Безопасный return_url: только внутренние списки, без open redirect."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import request

SAFE_RETURN_PREFIXES = (
    "/requests/",
    "/defects/",
    "/work-orders/",
    "/waybills/",
)


def is_safe_return_url(target: str | None) -> bool:
    if not target or not isinstance(target, str):
        return False
    value = target.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return False
    path = value.split("?", 1)[0]
    if ":" in path or ".." in path:
        return False
    for prefix in SAFE_RETURN_PREFIXES:
        bare = prefix.rstrip("/")
        if path == prefix or path == bare:
            return True
    return False


def _from_referrer() -> str | None:
    referrer = request.referrer or ""
    if not referrer:
        return None
    parsed = urlparse(referrer)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc and parsed.netloc != request.host:
        return None
    path = parsed.path or ""
    query = parsed.query
    candidate = path + (f"?{query}" if query else "")
    if is_safe_return_url(candidate):
        return candidate
    return None


def resolve_return_url(*, fallback: str) -> str:
    """Query `return_url`, иначе безопасный Referer, иначе fallback."""
    raw = (request.args.get("return_url") or "").strip()
    if is_safe_return_url(raw):
        return raw
    from_ref = _from_referrer()
    if from_ref:
        return from_ref
    return fallback if is_safe_return_url(fallback) else "/requests/"


def back_navigation(*, fallback: str) -> tuple[str, str]:
    """(url, label) для кнопки «Назад» на карточке."""
    url = resolve_return_url(fallback=fallback)
    path = url.split("?", 1)[0]
    if path.rstrip("/") == "/work-orders":
        return url, "Назад к работе по заявкам"
    if path.rstrip("/") == "/defects":
        return url, "Назад к дефектам"
    if path.rstrip("/") == "/waybills":
        return url, "Назад к путевым листам"
    return url, "Назад к заявкам"
