"""Районы Кирова для заявок и геокодера."""

from __future__ import annotations

REQUEST_DISTRICTS: tuple[str, ...] = (
    "Ленинский",
    "Октябрьский",
    "Первомайский",
    "Нововятский",
)

# OSM/suburb/микрорайоны → официальный район города
_DISTRICT_ALIASES: dict[str, str] = {
    "ленинский": "Ленинский",
    "ленинский район": "Ленинский",
    "октябрьский": "Октябрьский",
    "октябрьский район": "Октябрьский",
    "первомайский": "Первомайский",
    "первомайский район": "Первомайский",
    "нововятский": "Нововятский",
    "нововятский район": "Нововятский",
    "нововятск": "Нововятский",
    "лянгасово": "Ленинский",
    "дымково": "Первомайский",
    "костинский": "Октябрьский",
    "филейка": "Ленинский",
    "радюково": "Октябрьский",
}


def district_choices(*, empty_label: str = "Любой") -> list[tuple[str, str]]:
    return [("", empty_label), *((name, name) for name in REQUEST_DISTRICTS)]


def normalize_request_district(value: str | None) -> str | None:
    """Приводит «Ленинский район» / «Нововятск» к короткому имени из справочника."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    folded = text.casefold().replace("ё", "е")
    alias = _DISTRICT_ALIASES.get(folded)
    if alias:
        return alias
    for name in REQUEST_DISTRICTS:
        if name.casefold() in folded:
            return name
    # Часто OSM отдаёт «suburb» отдельно от city_district
    for key, alias_name in _DISTRICT_ALIASES.items():
        if key in folded:
            return alias_name
    return None


def long_district_name(value: str | None) -> str | None:
    """Короткое «Ленинский» → «Ленинский район» для подсказок."""
    short = normalize_request_district(value)
    if not short:
        return None
    return f"{short} район"
