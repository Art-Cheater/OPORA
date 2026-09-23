"""Качество точки: источник и точность не смешиваются с широтой и долготой."""

from __future__ import annotations

QUALITIES = ("MANUAL", "EXACT", "INTERPOLATED", "STREET", "SETTLEMENT", "UNKNOWN")


def quality_for(source: str | None, house: str | None = None) -> str | None:
    """Сохраняемое качество по уже известному источнику координат."""

    if not source or source == "cleared":
        return None
    if source == "manual":
        return "MANUAL"
    if source == "geocoder":
        return "EXACT" if str(house or "").strip() else "STREET"
    return "UNKNOWN"


def precision_of(item) -> str:
    """Точность подсказки. Номер подъезда и дом здесь не выдумываются."""

    explicit = getattr(item, "precision", None)
    if explicit in QUALITIES and explicit != "MANUAL":
        return explicit
    house = str(getattr(item, "house", None) or "").strip()
    street = str(getattr(item, "street", None) or "").strip()
    settlement = str(getattr(item, "settlement", None) or "").strip()
    has_point = getattr(item, "latitude", None) is not None and getattr(item, "longitude", None) is not None
    if house and has_point:
        return "EXACT"
    if street:
        return "STREET"
    if settlement:
        return "SETTLEMENT"
    return "UNKNOWN"
