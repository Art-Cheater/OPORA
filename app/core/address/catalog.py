"""Поиск по справочнику улиц Кирова: опечатки, тип, район."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.address.kirov_streets import KIROV_STREETS
from app.modules.requests.address_format import CITY, split_address_query

_KIND_RANK = {
    "улица": 0,
    "проспект": 1,
    "бульвар": 2,
    "площадь": 3,
    "набережная": 4,
    "переулок": 5,
    "проезд": 6,
    "шоссе": 7,
    "тракт": 8,
    "микрорайон": 9,
}

# При равном совпадении имени — сначала центральные районы, Нововятский в конце.
_DISTRICT_RANK = {
    "Ленинский район": 0,
    "Октябрьский район": 1,
    "Первомайский район": 2,
    "Нововятский район": 3,
}

# Главная «городская» улица, если одно имя есть в нескольких районах.
_PRIMARY_DISTRICT: dict[tuple[str, str], str] = {
    ("ленина", "улица"): "Октябрьский район",
    ("воровского", "улица"): "Первомайский район",
    ("московская", "улица"): "Ленинский район",
    ("советская", "улица"): "Октябрьский район",
    ("комсомольская", "улица"): "Октябрьский район",
    ("мира", "улица"): "Первомайский район",
    ("производственная", "улица"): "Ленинский район",
    ("свободы", "улица"): "Первомайский район",
    ("труда", "улица"): "Октябрьский район",
}


def _fold(text: str) -> str:
    return (text or "").casefold().replace("ё", "е").replace("й", "и")


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, char_l in enumerate(left, 1):
        current = [i]
        for j, char_r in enumerate(right, 1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (char_l != char_r)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


@dataclass(frozen=True, slots=True)
class StreetRecord:
    name: str
    kind: str
    district: str

    @property
    def folded_name(self) -> str:
        return _fold(self.name)

    @property
    def label(self) -> str:
        return f"{self.kind} {self.name}"


@lru_cache(maxsize=1)
def all_streets() -> tuple[StreetRecord, ...]:
    seen: set[tuple[str, str, str]] = set()
    items: list[StreetRecord] = []
    for name, kind, district in KIROV_STREETS:
        key = (_fold(name), kind, district)
        if key in seen:
            continue
        seen.add(key)
        items.append(StreetRecord(name=name, kind=kind, district=district))
    return tuple(items)


def _name_score(query_name: str, street_name: str) -> int:
    query = _fold(query_name)
    street = _fold(street_name)
    if not query or not street:
        return 0
    if query == street:
        return 100
    if street.startswith(query) and len(query) >= 3:
        return 92 - min(len(street) - len(query), 20)
    if query.startswith(street) and len(street) >= 4:
        return 84
    if len(query) >= 4 and query in street:
        return 72
    distance = _levenshtein(query, street)
    if distance == 1 and len(query) >= 4:
        return 88
    if distance == 2 and len(query) >= 6:
        return 74
    if distance == 3 and len(query) >= 9:
        return 58
    return 0


def _kind_bonus(query_kind: str | None, street_kind: str) -> int:
    if not query_kind:
        return 0
    if query_kind == street_kind:
        return 8
    return -6


def _district_bonus(street: StreetRecord) -> int:
    primary = _PRIMARY_DISTRICT.get((street.folded_name, street.kind))
    if primary and street.district == primary:
        return 18
    return 0


def _district_rank(district: str) -> int:
    return _DISTRICT_RANK.get(district, 50)


@dataclass(frozen=True, slots=True)
class CatalogHit:
    name: str
    kind: str
    district: str
    house: str
    street_label: str
    normalized_address: str


def search_streets(query: str, *, limit: int = 8) -> list[CatalogHit]:
    """Реальные улицы Кирова, а не титульный регистр введённого текста."""
    kind, name, house = split_address_query(query)
    if not name or len(_fold(name)) < 3:
        return []

    ranked: list[tuple[int, StreetRecord]] = []
    for street in all_streets():
        score = (
            _name_score(name, street.name)
            + _kind_bonus(kind, street.kind)
            + _district_bonus(street)
        )
        if score < 40:
            continue
        ranked.append((score, street))

    ranked.sort(
        key=lambda item: (
            -item[0],
            _KIND_RANK.get(item[1].kind, 20),
            _district_rank(item[1].district),
            item[1].name,
        )
    )

    hits: list[CatalogHit] = []
    seen: set[tuple[str, str, str]] = set()
    for _score, street in ranked:
        key = (street.kind, street.name, street.district)
        if key in seen:
            continue
        seen.add(key)
        street_label = street.label
        normalized = f"{CITY}, {street_label}"
        if house:
            normalized = f"{normalized}, дом {house}"
        hits.append(
            CatalogHit(
                name=street.name,
                kind=street.kind,
                district=street.district,
                house=house,
                street_label=street_label,
                normalized_address=normalized,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def unique_districts_for_street(name: str, kind: str) -> list[str]:
    """Все районы, где есть улица с таким именем и типом."""
    folded = _fold(name)
    districts: list[str] = []
    seen: set[str] = set()
    for street in all_streets():
        if street.kind != kind or street.folded_name != folded:
            continue
        if street.district in seen:
            continue
        seen.add(street.district)
        districts.append(street.district)
    districts.sort(key=_district_rank)
    return districts


def resolve_catalog_district(name: str, kind: str, preferred: str | None = None) -> str | None:
    """Район для улицы: явный preferred, единственный вариант или главный из справочника."""
    options = unique_districts_for_street(name, kind)
    if not options:
        return None
    preferred_norm = (preferred or "").strip()
    if preferred_norm:
        for item in options:
            if preferred_norm.casefold() in item.casefold() or item.casefold() in preferred_norm.casefold():
                return item
    if len(options) == 1:
        return options[0]
    primary = _PRIMARY_DISTRICT.get((_fold(name), kind))
    if primary and primary in options:
        return primary
    return None
