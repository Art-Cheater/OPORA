"""Поиск по импортированному справочнику. Пустая таблица не меняет старые подсказки."""

from __future__ import annotations

import re

from sqlalchemy import or_, select

from app.core.address.normalize import fold
from app.core.address.providers import AddressSuggestion
from app.extensions import db
from app.models.geo.directory import GeoHouse, GeoSettlement, GeoStreet
from app.modules.requests.address_format import split_address_query

_PLACE = re.compile(
    r"^(?:деревня|село|пос[её]лок|поселок|пгт|город|г\.?|д\.?|с\.)\s+",
    re.IGNORECASE,
)
_STREET_START = re.compile(
    r"^(?:улица|ул\.?|проспект|пр-т\.?|пр\.?|переулок|пер\.?|площадь|пл\.?|шоссе|ш\.?|набережная|наб\.?|бульвар|б-р\.?|проезд|тупик|микрорайон|мкр\.?)\s+",
    re.IGNORECASE,
)
_CORPUS = re.compile(r"(?:корпус|корп\.?|(?<![\wа-яё])к\.)\s*([0-9]+[а-яa-z]?)", re.IGNORECASE)
_STRUCTURE = re.compile(r"(?:строение|стр\.)\s*([0-9]+[а-яa-z]?)", re.IGNORECASE)


def split_place(query: str) -> tuple[str | None, str]:
    parts = [part.strip() for part in (query or "").split(",") if part.strip()]
    if len(parts) < 2:
        return None, query
    first, rest = parts[0], ", ".join(parts[1:])
    if _STREET_START.match(first) or re.fullmatch(r"(?:д\.?|дом)?\s*\d+\S*", rest, re.IGNORECASE):
        return None, query
    settlement = _PLACE.sub("", first).strip()
    return settlement or None, rest


def search_settlements(query: str, *, limit: int = 8) -> list[AddressSuggestion]:
    cleaned = _PLACE.sub("", " ".join((query or "").split())).strip()
    name_key = fold(cleaned)
    if len(name_key) < 3:
        return []
    rows = db.session.scalars(
        select(GeoSettlement)
        .where(
            GeoSettlement.deleted_at.is_(None),
            or_(GeoSettlement.name_key == name_key, GeoSettlement.name_key.startswith(name_key)),
        )
        .limit(limit)
    )
    hits = []
    for row in rows:
        hits.append(
            AddressSuggestion(
                original_address=query,
                normalized_address=f"{row.region_name or 'Кировская область'}, {row.kind} {row.name}",
                region=row.region_name,
                district=row.district_name,
                settlement=row.name,
                latitude=float(row.latitude) if row.latitude is not None else None,
                longitude=float(row.longitude) if row.longitude is not None else None,
                address_source="directory",
                address_external_id=row.external_id,
                other_settlement=fold(row.name) not in {"киров", "город киров"},
                precision="SETTLEMENT",
                official_address=f"{row.region_name or 'Кировская область'}, {row.kind} {row.name}",
                fias_id=row.fias_id,
                address_level="SETTLEMENT",
                coordinate_quality="SETTLEMENT" if row.latitude is not None else "UNKNOWN",
                coordinate_source="directory" if row.latitude is not None else None,
            )
        )
    return hits


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
        corpus = _CORPUS.search(cleaned)
        structure = _STRUCTURE.search(cleaned)
        rows = db.session.scalars(
            select(GeoHouse).where(
                GeoHouse.deleted_at.is_(None),
                GeoHouse.street_id.in_([street.id for street in streets]),
                GeoHouse.number_key == number_key,
            )
        )
        for row in rows:
            if corpus and fold(row.building or "") != fold(corpus.group(1)):
                continue
            if structure and fold(getattr(row, "structure", None) or "") != fold(structure.group(1)):
                continue
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
            suffix = f"дом {row.number if row is not None else house}"
            if row is not None and row.building:
                suffix = f"{suffix}, корп. {row.building}"
            if row is not None and row.structure:
                suffix = f"{suffix}, стр. {row.structure}"
            normalized = f"{normalized}, {suffix}"
        lat = float(row.latitude) if row is not None and row.latitude is not None else None
        lon = float(row.longitude) if row is not None and row.longitude is not None else None
        matched_house = row is not None and bool(house)
        if matched_house:
            level = "HOUSE"
            quality = "EXACT" if lat is not None else "UNKNOWN"
            point_source = "directory" if lat is not None else None
            fias_id = row.fias_id
            external_id = row.external_id
        else:
            level = "STREET"
            quality = "STREET"
            point_source = None
            fias_id = street.fias_id
            external_id = street.external_id
        hits.append(
            AddressSuggestion(
                original_address=cleaned,
                normalized_address=normalized,
                region=street.region_name or "Кировская область",
                district=street.district_name,
                settlement=settlement,
                street=label,
                house=row.number if matched_house else (house or None),
                latitude=lat,
                longitude=lon,
                address_source="directory",
                address_external_id=external_id,
                other_settlement=fold(settlement) not in {"киров", "город киров"},
                precision=quality,
                official_address=normalized,
                fias_id=fias_id,
                address_level=level,
                coordinate_source=point_source,
                coordinate_quality=quality,
            )
        )
        if len(hits) >= limit:
            break
    return hits
