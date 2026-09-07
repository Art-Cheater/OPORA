"""Небольшая абстракция дорожных расстояний для nearby без зависимости от UI."""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


class RoutingService:
    _cache: OrderedDict[tuple[float, float, float, float], tuple[float, int | None]] = OrderedDict()

    @classmethod
    def route_distance(cls, origin: tuple[float, float], destination: tuple[float, float]) -> int | None:
        """Возвращает дорожную длину в метрах либо None при недоступном backend."""
        base = cls._base_url()
        if not base:
            return None
        key = tuple(round(value, 5) for value in (*origin, *destination))
        now = time.monotonic()
        cached = cls._cache.get(key)
        if cached and now - cached[0] <= current_app.config["ROUTING_CACHE_TTL_SECONDS"]:
            cls._cache.move_to_end(key)
            return cached[1]
        lat1, lon1 = origin
        lat2, lon2 = destination
        result = None
        for _ in range(max(1, current_app.config["ROUTING_RETRIES"] + 1)):
            try:
                payload = cls._request_route([(lat1, lon1), (lat2, lon2)], geometry=False)
                distance = payload.get("distance") if payload else None
                result = int(round(float(distance))) if distance is not None else None
                break
            except Exception:
                continue
        cls._cache[key] = (now, result)
        cls._cache.move_to_end(key)
        while len(cls._cache) > current_app.config["ROUTING_CACHE_MAX_SIZE"]:
            cls._cache.popitem(last=False)
        return result

    @classmethod
    def route(cls, points: list[tuple[float, float]]) -> dict | None:
        """Дорожный маршрут в порядке мастера, без подмены прямыми линиями."""
        if len(points) < 2:
            return {"geometry": {"type": "LineString", "coordinates": [[lng, lat] for lat, lng in points]}, "distance_m": 0, "duration_s": 0}
        if not cls._base_url():
            return None
        for _ in range(max(1, current_app.config["ROUTING_RETRIES"] + 1)):
            try:
                route = cls._request_route(points, geometry=True)
                geometry = route.get("geometry") if route else None
                if not isinstance(geometry, dict) or not geometry.get("coordinates"):
                    return None
                return {
                    "geometry": geometry,
                    "distance_m": int(round(float(route.get("distance") or 0))),
                    "duration_s": int(round(float(route.get("duration") or 0))),
                }
            except Exception:
                continue
        return None

    @classmethod
    def optimize(cls, points: list[tuple[float, float]]) -> dict | None:
        """Зарезервировано для отдельного пользовательского действия оптимизации."""
        # Автоматически порядок WorkPlan не меняем: это должно быть явное действие мастера.
        return None

    @classmethod
    def _base_url(cls) -> str:
        provider = str(current_app.config.get("ROUTING_PROVIDER") or "osrm").strip().lower()
        if provider == "valhalla":
            return (current_app.config.get("VALHALLA_BASE_URL") or current_app.config.get("ROUTING_BASE_URL") or "").rstrip("/")
        return (current_app.config.get("ROUTING_BASE_URL") or "").rstrip("/")

    @classmethod
    def _request_route(cls, points: list[tuple[float, float]], *, geometry: bool) -> dict | None:
        """Нормализовать разные протоколы OSRM и Valhalla в единый internal contract."""
        base = cls._base_url()
        if not base:
            return None
        provider = str(current_app.config.get("ROUTING_PROVIDER") or "osrm").strip().lower()
        headers = {"User-Agent": "OPORA-routing/1.0", "Accept": "application/json"}
        if provider == "valhalla":
            body = json.dumps({
                "locations": [{"lat": lat, "lon": lng} for lat, lng in points],
                "costing": "auto",
                "units": "kilometers",
                "shape_format": "geojson",
            }).encode("utf-8")
            req = Request(f"{base}/route", data=body, headers={**headers, "Content-Type": "application/json"})
            with urlopen(req, timeout=current_app.config["ROUTING_TIMEOUT_SECONDS"]) as response:  # nosec B310: URL из config
                payload = json.loads(response.read().decode("utf-8"))
            trip = payload.get("trip") if isinstance(payload, dict) else None
            summary = trip.get("summary") if isinstance(trip, dict) else None
            shape = trip.get("shape") if isinstance(trip, dict) else None
            if shape is None and isinstance(trip, dict):
                legs = trip.get("legs")
                if isinstance(legs, list) and legs:
                    # Valhalla возвращает shape на уровне leg в ряде версий/настроек.
                    shape = legs[0].get("shape") if isinstance(legs[0], dict) else None
            distance_km = summary.get("length") if isinstance(summary, dict) else None
            time_s = summary.get("time") if isinstance(summary, dict) else None
            if isinstance(shape, dict):
                geometry_value = shape
            elif isinstance(shape, list):
                geometry_value = {"type": "LineString", "coordinates": shape}
            else:
                geometry_value = None
            return {
                "distance": float(distance_km or 0) * 1000,
                "duration": float(time_s or 0),
                "geometry": geometry_value if geometry else None,
            }
        coords = ";".join(f"{lng},{lat}" for lat, lng in points)
        url = f"{base}/route/v1/driving/{coords}?" + urlencode({"overview": "full" if geometry else "false", "geometries": "geojson"})
        req = Request(url, headers=headers)
        with urlopen(req, timeout=current_app.config["ROUTING_TIMEOUT_SECONDS"]) as response:  # nosec B310
            route = json.loads(response.read().decode("utf-8")).get("routes", [])[0]
        return {"distance": route.get("distance"), "duration": route.get("duration"), "geometry": route.get("geometry") if geometry else None}
