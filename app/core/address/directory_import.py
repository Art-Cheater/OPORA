"""Идемпотентный импорт адресного NDJSON. Не запускается при старте сайта."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.address.normalize import fold
from app.extensions import db
from app.models.geo.directory import GeoEntrance, GeoHouse, GeoSettlement, GeoStreet

_BATCH = 400


def _clean(value, limit: int) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:limit] or None


def _coord(value) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if number != number:
        raise ValueError("координата не число")
    return number


def _existing(model, source_name: str, external_id: str):
    return db.session.scalar(
        select(model).where(
            model.source == source_name,
            model.external_id == external_id,
            model.deleted_at.is_(None),
        )
    )


def _remember(stats: dict[str, int], row, is_new: bool) -> None:
    if is_new:
        db.session.add(row)
        db.session.flush()
        stats["created"] += 1
    else:
        stats["updated"] += 1


def import_ndjson(path: str | Path, *, source: str = "import") -> dict[str, int]:
    """Повторный запуск обновляет те же external_id и не плодит дубли."""

    stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
    source_name = _clean(source, 32) or "import"
    settlements: dict[str, GeoSettlement] = {}
    streets: dict[str, GeoStreet] = {}
    houses: dict[str, GeoHouse] = {}
    pending = 0

    def flush() -> None:
        nonlocal pending
        if pending:
            db.session.commit()
            pending = 0

    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            try:
                item = json.loads(text)
                if not isinstance(item, dict):
                    raise ValueError("строка не объект")
                kind = str(item.get("type") or "").strip().lower()
                external_id = _clean(item.get("external_id"), 128)
                if not external_id:
                    raise ValueError("нет external_id")
                if kind == "settlement":
                    row = _existing(GeoSettlement, source_name, external_id)
                    is_new = row is None
                    row = row or GeoSettlement(source=source_name, external_id=external_id)
                    name = _clean(item.get("name"), 255)
                    if not name:
                        raise ValueError("нет названия")
                    parent_key = _clean(item.get("parent_external_id"), 128)
                    row.kind = _clean(item.get("kind"), 32) or "settlement"
                    row.name = name
                    row.name_key = fold(name)[:255]
                    row.region_name = _clean(item.get("region"), 255)
                    row.district_name = _clean(item.get("district"), 255)
                    row.fias_id = _clean(item.get("fias_id"), 64)
                    row.osm_id = _clean(item.get("osm_id"), 64)
                    row.latitude = _coord(item.get("latitude"))
                    row.longitude = _coord(item.get("longitude"))
                    if parent_key and parent_key in settlements:
                        row.parent_id = settlements[parent_key].id
                    _remember(stats, row, is_new)
                    settlements[external_id] = row
                elif kind == "street":
                    row = _existing(GeoStreet, source_name, external_id)
                    is_new = row is None
                    row = row or GeoStreet(source=source_name, external_id=external_id, name="", name_key="")
                    name = _clean(item.get("name"), 255)
                    if not name:
                        raise ValueError("нет названия улицы")
                    settlement_key = _clean(item.get("settlement_external_id"), 128)
                    row.name = name
                    row.name_key = fold(name)[:255]
                    row.kind = _clean(item.get("kind"), 32) or "улица"
                    row.settlement_name = _clean(item.get("settlement"), 255)
                    row.district_name = _clean(item.get("district"), 255)
                    row.region_name = _clean(item.get("region"), 255) or "Кировская область"
                    row.fias_id = _clean(item.get("fias_id"), 64)
                    row.osm_id = _clean(item.get("osm_id"), 64)
                    if settlement_key and settlement_key in settlements:
                        row.settlement_id = settlements[settlement_key].id
                        row.settlement_name = row.settlement_name or settlements[settlement_key].name
                    _remember(stats, row, is_new)
                    streets[external_id] = row
                elif kind == "house":
                    row = _existing(GeoHouse, source_name, external_id)
                    is_new = row is None
                    row = row or GeoHouse(source=source_name, external_id=external_id, number="", number_key="")
                    number = _clean(item.get("number"), 32)
                    if not number:
                        raise ValueError("нет номера дома")
                    street_key = _clean(item.get("street_external_id"), 128)
                    row.number = number
                    row.number_key = fold(number).replace(" ", "")[:32]
                    row.building = _clean(item.get("building"), 32)
                    row.postal_code = _clean(item.get("postal_code"), 12)
                    row.fias_id = _clean(item.get("fias_id"), 64)
                    row.osm_id = _clean(item.get("osm_id"), 64)
                    row.latitude = _coord(item.get("latitude"))
                    row.longitude = _coord(item.get("longitude"))
                    if street_key and street_key in streets:
                        row.street_id = streets[street_key].id
                    elif street_key:
                        linked = _existing(GeoStreet, source_name, street_key)
                        if linked is not None:
                            row.street_id = linked.id
                    _remember(stats, row, is_new)
                    houses[external_id] = row
                elif kind == "entrance":
                    lat, lon = _coord(item.get("latitude")), _coord(item.get("longitude"))
                    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError("у подъезда нет координат")
                    row = _existing(GeoEntrance, source_name, external_id)
                    is_new = row is None
                    row = row or GeoEntrance(source=source_name, external_id=external_id, latitude=lat, longitude=lon)
                    house_key = _clean(item.get("house_external_id"), 128)
                    row.latitude = lat
                    row.longitude = lon
                    row.ref = _clean(item.get("ref"), 32)
                    row.name = _clean(item.get("name"), 255)
                    row.settlement_name = _clean(item.get("settlement"), 255)
                    row.street_name = _clean(item.get("street"), 255)
                    row.house_number = _clean(item.get("house"), 32)
                    row.osm_id = _clean(item.get("osm_id"), 64)
                    if house_key and house_key in houses:
                        row.house_id = houses[house_key].id
                    _remember(stats, row, is_new)
                else:
                    raise ValueError("неизвестный type")
                pending += 1
                if pending >= _BATCH:
                    flush()
            except (ValueError, TypeError, json.JSONDecodeError):
                stats["errors"] += 1
                stats["skipped"] += 1
            except Exception:
                db.session.rollback()
                raise
    flush()
    return stats
