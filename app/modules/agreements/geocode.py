"""Геокодирование адресов из договоров на опорах (Nominatim, Киров)."""

from __future__ import annotations

import logging
import re

from app.core.address.providers import GeocodingError
from app.modules.requests.address_format import split_address_query

logger = logging.getLogger(__name__)

_PAREN = re.compile(r"\([^)]*\)")
_RANGE_TAIL = re.compile(r"\s+(?:от|до)\s+.+", re.IGNORECASE)
_LEAD_PREP = re.compile(r"^(?:по|на)\s+", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


def geocode_query(address: str) -> str:
    """Упрощает строку таблицы до «Киров, улица …» — без участков «от … до …»."""

    text = _PAREN.sub(" ", address or "")
    text = _RANGE_TAIL.sub("", text)
    text = _LEAD_PREP.sub("", text)
    text = _SPACES.sub(" ", text).strip(" ,.;")
    if not text:
        return "Киров"

    street_type, name, house = split_address_query(text)
    if name:
        parts = ["Киров", f"{street_type or 'улица'} {name}"]
        if house:
            parts.append(house)
        return ", ".join(parts)
    if "киров" not in text.casefold():
        return f"Киров, {text}"
    return text


_MISS_QUERIES: set[str] = set()


def geocode_address(address: str) -> tuple[float, float] | None:
    """Точка на карте или None. В тестах сеть не дергаем."""

    from flask import current_app

    if current_app.config.get("TESTING"):
        return None

    query = geocode_query(address)
    if not query or query in _MISS_QUERIES:
        return None

    from app.core.address.service import get_address_suggestion_service

    try:
        hits = get_address_suggestion_service().provider.search(query, limit=1)
    except (GeocodingError, ValueError, RuntimeError) as exc:
        logger.warning("Геокод договора: %s (%s)", query, exc)
        return None
    if not hits:
        _MISS_QUERIES.add(query)
        return None
    lat, lng = hits[0].latitude, hits[0].longitude
    if lat is None or lng is None:
        _MISS_QUERIES.add(query)
        return None
    return float(lat), float(lng)
