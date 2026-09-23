"""Импорт официального XML-архива ГАР/ФИАС. В заявки и ручные координаты не пишет."""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select

from app.core.address.normalize import fold
from app.extensions import db
from app.models.geo.directory import GeoHouse, GeoSettlement, GeoStreet

_BATCH = 400
_SETTLEMENT_LEVELS = {"4", "5", "6"}
_STREET_LEVELS = {"7", "8"}
_KIND = {
    "ул": "улица",
    "улица": "улица",
    "пр-кт": "проспект",
    "проспект": "проспект",
    "пер": "переулок",
    "переулок": "переулок",
    "пл": "площадь",
    "площадь": "площадь",
    "ш": "шоссе",
    "шоссе": "шоссе",
    "наб": "набережная",
    "набережная": "набережная",
    "б-р": "бульвар",
    "бульвар": "бульвар",
    "проезд": "проезд",
    "туп": "тупик",
    "тупик": "тупик",
    "мкр": "микрорайон",
    "микрорайон": "микрорайон",
    "г": "город",
    "город": "город",
    "д": "деревня",
    "деревня": "деревня",
    "с": "село",
    "село": "село",
    "п": "поселок",
    "пгт": "пгт",
    "рп": "поселок",
    "х": "хутор",
    "дп": "поселок",
    "кп": "поселок",
}
_DEFAULT_ADD = {"1": "корпус", "2": "строение", "3": "сооружение", "4": "литера"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].upper()


def _attr(elem: ET.Element, *names: str) -> str:
    wanted = {name.upper() for name in names}
    for key, value in elem.attrib.items():
        if key.upper() in wanted:
            return " ".join(str(value or "").split())
    return ""


def _active(elem: ET.Element) -> bool:
    flag = _attr(elem, "ISACTIVE")
    actual = _attr(elem, "ISACTUAL")
    if flag and flag not in {"1", "true"}:
        return False
    if actual and actual not in {"1", "true"}:
        return False
    return bool(flag or actual)


def _kind(typename: str, default: str) -> str:
    return _KIND.get(typename.casefold(), typename or default)[:32]


def _region_folder(region: str) -> str:
    text = str(region or "43").strip()
    return text.zfill(2) if text.isdigit() else text


def _members(names: list[str], region: str) -> dict[str, list[str]]:
    folder = _region_folder(region)
    groups = {"objects": [], "houses": [], "hierarchy": [], "house_types": [], "add_types": []}
    for name in names:
        parts = name.replace("\\", "/").split("/")
        filename = parts[-1].upper()
        parent = parts[-2] if len(parts) > 1 else ""
        parent_key = parent.lstrip("0") or "0"
        in_region = parent_key == folder.lstrip("0")
        if filename.startswith("AS_ADDR_OBJ_") and "PARAM" not in filename and "DIVISION" not in filename and "TYPE" not in filename and in_region:
            groups["objects"].append(name)
        elif filename.startswith("AS_HOUSES_") and "PARAM" not in filename and in_region:
            groups["houses"].append(name)
        elif filename.startswith("AS_ADM_HIERARCHY_") and in_region:
            groups["hierarchy"].append(name)
        elif filename.startswith("AS_HOUSE_TYPES_"):
            groups["house_types"].append(name)
        elif filename.startswith("AS_ADDHOUSE_TYPES_"):
            groups["add_types"].append(name)
    if not groups["hierarchy"]:
        groups["hierarchy"] = [
            name
            for name in names
            if Path(name).name.upper().startswith("AS_MUN_HIERARCHY_")
            and ((name.replace("\\", "/").split("/")[-2].lstrip("0") or "0") == folder.lstrip("0") if "/" in name.replace("\\", "/") or "\\" in name else False)
        ]
    return groups


_ROW_TAGS = {"OBJECT", "HOUSE", "ITEM"}


def _xml_rows(archive: zipfile.ZipFile, name: str) -> Iterator[ET.Element]:
    with archive.open(name) as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
            if elem.attrib and _local(elem.tag) in _ROW_TAGS:
                yield elem
            elem.clear()


def _load(model, source: str) -> dict[str, object]:
    rows = db.session.scalars(select(model).where(model.source == source, model.deleted_at.is_(None)))
    return {row.external_id: row for row in rows}


def _save(row, existing: dict, stats: dict[str, int], pending: list[int]) -> None:
    if row.external_id in existing and existing[row.external_id] is not row:
        stats["updated"] += 1
    elif row.external_id not in existing:
        db.session.add(row)
        existing[row.external_id] = row
        stats["created"] += 1
        pending[0] += 1
        if pending[0] >= _BATCH:
            db.session.commit()
            pending[0] = 0
    else:
        stats["updated"] += 1


def import_gar_archive(path: str | Path, *, region: str = "43", progress: Callable[[str], None] | None = None) -> dict[str, int]:
    """Загружает один регион из zip ГАР. Повтор обновляет те же GUID и не плодит дубли.

    Координаты домов архив не задаёт: широта и долгота остаются пустыми,
    чтобы геокодер или ручная точка заполнили их отдельно.
    """

    stats = {"created": 0, "updated": 0, "skipped": 0, "settlements": 0, "streets": 0, "houses": 0}
    source = "gar"
    folder = _region_folder(region)
    region_label = "Кировская область" if folder.lstrip("0") == "43" else f"Регион {folder}"

    def emit(message: str) -> None:
        if progress:
            progress(message)

    with zipfile.ZipFile(path) as archive:
        groups = _members(archive.namelist(), region)
        if not groups["objects"] or not groups["houses"] or not groups["hierarchy"]:
            raise ValueError(
                f"В архиве нет XML региона {folder}. Нужны AS_ADDR_OBJ, AS_HOUSES и AS_ADM_HIERARCHY внутри папки региона."
            )
        add_types = dict(_DEFAULT_ADD)
        for name in groups["add_types"]:
            for elem in _xml_rows(archive, name):
                type_id = _attr(elem, "ID")
                short = _attr(elem, "SHORTNAME") or _attr(elem, "NAME")
                if type_id and short:
                    add_types[type_id] = short.casefold()
        objects: dict[str, dict] = {}
        parents: dict[str, str] = {}
        for name in groups["objects"]:
            emit(f"Объекты: {name}")
            for elem in _xml_rows(archive, name):
                if not _active(elem):
                    continue
                object_id = _attr(elem, "OBJECTID")
                name_text = _attr(elem, "NAME")
                if not object_id or not name_text:
                    continue
                objects[object_id] = {
                    "id": object_id,
                    "guid": _attr(elem, "OBJECTGUID") or f"gar:{object_id}",
                    "name": name_text,
                    "typename": _attr(elem, "TYPENAME"),
                    "level": _attr(elem, "LEVEL"),
                }
        for name in groups["hierarchy"]:
            emit(f"Иерархия: {name}")
            for elem in _xml_rows(archive, name):
                if not _active(elem):
                    continue
                object_id = _attr(elem, "OBJECTID")
                parent_id = _attr(elem, "PARENTOBJID")
                if object_id and parent_id and parent_id != "0":
                    parents[object_id] = parent_id

        def chain(start: str) -> list[dict]:
            found = []
            current = parents.get(start)
            seen: set[str] = set()
            while current and current not in seen:
                seen.add(current)
                item = objects.get(current)
                if item:
                    found.append(item)
                current = parents.get(current)
            return found

        settlements = _load(GeoSettlement, source)
        streets = _load(GeoStreet, source)
        houses = _load(GeoHouse, source)
        pending = [0]
        settlement_by_guid: dict[str, GeoSettlement] = {}
        street_by_guid: dict[str, GeoStreet] = {}

        for object_id, item in objects.items():
            if item["level"] not in _SETTLEMENT_LEVELS:
                continue
            guid = item["guid"][:128]
            row = settlements.get(guid) or GeoSettlement(source=source, external_id=guid, name=item["name"], name_key=fold(item["name"])[:255])
            ancestors = chain(object_id)
            district = next((parent["name"] for parent in ancestors if parent["level"] in {"2", "3"}), None)
            region_name = next((parent["name"] for parent in ancestors if parent["level"] == "1"), None)
            row.kind = _kind(item["typename"], "населенный пункт")
            row.name = item["name"][:255]
            row.name_key = fold(item["name"])[:255]
            row.region_name = (region_name or region_label)[:255]
            row.district_name = district[:255] if district else None
            row.fias_id = guid[:64]
            _save(row, settlements, stats, pending)
            settlement_by_guid[guid] = row
            stats["settlements"] += 1
        db.session.commit()
        pending[0] = 0

        for object_id, item in objects.items():
            if item["level"] not in _STREET_LEVELS:
                continue
            guid = item["guid"][:128]
            ancestors = chain(object_id)
            settlement = next((parent for parent in ancestors if parent["level"] in _SETTLEMENT_LEVELS), None)
            district = next((parent["name"] for parent in ancestors if parent["level"] in {"2", "3"}), None)
            settlement_row = settlement_by_guid.get(settlement["guid"][:128]) if settlement else None
            row = streets.get(guid) or GeoStreet(source=source, external_id=guid, name=item["name"], name_key=fold(item["name"])[:255])
            row.name = item["name"][:255]
            row.name_key = fold(item["name"])[:255]
            row.kind = _kind(item["typename"], "улица")
            row.settlement_name = (settlement_row.name if settlement_row else (settlement["name"] if settlement else None))
            row.settlement_id = settlement_row.id if settlement_row is not None else None
            row.district_name = district[:255] if district else None
            row.region_name = region_label[:255]
            row.fias_id = guid[:64]
            _save(row, streets, stats, pending)
            street_by_guid[guid] = row
            stats["streets"] += 1
        db.session.commit()
        pending[0] = 0

        seen_houses = 0
        for name in groups["houses"]:
            emit(f"Дома: {name}")
            for elem in _xml_rows(archive, name):
                seen_houses += 1
                if seen_houses % 5000 == 0:
                    emit(f"Дома просмотрено: {seen_houses}")
                if not _active(elem):
                    stats["skipped"] += 1
                    continue
                number = _attr(elem, "HOUSENUM")
                object_id = _attr(elem, "OBJECTID")
                if not number or not object_id:
                    stats["skipped"] += 1
                    continue
                ancestors = chain(object_id)
                street = next((parent for parent in ancestors if parent["level"] in _STREET_LEVELS), None)
                if street is None:
                    stats["skipped"] += 1
                    continue
                street_row = street_by_guid.get(street["guid"][:128])
                add1 = _attr(elem, "ADDNUM1")
                add2 = _attr(elem, "ADDNUM2")
                add_kind_1 = add_types.get(_attr(elem, "ADDTYPE1"), "")
                add_kind_2 = add_types.get(_attr(elem, "ADDTYPE2"), "")
                corpus = structure = ""
                for value, kind_name in ((add1, add_kind_1), (add2, add_kind_2)):
                    if not value:
                        continue
                    if "стр" in kind_name:
                        structure = value
                    elif "лит" in kind_name:
                        number = f"{number}{value}"
                    else:
                        corpus = corpus or value
                guid = (_attr(elem, "OBJECTGUID") or f"house:{object_id}")[:128]
                row = houses.get(guid) or GeoHouse(source=source, external_id=guid, number=number[:32], number_key=fold(number).replace(" ", "")[:32])
                row.number = number[:32]
                row.number_key = fold(number).replace(" ", "")[:32]
                row.building = corpus[:32] or None
                row.structure = structure[:32] or None
                row.street_id = street_row.id if street_row is not None else None
                row.fias_id = guid[:64]
                _save(row, houses, stats, pending)
                stats["houses"] += 1
        db.session.commit()
    emit(
        "Импорт ГАР: населённые пункты={settlements}, улицы={streets}, дома={houses}, "
        "создано={created}, обновлено={updated}, пропущено={skipped}".format(**stats)
    )
    return stats
