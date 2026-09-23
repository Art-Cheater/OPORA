"""Импорт подъездов OSM. Это разовая команда администратора, не запрос карты."""

from __future__ import annotations

import json
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select

from app.extensions import db
from app.models.geo.directory import GeoEntrance

_BATCH = 400


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("неполный OSM PBF")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def _fields(buf: bytes) -> list[tuple[int, int, object]]:
    pos = 0
    found = []
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
            found.append((field, wire, value))
        elif wire == 2:
            length, pos = _varint(buf, pos)
            found.append((field, wire, buf[pos : pos + length]))
            pos += length
        elif wire == 1:
            found.append((field, wire, buf[pos : pos + 8]))
            pos += 8
        elif wire == 5:
            found.append((field, wire, buf[pos : pos + 4]))
            pos += 4
        else:
            raise ValueError("неподдерживаемое поле OSM PBF")
    return found


def _zigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _packed(buf: bytes) -> list[int]:
    pos = 0
    values = []
    while pos < len(buf):
        value, pos = _varint(buf, pos)
        values.append(value)
    return values


def _blob_payload(blob: bytes) -> bytes:
    raw = b""
    compressed = b""
    for field, _wire, value in _fields(blob):
        if field == 1 and isinstance(value, bytes):
            raw = value
        elif field == 3 and isinstance(value, bytes):
            compressed = value
    if compressed:
        return zlib.decompress(compressed)
    return raw


def iter_pbf_nodes(path: str | Path) -> Iterator[dict]:
    """Узлы OSM PBF. Линии зданий не читаются: подъезд в выгрузке почти всегда точка."""

    data = Path(path).read_bytes()
    pos = 0
    while pos + 4 <= len(data):
        size = int.from_bytes(data[pos : pos + 4], "big")
        pos += 4
        header = data[pos : pos + size]
        pos += size
        blob_type = ""
        blob_size = 0
        for field, _wire, value in _fields(header):
            if field == 1 and isinstance(value, bytes):
                blob_type = value.decode("utf-8", "replace")
            elif field == 3 and isinstance(value, int):
                blob_size = value
        blob = data[pos : pos + blob_size]
        pos += blob_size
        if blob_type != "OSMData":
            continue
        payload = _blob_payload(blob)
        strings = [b""]
        groups = []
        granularity = 100
        lat_offset = 0
        lon_offset = 0
        for field, _wire, value in _fields(payload):
            if field == 1 and isinstance(value, bytes):
                strings = [item.decode("utf-8", "replace") for _f, _w, item in _fields(value) if _f == 1 and isinstance(item, bytes)] or [""]
            elif field == 2 and isinstance(value, bytes):
                groups.append(value)
            elif field == 17 and isinstance(value, int):
                granularity = value or 100
            elif field == 19 and isinstance(value, int):
                lat_offset = _zigzag(value)
            elif field == 20 and isinstance(value, int):
                lon_offset = _zigzag(value)
        for group in groups:
            dense = next((value for field, _wire, value in _fields(group) if field == 2 and isinstance(value, bytes)), None)
            if not isinstance(dense, bytes):
                continue
            ids: list[int] = []
            lats: list[int] = []
            lons: list[int] = []
            tags: list[int] = []
            for field, _wire, value in _fields(dense):
                if not isinstance(value, bytes):
                    continue
                if field == 1:
                    ids = [_zigzag(item) for item in _packed(value)]
                elif field == 8:
                    lats = [_zigzag(item) for item in _packed(value)]
                elif field == 9:
                    lons = [_zigzag(item) for item in _packed(value)]
                elif field == 10:
                    tags = _packed(value)
            node_id = lat = lon = 0
            cursor = 0
            for index, delta in enumerate(ids):
                node_id += delta
                lat += lats[index] if index < len(lats) else 0
                lon += lons[index] if index < len(lons) else 0
                node_tags = {}
                while cursor < len(tags) and tags[cursor] != 0:
                    key_index = tags[cursor]
                    value_index = tags[cursor + 1] if cursor + 1 < len(tags) else 0
                    cursor += 2
                    if key_index < len(strings) and value_index < len(strings):
                        node_tags[strings[key_index]] = strings[value_index]
                if cursor < len(tags) and tags[cursor] == 0:
                    cursor += 1
                if node_tags:
                    yield {
                        "id": str(node_id),
                        "lat": (lat_offset + granularity * lat) / 1_000_000_000,
                        "lon": (lon_offset + granularity * lon) / 1_000_000_000,
                        "tags": node_tags,
                    }


def _xml_elements(path: Path) -> Iterator[dict]:
    nodes: dict[str, tuple[float, float]] = {}
    for _event, elem in ET.iterparse(path, events=("end",)):
        kind = elem.tag.rsplit("}", 1)[-1]
        if kind == "node" and elem.get("id") and elem.get("lat") and elem.get("lon"):
            tags = {tag.get("k"): tag.get("v") for tag in elem if tag.tag.rsplit("}", 1)[-1] == "tag"}
            nodes[elem.get("id")] = (float(elem.get("lat")), float(elem.get("lon")))
            if tags:
                yield {"id": elem.get("id"), "lat": float(elem.get("lat")), "lon": float(elem.get("lon")), "tags": tags}
        elif kind == "way":
            tags = {tag.get("k"): tag.get("v") for tag in elem if tag.tag.rsplit("}", 1)[-1] == "tag"}
            refs = [node.get("ref") for node in elem if node.tag.rsplit("}", 1)[-1] == "nd" and node.get("ref") in nodes]
            if tags and refs:
                points = [nodes[ref] for ref in refs]
                lat = sum(point[0] for point in points) / len(points)
                lon = sum(point[1] for point in points) / len(points)
                yield {"id": elem.get("id"), "lat": lat, "lon": lon, "tags": tags, "building_osm_id": elem.get("id") if tags.get("building") else None}
        if kind in {"node", "way", "relation"}:
            elem.clear()


def _json_elements(path: Path) -> Iterator[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("elements") or []:
        if not isinstance(item, dict) or item.get("lat") is None or item.get("lon") is None:
            continue
        yield {
            "id": str(item.get("id") or ""),
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "tags": item.get("tags") or {},
        }


def _elements(path: Path) -> Iterator[dict]:
    name = path.name.casefold()
    if name.endswith(".pbf"):
        return iter_pbf_nodes(path)
    if name.endswith(".json"):
        return _json_elements(path)
    return _xml_elements(path)


def _entrance_record(item: dict) -> dict | None:
    tags = {str(key): str(value) for key, value in (item.get("tags") or {}).items() if key}
    entrance = tags.get("entrance") or tags.get("door")
    if not entrance:
        return None
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    street = tags.get("addr:street") or ""
    house = tags.get("addr:housenumber") or ""
    settlement = tags.get("addr:city") or tags.get("addr:place") or tags.get("addr:suburb") or ""
    address = ", ".join(part for part in (settlement, street, f"д. {house}" if house else "") if part)
    return {
        "external_id": str(item.get("id") or "")[:128],
        "osm_id": str(item.get("id") or "")[:64],
        "lat": lat,
        "lon": lon,
        "entrance_type": entrance[:32],
        "ref": (tags.get("ref") or "")[:32] or None,
        "name": (tags.get("name") or "")[:255] or None,
        "settlement": settlement[:255] or None,
        "street": street[:255] or None,
        "house": house[:32] or None,
        "address_text": address[:500] or None,
        "building_osm_id": (str(item.get("building_osm_id") or tags.get("building:id") or "")[:64] or None),
    }


def import_entrances(path: str | Path, *, progress: Callable[[str], None] | None = None) -> dict[str, int]:
    """Повторный запуск обновляет тот же osm id. Заявки и дома ГАР не изменяет."""

    stats = {"created": 0, "updated": 0, "skipped": 0}
    source = "osm"
    existing = {
        row.external_id: row
        for row in db.session.scalars(select(GeoEntrance).where(GeoEntrance.source == source, GeoEntrance.deleted_at.is_(None)))
    }
    pending = 0
    seen = 0
    for item in _elements(Path(path)):
        seen += 1
        if progress and seen % 5000 == 0:
            progress(f"Просмотрено объектов OSM: {seen}")
        record = _entrance_record(item)
        if record is None or not record["external_id"]:
            stats["skipped"] += 1
            continue
        row = existing.get(record["external_id"])
        is_new = row is None
        row = row or GeoEntrance(source=source, external_id=record["external_id"], latitude=record["lat"], longitude=record["lon"])
        row.latitude = record["lat"]
        row.longitude = record["lon"]
        row.osm_id = record["osm_id"]
        row.entrance_type = record["entrance_type"]
        row.ref = record["ref"]
        row.name = record["name"]
        row.settlement_name = record["settlement"]
        row.street_name = record["street"]
        row.house_number = record["house"]
        row.address_text = record["address_text"]
        row.building_osm_id = record["building_osm_id"]
        if is_new:
            db.session.add(row)
            existing[record["external_id"]] = row
            stats["created"] += 1
        else:
            stats["updated"] += 1
        pending += 1
        if pending >= _BATCH:
            db.session.commit()
            pending = 0
    db.session.commit()
    if progress:
        progress("Подъезды: создано={created}, обновлено={updated}, пропущено={skipped}".format(**stats))
    return stats
