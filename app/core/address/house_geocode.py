"""Координаты дома по запросу. Официальный адрес ГАР эта функция не меняет."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from sqlalchemy import select

from app.core.address.normalize import fold
from app.core.address.providers import AddressSuggestion, GeocodingError
from app.extensions import db
from app.models.geo.directory import GeoGeocodeCache, GeoHouse

_QUALITIES = {"EXACT", "INTERPOLATED", "STREET", "SETTLEMENT", "UNKNOWN"}


def geocode_missing_houses(
    hits: list[AddressSuggestion],
    search: Callable[[str], list[AddressSuggestion]],
) -> list[AddressSuggestion]:
    """Для дома без точки спрашивает геокодер один раз и запоминает ответ."""

    ready: list[AddressSuggestion] = []
    for hit in hits:
        if hit.address_level != "HOUSE" or hit.latitude is not None or not hit.address_external_id:
            ready.append(hit)
            continue
        cached = _read_cache(hit.address_external_id)
        if cached is not None:
            ready.append(_apply(hit, cached))
            continue
        try:
            found = search(_geocode_query(hit)) or []
        except GeocodingError:
            found = []
        if not found:
            ready.append(hit)
            continue
        chosen = _pick(hit, found)
        _write_cache(hit.address_external_id, chosen)
        if chosen["coordinate_quality"] == "EXACT":
            _store_exact_point(hit.address_external_id, chosen["latitude"], chosen["longitude"])
        ready.append(_apply(hit, chosen))
    return ready


def _geocode_query(hit: AddressSuggestion) -> str:
    official = (hit.official_address or hit.normalized_address or "").strip()
    region = (hit.region or "").strip()
    if region and region.casefold() not in official.casefold():
        return f"{region}, {official}"
    return official


def _number(value: str | None) -> str:
    return fold(value or "").replace(" ", "")


def _pick(hit: AddressSuggestion, found: list[AddressSuggestion]) -> dict:
    wanted = _number(hit.house)
    for item in found:
        quality = item.precision if item.precision in _QUALITIES else "UNKNOWN"
        if quality in {"EXACT"} and wanted and _number(item.house) == wanted and item.latitude is not None and item.longitude is not None:
            return {
                "latitude": float(item.latitude),
                "longitude": float(item.longitude),
                "coordinate_quality": "EXACT",
                "coordinate_source": item.address_source or "geocoder",
            }
    for item in found:
        quality = item.precision if item.precision in {"STREET", "SETTLEMENT", "INTERPOLATED"} else ""
        if quality and item.latitude is not None and item.longitude is not None:
            return {
                "latitude": float(item.latitude),
                "longitude": float(item.longitude),
                "coordinate_quality": quality,
                "coordinate_source": item.address_source or "geocoder",
            }
    return {"latitude": None, "longitude": None, "coordinate_quality": "UNKNOWN", "coordinate_source": None}


def _apply(hit: AddressSuggestion, chosen: dict) -> AddressSuggestion:
    return replace(
        hit,
        latitude=chosen["latitude"],
        longitude=chosen["longitude"],
        precision=chosen["coordinate_quality"],
        coordinate_quality=chosen["coordinate_quality"],
        coordinate_source=chosen["coordinate_source"],
    )


def _cache_key(external_id: str) -> str:
    return f"house-point|{external_id}"[:400]


def _read_cache(external_id: str) -> dict | None:
    try:
        with db.session.begin_nested():
            row = db.session.scalar(
                select(GeoGeocodeCache).where(
                    GeoGeocodeCache.cache_key == _cache_key(external_id),
                    GeoGeocodeCache.deleted_at.is_(None),
                )
            )
            payload = row.payload if row is not None else None
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return None
        item = payload[0]
        if "coordinate_quality" not in item:
            return None
        return item
    except Exception:
        return None


def _write_cache(external_id: str, chosen: dict) -> None:
    try:
        with db.session.begin_nested():
            key = _cache_key(external_id)
            row = db.session.scalar(select(GeoGeocodeCache).where(GeoGeocodeCache.cache_key == key))
            if row is None:
                db.session.add(
                    GeoGeocodeCache(
                        cache_key=key,
                        provider=str(chosen.get("coordinate_source") or "geocoder")[:32],
                        payload=[chosen],
                    )
                )
            else:
                row.provider = str(chosen.get("coordinate_source") or "geocoder")[:32]
                row.payload = [chosen]
                row.deleted_at = None
        db.session.commit()
    except Exception:
        db.session.rollback()


def _store_exact_point(external_id: str, latitude: float | None, longitude: float | None) -> None:
    if latitude is None or longitude is None:
        return
    row = db.session.scalar(
        select(GeoHouse).where(GeoHouse.external_id == external_id, GeoHouse.deleted_at.is_(None))
    )
    if row is None:
        return
    row.latitude = latitude
    row.longitude = longitude
    db.session.commit()
