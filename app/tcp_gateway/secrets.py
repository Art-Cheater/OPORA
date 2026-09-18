"""Encryption wrapper for device pre-shared secrets at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet() -> Fernet:
    key = current_app.config.get("DEVICE_SECRET_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("DEVICE_SECRET_ENCRYPTION_KEY is required for device provisioning")
    return Fernet(key.encode("ascii"))


def encrypt_device_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_device_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Device secret cannot be decrypted") from exc
