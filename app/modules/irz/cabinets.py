"""Mercury serial -> ШУНО reference: Excel import and IRZ matching by the physically read serial."""

from __future__ import annotations

import io
import logging
import math
import re
import unicodedata
from collections import Counter
from decimal import Decimal
from datetime import date, datetime, timezone
from pathlib import Path
from typing import IO

from app.extensions import db
from app.models.irz import IRZDevice, IRZMeter, MeterCabinetDirectory

logger = logging.getLogger(__name__)

SHEET_NAME = "Счётчики"
COLUMNS = {
    "Серийный номер": "meter_serial",
    "ШУНО": "cabinet_name",
    "ID ШУНО": "cabinet_external_id",
    "Модель": "meter_model",
    "Установлен": "installed",
    "КТТ": "ktt",
    "Широта": "latitude",
    "Долгота": "longitude",
}
MATCHED = "MATCHED"
NOT_FOUND = "NOT_FOUND"
CONFLICT = "METER_SERIAL_CONFLICT"
MERCURY_SERIAL_DIGITS = 8
FIELDS = ("cabinet_name", "cabinet_external_id", "meter_model", "installed_at", "installed_raw", "ktt",
          "latitude", "longitude")
_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def normalize_meter_serial(value: object) -> str | None:
    """Single serial key for Excel, PostgreSQL lookup, Mercury and CLI.

    Strings keep leading zeros. Integer Excel/Mercury values shorter than 8 digits
    are padded so they still match a zero-padded text cell.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            return None
        text = str(int(value))
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        text = str(int(value))
    elif isinstance(value, int):
        text = str(value)
    else:
        text = unicodedata.normalize("NFKC", str(value))
        text = "".join(" " if _is_space(char) else char for char in text)
        text = "".join(text.split())
        if re.fullmatch(r"\d+\.0+", text):
            text = text.split(".", 1)[0]
    if not text:
        return None
    if text.isdigit() and len(text) < MERCURY_SERIAL_DIGITS:
        text = text.zfill(MERCURY_SERIAL_DIGITS)
    return text[:40]


def normalize_serial(value: object) -> str | None:
    """Alias kept so older call sites and tests use the same function."""
    return normalize_meter_serial(value)


def _is_space(char: str) -> bool:
    return char.isspace() or unicodedata.category(char) == "Zs"


def _header(value: object) -> str:
    return " ".join(str(value or "").split()).casefold().replace("ё", "е")


def _text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    return text[:limit] if text else None


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    number = float(str(value).strip().replace(",", ".")) if isinstance(value, str) else float(value)
    if not math.isfinite(number):
        raise ValueError("not finite")
    return number


def _installed(value: object) -> tuple[date | None, str | None]:
    if isinstance(value, datetime):
        return value.date(), value.date().isoformat()
    if isinstance(value, date):
        return value, value.isoformat()
    raw = _text(value, 60)
    if raw is None or raw.strip("-— ") == "":
        return None, None
    found = _DATE.search(raw)
    if found is None:
        return None, raw
    day, month, year = (int(part) for part in found.groups())
    try:
        return date(year, month, day), raw
    except ValueError:
        return None, raw


def _coordinates(lat_raw: object, lon_raw: object, warn) -> tuple[float | None, float | None]:
    try:
        latitude, longitude = _number(lat_raw), _number(lon_raw)
    except (TypeError, ValueError):
        warn("невалидные координаты, записаны пустыми")
        return None, None
    if latitude is None and longitude is None:
        return None, None
    if latitude is None or longitude is None:
        warn("указана только одна координата, записаны пустыми")
        return None, None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        warn("координаты вне допустимого диапазона, записаны пустыми")
        return None, None
    return latitude, longitude


def _parse_row(values: dict, warn) -> dict:
    installed_at, installed_raw = _installed(values.get("installed"))
    try:
        ktt = _number(values.get("ktt"))
    except (TypeError, ValueError):
        warn("невалидный КТТ, записан пустым")
        ktt = None
    latitude, longitude = _coordinates(values.get("latitude"), values.get("longitude"), warn)
    return {
        "cabinet_name": _text(values.get("cabinet_name"), 160),
        "cabinet_external_id": _text(values.get("cabinet_external_id"), 40),
        "meter_model": _text(values.get("meter_model"), 120),
        "installed_at": installed_at,
        "installed_raw": installed_raw,
        "ktt": ktt,
        "latitude": latitude,
        "longitude": longitude,
    }


def default_directory_path(root: str | Path) -> Path:
    return Path(root) / "meters_with_cabinets.xlsx"


def import_meter_directory(source: str | Path | IO[bytes], *, user_id=None, dry_run: bool = False) -> dict:
    """Idempotent upsert by meter_serial.

    Rows whose serial ends with ``*`` are past installations of a meter that also has a current row,
    so they are skipped instead of overwriting the current cabinet.
    """
    import openpyxl

    if hasattr(source, "read"):
        source = io.BytesIO(source.read())
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise ValueError(f"В файле нет листа «{SHEET_NAME}»")
        rows = workbook[SHEET_NAME].iter_rows(values_only=True)
        header = next(rows, None) or ()
        keys = {_header(name): key for name, key in COLUMNS.items()}
        positions = {keys[_header(cell)]: index for index, cell in enumerate(header) if _header(cell) in keys}
        missing = [name for name, key in COLUMNS.items() if key not in positions]
        if missing:
            raise ValueError("Не найдены столбцы: " + ", ".join(missing))
        report = {"total": 0, "inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0, "errors": 0,
                  "skip_reasons": Counter(), "warnings": []}
        existing = {entry.meter_serial: entry for entry in db.session.scalars(db.select(MeterCabinetDirectory))}
        seen: set[str] = set()
        for number, row in enumerate(rows, start=2):
            if row is None or all(cell in (None, "") for cell in row):
                continue
            report["total"] += 1
            values = {key: row[index] if index < len(row) else None for key, index in positions.items()}
            raw_serial = values.get("meter_serial")
            if isinstance(raw_serial, str) and raw_serial.strip().endswith("*"):
                report["skipped"] += 1
                report["skip_reasons"]["историческая установка (*)"] += 1
                continue
            serial = normalize_serial(raw_serial)
            if serial is None:
                report["skipped"] += 1
                report["skip_reasons"]["пустой серийный номер"] += 1
                continue
            if serial in seen:
                report["skipped"] += 1
                report["skip_reasons"]["повтор серийного номера в файле"] += 1
                report["warnings"].append(f"строка {number}: серийный № {serial} повторяется, оставлена первая строка")
                continue
            seen.add(serial)

            def warn(text: str, number=number, serial=serial) -> None:
                report["warnings"].append(f"строка {number} (№ {serial}): {text}")

            try:
                data = _parse_row(values, warn)
            except Exception as exc:  # one broken row must not stop the import
                report["errors"] += 1
                report["warnings"].append(f"строка {number} (№ {serial}): ошибка разбора — {exc}")
                continue
            entry = existing.get(serial)
            if entry is None:
                entry = MeterCabinetDirectory(meter_serial=serial, created_by=user_id, updated_by=user_id, **data)
                db.session.add(entry)
                existing[serial] = entry
                report["inserted"] += 1
                continue
            changed = entry.deleted_at is not None or any(getattr(entry, key) != value for key, value in data.items())
            if not changed:
                report["unchanged"] += 1
                continue
            for key, value in data.items():
                setattr(entry, key, value)
            entry.deleted_at = None
            entry.updated_by = user_id
            report["updated"] += 1
    finally:
        workbook.close()
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    report["skip_reasons"] = dict(report["skip_reasons"])
    return report


def find_entry(serial: object) -> MeterCabinetDirectory | None:
    normalized = normalize_meter_serial(serial)
    if normalized is None:
        return None
    return db.session.scalar(db.select(MeterCabinetDirectory).where(
        MeterCabinetDirectory.active_filter(), MeterCabinetDirectory.meter_serial == normalized))


def similar_serials(serial: object, *, limit: int = 20) -> list[str]:
    """Nearby stored keys when exact lookup misses (spaces, .0, leftover cache)."""
    normalized = normalize_meter_serial(serial) or "".join(str(serial or "").split())
    if not normalized:
        return []
    digits = re.sub(r"\D", "", normalized)
    found: list[str] = []
    for stored in db.session.scalars(db.select(MeterCabinetDirectory.meter_serial).where(
            MeterCabinetDirectory.active_filter())):
        compact = re.sub(r"\D", "", stored)
        if stored == normalized:
            continue
        if normalized in stored or stored in normalized or (digits and digits in compact):
            found.append(stored)
        if len(found) >= limit:
            break
    return found


def _entry_owner(entry: MeterCabinetDirectory, device: IRZDevice) -> IRZDevice | None:
    return db.session.scalar(db.select(IRZDevice).where(
        IRZDevice.active_filter(), IRZDevice.directory_entry_id == entry.id, IRZDevice.id != device.id).limit(1))


def _default_name(device: IRZDevice) -> str:
    return f"ATM21 {device.imei}"


def _link(device: IRZDevice, entry: MeterCabinetDirectory) -> None:
    device.directory_entry_id = entry.id
    device.directory_match_status = MATCHED
    device.directory_match_serial = entry.meter_serial
    device.directory_matched_at = datetime.now(timezone.utc)


def _has_coordinates(entry: MeterCabinetDirectory) -> bool:
    return entry.latitude is not None and entry.longitude is not None


def match_irz_from_meter_serial(device: IRZDevice, serial: object, *, meter: IRZMeter | None = None) -> str | None:
    """First match after a physically read serial; an existing match is never re-applied automatically.

    NOT_FOUND is not sticky: a later directory import or CLI rematch looks up again.
    Only empty fields are filled here: a default IMEI name and missing coordinates. Replacing
    operator-entered values is the explicit re-apply action.
    """
    normalized = normalize_meter_serial(serial)
    if normalized is None or device.directory_entry_id is not None:
        return device.directory_match_status
    device.directory_match_serial = normalized
    entry = find_entry(normalized)
    if entry is None:
        device.directory_match_status = NOT_FOUND
        return NOT_FOUND
    owner = _entry_owner(entry, device)
    if owner is not None:
        if device.directory_match_status != CONFLICT:
            logger.warning("IRZ %s: Mercury serial %s is already matched to IRZ %s, not re-linked",
                           device.imei, normalized, owner.imei)
        device.directory_match_status = CONFLICT
        return CONFLICT
    if entry.cabinet_name and device.name in ("", _default_name(device)):
        device.name = entry.cabinet_name
    if _has_coordinates(entry) and device.latitude is None and device.longitude is None:
        device.latitude, device.longitude = entry.latitude, entry.longitude
    if meter is not None and entry.meter_model:
        meter.catalog_model = entry.meter_model
    _link(device, entry)
    return MATCHED


def current_serial(device: IRZDevice, meter: IRZMeter | None) -> str | None:
    return normalize_meter_serial(meter.serial_number if meter is not None else device.serial_number)


def _device_meter(device: IRZDevice) -> IRZMeter | None:
    return db.session.scalar(
        db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id)
        .order_by(IRZMeter.last_seen_at.desc())
    )


def refresh_directory_match(device: IRZDevice, meter: IRZMeter | None = None) -> str | None:
    """Retry lookup when the IRZ is not linked yet, including a previous NOT_FOUND."""
    if meter is None:
        meter = _device_meter(device)
    return match_irz_from_meter_serial(device, current_serial(device, meter), meter=meter)


def match_existing_devices(*, dry_run: bool = False) -> list[dict]:
    """Link unmatched / NOT_FOUND IRZ. Already matched cards and conflicts are left alone."""
    rows = []
    for device in db.session.scalars(db.select(IRZDevice).where(IRZDevice.active_filter())).all():
        try:
            rows.append(_match_existing_one(device, dry_run=dry_run))
        except Exception as exc:
            logger.exception("IRZ %s: directory rematch failed", device.imei)
            rows.append({"imei": device.imei, "serial": current_serial(device, _device_meter(device)),
                         "cabinet": None, "result": "ERROR", "error": str(exc)})
    if not dry_run:
        db.session.commit()
    return rows


def _match_existing_one(device: IRZDevice, *, dry_run: bool) -> dict:
    meter = _device_meter(device)
    serial = current_serial(device, meter)
    if device.directory_entry_id is not None:
        entry = db.session.get(MeterCabinetDirectory, device.directory_entry_id)
        return {"imei": device.imei, "serial": serial or device.directory_match_serial,
                "cabinet": entry.cabinet_name if entry else None,
                "cabinet_external_id": entry.cabinet_external_id if entry else None,
                "result": "ALREADY_MATCHED"}
    if serial is None:
        return {"imei": device.imei, "serial": None, "cabinet": None, "result": "NO_SERIAL"}
    if device.directory_match_status == CONFLICT:
        entry = find_entry(serial)
        return {"imei": device.imei, "serial": serial,
                "cabinet": entry.cabinet_name if entry else None,
                "cabinet_external_id": entry.cabinet_external_id if entry else None,
                "result": "CONFLICT"}
    entry = find_entry(serial)
    if entry is None:
        if not dry_run:
            device.directory_match_serial = serial
            device.directory_match_status = NOT_FOUND
        return {"imei": device.imei, "serial": serial, "cabinet": None, "result": "NOT_FOUND"}
    owner = _entry_owner(entry, device)
    if owner is not None:
        if not dry_run:
            device.directory_match_serial = serial
            device.directory_match_status = CONFLICT
        return {"imei": device.imei, "serial": serial, "cabinet": entry.cabinet_name,
                "cabinet_external_id": entry.cabinet_external_id, "result": "CONFLICT"}
    if not dry_run:
        match_irz_from_meter_serial(device, serial, meter=meter)
    return {"imei": device.imei, "serial": serial, "cabinet": entry.cabinet_name,
            "cabinet_external_id": entry.cabinet_external_id, "result": "MATCH"}


def serialize_entry(entry: MeterCabinetDirectory) -> dict:
    return {
        "id": str(entry.id), "meter_serial": entry.meter_serial, "cabinet_name": entry.cabinet_name,
        "cabinet_external_id": entry.cabinet_external_id, "meter_model": entry.meter_model,
        "installed_at": entry.installed_at.isoformat() if entry.installed_at else None,
        "installed_raw": entry.installed_raw, "ktt": entry.ktt,
        "latitude": entry.latitude, "longitude": entry.longitude,
    }


def directory_state(device: IRZDevice, meter: IRZMeter | None) -> dict:
    """Live lookup: cached NOT_FOUND is rematched if the directory now has the serial."""
    if device.directory_entry_id is None:
        before = (device.directory_match_status, device.directory_entry_id)
        refresh_directory_match(device, meter)
        if (device.directory_match_status, device.directory_entry_id) != before:
            db.session.commit()
    entry = db.session.get(MeterCabinetDirectory, device.directory_entry_id) if device.directory_entry_id else None
    serial = current_serial(device, meter)
    return {
        "status": device.directory_match_status,
        "matched_serial": device.directory_match_serial or serial,
        "matched_at": device.directory_matched_at.isoformat() if device.directory_matched_at else None,
        "current_serial": serial,
        "serial_changed": bool(entry and serial and serial != entry.meter_serial),
        "entry": serialize_entry(entry) if entry and entry.deleted_at is None else None,
    }


def _planned_changes(device: IRZDevice, meter: IRZMeter | None, entry: MeterCabinetDirectory) -> list[dict]:
    changes = []
    if entry.cabinet_name and entry.cabinet_name != device.name:
        changes.append({"field": "name", "label": "Название", "current": device.name, "new": entry.cabinet_name})
    if _has_coordinates(entry) and (entry.latitude, entry.longitude) != (device.latitude, device.longitude):
        changes.append({"field": "coordinates", "label": "Координаты",
                        "current": None if device.latitude is None else f"{device.latitude}, {device.longitude}",
                        "new": f"{entry.latitude}, {entry.longitude}"})
    if meter is not None and entry.meter_model and entry.meter_model != meter.catalog_model:
        changes.append({"field": "catalog_model", "label": "Модель по справочнику",
                        "current": meter.catalog_model, "new": entry.meter_model})
    return changes


def _resolve(device: IRZDevice, meter: IRZMeter | None) -> MeterCabinetDirectory:
    serial = current_serial(device, meter)
    if serial is None:
        raise LookupError("METER_SERIAL_UNKNOWN")
    entry = find_entry(serial)
    if entry is None:
        raise LookupError("DIRECTORY_ENTRY_NOT_FOUND")
    return entry


def reapply_preview(device: IRZDevice, meter: IRZMeter | None) -> dict:
    entry = _resolve(device, meter)
    owner = _entry_owner(entry, device)
    return {
        "serial": entry.meter_serial,
        "entry": serialize_entry(entry),
        "changes": _planned_changes(device, meter, entry),
        "conflict": {"id": str(owner.id), "imei": owner.imei, "name": owner.name} if owner else None,
    }


def reapply_directory(device: IRZDevice, meter: IRZMeter | None, *, entry_id: object, user_id) -> dict:
    """Operator-confirmed overwrite; moves the link from another IRZ only through this call."""
    entry = _resolve(device, meter)
    if str(entry.id) != str(entry_id or ""):
        raise ValueError("DIRECTORY_PREVIEW_OUTDATED")
    changes = _planned_changes(device, meter, entry)
    owner = _entry_owner(entry, device)
    if owner is not None:
        logger.warning("IRZ %s: directory entry %s moved from IRZ %s by operator",
                       device.imei, entry.meter_serial, owner.imei)
        owner.directory_entry_id = None
        owner.directory_match_status = None
        owner.directory_matched_at = None
        owner.updated_by = user_id
    if entry.cabinet_name:
        device.name = entry.cabinet_name
    if _has_coordinates(entry):
        device.latitude, device.longitude = entry.latitude, entry.longitude
    if meter is not None and entry.meter_model:
        meter.catalog_model = entry.meter_model
        meter.updated_by = user_id
    _link(device, entry)
    device.updated_by = user_id
    db.session.commit()
    return {"serial": entry.meter_serial, "changes": changes,
            "released": {"imei": owner.imei, "name": owner.name} if owner else None}
