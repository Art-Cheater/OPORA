"""Открытые заявки для публичной карты.

Наружу уходят только адрес неисправности и статус. Имена, телефоны, тексты
обращений, номера заявок и внутренние id не читаются из базы и не попадают в ответ.
"""

from __future__ import annotations

import re
import threading
import time
from decimal import Decimal

from flask import current_app

from app.extensions import db
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus

PUBLIC_FIELDS = ("address", "status", "district", "lat", "lon")
_MAX_ITEMS = 2000
_CACHE_SECONDS = 30
_PHONE = re.compile(
    r"(?:\+?\d[\d\-\s()]{8,}\d)|(?:\b\d{3}[\s\-]\d{2}[\s\-]\d{2}\b)",
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_APARTMENT = re.compile(r"(?:,?\s*)(?:кв\.?|квартира)\s*\d+\w*", re.IGNORECASE)
_cache_lock = threading.Lock()
_cache_payload: list[dict] | None = None
_cache_until = 0.0


def public_open_requests() -> list[dict]:
    if not current_app.config.get("TESTING"):
        cached = _read_cache()
        if cached is not None:
            return cached
    items = _load_open_requests()
    if not current_app.config.get("TESTING"):
        _write_cache(items)
    return items


def _load_open_requests() -> list[dict]:
    rows = db.session.execute(
        db.select(
            Request.address,
            Request.street,
            Request.house,
            Request.district,
            Request.latitude,
            Request.longitude,
            RequestStatus.name,
        )
        .join(RequestStatus, Request.status_id == RequestStatus.id)
        .where(
            Request.deleted_at.is_(None),
            RequestStatus.deleted_at.is_(None),
            RequestStatus.is_active.is_(True),
            RequestStatus.is_final.is_(False),
        )
        .order_by(Request.received_at.desc(), Request.created_at.desc())
        .limit(_MAX_ITEMS)
    ).all()
    items: list[dict] = []
    for address, street, house, district, latitude, longitude, status_name in rows:
        public_address = _public_address(street, house, address)
        status = _scrub(status_name, 80)
        if not public_address or not status:
            continue
        item = {"address": public_address, "status": status}
        public_district = _scrub(district, 80)
        if public_district:
            item["district"] = public_district
        point = _public_point(latitude, longitude)
        if point is not None:
            item["lat"], item["lon"] = point
        items.append(item)
    return items


def _public_address(street: str | None, house: str | None, address: str | None) -> str:
    street_text = _scrub(street, 160)
    house_text = _scrub(house, 40)
    if street_text and house_text:
        return _scrub(f"{street_text}, {house_text}", 180)
    if street_text:
        return street_text
    return _scrub(address, 180)


def _public_point(latitude: Decimal | float | None, longitude: Decimal | float | None) -> tuple[float, float] | None:
    if latitude is None or longitude is None:
        return None
    lat = round(float(latitude), 5)
    lon = round(float(longitude), 5)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 0.01 and abs(lon) < 0.01:
        return None
    return lat, lon


def _scrub(value: str | None, limit: int) -> str:
    text = " ".join((value or "").split())
    text = _EMAIL.sub("", text)
    text = _PHONE.sub("", text)
    text = _APARTMENT.sub("", text)
    text = " ".join(text.split()).strip(" ,;")
    return text[:limit].strip()


def _read_cache() -> list[dict] | None:
    with _cache_lock:
        if _cache_payload is not None and time.monotonic() < _cache_until:
            return list(_cache_payload)
    return None


def _write_cache(items: list[dict]) -> None:
    global _cache_payload, _cache_until
    with _cache_lock:
        _cache_payload = list(items)
        _cache_until = time.monotonic() + _CACHE_SECONDS
