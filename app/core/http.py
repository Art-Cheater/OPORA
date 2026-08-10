"""HTTP-утилиты для AJAX-взаимодействия."""

from __future__ import annotations

from flask import jsonify, request


def is_ajax() -> bool:
    """Запрос выполнен через Fetch/XHR."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def ajax_ok(message: str = "", **extra):
    """Успешный JSON-ответ."""
    payload = {"success": True, "message": message}
    payload.update(extra)
    return jsonify(payload)


def ajax_error(message: str, errors: dict | None = None, html: str | None = None, status: int = 400):
    """JSON-ответ с ошибкой."""
    payload: dict = {"success": False, "message": message}
    if errors:
        payload["errors"] = errors
    if html is not None:
        payload["html"] = html
    return jsonify(payload), status
