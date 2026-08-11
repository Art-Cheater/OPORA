"""Нормализация адресов заявок: всегда Киров, единообразный вид."""

from __future__ import annotations

import re

CITY = "Киров"

_STREET_TYPES: tuple[tuple[str, str], ...] = (
    (r"микрорайон|мкр\.?", "микрорайон"),
    (r"набережная|наб\.?", "набережная"),
    (r"проспект|пр-т\.?|пр\.?", "проспект"),
    (r"переулок|пер\.?", "переулок"),
    (r"бульвар|б-р\.?", "бульвар"),
    (r"площадь|пл\.?", "площадь"),
    (r"шоссе|ш\.?", "шоссе"),
    (r"проезд|пр-д\.?", "проезд"),
    (r"тупик|туп\.?", "тупик"),
    (r"аллея", "аллея"),
    (r"тракт", "тракт"),
    (r"улица|ул\.?", "улица"),
)

_CITY_PREFIX = re.compile(
    r"^(?:г\.?\s*)?(?:город\s+)?киров[ае]?\s*[,.]?\s*",
    re.IGNORECASE,
)

_HOUSE_PREFIX = re.compile(
    r"^(?:д\.?|дом|стр\.?|строение)\s*",
    re.IGNORECASE,
)

_HOUSE_TAIL = re.compile(
    r"(?:,?\s*(?:д\.?|дом|стр\.?|строение)\s*)?"
    r"(?P<house>\d+[а-яёa-z]?(?:\s*/\s*\d+[а-яёa-z]?)?)\s*$",
    re.IGNORECASE,
)

_MULTI_SPACE = re.compile(r"\s+")


def _title_ru(text: str) -> str:
    parts = []
    for word in text.split():
        if not word:
            continue
        lower = word.lower()
        parts.append(lower[:1].upper() + lower[1:] if lower else word)
    return " ".join(parts)


def _detect_street_type(street: str) -> tuple[str, str]:
    raw = street.strip(" ,.-")
    for pattern, label in _STREET_TYPES:
        m = re.match(rf"^(?:{pattern})\s+(.+)$", raw, flags=re.IGNORECASE)
        if m:
            return label, m.group(1).strip(" ,.-")
        m = re.match(rf"^(.+?)\s+(?:{pattern})$", raw, flags=re.IGNORECASE)
        if m:
            return label, m.group(1).strip(" ,.-")
    return "улица", raw


def format_address(address: str | None) -> str:
    """Приводит адрес к виду: «Киров, улица Лепсе, дом 79»."""
    text = _MULTI_SPACE.sub(" ", (address or "").strip())
    if not text:
        return ""

    text = _CITY_PREFIX.sub("", text).strip(" ,.-")
    if not text:
        return CITY

    # Уже канонический вид
    canon = re.match(
        r"^киров,\s*(?P<stype>улица|проспект|переулок|бульвар|площадь|шоссе|набережная|"
        r"микрорайон|проезд|тупик|аллея|тракт)\s+(?P<name>.+?),\s*дом\s+(?P<house>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if canon:
        return (
            f"{CITY}, {canon.group('stype').lower()} {_title_ru(canon.group('name'))}, "
            f"дом {canon.group('house').replace(' ', '')}"
        )

    house = ""
    street_part = text
    m = _HOUSE_TAIL.search(text)
    if m:
        house = m.group("house").replace(" ", "")
        street_part = text[: m.start()].strip(" ,.-")

    if not street_part and house:
        # Только номер без улицы — не угадываем
        return f"{CITY}, дом {house}"

    # «лепсе79» без пробела
    if not house:
        glued = re.match(r"^(?P<name>.+?)(?P<house>\d+[а-яёa-z]?(?:/\d+[а-яёa-z]?)?)$", street_part, re.I)
        if glued and not re.search(r"\d", glued.group("name")):
            street_part = glued.group("name").strip(" ,.-")
            house = glued.group("house")

    stype, name = _detect_street_type(street_part)
    name = _title_ru(_HOUSE_PREFIX.sub("", name).strip(" ,.-"))
    if not name:
        return f"{CITY}, дом {house}" if house else CITY

    result = f"{CITY}, {stype} {name}"
    if house:
        result += f", дом {_HOUSE_PREFIX.sub('', house).strip()}"
    return result


def normalize_address(address: str | None) -> str:
    """Ключ сравнения адресов (после канонизации)."""
    formatted = format_address(address)
    text = formatted.strip().lower()
    return _MULTI_SPACE.sub(" ", text)
