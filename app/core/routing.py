"""Опциональная дорожная маршрутизация без зависимости приложения от provider."""

from __future__ import annotations

import json
import socket
import time
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


class RoutingError(Exception):
    """Безопасная ошибка routing API, пригодная для отображения пользователю."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class RoutingService:
    _cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls._provider() and cls._base_url())

    @classmethod
    def check_health(cls) -> dict:
        if not cls.is_configured():
            return {"ok": False, "code": "routing_not_configured", "message": "Маршрутизация выключена."}
        try:
            return {"ok": True, **cls.build_route([(58.6035, 49.6680), (58.6070, 49.6750)])}
        except RoutingError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message}

    @classmethod
    def build_route(cls, points: list[tuple[float, float]], profile: str = "car") -> dict:
        """Вернуть дорожную GeoJSON-геометрию в заданном порядке точек.

        Прямые линии не используются как fallback: карта сохраняет markers, а UI
        получает понятную RoutingError.
        """
        normalized = cls._validate_points(points)
        if not cls.is_configured():
            raise RoutingError("routing_not_configured", "Дорожные маршруты пока не настроены. Карта и план работ доступны без маршрута.")
        key = (cls._provider(), profile, *(round(value, 5) for point in normalized for value in point))
        cached = cls._get_cache(key)
        if cached is not None:
            return {**cached, "warnings": [*cached.get("warnings", []), "cache_hit"]}
        try:
            raw = cls._request_route(normalized, geometry=True, profile=profile)
        except TimeoutError as exc:
            raise RoutingError("routing_timeout", "Не удалось построить маршрут: сервис маршрутизации не ответил вовремя.") from exc
        except (URLError, ConnectionError, socket.timeout) as exc:
            raise RoutingError("routing_unavailable", "Не удалось подключиться к сервису дорожных маршрутов.") from exc
        except HTTPError as exc:
            code = "out_of_region" if exc.code in {400, 404, 422} else "routing_unavailable"
            message = "Не удалось построить маршрут: часть точек вне доступной карты маршрутизации." if code == "out_of_region" else "Сервис дорожных маршрутов временно недоступен."
            raise RoutingError(code, message) from exc
        except (ValueError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RoutingError("routing_bad_response", "Сервис маршрутизации вернул некорректный ответ.") from exc
        geometry = raw.get("geometry") if isinstance(raw, dict) else None
        if not cls._valid_geometry(geometry):
            raise RoutingError("routing_no_route", "Не удалось построить маршрут: часть точек вне доступной карты маршрутизации.")
        result = {"geometry": geometry, "distance_m": int(round(float(raw.get("distance") or 0))), "duration_s": int(round(float(raw.get("duration") or 0))), "provider": cls._provider(), "warnings": []}
        cls._put_cache(key, result)
        return result

    @classmethod
    def route_distance(cls, origin: tuple[float, float], destination: tuple[float, float]) -> int | None:
        if not cls.is_configured():
            return None
        try:
            raw = cls._request_route(cls._validate_points([origin, destination]), geometry=False, profile="car")
            return int(round(float(raw.get("distance") or 0)))
        except (RoutingError, URLError, HTTPError, TimeoutError, ValueError, OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            return None

    @classmethod
    def route(cls, points: list[tuple[float, float]]) -> dict | None:
        """Совместимый API для legacy callers: None при недоступном routing."""
        try:
            result = cls.build_route(points)
            return {key: result[key] for key in ("geometry", "distance_m", "duration_s")}
        except RoutingError:
            return None

    @classmethod
    def optimize(cls, points: list[tuple[float, float]]) -> dict | None:
        """Место для отдельного подтверждаемого действия оптимизации в будущем."""
        return None

    @classmethod
    def _provider(cls) -> str:
        provider = str(current_app.config.get("ROUTING_PROVIDER") or "").strip().lower()
        return provider if provider in {"valhalla", "osrm"} else ""

    @classmethod
    def _base_url(cls) -> str:
        # ROUTING_BASE_URL — единый основной контракт; legacy fallback сохранён.
        base = str(current_app.config.get("ROUTING_BASE_URL") or "").strip()
        if not base and cls._provider() == "valhalla":
            base = str(current_app.config.get("VALHALLA_BASE_URL") or "").strip()
        return base.rstrip("/")

    @classmethod
    def _validate_points(cls, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if not isinstance(points, list) or not 2 <= len(points) <= 50:
            raise RoutingError("invalid_points", "Для маршрута нужно от двух до 50 точек с координатами.")
        result: list[tuple[float, float]] = []
        for point in points:
            try:
                lat, lng = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError) as exc:
                raise RoutingError("invalid_points", "Координаты маршрута указаны неверно.") from exc
            if not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise RoutingError("invalid_points", "Координаты маршрута вне допустимого диапазона.")
            result.append((lat, lng))
        return result

    @staticmethod
    def _valid_geometry(geometry: object) -> bool:
        if not isinstance(geometry, dict) or geometry.get("type") not in {"LineString", "MultiLineString"}:
            return False
        return isinstance(geometry.get("coordinates"), list) and len(geometry["coordinates"]) > 1

    @classmethod
    def _request_route(cls, points: list[tuple[float, float]], *, geometry: bool, profile: str) -> dict:
        base, provider = cls._base_url(), cls._provider()
        if not base or not provider:
            raise RoutingError("routing_not_configured", "Маршрутизация не настроена.")
        headers, timeout = {"User-Agent": "OPORA-routing/1.0", "Accept": "application/json"}, float(current_app.config["ROUTING_TIMEOUT_SECONDS"])
        if provider == "valhalla":
            body = json.dumps({"locations": [{"lat": lat, "lon": lng} for lat, lng in points], "costing": "auto" if profile == "car" else profile, "units": "kilometers", "shape_format": "geojson"}).encode("utf-8")
            with urlopen(Request(f"{base}/route", data=body, headers={**headers, "Content-Type": "application/json"}), timeout=timeout) as response:  # nosec B310: config URL
                payload = json.loads(response.read().decode("utf-8"))
            trip = payload.get("trip") if isinstance(payload, dict) else None
            summary = trip.get("summary") if isinstance(trip, dict) else None
            shape = trip.get("shape") if isinstance(trip, dict) else None
            if shape is None and isinstance(trip, dict):
                legs = trip.get("legs") or []
                shape = legs[0].get("shape") if legs and isinstance(legs[0], dict) else None
            geojson = shape if isinstance(shape, dict) else {"type": "LineString", "coordinates": shape} if isinstance(shape, list) else None
            return {"distance": float((summary or {}).get("length") or 0) * 1000, "duration": float((summary or {}).get("time") or 0), "geometry": geojson if geometry else None}
        coords = ";".join(f"{lng},{lat}" for lat, lng in points)
        url = f"{base}/route/v1/driving/{coords}?" + urlencode({"overview": "full" if geometry else "false", "geometries": "geojson"})
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:  # nosec B310: config URL
            route = json.loads(response.read().decode("utf-8")).get("routes", [])[0]
        return {"distance": route.get("distance"), "duration": route.get("duration"), "geometry": route.get("geometry") if geometry else None}

    @classmethod
    def _get_cache(cls, key: tuple) -> dict | None:
        cached = cls._cache.get(key)
        if not cached or time.monotonic() - cached[0] > int(current_app.config["ROUTING_CACHE_TTL_SECONDS"]):
            return None
        cls._cache.move_to_end(key)
        return cached[1]

    @classmethod
    def _put_cache(cls, key: tuple, result: dict) -> None:
        cls._cache[key] = (time.monotonic(), result)
        cls._cache.move_to_end(key)
        while len(cls._cache) > int(current_app.config["ROUTING_CACHE_MAX_SIZE"]):
            cls._cache.popitem(last=False)
