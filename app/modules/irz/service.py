"""IRZ control client and exchange-log queries."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from app.extensions import db
from app.models.irz import IRZDevice, IRZExchangeLog, IRZExperiment, IRZOperationLog
from app.modules.irz.commands import command_list, get_command


class GatewayUnavailable(RuntimeError):
    pass


class GatewayResponseError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502, error_code: str = "GATEWAY_ERROR", details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


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
        error_payload = {}
        try:
            error_payload = json.loads(exc.read())
            detail = error_payload.get("message") or error_payload.get("error")
            error_code = error_payload.get("error_code") or "GATEWAY_ERROR"
        except (ValueError, AttributeError):
            detail = None
            error_code = "GATEWAY_ERROR"
        status = 409 if exc.code == 404 else exc.code
        raise GatewayResponseError(detail or "gateway request failed", status, error_code, error_payload if isinstance(error_payload, dict) else {}) from exc
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


def record_exchange(imei: str | None, direction: str, data: bytes, packet_type: str | None = None) -> None:
    text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data)
    db.session.add(
        IRZExchangeLog(
            imei=imei,
            direction=direction,
            raw_hex=data.hex(" ").upper(),
            raw_ascii=text,
            raw_length=len(data),
            packet_type=packet_type,
        )
    )
    db.session.commit()


def _device_id(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid device id") from exc


def get_device(value: object) -> IRZDevice:
    device = db.session.get(IRZDevice, _device_id(value))
    if device is None or device.deleted_at is not None:
        raise LookupError("device not found")
    return device


def upsert_atm21(metadata: dict) -> IRZDevice:
    """Persist identification metadata; the live socket remains in the gateway."""
    imei = str(metadata.get("imei") or "")
    if len(imei) != 15 or not imei.isdigit():
        raise ValueError("invalid IMEI")
    device = db.session.scalar(db.select(IRZDevice).where(IRZDevice.imei == imei))
    if device is None:
        device = IRZDevice(imei=imei, name=f"ATM21 {imei}", model="ATM21", network_address=None,
                           transport_type=None, enabled=True)
        db.session.add(device)
    mapping = {"dev": "device_type", "ver": "firmware_version", "rev": "firmware_revision",
               "bld": "firmware_build", "hdw": "hardware_version", "sim": "sim", "atp": "atp",
               "int": "interfaces", "ip": "last_ip"}
    for source, target in mapping.items():
        if metadata.get(source) is not None:
            setattr(device, target, str(metadata[source]))
    if metadata.get("csq") not in (None, ""):
        try: device.csq = int(metadata["csq"])
        except (TypeError, ValueError): pass
    now = datetime.now(timezone.utc)
    try:
        connected_at = datetime.fromisoformat(str(metadata.get("connected_at"))) if metadata.get("connected_at") else now
        last_seen_at = datetime.fromisoformat(str(metadata.get("last_seen_at"))) if metadata.get("last_seen_at") else now
    except ValueError:
        connected_at = last_seen_at = now
    device.last_seen_at = last_seen_at
    if device.last_connected_at is None or device.last_connected_at != connected_at:
        device.last_connected_at = connected_at
    db.session.commit()
    return device


def list_mercury_devices() -> tuple[list[IRZDevice], set[str], dict[str, dict]]:
    try:
        live = _gateway_request("/devices")
    except (GatewayUnavailable, GatewayResponseError):
        live = []
    if not isinstance(live, list):
        raise GatewayUnavailable("gateway returned invalid response")
    by_imei = {item["imei"]: item for item in live if isinstance(item, dict) and item.get("imei")}
    for metadata in by_imei.values():
        upsert_atm21(metadata)
    devices = list(db.session.scalars(db.select(IRZDevice).where(IRZDevice.active_filter(), IRZDevice.imei.is_not(None)).order_by(IRZDevice.name)))
    return devices, set(by_imei), by_imei


def serialize_device(device: IRZDevice, *, online: bool = False, runtime: dict | None = None) -> dict:
    runtime = runtime or {}
    return {
        "id": str(device.id),
        "name": device.name,
        "model": device.model,
        "serial_number": device.serial_number,
        "network_address": device.network_address,
        "imei": device.imei,
        "device_type": device.device_type,
        "firmware_version": device.firmware_version,
        "firmware_revision": device.firmware_revision,
        "firmware_build": device.firmware_build,
        "hardware_version": device.hardware_version,
        "csq": device.csq,
        "interfaces": device.interfaces,
        "ip": runtime.get("ip") or device.last_ip,
        "port": runtime.get("port"),
        "connected_at": runtime.get("connected_at"),
        "last_seen_at": runtime.get("last_seen_at") or (device.last_seen_at.isoformat() if device.last_seen_at else None),
        "enabled": device.enabled,
        "online": online,
        "connection_state": "ONLINE" if online else "OFFLINE",
        "last_connected_at": device.last_connected_at.isoformat() if device.last_connected_at else None,
        "last_polled_at": device.last_polled_at.isoformat() if device.last_polled_at else None,
        "last_success_at": device.last_success_at.isoformat() if device.last_success_at else None,
        "last_error_at": device.last_error_at.isoformat() if device.last_error_at else None,
        "last_latency_ms": device.last_latency_ms,
        "last_error": device.last_error,
    }


def set_network_address(device: IRZDevice, value: object) -> None:
    try:
        address = int(value)
        driver = __import__("mercury_base").mercury_v2
        driver.format_address(driver.prepare_address(address))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("INVALID_ADDRESS") from exc
    device.network_address = address
    db.session.commit()


def _store_operation(device: IRZDevice, user_id, command_id: str, operation: str, result: dict | None = None, error: GatewayResponseError | GatewayUnavailable | None = None) -> IRZOperationLog:
    status = "SUCCESS"
    error_code = error_message = None
    if error is not None:
        error_code = error.error_code if isinstance(error, GatewayResponseError) else "CONNECTION_ERROR"
        error_message = str(error)
        status = "TIMEOUT" if error_code == "MERCURY_TIMEOUT" else "ERROR"
    command = None
    try:
        command = get_command(command_id, require_available=False)
    except (KeyError, ValueError):
        pass
    log = IRZOperationLog(
        device_id=device.id,
        user_id=user_id,
        command_id=command_id,
        mercury_command=command.mercury_command if command else None,
        operation=operation,
        request_parameters={},
        status=status,
        result=result.get("data") if result else None,
        error_code=error_code,
        error_message=error_message,
        duration_ms=result.get("duration_ms") if result else (error.details.get("duration_ms") if isinstance(error, GatewayResponseError) else None),
        tx_raw=(result or {}).get("tx_raw") if result else (error.details.get("tx_raw") if isinstance(error, GatewayResponseError) else None),
        rx_raw=(result or {}).get("rx_raw") if result else (error.details.get("rx_raw") if isinstance(error, GatewayResponseError) else None),
        created_by=user_id,
        updated_by=user_id,
    )
    db.session.add(log)
    if result:
        device.last_success_at = datetime.now(timezone.utc)
        device.last_latency_ms = result.get("duration_ms")
        device.last_error = None
        if command_id == "serial_and_manufacture" and isinstance(result.get("data"), dict):
            device.serial_number = str(result["data"].get("serial_number") or device.serial_number or "") or None
    elif error:
        device.last_error_at = datetime.now(timezone.utc)
        device.last_error = error_message
    db.session.commit()
    return log


def execute_device_command(device: IRZDevice, command_id: str, *, user_id, operation: str = "COMMAND") -> dict:
    if not device.enabled:
        raise ValueError("DEVICE_DISABLED")
    get_command(command_id)
    if device.network_address is None:
        raise ValueError("MERCURY_ADDRESS_REQUIRED")
    try:
        result = _gateway_request(
            "/mercury/command" if operation == "COMMAND" else "/mercury/test",
            payload={"imei": device.imei, "network_address": device.network_address, "command_id": command_id},
            timeout=7,
        )
    except (GatewayResponseError, GatewayUnavailable) as exc:
        _store_operation(device, user_id, command_id, operation, error=exc)
        raise
    _store_operation(device, user_id, command_id, operation, result=result)
    return result


def poll_device(device: IRZDevice, *, user_id) -> dict:
    if not device.enabled:
        raise ValueError("DEVICE_DISABLED")
    if device.network_address is None:
        raise ValueError("MERCURY_ADDRESS_REQUIRED")
    result = _gateway_request("/mercury/poll", payload={"imei": device.imei, "network_address": device.network_address}, timeout=35)
    for command_id, command_result in result.get("results", {}).items():
        _store_operation(device, user_id, command_id, "POLL", result=command_result)
    for error in result.get("errors", []):
        gateway_error = GatewayResponseError(error.get("message", "Ошибка опроса"), 502, error.get("error_code", "PROTOCOL_ERROR"), error)
        _store_operation(device, user_id, error.get("command", "poll"), "POLL", error=gateway_error)
    device.last_polled_at = datetime.now(timezone.utc)
    db.session.commit()
    return result


def operation_logs(device: IRZDevice, *, limit: int = 100, status: str | None = None) -> list[IRZOperationLog]:
    query = db.select(IRZOperationLog).where(IRZOperationLog.active_filter(), IRZOperationLog.device_id == device.id)
    if status in {"SUCCESS", "ERROR", "TIMEOUT"}:
        query = query.where(IRZOperationLog.status == status)
    return list(db.session.scalars(query.order_by(IRZOperationLog.created_at.desc()).limit(min(max(limit, 1), 200))))
