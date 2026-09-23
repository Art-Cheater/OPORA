"""Единый ответ карты: список точек и GeoJSON FeatureCollection."""

from __future__ import annotations


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def points_to_geojson(points: list[dict]) -> dict:
    features = []
    for point in points or []:
        lat = _finite(point.get("lat"))
        lng = _finite(point.get("lng"))
        if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        properties = {key: value for key, value in point.items() if key not in {"lat", "lng"}}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def map_payload(points: list[dict], *, remaining: int = 0) -> dict:
    return {"points": points, "geojson": points_to_geojson(points), "remaining": remaining}
