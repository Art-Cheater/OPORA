"""Вход в кабинет сайта тем же логином, что в «Опоре». Только администратор и директор."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

ALLOWED_ROLES = ("admin", "director")
MAX_AGE = 12 * 60 * 60


def _secret() -> bytes:
    secret = os.environ.get("POSTGRES_PASSWORD") or ""
    if not secret:
        raise RuntimeError("Нет POSTGRES_PASSWORD")
    return secret.encode("utf-8")


def sign_session(user_id: str, name: str, csrf: str, now: int | None = None) -> str:
    payload = {
        "uid": user_id,
        "name": name[:80],
        "csrf": csrf,
        "exp": int(now if now is not None else time.time()) + MAX_AGE,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def read_session(token: str | None, now: int | None = None) -> dict | None:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp") or 0) < int(now if now is not None else time.time()):
        return None
    if not payload.get("uid") or not payload.get("csrf"):
        return None
    return payload


def authenticate(connection, email: str, password: str) -> tuple[str, str] | None:
    email = (email or "").strip().lower()
    if not email or not password:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT u.id::text, u.password_hash, u.full_name
            FROM users u
            WHERE lower(u.email) = %s
              AND u.deleted_at IS NULL
              AND u.is_active IS TRUE
              AND u.is_blocked IS FALSE
            """,
            (email,),
        )
        row = cursor.fetchone()
        if row is None or not _password_ok(password, row[1]):
            return "bad"
        cursor.execute(
            """
            SELECT 1
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            LEFT JOIN role_permissions rp
              ON rp.role_id = r.id AND rp.deleted_at IS NULL
            LEFT JOIN permissions p
              ON p.id = rp.permission_id AND p.deleted_at IS NULL
            WHERE ur.user_id = %s
              AND ur.deleted_at IS NULL
              AND r.deleted_at IS NULL
              AND r.is_active IS TRUE
              AND (r.code IN ('admin', 'director') OR p.code = 'roles.manage')
            """,
            (row[0],),
        )
        if cursor.fetchone() is None:
            return "role"
    return row[0], row[2] or email


def _password_ok(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        if password_hash.startswith("$2"):
            import bcrypt
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        from werkzeug.security import check_password_hash
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False
