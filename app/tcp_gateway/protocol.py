"""Authentication JSON and lightweight v2 text protocol primitives.

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


def encode_v2_frame(command: str) -> bytes:
    """Encode one strict ASCII v2 line without allowing frame injection."""
    if not command or "\n" in command or "\r" in command:
        raise ValueError("invalid v2 command")
    return (command + "\n").encode("ascii")


def decode_v2_frame(raw: bytes, max_size: int) -> tuple[str, list[str]]:
    """Decode a device v2 line into an uppercase verb and opaque arguments."""
    if not raw or len(raw) > max_size:
        raise ValueError("frame size")
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("v2 frame must be ascii") from exc
    if not text:
        raise ValueError("empty v2 frame")
    parts = text.split()
    return parts[0].upper(), parts[1:]


def _parse_bitmask(value: str, width: int) -> int:
    if len(value) != width or any(bit not in "01" for bit in value):
        raise ValueError("invalid bitmask")
    return int(value, 2)


def parse_v2_state(args: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse extensible ``STATE KEY=VALUE`` into OPORA-owned state semantics."""
    values: dict[str, str] = {}
    for item in args:
        if "=" not in item:
            raise ValueError("invalid state token")
        key, value = item.split("=", 1)
        key = key.upper()
        if not key or not value:
            raise ValueError("invalid state token")
        values[key] = value

    outputs: dict[str, int] = {}
    if "O" in values:
        output_bits = values.pop("O")
        if len(output_bits) != 3 or any(bit not in "01" for bit in output_bits):
            raise ValueError("invalid output bitmask")
        outputs = {relay: int(bit) for relay, bit in zip(("C6", "C7", "C8"), output_bits, strict=True)}

    inputs: dict[str, int] = {}
    raw: dict[str, str] = {}
    if "U2" in values:
        encoded = values.pop("U2")
        mask = _parse_bitmask(encoded, 4)
        raw["U2"] = encoded
        inputs.update({name: (mask >> bit) & 1 for bit, name in enumerate(("SW2", "SW3", "SW4", "SW5"))})
    if "U3" in values:
        encoded = values.pop("U3")
        mask = _parse_bitmask(encoded, 8)
        raw["U3"] = encoded
        mapping = {7: "REF", 0: "AUX0", 1: "G1", 2: "G2", 3: "G3", 4: "G4", 5: "G5", 6: "AUX6"}
        inputs.update({name: (mask >> bit) & 1 for bit, name in mapping.items()})

    telemetry: dict[str, Any] = {}
    for key, value in values.items():
        telemetry[key.lower()] = int(value) if value.isdigit() else value
    return {"outputs": outputs, "inputs": inputs, "raw": raw}, telemetry
