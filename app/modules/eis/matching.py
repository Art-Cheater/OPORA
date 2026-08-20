"""Сопоставление текста ЕИС с адресными объектами Опоры."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.requests.address_format import normalize_address, split_address_query
from app.models.work_objects.work_object import WorkObject

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_SETTLEMENT_RE = re.compile(
    r"(?:деревня|дер\.?|д\.?|поселок|посёлок|пос\.?|п\.?|село|с\.?|микрорайон|мкр\.?)\s+"
    r"([а-яёa-z0-9\-]+(?:\s+[а-яёa-z0-9\-]+)?)",
    re.IGNORECASE,
)
_STREET_RE = re.compile(
    r"(?:улица|ул(?:\.|\s+)|проспект|пр-кт\.?|пр-т\.?|пр(?:\.|\s+)|"
    r"переулок|пер(?:\.|\s+)|бульвар|б-р\.?|"
    r"площадь|пл(?:\.|\s+)|шоссе|ш(?:\.|\s+)|тракт|"
    r"проезд|пр-д\.?|набережная|наб(?:\.|\s+))\s*"
    r"([а-яёa-z0-9\-]+)",
    re.IGNORECASE,
)
_HOUSE_RE = re.compile(
    r"(?:дом|д\.?)\s*(\d+[а-яёa-z]?)",
    re.IGNORECASE,
)

_STOPWORDS = {
    "выполнение",
    "работ",
    "работы",
    "по",
    "устройству",
    "устройство",
    "наружного",
    "освещения",
    "освещение",
    "недостающего",
    "электрического",
    "российская",
    "федерация",
    "область",
    "обл",
    "кировская",
    "кировской",
    "город",
    "города",
    "киров",
    "кирова",
    "г",
    "о",
    "го",
    "в",
    "на",
    "и",
    "за",
    "его",
    "пределами",
    "расстоянии",
    "не",
    "менее",
    "метров",
    "м",
    "ул",
    "улица",
    "проезд",
    "между",
    "дом",
    "д",
    "п",
    "пос",
    "поселок",
    "посёлок",
    "деревня",
    "дер",
    "село",
    "с",
    "микрорайон",
    "мкр",
}


@dataclass
class AddressMatch:
    work_object: WorkObject | None
    reason: str
    candidates: int = 0


def _words(text: str | None) -> set[str]:
    return {item.casefold() for item in _WORD_RE.findall(text or "") if item}


def distinctive_tokens(text: str | None) -> set[str]:
    tokens: set[str] = set()
    raw = text or ""
    for match in _SETTLEMENT_RE.finditer(raw):
        tokens.update(_words(match.group(1)))
    for match in _STREET_RE.finditer(raw):
        tokens.update(_words(match.group(1)))
    for match in _HOUSE_RE.finditer(raw):
        tokens.add(match.group(1).casefold())
    _, street_name, house = split_address_query(raw)
    if street_name:
        tokens.update(_words(street_name))
    if house:
        tokens.add(house.casefold())
    leftover = _words(raw) - _STOPWORDS
    tokens.update({item for item in leftover if len(item) >= 5 or item.isdigit()})
    return {item for item in tokens if item and item not in _STOPWORDS}


def object_haystack(obj: WorkObject) -> str:
    parts = [obj.address or "", obj.name or ""]
    return " ".join(parts)


def match_work_objects(
    texts: list[str | None],
    objects: list[WorkObject],
) -> AddressMatch:
    """Однозначное попадание: ровно один объект содержит все отличительные токены."""
    query_tokens: set[str] = set()
    for text in texts:
        query_tokens |= distinctive_tokens(text)
    if not query_tokens:
        return AddressMatch(None, "В тексте ЕИС нет адреса для сопоставления", 0)

    normalized_queries = {
        normalize_address(text) for text in texts if (text or "").strip()
    }
    hits: list[WorkObject] = []
    for obj in objects:
        hay = object_haystack(obj)
        hay_tokens = _words(hay)
        hay_norm = normalize_address(obj.address or obj.name)
        if hay_norm and hay_norm in normalized_queries:
            hits.append(obj)
            continue
        if query_tokens and query_tokens <= hay_tokens:
            hits.append(obj)

    unique: list[WorkObject] = []
    seen: set = set()
    for obj in hits:
        if obj.id in seen:
            continue
        seen.add(obj.id)
        unique.append(obj)

    if len(unique) == 1:
        return AddressMatch(unique[0], "Совпал адрес объекта", 1)
    if not unique:
        return AddressMatch(
            None,
            f"Объект из ЕИС не найден в плане: {', '.join(sorted(query_tokens))}",
            0,
        )
    return AddressMatch(
        None,
        "Несколько объектов подходят под адрес ЕИС: "
        + ", ".join((item.display_address or item.name)[:80] for item in unique[:5]),
        len(unique),
    )
