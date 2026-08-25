"""Районы Кирова для заявок."""

from __future__ import annotations

REQUEST_DISTRICTS: tuple[str, ...] = (
    "Ленинский",
    "Октябрьский",
    "Первомайский",
    "Нововятский",
)


def district_choices(*, empty_label: str = "Любой") -> list[tuple[str, str]]:
    return [("", empty_label), *((name, name) for name in REQUEST_DISTRICTS)]


def normalize_request_district(value: str | None) -> str | None:
    """Приводит «Ленинский район» / «ленинский» к короткому имени из справочника."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    folded = text.casefold()
    for name in REQUEST_DISTRICTS:
        if name.casefold() in folded:
            return name
    return text
