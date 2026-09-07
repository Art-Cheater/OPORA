"""Безопасное выделение адресных частей для repair координат.

Это не меняет исходный адрес и не разворачивает сомнительные корпуса/строения.
"""
from __future__ import annotations

import re

MAX_RANGE_HOUSES = 20
_RANGE = re.compile(r"(?:дом\s+)?(\d{1,4})\s*-\s*(\d{1,4})\s*$", re.I)
_HOUSE_LIST = re.compile(r"^(.*?\D)\s+(\d{1,4}[а-яa-z]?)(?:\s*,\s*(\d{1,4}[а-яa-z]?)){1,}$", re.I)


def split_map_address_parts(address: str) -> tuple[list[str], str | None]:
    """Вернуть геокодируемые части и необязательное безопасное предупреждение."""
    raw = " ".join((address or "").split())
    if not raw:
        return [], None
    match = _RANGE.search(raw)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if start <= end and end - start + 1 <= MAX_RANGE_HOUSES:
            prefix = raw[:match.start()].rstrip(" ,-")
            return [f"{prefix}, дом {number}" for number in range(start, end + 1)], None
        return [raw], "Диапазон домов слишком большой или неоднозначный: использована опорная точка."
    # Список домов распознаём только в хвосте после названия улицы; обычный
    # «Киров, улица Ленина, дом 15» этому шаблону не соответствует.
    tail = _HOUSE_LIST.match(raw)
    if tail and "дом " not in raw.casefold():
        prefix = tail.group(1).rstrip(" ,")
        houses = re.findall(r"\d{1,4}[а-яa-z]?", raw[tail.start(2):], re.I)
        if 1 < len(houses) <= MAX_RANGE_HOUSES:
            return [f"{prefix}, дом {house}" for house in houses], None
    return [raw], None
