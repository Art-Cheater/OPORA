"""Compact ATM21 directory for the IRZ map, list and wall display.

The whole directory is built with two SQL queries (devices, meters) and one
gateway call for live sessions, so it stays cheap for hundreds of devices.
`operational_status` is the lighting state; `online` is only the ATM21 transport.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models.irz import IRZDevice, IRZMeter
from app.modules.irz import service, status as operational

FILTERS = ("all", "on", "off", "problem", "critical", "online", "offline", "no_coordinates")
STATUS_FILTERS = {"on": operational.ON, "off": operational.OFF, "problem": operational.PROBLEM,
                  "critical": operational.CRITICAL}
SUMMARY_KEYS = ("u_a", "u_b", "u_c", "i_a", "i_b", "i_c", "p_total", "frequency")
DEFAULT_METER_MODEL = "Mercury 230"
MAX_PER_PAGE = 1000


def default_name(imei: str | None) -> str:
    return f"ATM21 {imei}"


def custom_name(device: IRZDevice) -> str | None:
    name = (device.name or "").strip()
    return None if not name or name == default_name(device.imei) else name


def live_sessions() -> tuple[dict[str, dict], bool]:
    """Live ATM21 sessions by IMEI and whether the gateway answered at all."""
    try:
        items = service.get_devices()
    except (service.GatewayUnavailable, service.GatewayResponseError):
        return {}, False
    return {item["imei"]: item for item in items if isinstance(item, dict) and item.get("imei")}, True


def _iso(value: datetime | None) -> str | None:
    return service._aware(value).isoformat() if value else None


def _latest_meters() -> dict:
    meters: dict = {}
    rows = db.session.scalars(
        db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id.is_not(None))
    )
    floor = datetime.min.replace(tzinfo=timezone.utc)
    for meter in rows:
        current = meters.get(meter.irz_device_id)
        seen = service._aware(meter.last_seen_at) if meter.last_seen_at else floor
        if current is None or seen > (service._aware(current.last_seen_at) if current.last_seen_at else floor):
            meters[meter.irz_device_id] = meter
    return meters


def _data_state(meter: IRZMeter | None, updated_at: datetime | None, now: datetime, fresh_seconds: int) -> str:
    if meter is None or updated_at is None:
        return "NO_DATA"
    if (now - updated_at).total_seconds() > fresh_seconds:
        return "STALE"
    return {"SUCCESS": "GOOD", "PARTIAL": "PARTIAL"}.get(meter.last_poll_status or "", "STALE")


def _summary(values: dict) -> dict:
    result = {}
    for key in SUMMARY_KEYS:
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
    return result


def build_directory(live: dict[str, dict], gateway_ok: bool, *, now: datetime | None = None) -> list[dict]:
    """Every active ATM21 as a compact dict, problems first."""
    now = now or datetime.now(timezone.utc)
    fresh_seconds = int(current_app.config.get("IRZ_DATA_FRESH_SECONDS", 900))
    devices = list(db.session.scalars(
        db.select(IRZDevice).where(IRZDevice.active_filter(), IRZDevice.imei.is_not(None))
    ))
    missing = set(live) - {device.imei for device in devices}
    for imei in sorted(missing):
        try:
            devices.append(service.upsert_atm21(live[imei]))
        except ValueError:
            continue
    meters = _latest_meters()
    items = []
    for device in devices:
        meter = meters.get(device.id)
        state = service._current_state(meter.latest_snapshot) if meter else {"values": {}, "updated_at": None}
        updated_at = service._parse_time(state.get("updated_at"))
        online = device.imei in live
        data_state = _data_state(meter, updated_at, now, fresh_seconds)
        lighting = operational.get_irz_operational_status(device, meter, online=online, now=now)
        problem = lighting["reason"]
        if problem and not gateway_ok:
            problem = "Шлюз связи недоступен"
        name = custom_name(device)
        has_coordinates = device.latitude is not None and device.longitude is not None
        runtime = live.get(device.imei, {})
        items.append({
            "id": str(device.id),
            "imei": device.imei,
            "name": name,
            "title": name or default_name(device.imei),
            "device_type": device.device_type or device.model or "ATM21",
            "meter": {"serial": meter.serial_number,
                      "model": meter.catalog_model or meter.model or DEFAULT_METER_MODEL} if meter else None,
            "latitude": device.latitude if has_coordinates else None,
            "longitude": device.longitude if has_coordinates else None,
            "has_coordinates": has_coordinates,
            "address": device.address_text,
            "cabinet_type": operational.cabinet_type(name),
            "online": online,
            "operational_status": lighting["code"],
            "operational_label": lighting["label"],
            "problem": problem,
            "last_successful_meter_response": lighting["last_success_at"],
            "no_data_seconds": lighting["no_data_seconds"],
            "data_state": data_state,
            "last_seen_at": runtime.get("last_seen_at") or _iso(device.last_seen_at),
            "last_poll_at": _iso(meter.last_poll_at) if meter else _iso(device.last_polled_at),
            "updated_at": updated_at.isoformat() if updated_at else None,
            "summary": _summary(state.get("values") or {}),
        })
    items.sort(key=lambda item: (operational.ORDER[item["operational_status"]], item["name"] is None,
                                 _natural(item["title"]), item["imei"]))
    return items


MAP_KEYS = ("id", "imei", "name", "title", "meter", "latitude", "longitude", "has_coordinates", "cabinet_type",
            "online", "operational_status", "problem", "last_successful_meter_response", "no_data_seconds", "last_seen_at")
MAP_SUMMARY_KEYS = ("u_a", "u_b", "u_c")


def map_item(item: dict) -> dict:
    """Marker and short popup fields only: no address, poll bookkeeping or full measurement summary."""
    result = {key: item[key] for key in MAP_KEYS}
    result["summary"] = {key: value for key, value in item["summary"].items() if key in MAP_SUMMARY_KEYS}
    return result


def _natural(value: str) -> list:
    """«Улица 2» before «Улица 10»."""
    return [int(part) if index % 2 else part for index, part in enumerate(re.split(r"(\d+)", value.casefold()))]


def counters(items: list[dict]) -> dict:
    """Lighting states partition the total; online/offline is a separate ATM21 transport split."""
    result = {"total": len(items)}
    for key, code in STATUS_FILTERS.items():
        result[key] = sum(1 for item in items if item["operational_status"] == code)
    result["online"] = sum(1 for item in items if item["online"])
    result["offline"] = len(items) - result["online"]
    result["no_coordinates"] = sum(1 for item in items if not item["has_coordinates"])
    return result


def _normalize(value: object) -> str:
    return str(value or "").casefold().replace("ё", "е").strip()


def matches(item: dict, query: str) -> bool:
    needle = _normalize(query)
    if not needle:
        return True
    haystack = " ".join(_normalize(part) for part in (
        item["title"], item["imei"], (item["meter"] or {}).get("serial"), item["address"],
    ))
    return needle in haystack


def filter_items(items: list[dict], *, query: str = "", status: str = "all",
                 has_coordinates: bool | None = None) -> list[dict]:
    if status not in FILTERS:
        raise ValueError("INVALID_STATUS_FILTER")
    selected = []
    for item in items:
        if status in STATUS_FILTERS and item["operational_status"] != STATUS_FILTERS[status]:
            continue
        if status == "online" and not item["online"]:
            continue
        if status == "offline" and item["online"]:
            continue
        if status == "no_coordinates" and item["has_coordinates"]:
            continue
        if has_coordinates is not None and item["has_coordinates"] != has_coordinates:
            continue
        if matches(item, query):
            selected.append(item)
    return selected


def parse_bool(value: object) -> bool | None:
    text = _normalize(value)
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def paginate(items: list[dict], page: int, per_page: int) -> tuple[list[dict], dict]:
    per_page = min(max(per_page, 1), MAX_PER_PAGE)
    pages = max((len(items) + per_page - 1) // per_page, 1)
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    return items[start:start + per_page], {"page": page, "per_page": per_page, "pages": pages, "total": len(items)}
