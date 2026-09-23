"""Поиск по импортированному справочнику. Пустая таблица не меняет старые подсказки."""

from __future__ import annotations

import re

from sqlalchemy import or_, select

from app.core.address.normalize import fold
from app.core.address.providers import AddressSuggestion
from app.extensions import db
from app.models.geo.directory import GeoHouse, GeoStreet
from app.modules.requests.address_format import split_address_query

_PLACE = re.compile(
    r"^(?:деревня|село|пос[её]лок|поселок|пгт|город|г\.?|д\.?|с\.)\s+",
    re.IGNORECASE,
)


def split_place(query: str) -> tuple[str | None, str]:
    parts = [part.strip() for part in (query or "").split(",") if part.strip()]
    if len(parts) < 2 or not _PLACE.match(parts[0]):
        return None, query
    settlement = _PLACE.sub("", parts[0]).strip()
    return settlement or None, ", ".join(parts[1:])


def search_directory(query: str, *, limit: int = 8) -> list[AddressSuggestion]:
    cleaned = " ".join((query or "").split())
    if len(fold(cleaned)) < 3:
        return []
    settlement_name, rest = split_place(cleaned)
    kind, name, house = split_address_query(rest or cleaned)
    name_key = fold(name)
    if len(name_key) < 3:
        return []
    streets = list(
        db.session.scalars(
            select(GeoStreet)
            .where(
                GeoStreet.deleted_at.is_(None),
                or_(GeoStreet.name_key == name_key, GeoStreet.name_key.startswith(name_key)),
            )
            .limit(40)
        )
    )
    if settlement_name:
        wanted = fold(settlement_name)
        streets = [street for street in streets if fold(street.settlement_name or "") == wanted or wanted in fold(street.settlement_name or "")]
    if kind:
        typed = [street for street in streets if street.kind == kind]
        if typed:
            streets = typed
    houses: dict[str, GeoHouse] = {}
    if house and streets:
        number_key = fold(house).replace(" ", "")
        rows = db.session.scalars(
            select(GeoHouse).where(
                GeoHouse.deleted_at.is_(None),
                GeoHouse.street_id.in_([street.id for street in streets]),
                GeoHouse.number_key == number_key,
            )
        )
        for row in rows:
            houses.setdefault(str(row.street_id), row)
        if houses:
            streets = [street for street in streets if str(street.id) in houses]
    hits: list[AddressSuggestion] = []
    seen: set[tuple[str, str, str]] = set()
    for street in streets:
        key = (street.kind, street.name_key, fold(street.settlement_name or street.district_name or ""))
        if key in seen:
            continue
        seen.add(key)
        row = houses.get(str(street.id))
        settlement = street.settlement_name or "Киров"
        label = f"{street.kind} {street.name}"
        normalized = f"{settlement}, {label}"
        if house:
            normalized = f"{normalized}, дом {house}"
        lat = float(row.latitude) if row is not None and row.latitude is not None else None
        lon = float(row.longitude) if row is not None and row.longitude is not None else None
        hits.append(
            AddressSuggestion(
                original_address=cleaned,
                normalized_address=normalized,
                region=street.region_name or "Кировская область",
                district=street.district_name,
                settlement=settlement,
                street=label,
                house=house or None,
                latitude=lat,
                longitude=lon,
                address_source="directory",
                address_external_id=row.external_id if row is not None else street.external_id,
                other_settlement=fold(settlement) not in {"киров", "город киров"},
                precision="EXACT" if lat is not None and house else "STREET",
            )
        )
        if len(hits) >= limit:
            break
    return hits
