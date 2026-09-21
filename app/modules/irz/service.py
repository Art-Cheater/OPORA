"""IRZ control client and exchange-log queries."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from app.extensions import db
from app.models.irz import IRZExchangeLog, IRZExperiment


class GatewayUnavailable(RuntimeError):
    pass


class GatewayResponseError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def normalize_hex(value: object) -> tuple[str, bytes]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid HEX")
    try:
        data = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("invalid HEX") from exc
    if not data:
        raise ValueError("invalid HEX")
    return data.hex(" ").upper(), data


def _gateway_request(path: str, *, payload: dict | None = None, timeout: float | None = None):
    base_url = current_app.config["IRZ_GATEWAY_URL"].rstrip("/")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout or current_app.config["IRZ_GATEWAY_TIMEOUT_SECONDS"]) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("error")
        except (ValueError, AttributeError):
            detail = None
        status = 409 if exc.code == 404 else exc.code
        raise GatewayResponseError(detail or "gateway request failed", status) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GatewayUnavailable("gateway unavailable") from exc


def get_devices() -> list[dict]:
    payload = _gateway_request("/devices")
    if not isinstance(payload, list):
        raise GatewayUnavailable("gateway returned invalid response")
    return payload


def send_command(imei: str, hex_value: object) -> dict:
    if not isinstance(imei, str) or len(imei) != 15 or not imei.isdigit():
        raise ValueError("invalid IMEI")
    normalized, _data = normalize_hex(hex_value)
    payload = _gateway_request("/send", payload={"imei": imei, "hex": normalized})
    if not isinstance(payload, dict):
        raise GatewayUnavailable("gateway returned invalid response")
    return payload


def modbus_crc16(data: bytes) -> bytes:
    """CRC-16/MODBUS, serialized low byte first as it appears on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def mercury_crc(data: bytes) -> bytes:
    """Mercury protocol CRC (the documented MODBUS CRC16 polynomial)."""
    return modbus_crc16(data)


def build_test_command(hex_value: object, crc: object = "none", append: object = "none") -> bytes:
    _normalized, data = normalize_hex(hex_value)
    crc_mode = str(crc or "none").strip().lower().replace(" ", "_")
    append_mode = str(append or "none").strip().lower().replace(" ", "")
    crc_mode = {"modbus_crc16": "modbus", "mercury_crc": "mercury"}.get(crc_mode, crc_mode)
    if crc_mode == "modbus":
        data += modbus_crc16(data)
    elif crc_mode == "mercury":
        data += mercury_crc(data)
    elif crc_mode != "none":
        raise ValueError("invalid CRC mode")
    suffixes = {"none": b"", "0d": b"\r", "0a": b"\n", "0d0a": b"\r\n"}
    if append_mode not in suffixes:
        raise ValueError("invalid append mode")
    return data + suffixes[append_mode]


def run_experiment(imei: str, hex_value: object, *, crc: object, append: object, user_id) -> IRZExperiment:
    if not isinstance(imei, str) or len(imei) != 15 or not imei.isdigit():
        raise ValueError("invalid IMEI")
    command = build_test_command(hex_value, crc, append)
    experiment = IRZExperiment(
        imei=imei,
        command_hex=command.hex(" ").upper(),
        response_hex="",
        response_ascii="",
        success=False,
        created_by=user_id,
        updated_by=user_id,
    )
    db.session.add(experiment)
    db.session.commit()
    try:
        payload = _gateway_request(
            "/test-command",
            payload={"imei": imei, "hex": experiment.command_hex},
            timeout=6.5,
        )
    except (GatewayUnavailable, GatewayResponseError):
        experiment.success = False
        db.session.commit()
        raise
    if not isinstance(payload, dict):
        raise GatewayUnavailable("gateway returned invalid response")
    experiment.response_hex = str(payload.get("response_hex") or "")
    experiment.response_ascii = str(payload.get("response_ascii") or "")
    experiment.success = bool(payload.get("success"))
    db.session.commit()
    return experiment


def recent_logs(*, limit: int = 200, imei: str | None = None) -> list[IRZExchangeLog]:
    query = db.select(IRZExchangeLog).where(IRZExchangeLog.active_filter())
    if imei:
        query = query.where(IRZExchangeLog.imei == imei)
    return list(db.session.scalars(query.order_by(IRZExchangeLog.created_at.desc()).limit(limit)))[::-1]


def all_logs(*, imei: str | None = None) -> list[IRZExchangeLog]:
    query = db.select(IRZExchangeLog).where(IRZExchangeLog.active_filter())
    if imei:
        query = query.where(IRZExchangeLog.imei == imei)
    return list(db.session.scalars(query.order_by(IRZExchangeLog.created_at.asc())))


def recent_experiments(*, limit: int = 50, imei: str | None = None) -> list[IRZExperiment]:
    query = db.select(IRZExperiment).where(IRZExperiment.active_filter())
    if imei:
        query = query.where(IRZExperiment.imei == imei)
    return list(db.session.scalars(query.order_by(IRZExperiment.created_at.desc()).limit(limit)))


def record_exchange(imei: str | None, direction: str, data: bytes) -> None:
    text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data)
    db.session.add(
        IRZExchangeLog(
            imei=imei,
            direction=direction,
            raw_hex=data.hex(" ").upper(),
            raw_ascii=text,
            raw_length=len(data),
        )
    )
    db.session.commit()
