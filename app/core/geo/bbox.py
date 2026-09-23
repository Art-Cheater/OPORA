"""Разбор прямоугольника карты. Неверный bbox не подменяется всей базой."""

from __future__ import annotations


class BboxError(ValueError):
    """Клиент передал неполный или невозможный bbox."""


def parse_bbox(args) -> tuple[float, float, float, float] | None:
    """Вернуть (min_lat, max_lat, min_lon, max_lon) либо None, если параметров нет."""

    keys = ("min_lat", "max_lat", "min_lon", "max_lon")
    raw = [args.get(key) for key in keys]
    if all(value in (None, "") for value in raw):
        return None
    if any(value in (None, "") for value in raw):
        raise BboxError("Для фильтра карты нужны все четыре границы: min_lat, max_lat, min_lon, max_lon.")
    try:
        min_lat, max_lat, min_lon, max_lon = (float(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise BboxError("Границы карты должны быть числами.") from exc
    if min_lat > max_lat or min_lon > max_lon:
        raise BboxError("Границы карты перепутаны.")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90 and -180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise BboxError("Границы карты вне допустимого диапазона координат.")
    return min_lat, max_lat, min_lon, max_lon


def contains(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    min_lat, max_lat, min_lon, max_lon = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def filter_records(items: list[dict], bbox: tuple[float, float, float, float] | None, lat_key: str = "latitude", lon_key: str = "longitude") -> list[dict]:
    if bbox is None:
        return items
    selected = []
    for item in items:
        try:
            lat, lon = float(item.get(lat_key)), float(item.get(lon_key))
        except (TypeError, ValueError):
            continue
        if contains(lat, lon, bbox):
            selected.append(item)
    return selected
