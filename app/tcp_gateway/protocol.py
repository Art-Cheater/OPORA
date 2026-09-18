"""Versioned newline-delimited JSON protocol primitives.

This is an OPORA gateway contract, not a claim of compatibility with any
existing BGS2T/IPP firmware. Firmware must implement this exact contract before
it is pointed at the production TCP endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any


def new_nonce() -> str:
    return secrets.token_urlsafe(32)


def auth_message(device_id: str, nonce: str) -> bytes:
    return f"{device_id}:{nonce}".encode("utf-8")


def calculate_hmac(secret: str, device_id: str, nonce: str) -> str:
    return hmac.new(secret.encode("utf-8"), auth_message(device_id, nonce), hashlib.sha256).hexdigest()


def hmac_matches(secret: str, device_id: str, nonce: str, provided: str) -> bool:
    return hmac.compare_digest(calculate_hmac(secret, device_id, nonce), provided or "")


def encode_frame(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def decode_frame(raw: bytes, max_size: int) -> dict[str, Any]:
    if not raw or len(raw) > max_size:
        raise ValueError("frame size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid json") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        raise ValueError("invalid envelope")
    return payload
