"""IRZ control client and exchange-log queries."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from app.extensions import db
from app.models.irz import IRZDevice, IRZExchangeLog, IRZExperiment, IRZMeter, IRZMeterSnapshot, IRZOperationLog
from app.modules.irz import cabinets
from app.modules.irz.commands import COMMANDS, command_list, get_command, poll_commands

PHASE_PREFIXES = {
    "voltage_phases": "u", "current_phases": "i", "active_power": "p",
    "reactive_power": "q", "apparent_power": "s", "power_factor": "cos_phi",
}
ENERGY_KEYS = ("a_plus", "a_minus", "r_plus", "r_minus")
QUALITY_BY_ERROR = {
    "CRC_ERROR": "CRC_ERROR",
    "UNSUPPORTED": "UNSUPPORTED", "COMMAND_NOT_SUPPORTED": "UNSUPPORTED",
    "UNKNOWN_RESPONSE_FORMAT": "INVALID", "WRONG_ADDRESS": "INVALID", "INCOMPLETE_RESPONSE": "INVALID",
    "PROTOCOL_ERROR": "INVALID", "METER_INTERNAL_ERROR": "INVALID",
}
COMMAND_TIMEOUTS = {"events": 90}


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
    current = serialize_current(meter) if meter else {"values": {}, "quality": {}, "captured_at": {}, "updated_at": None}
    stale_seconds = int(current_app.config.get("IRZ_DATA_FRESH_SECONDS", 900))
    reference = _parse_time(current.get("updated_at")) or (_aware(latest.captured_at) if latest else None)
    is_stale = (reference is None or (datetime.now(timezone.utc) - reference).total_seconds() > stale_seconds
                or bool(latest and latest.status == "ERROR"))
    if not current["values"] and latest is None:
        data_state = "NO_DATA"
    elif is_stale:
        data_state = "STALE"
    else:
        data_state = latest.quality if latest else "GOOD"
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
        "data_state": data_state,
        "stale": is_stale,
        "latest": serialize_snapshot(latest, include_delta=True) if latest else None,
        "current": current,
        "meter": serialize_meter(meter) if meter else None,
        "directory": cabinets.directory_state(device, meter),
    }


def serialize_meter(meter: IRZMeter) -> dict:
    return {
        "id": str(meter.id), "serial_number": meter.serial_number, "custom_name": meter.custom_name,
        "display_name": meter.custom_name or f"Mercury {meter.serial_number}", "model": meter.model,
        "model_source": meter.model_source, "catalog_model": meter.catalog_model,
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


def _num(value: object) -> object:
    """Canonical JSON number for a measurement; 0 stays 0, None stays None."""
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            return value
        if not number.is_finite():
            return None
        return int(number) if "." not in value and "e" not in value.lower() else float(number)
    return value


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _meter_timezone() -> ZoneInfo:
    try:
        name = current_app.config.get("IRZ_METER_TIMEZONE") or "Europe/Moscow"
    except RuntimeError:
        name = "Europe/Moscow"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Moscow")


def normalize_command(command_id: str, data: object, item: dict | None = None) -> dict:
    """Map one command result to canonical monitoring keys (u_a, p_total, energy_*…)."""
    values: dict = {}
    if command_id == "serial_and_manufacture" and isinstance(data, dict):
        values["serial_number"] = data.get("serial_number")
        values["manufacture_date"] = data.get("date_of_manufacture")
    elif command_id == "firmware_version" and data is not None:
        values["firmware_version"] = data
    elif command_id == "transformation_ratios" and isinstance(data, dict):
        values["transformation_voltage"] = _num(data.get("voltage"))
        values["transformation_current"] = _num(data.get("current"))
    elif command_id in PHASE_PREFIXES and isinstance(data, dict):
        prefix = PHASE_PREFIXES[command_id]
        for phase in ("a", "b", "c", "total"):
            if phase in data:
                values[f"{prefix}_{phase}"] = _num(data[phase])
    elif command_id == "frequency":
        values["frequency"] = _num(data.get("value") if isinstance(data, dict) else data)
    elif command_id == "phase_angles" and isinstance(data, dict):
        for source in ("ab", "ac", "bc"):
            if source in data:
                values[f"phase_angle_{source}"] = _num(data[source])
    elif command_id == "energy_current" and isinstance(data, dict):
        for key in ENERGY_KEYS:
            values[f"energy_{key}_total"] = _num(data.get(key))
    elif command_id == "energy_tariffs" and isinstance(data, dict):
        for tariff, block in data.items():
            for key in ENERGY_KEYS:
                values[f"energy_{key}_{tariff}"] = _num(block.get(key)) if isinstance(block, dict) else None
    elif command_id == "meter_time" and isinstance(data, dict) and data.get("value"):
        values["meter_time"] = data["value"]
        meter_local = _parse_naive_local(data["value"])
        received = _parse_time((item or {}).get("received_at")) or datetime.now(timezone.utc)
        if meter_local is not None:
            values["drift_seconds"] = round((meter_local - received).total_seconds())
    elif command_id == "status_word" and isinstance(data, dict):
        values["status_word"] = data.get("raw")
        values["diagnostics"] = data.get("errors") or []
        values["diagnostics_ok"] = bool(data.get("ok"))
    return values


def _parse_naive_local(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=_meter_timezone()) if parsed.tzinfo is None else parsed


def normalize_poll_values(result: dict) -> dict:
    """Build the stable monitoring schema from command-oriented gateway results."""
    items = {command_id: item for command_id, item in result.get("results", {}).items()
             if isinstance(item, dict) and "data" in item}
    values: dict = dict(result.get("normalized") or {})
    if items:
        values["commands"] = {command_id: item.get("data") for command_id, item in items.items()}
    for command_id, item in items.items():
        values.update(normalize_command(command_id, item.get("data"), item))
    return values


def command_quality(error_code: object) -> str:
    return QUALITY_BY_ERROR.get(str(error_code or ""), "STALE")


def poll_quality(result: dict) -> str:
    """GOOD / PARTIAL / STALE / INVALID / CRC_ERROR / UNSUPPORTED for one logical poll."""
    errors = [item for item in result.get("errors", []) if isinstance(item, dict)]
    relevant = [item for item in errors if command_quality(item.get("error_code")) != "UNSUPPORTED"]
    if result.get("results") or result.get("success"):
        return "PARTIAL" if relevant else "GOOD"
    qualities = {command_quality(item.get("error_code")) for item in errors} or {"STALE"}
    if qualities == {"CRC_ERROR"}:
        return "CRC_ERROR"
    if qualities == {"UNSUPPORTED"}:
        return "UNSUPPORTED"
    return "INVALID" if "INVALID" in qualities else "STALE"


def _current_state(raw: object) -> dict:
    if isinstance(raw, dict) and isinstance(raw.get("values"), dict) and isinstance(raw.get("commands"), dict):
        return {"values": dict(raw["values"]), "commands": {key: dict(value) for key, value in raw["commands"].items()},
                "updated_at": raw.get("updated_at")}
    legacy = {key: value for key, value in (raw or {}).items()
              if key != "commands" and not (isinstance(value, dict) and "timestamp" in value)} if isinstance(raw, dict) else {}
    return {"values": legacy, "commands": {}, "updated_at": None}


def merge_current(raw: object, results: dict, errors: list, now: datetime) -> dict:
    """Latest known value per field; failed commands keep old values marked STALE."""
    state, stamp = _current_state(raw), now.isoformat()
    for command_id, item in results.items():
        if not isinstance(item, dict) or "data" not in item:
            continue
        fields = normalize_command(command_id, item.get("data"), item)
        state["values"].update(fields)
        state["commands"][command_id] = {"captured_at": stamp, "quality": "GOOD", "fields": sorted(fields)}
        state["updated_at"] = stamp
    for error in errors:
        command_id = error.get("command") if isinstance(error, dict) else None
        if command_id not in COMMANDS:
            continue
        meta = state["commands"].get(command_id) or {"fields": []}
        quality = command_quality(error.get("error_code"))
        if quality != "UNSUPPORTED" and meta.get("captured_at"):
            quality = "STALE"
        meta.update(quality=quality, error_code=error.get("error_code"), failed_at=stamp)
        state["commands"][command_id] = meta
    return state


def serialize_current(meter: IRZMeter) -> dict:
    state = _current_state(meter.latest_snapshot)
    fresh_seconds = int(current_app.config.get("IRZ_DATA_FRESH_SECONDS", 900))
    now = datetime.now(timezone.utc)
    quality, captured = {}, {}
    for meta in state["commands"].values():
        value_quality, captured_at = meta.get("quality"), meta.get("captured_at")
        moment = _parse_time(captured_at)
        if value_quality == "GOOD" and (moment is None or (now - moment).total_seconds() > fresh_seconds):
            value_quality = "STALE"
        for field in meta.get("fields", []):
            quality[field], captured[field] = value_quality, captured_at
    return {"values": state["values"], "quality": quality, "captured_at": captured, "updated_at": state.get("updated_at")}


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


def _coordinate(raw: object, key: str, low: float, high: float) -> float | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool):
        raise ValueError(f"INVALID_{key.upper()}")
    try:
        value = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_{key.upper()}") from exc
    if not low <= value <= high:
        raise ValueError(f"INVALID_{key.upper()}")
    return value


def update_device_profile(device: IRZDevice, payload: dict, *, user_id) -> None:
    """Name, address and coordinates; an empty name restores the IMEI-based default."""
    changes: dict = {}
    if "name" in payload:
        name = str(payload.get("name") or "").strip() or f"ATM21 {device.imei}"
        if len(name) > 160:
            raise ValueError("INVALID_NAME")
        changes["name"] = name
    for key, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
        if key in payload:
            changes[key] = _coordinate(payload.get(key), key, low, high)
    latitude = changes.get("latitude", device.latitude)
    longitude = changes.get("longitude", device.longitude)
    if (latitude is None) != (longitude is None):
        raise ValueError("INCOMPLETE_COORDINATES")
    if "address_text" in payload:
        address = str(payload.get("address_text") or "").strip()
        if len(address) > 500:
            raise ValueError("INVALID_ADDRESS_TEXT")
        changes["address_text"] = address or None
    for key, value in changes.items():
        setattr(device, key, value)
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


def _device_meter(device: IRZDevice) -> IRZMeter | None:
    return db.session.scalar(
        db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id)
        .order_by(IRZMeter.last_seen_at.desc())
    )


def _apply_results(device: IRZDevice, results: dict, errors: list, now: datetime, user_id) -> IRZMeter | None:
    """Update device identity and the merged current meter state from command results."""
    for command_id, item in results.items():
        data = item.get("data") if isinstance(item, dict) else None
        if command_id == "serial_and_manufacture" and isinstance(data, dict):
            device.serial_number = str(data.get("serial_number") or device.serial_number or "") or None
            raw_date = data.get("date_of_manufacture")
            if raw_date:
                try: device.last_manufacture_date = datetime.fromisoformat(str(raw_date)).date()
                except ValueError: pass
            meter = _upsert_meter(device, data, now, user_id)
            if meter is not None:
                cabinets.match_irz_from_meter_serial(device, meter.serial_number, meter=meter)
        elif command_id == "firmware_version" and data is not None:
            device.last_firmware_version = str(data)
        elif command_id == "transformation_ratios" and isinstance(data, dict):
            device.last_transformation_ratios = data
    if results:
        durations = [item.get("duration_ms") for item in results.values() if isinstance(item, dict) and item.get("duration_ms") is not None]
        device.last_success_at = now
        device.last_mercury_seen_at = now
        device.last_latency_ms = max(durations) if durations else device.last_latency_ms
        device.last_error = None
    elif errors:
        device.last_error_at = now
        device.last_error = next((str(item.get("message")) for item in errors if isinstance(item, dict) and item.get("message")), "Ошибка опроса")
    meter = _device_meter(device)
    if meter is not None:
        firmware = (results.get("firmware_version") or {}).get("data") if isinstance(results.get("firmware_version"), dict) else None
        if firmware is not None:
            meter.firmware_version = str(firmware)
        meter.latest_snapshot = merge_current(meter.latest_snapshot, results, errors, now)
        if results:
            meter.last_seen_at = now
    return meter


def _store_operation(device: IRZDevice, user_id, command_id: str, operation: str, result: dict | None = None,
                     error: GatewayResponseError | GatewayUnavailable | None = None, *, apply: bool = True,
                     parameters: dict | None = None) -> IRZOperationLog:
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
        request_parameters=parameters or {},
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
    if apply:
        now = datetime.now(timezone.utc)
        if result:
            _apply_results(device, {command_id: result}, [], now, user_id)
        elif error:
            _apply_results(device, {}, [{"command": command_id, "error_code": error_code, "message": error_message}], now, user_id)
    db.session.commit()
    return log


def execute_device_command(device: IRZDevice, command_id: str, *, user_id, operation: str = "COMMAND",
                           params: dict | None = None) -> dict:
    if not device.enabled:
        raise ValueError("DEVICE_DISABLED")
    get_command(command_id)
    address = device.network_address if device.network_address is not None else 0
    payload = {"imei": device.imei, "network_address": address, "command_id": command_id}
    if params:
        payload["params"] = params
    try:
        result = _gateway_request(
            "/mercury/command" if operation == "COMMAND" else "/mercury/test",
            payload=payload,
            timeout=COMMAND_TIMEOUTS.get(command_id, 30),
        )
    except (GatewayResponseError, GatewayUnavailable) as exc:
        _store_operation(device, user_id, command_id, operation, error=exc, parameters=params)
        raise
    _store_operation(device, user_id, command_id, operation, result=result, parameters=params)
    return result


def energy_archive_params(payload: dict) -> dict:
    from app.modem_gateway.mercury230 import ARCHIVE_PERIODS
    period = str(payload.get("period") or "")
    try:
        month = int(payload.get("month") or 0)
        tariff = int(payload.get("tariff") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_PARAMETERS") from exc
    if period not in ARCHIVE_PERIODS or not 0 <= tariff <= 4 or (period == "month" and not 1 <= month <= 12):
        raise ValueError("INVALID_PARAMETERS")
    return {"period": period, "month": month if period == "month" else 0, "tariff": tariff}


def _acquire_poll_lease(device: IRZDevice) -> bool:
    now = datetime.now(timezone.utc)
    lease = int(current_app.config.get("IRZ_POLL_TIMEOUT_SECONDS", 90)) + 30
    result = db.session.execute(db.update(IRZDevice).where(
        IRZDevice.id == device.id,
        db.or_(IRZDevice.poll_lock_until.is_(None), IRZDevice.poll_lock_until < now),
    ).values(poll_lock_until=now + timedelta(seconds=lease)).execution_options(synchronize_session=False))
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
    imei = device.imei
    address = device.network_address if device.network_address is not None else 0
    started = datetime.now(timezone.utc)
    db.session.commit()
    try:
        try:
            result = _gateway_request("/mercury/poll", payload={"imei": imei, "network_address": address},
                                      timeout=int(current_app.config.get("IRZ_POLL_TIMEOUT_SECONDS", 90)))
        except (GatewayResponseError, GatewayUnavailable) as exc:
            code = exc.error_code if isinstance(exc, GatewayResponseError) else "CONNECTION_ERROR"
            failed = {"success": False, "partial": False, "results": {},
                      "errors": [{"command": "poll", "error_code": code, "message": str(exc)}]}
            _record_poll(device, failed, source=source, user_id=user_id, started=started)
            raise
        if log_operations:
            for command_id, command_result in result.get("results", {}).items():
                _store_operation(device, user_id, command_id, "POLL", result=command_result, apply=False)
            for error in result.get("errors", []):
                if error.get("command") not in COMMANDS:
                    continue
                gateway_error = GatewayResponseError(error.get("message", "Ошибка опроса"), 502, error.get("error_code", "PROTOCOL_ERROR"), error)
                _store_operation(device, user_id, error["command"], "POLL", error=gateway_error, apply=False)
        snapshot = _record_poll(device, result, source=source, user_id=user_id, started=started)
        if snapshot is not None:
            result["snapshot"] = serialize_snapshot(snapshot, include_delta=True)
        result["quality"] = poll_quality(result)
        return result
    finally:
        _release_poll_lease(device)


def _record_poll(device: IRZDevice, result: dict, *, source: str, user_id, started: datetime) -> IRZMeterSnapshot | None:
    """One logical poll → one snapshot; failed commands keep previous values as STALE."""
    now = datetime.now(timezone.utc)
    results = {key: value for key, value in (result.get("results") or {}).items() if isinstance(value, dict)}
    errors = [item for item in (result.get("errors") or []) if isinstance(item, dict)]
    device.last_polled_at = now
    if errors and not results and not any(item.get("command") in COMMANDS for item in errors):
        first = errors[0]
        errors = errors + [{"command": command.id, "error_code": first.get("error_code"), "message": first.get("message")}
                           for command in poll_commands()]
    meter = _apply_results(device, results, errors, now, user_id)
    quality = poll_quality(result)
    status = "SUCCESS" if quality == "GOOD" else ("PARTIAL" if quality == "PARTIAL" else "ERROR")
    snapshot = None
    if meter is not None:
        meter.last_poll_at = now
        meter.last_poll_status = status
        snapshot = IRZMeterSnapshot(
            meter_id=meter.id, captured_at=now, values=normalize_poll_values(result),
            quality=quality,
            quality_flags={"errors": result.get("errors", [])} if result.get("errors") else None,
            poll_duration_ms=int((now - started).total_seconds() * 1000),
            source=source, status=status, extras=None, created_by=user_id, updated_by=user_id,
        )
        db.session.add(snapshot)
    db.session.commit()
    return snapshot


def operation_logs(device: IRZDevice, *, limit: int = 100, status: str | None = None) -> list[IRZOperationLog]:
    query = db.select(IRZOperationLog).where(IRZOperationLog.active_filter(), IRZOperationLog.device_id == device.id)
    if status in {"SUCCESS", "ERROR", "TIMEOUT"}:
        query = query.where(IRZOperationLog.status == status)
    return list(db.session.scalars(query.order_by(IRZOperationLog.created_at.desc()).limit(min(max(limit, 1), 200))))
