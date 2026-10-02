"""Чтение открытых заявок напрямую из PostgreSQL контейнера db.

В запрос входят только адрес и статус. Телефон, имя, текст и номер заявки
в SELECT нет — их нельзя случайно отдать наружу.
"""

from __future__ import annotations

import os
import re

_PHONE = re.compile(r"(?:\+?\d[\d\-\s()]{8,}\d)|(?:\b\d{3}[\s\-]\d{2}[\s\-]\d{2}\b)")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_APARTMENT = re.compile(r"(?:,?\s*)(?:кв\.?|квартира)\s*\d+\w*", re.IGNORECASE)

# Явный список колонок. Не добавлять phone, applicant_name, description, title, number, id.
OPEN_REQUESTS_SQL = """
SELECT r.address, r.street, r.house, r.district, r.latitude, r.longitude, s.name
FROM requests r
JOIN request_statuses s ON s.id = r.status_id
WHERE r.deleted_at IS NULL
  AND s.deleted_at IS NULL
  AND s.is_active IS TRUE
  AND s.is_final IS FALSE
ORDER BY r.received_at DESC NULLS LAST, r.created_at DESC
LIMIT 2000
"""


def connect():
    import psycopg2

    user = os.environ.get("POSTGRES_USER", "").strip()
    password = os.environ.get("POSTGRES_PASSWORD")
    host = (os.environ.get("DB_HOST") or os.environ.get("POSTGRES_HOST") or "").strip()
    if not user or password is None or not host:
        raise RuntimeError("Не заданы DB_HOST, POSTGRES_USER и POSTGRES_PASSWORD")
    schema = os.environ.get("POSTGRES_SCHEMA", "opora").strip() or "public"
    if not schema.replace("_", "").isalnum():
        raise RuntimeError("Недопустимое имя схемы")
    port = os.environ.get("DB_PORT") or os.environ.get("POSTGRES_PORT") or "5432"
    dbname = os.environ.get("POSTGRES_DB", "opora").strip() or "opora"
    return psycopg2.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        dbname=dbname,
        connect_timeout=5,
        options=f"-csearch_path={schema},public",
    )


def load_open_requests(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(OPEN_REQUESTS_SQL)
        rows = cursor.fetchall()
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


def _public_address(street, house, address) -> str:
    street_text = _scrub(street, 160)
    house_text = _scrub(house, 40)
    if street_text and house_text:
        return _scrub(f"{street_text}, {house_text}", 180)
    if street_text:
        return street_text
    return _scrub(address, 180)


def _public_point(latitude, longitude):
    if latitude is None or longitude is None:
        return None
    lat = round(float(latitude), 5)
    lon = round(float(longitude), 5)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 0.01 and abs(lon) < 0.01:
        return None
    return lat, lon


def _scrub(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    text = _EMAIL.sub("", text)
    text = _PHONE.sub("", text)
    text = _APARTMENT.sub("", text)
    return " ".join(text.split()).strip(" ,;")[:limit].strip()
