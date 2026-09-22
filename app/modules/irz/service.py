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


def list_mercury_devices() -> list[IRZDevice]:
    return list(db.session.scalars(db.select(IRZDevice).where(IRZDevice.active_filter()).order_by(IRZDevice.name)))


def sync_runtime_statuses(devices: list[IRZDevice]) -> None:
    try:
        statuses = _gateway_request("/mercury/status")
    except (GatewayUnavailable, GatewayResponseError):
        return
    by_id = {item.get("device_id"): item for item in statuses if isinstance(item, dict)} if isinstance(statuses, list) else {}
    changed = False
    for device in devices:
        runtime = by_id.get(str(device.id), {"state": "DISCONNECTED"})
        if runtime.get("state") != device.connection_state:
            _set_runtime_state(device, runtime)
            changed = True
    if changed:
        db.session.commit()


def device_config(device: IRZDevice) -> dict:
    return {
        "transport_type": device.transport_type,
        "network_address": device.network_address,
        "serial_port": device.serial_port,
        "baudrate": device.baudrate,
        "host": device.host,
        "port": device.port,
        "timeout": (device.connection_params or {}).get("timeout", 5),
    }


def serialize_device(device: IRZDevice) -> dict:
    return {
        "id": str(device.id),
        "name": device.name,
        "model": device.model,
        "serial_number": device.serial_number,
        "network_address": device.network_address,
        "transport_type": device.transport_type,
        "serial_port": device.serial_port,
        "host": device.host,
        "port": device.port,
        "baudrate": device.baudrate,
        "connection_params": device.connection_params or {},
        "enabled": device.enabled,
        "connection_state": device.connection_state,
        "last_connected_at": device.last_connected_at.isoformat() if device.last_connected_at else None,
        "last_polled_at": device.last_polled_at.isoformat() if device.last_polled_at else None,
        "last_success_at": device.last_success_at.isoformat() if device.last_success_at else None,
        "last_error_at": device.last_error_at.isoformat() if device.last_error_at else None,
        "last_latency_ms": device.last_latency_ms,
        "last_error": device.last_error,
    }


def save_device(payload: dict, *, user_id, device: IRZDevice | None = None) -> IRZDevice:
    if not isinstance(payload, dict):
        raise ValueError("invalid request")
    name = str(payload.get("name") or "").strip()
    model = str(payload.get("model") or "Mercury V2").strip()
    transport = str(payload.get("transport_type") or "").upper()
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("invalid enabled flag")
    if not name or len(name) > 160 or not model or len(model) > 40:
        raise ValueError("invalid name or model")
    try:
        address = int(payload.get("network_address"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid network address") from exc
    if not 1 <= address <= 99999999 or transport not in {"SERIAL", "TCP"}:
        raise ValueError("invalid transport parameters")
    values = {
        "name": name,
        "model": model,
        "serial_number": str(payload.get("serial_number") or "").strip() or None,
        "network_address": address,
        "transport_type": transport,
        "serial_port": str(payload.get("serial_port") or "").strip() or None,
        "host": str(payload.get("host") or "").strip() or None,
        "port": int(payload["port"]) if payload.get("port") not in (None, "") else None,
        "baudrate": int(payload.get("baudrate") or 9600),
        "connection_params": {"timeout": min(max(float(payload.get("timeout") or 5), 0.2), 30)},
        "enabled": enabled,
        "updated_by": user_id,
    }
    if transport == "SERIAL" and not values["serial_port"]:
        raise ValueError("serial port is required")
    if transport == "TCP" and (not values["host"] or not values["port"] or not 1 <= values["port"] <= 65535):
        raise ValueError("host and port are required")
    if device is None:
        device = IRZDevice(created_by=user_id, **values)
        db.session.add(device)
    else:
        if device.connection_state != "DISCONNECTED":
            disconnect_device(device)
        for key, value in values.items():
            setattr(device, key, value)
        device.connection_state = "DISCONNECTED"
    db.session.commit()
    return device


def _set_runtime_state(device: IRZDevice, payload: dict) -> None:
    state = str(payload.get("state") or device.connection_state)
    if state in {"DISCONNECTED", "CONNECTING", "CONNECTED", "BUSY", "ERROR"}:
        device.connection_state = state
    device.last_latency_ms = payload.get("last_latency_ms", device.last_latency_ms)
    device.last_error = payload.get("last_error", device.last_error)


def connect_device(device: IRZDevice, *, reconnect: bool = False) -> dict:
    if not device.enabled:
        raise ValueError("DEVICE_DISABLED")
    device.connection_state = "CONNECTING"
    db.session.commit()
    try:
        result = _gateway_request(
            f"/mercury/{'reconnect' if reconnect else 'connect'}",
            payload={"device_id": str(device.id), "config": device_config(device)},
            timeout=35,
        )
    except (GatewayUnavailable, GatewayResponseError) as exc:
        device.connection_state = "ERROR"
        device.last_error_at = datetime.now(timezone.utc)
        device.last_error = str(exc)
        db.session.commit()
        raise
    _set_runtime_state(device, result)
    device.last_connected_at = datetime.now(timezone.utc)
    device.last_error = None
    db.session.commit()
    return result


def disconnect_device(device: IRZDevice) -> dict:
    result = _gateway_request("/mercury/disconnect", payload={"device_id": str(device.id)})
    device.connection_state = "DISCONNECTED"
    db.session.commit()
    return result


def refresh_device_status(device: IRZDevice) -> dict:
    result = _gateway_request(f"/mercury/status/{device.id}")
    _set_runtime_state(device, result)
    db.session.commit()
    return result


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
        device.connection_state = "CONNECTED"
        device.last_success_at = datetime.now(timezone.utc)
        device.last_latency_ms = result.get("duration_ms")
        device.last_error = None
        if command_id == "serial_and_manufacture" and isinstance(result.get("data"), dict):
            device.serial_number = str(result["data"].get("serial_number") or device.serial_number or "") or None
    elif error:
        device.connection_state = "ERROR"
        device.last_error_at = datetime.now(timezone.utc)
        device.last_error = error_message
    db.session.commit()
    return log


def execute_device_command(device: IRZDevice, command_id: str, *, user_id, operation: str = "COMMAND") -> dict:
    if not device.enabled:
        raise ValueError("DEVICE_DISABLED")
    get_command(command_id)
    try:
        result = _gateway_request(
            "/mercury/command" if operation == "COMMAND" else "/mercury/test",
            payload={"device_id": str(device.id), "command_id": command_id},
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
    result = _gateway_request("/mercury/poll", payload={"device_id": str(device.id)}, timeout=35)
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
