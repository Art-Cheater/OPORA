"""IRZ control client and exchange-log queries."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from app.extensions import db
from app.models.irz import IRZDevice, IRZExchangeLog, IRZExperiment, IRZMeter, IRZMeterSnapshot, IRZOperationLog
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


def get_device_by_imei(imei: object) -> IRZDevice:
    value = str(imei or "").strip()
    if len(value) != 15 or not value.isdigit():
        raise ValueError("invalid IMEI")
    device = db.session.scalar(db.select(IRZDevice).where(IRZDevice.active_filter(), IRZDevice.imei == value))
    if device is None:
        raise LookupError("device not found")
    return device


def upsert_atm21(metadata: dict) -> IRZDevice:
    """Persist identification metadata; the live socket remains in the gateway."""
    imei = str(metadata.get("imei") or "")
    if len(imei) != 15 or not imei.isdigit():
        raise ValueError("invalid IMEI")
    device = db.session.scalar(db.select(IRZDevice).where(IRZDevice.imei == imei))
    if device is None:
        device = IRZDevice(imei=imei, name=f"ATM21 {imei}", model="ATM21", network_address=0,
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
    meter = db.session.scalar(
        db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id)
        .order_by(IRZMeter.last_seen_at.desc())
    )
    latest = latest_meter_snapshot(meter) if meter else None
    stale_seconds = int(current_app.config.get("IRZ_DATA_FRESH_SECONDS", 900))
    is_stale = not latest or (datetime.now(timezone.utc) - _aware(latest.captured_at)).total_seconds() > stale_seconds
    return {
        "id": str(device.id),
        "name": device.name,
        "model": device.model,
        "serial_number": device.serial_number,
        "network_address": device.network_address if device.network_address is not None else 0,
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
        "last_mercury_seen_at": device.last_mercury_seen_at.isoformat() if device.last_mercury_seen_at else None,
        "mercury_responding": bool(device.last_mercury_seen_at and (not device.last_error_at or device.last_mercury_seen_at.timestamp() >= device.last_error_at.timestamp())),
        "last_values": {
            "serial_number": device.serial_number,
            "date_of_manufacture": device.last_manufacture_date.isoformat() if device.last_manufacture_date else None,
            "firmware_version": device.last_firmware_version,
            "transformation_ratios": device.last_transformation_ratios,
        },
        "location": {"latitude": device.latitude, "longitude": device.longitude, "address_text": device.address_text},
        "data_state": "NO_DATA" if latest is None else ("STALE" if is_stale else latest.status),
        "stale": is_stale,
        "latest": serialize_snapshot(latest, include_delta=True) if latest else None,
        "meter": serialize_meter(meter) if meter else None,
    }


def serialize_meter(meter: IRZMeter) -> dict:
    return {
        "id": str(meter.id), "serial_number": meter.serial_number, "custom_name": meter.custom_name,
        "display_name": meter.custom_name or f"Mercury {meter.serial_number}", "model": meter.model,
        "model_source": meter.model_source,
        "manufacture_date": meter.manufacture_date.isoformat() if meter.manufacture_date else None,
        "firmware_version": meter.firmware_version,
        "last_seen_at": meter.last_seen_at.isoformat() if meter.last_seen_at else None,
        "last_poll_at": meter.last_poll_at.isoformat() if meter.last_poll_at else None,
        "last_poll_status": meter.last_poll_status, "latest_snapshot": meter.latest_snapshot or {},
    }


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def latest_meter_snapshot(meter: IRZMeter) -> IRZMeterSnapshot | None:
    return db.session.scalar(db.select(IRZMeterSnapshot).where(
        IRZMeterSnapshot.active_filter(), IRZMeterSnapshot.meter_id == meter.id
    ).order_by(IRZMeterSnapshot.captured_at.desc()).limit(1))


def meter_snapshots(meter: IRZMeter, *, limit: int = 30) -> list[IRZMeterSnapshot]:
    return list(db.session.scalars(db.select(IRZMeterSnapshot).where(
        IRZMeterSnapshot.active_filter(), IRZMeterSnapshot.meter_id == meter.id
    ).order_by(IRZMeterSnapshot.captured_at.desc()).limit(min(max(limit, 1), 50))))


def _numeric_delta(current: object, previous: object) -> object:
    if isinstance(current, dict):
        return {key: _numeric_delta(value, previous.get(key) if isinstance(previous, dict) else None)
                for key, value in current.items()}
    if isinstance(current, (int, float)) and not isinstance(current, bool) and isinstance(previous, (int, float)):
        return round(current - previous, 6)
    return None


def normalize_poll_values(result: dict) -> dict:
    """Build the stable monitoring schema from command-oriented gateway results."""
    command_values = {
        command_id: item.get("data")
        for command_id, item in result.get("results", {}).items()
        if isinstance(item, dict) and "data" in item
    }
    values: dict = dict(result.get("normalized") or {})
    if command_values:
        values["commands"] = command_values
    serial = command_values.get("serial_and_manufacture")
    if isinstance(serial, dict):
        values["serial_number"] = serial.get("serial_number")
        values["manufacture_date"] = serial.get("date_of_manufacture")
    if "firmware_version" in command_values:
        values["firmware_version"] = command_values["firmware_version"]
    ratios = command_values.get("transformation_ratios")
    if isinstance(ratios, dict):
        values["transformation_voltage"] = ratios.get("voltage")
        values["transformation_current"] = ratios.get("current")
    mappings = {
        "voltage_phases": "u", "current_phases": "i", "active_power": "p",
        "reactive_power": "q", "apparent_power": "s", "power_factor": "cos_phi",
    }
    for command_id, prefix in mappings.items():
        data = command_values.get(command_id)
        if isinstance(data, dict):
            for phase in ("a", "b", "c", "total"):
                if phase in data:
                    values[f"{prefix}_{phase}"] = data[phase]
    frequency = command_values.get("frequency")
    if isinstance(frequency, dict) and "value" in frequency:
        values["frequency"] = frequency["value"]
    elif frequency is not None:
        values["frequency"] = frequency
    return values


def serialize_snapshot(snapshot: IRZMeterSnapshot, *, include_delta: bool = False) -> dict:
    payload = {
        "id": str(snapshot.id), "captured_at": snapshot.captured_at.isoformat(), "values": snapshot.values,
        "quality": snapshot.quality, "quality_flags": snapshot.quality_flags or {},
        "poll_duration_ms": snapshot.poll_duration_ms, "source": snapshot.source, "status": snapshot.status,
        "extras": snapshot.extras or {},
    }
    if include_delta:
        previous = db.session.scalar(db.select(IRZMeterSnapshot).where(
            IRZMeterSnapshot.active_filter(), IRZMeterSnapshot.meter_id == snapshot.meter_id,
            IRZMeterSnapshot.captured_at < snapshot.captured_at,
        ).order_by(IRZMeterSnapshot.captured_at.desc()).limit(1))
        payload["delta"] = _numeric_delta(snapshot.values, previous.values if previous else {})
    return payload


def rename_device(device: IRZDevice, value: object, *, user_id) -> None:
    name = str(value or "").strip()
    if not 1 <= len(name) <= 160:
        raise ValueError("INVALID_NAME")
    device.name = name
    device.updated_by = user_id
    db.session.commit()


def update_device_profile(device: IRZDevice, payload: dict, *, user_id) -> None:
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not 1 <= len(name) <= 160:
            raise ValueError("INVALID_NAME")
        device.name = name
    for key, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
        if key in payload:
            raw = payload.get(key)
            if raw in (None, ""):
                setattr(device, key, None)
            else:
                try:
                    value = float(raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"INVALID_{key.upper()}") from exc
                if not low <= value <= high:
                    raise ValueError(f"INVALID_{key.upper()}")
                setattr(device, key, value)
    if "address_text" in payload:
        address = str(payload.get("address_text") or "").strip()
        if len(address) > 500:
            raise ValueError("INVALID_ADDRESS_TEXT")
        device.address_text = address or None
    device.updated_by = user_id
    db.session.commit()


def update_meter_identity(device: IRZDevice, payload: dict, *, user_id) -> IRZMeter:
    meter = db.session.scalar(db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id))
    if meter is None:
        raise LookupError("meter not discovered")
    if "custom_name" in payload:
        name = str(payload.get("custom_name") or "").strip()
        if len(name) > 160:
            raise ValueError("INVALID_NAME")
        meter.custom_name = name or None
    if "model" in payload:
        model = str(payload.get("model") or "").strip()
        if len(model) > 80:
            raise ValueError("INVALID_MODEL")
        meter.model = model or None
        meter.model_source = "MANUAL" if model else None
    meter.updated_by = user_id
    db.session.commit()
    return meter


def _upsert_meter(device: IRZDevice, data: dict, now: datetime, user_id) -> IRZMeter | None:
    serial = str(data.get("serial_number") or "").strip()
    if not serial:
        return None
    meter = db.session.scalar(db.select(IRZMeter).where(IRZMeter.serial_number == serial))
    if meter is None:
        meter = IRZMeter(irz_device_id=device.id, serial_number=serial, created_by=user_id, updated_by=user_id)
        db.session.add(meter)
    else:
        meter.irz_device_id = device.id
        meter.updated_by = user_id
    raw_date = data.get("date_of_manufacture")
    if raw_date:
        try: meter.manufacture_date = datetime.fromisoformat(str(raw_date)).date()
        except ValueError: pass
    meter.last_seen_at = now
    return meter


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
        now = datetime.now(timezone.utc)
        device.last_success_at = now
        device.last_mercury_seen_at = now
        device.last_latency_ms = result.get("duration_ms")
        device.last_error = None
        if command_id == "serial_and_manufacture" and isinstance(result.get("data"), dict):
            device.serial_number = str(result["data"].get("serial_number") or device.serial_number or "") or None
            raw_date = result["data"].get("date_of_manufacture")
            if raw_date:
                try: device.last_manufacture_date = datetime.fromisoformat(str(raw_date)).date()
                except ValueError: pass
            _upsert_meter(device, result["data"], now, user_id)
        elif command_id == "firmware_version" and result.get("data") is not None:
            device.last_firmware_version = str(result["data"])
        elif command_id == "transformation_ratios" and isinstance(result.get("data"), dict):
            device.last_transformation_ratios = result["data"]
        meter = db.session.scalar(db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id))
        if meter:
            if command_id == "firmware_version": meter.firmware_version = str(result.get("data"))
            snapshot = dict(meter.latest_snapshot or {})
            snapshot[command_id] = {"timestamp": now.isoformat(), "value": result.get("data")}
            meter.latest_snapshot = snapshot
            meter.last_seen_at = now
    elif error:
        device.last_error_at = datetime.now(timezone.utc)
        device.last_error = error_message
    db.session.commit()
    return log


def execute_device_command(device: IRZDevice, command_id: str, *, user_id, operation: str = "COMMAND") -> dict:
    if not device.enabled:
        raise ValueError("DEVICE_DISABLED")
    get_command(command_id)
    address = device.network_address if device.network_address is not None else 0
    try:
        result = _gateway_request(
            "/mercury/command" if operation == "COMMAND" else "/mercury/test",
            payload={"imei": device.imei, "network_address": address, "command_id": command_id},
            timeout=7,
        )
    except (GatewayResponseError, GatewayUnavailable) as exc:
        _store_operation(device, user_id, command_id, operation, error=exc)
        raise
    _store_operation(device, user_id, command_id, operation, result=result)
    return result


def _acquire_poll_lease(device: IRZDevice) -> bool:
    now = datetime.now(timezone.utc)
    result = db.session.execute(db.update(IRZDevice).where(
        IRZDevice.id == device.id,
        db.or_(IRZDevice.poll_lock_until.is_(None), IRZDevice.poll_lock_until < now),
    ).values(poll_lock_until=now + timedelta(seconds=45)).execution_options(synchronize_session=False))
    db.session.commit()
    return result.rowcount == 1


def _release_poll_lease(device: IRZDevice) -> None:
    db.session.execute(db.update(IRZDevice).where(IRZDevice.id == device.id).values(poll_lock_until=None).execution_options(synchronize_session=False))
    db.session.commit()


def poll_device(device: IRZDevice, *, user_id, source: str = "MANUAL", log_operations: bool = True) -> dict:
    if not device.enabled:
        raise ValueError("DEVICE_DISABLED")
    source = str(source).upper()
    if source not in {"MANUAL", "AUTO"}:
        raise ValueError("INVALID_POLL_SOURCE")
    if not _acquire_poll_lease(device):
        raise ValueError("POLL_IN_PROGRESS")
    address = device.network_address if device.network_address is not None else 0
    started = datetime.now(timezone.utc)
    try:
        result = _gateway_request("/mercury/poll", payload={"imei": device.imei, "network_address": address}, timeout=35)
        if log_operations:
            for command_id, command_result in result.get("results", {}).items():
                _store_operation(device, user_id, command_id, "POLL", result=command_result)
            for error in result.get("errors", []):
                gateway_error = GatewayResponseError(error.get("message", "Ошибка опроса"), 502, error.get("error_code", "PROTOCOL_ERROR"), error)
                _store_operation(device, user_id, error.get("command", "poll"), "POLL", error=gateway_error)
        device.last_polled_at = datetime.now(timezone.utc)
        meter = db.session.scalar(db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id))
        status = "PARTIAL" if result.get("partial") else ("SUCCESS" if result.get("success") else "ERROR")
        snapshot = None
        if meter:
            meter.last_poll_at = device.last_polled_at
            meter.last_poll_status = status
            values = normalize_poll_values(result)
            if values:
                meter.latest_snapshot = values
            snapshot = IRZMeterSnapshot(
                meter_id=meter.id, captured_at=device.last_polled_at, values=values,
                quality="PARTIAL" if result.get("partial") else ("GOOD" if result.get("success") else "INVALID"),
                quality_flags={"errors": result.get("errors", [])} if result.get("errors") else None,
                poll_duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                source=source, status=status, extras=None, created_by=user_id, updated_by=user_id,
            )
            db.session.add(snapshot)
        db.session.commit()
        if snapshot is not None:
            result["snapshot"] = serialize_snapshot(snapshot, include_delta=True)
        return result
    finally:
        _release_poll_lease(device)


def operation_logs(device: IRZDevice, *, limit: int = 100, status: str | None = None) -> list[IRZOperationLog]:
    query = db.select(IRZOperationLog).where(IRZOperationLog.active_filter(), IRZOperationLog.device_id == device.id)
    if status in {"SUCCESS", "ERROR", "TIMEOUT"}:
        query = query.where(IRZOperationLog.status == status)
    return list(db.session.scalars(query.order_by(IRZOperationLog.created_at.desc()).limit(min(max(limit, 1), 200))))
