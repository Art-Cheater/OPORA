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
        base = (current_app.config.get("ROUTING_BASE_URL") or "").rstrip("/")
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
        url = f"{base}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?" + urlencode({"overview": "false"})
        result = None
        for _ in range(max(1, current_app.config["ROUTING_RETRIES"] + 1)):
            try:
                req = Request(url, headers={"User-Agent": "OPORA-routing/1.0", "Accept": "application/json"})
                with urlopen(req, timeout=current_app.config["ROUTING_TIMEOUT_SECONDS"]) as response:  # nosec B310: URL из config
                    payload = json.loads(response.read().decode("utf-8"))
                distance = payload.get("routes", [{}])[0].get("distance")
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
            return {"geometry": [[lat, lng] for lat, lng in points], "distance_m": 0}
        base = (current_app.config.get("ROUTING_BASE_URL") or "").rstrip("/")
        if not base:
            return None
        coords = ";".join(f"{lng},{lat}" for lat, lng in points)
        url = f"{base}/route/v1/driving/{coords}?" + urlencode({"overview": "full", "geometries": "geojson"})
        for _ in range(max(1, current_app.config["ROUTING_RETRIES"] + 1)):
            try:
                req = Request(url, headers={"User-Agent": "OPORA-routing/1.0", "Accept": "application/json"})
                with urlopen(req, timeout=current_app.config["ROUTING_TIMEOUT_SECONDS"]) as response:  # nosec B310
                    route = json.loads(response.read().decode("utf-8")).get("routes", [])[0]
                coords_out = route.get("geometry", {}).get("coordinates", [])
                if not coords_out:
                    return None
                return {"geometry": [[lat, lng] for lng, lat in coords_out], "distance_m": int(round(float(route.get("distance") or 0)))}
            except Exception:
                continue
        return None
