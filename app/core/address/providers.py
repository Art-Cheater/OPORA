"""Провайдеры серверного поиска и нормализации адресов."""

from __future__ import annotations

import json
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class GeocodingError(RuntimeError):
    """Внешний геокодер не смог безопасно выполнить запрос."""


@dataclass(frozen=True, slots=True)
class AddressSuggestion:
    """Нормализованный адрес, не зависящий от формата конкретного геокодера."""

    original_address: str
    normalized_address: str
    region: str | None = None
    district: str | None = None
    settlement: str | None = None
    street: str | None = None
    house: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    address_source: str = "heuristic"
    address_external_id: str | None = None
    other_settlement: bool = False

    def with_query(self, query: str) -> "AddressSuggestion":
        return replace(self, original_address=query)

    def as_dict(self) -> dict[str, object]:
        return {
            "original_address": self.original_address,
            "normalized_address": self.normalized_address,
            "region": self.region,
            "district": self.district,
            "settlement": self.settlement,
            "street": self.street,
            "house": self.house,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "address_source": self.address_source,
            "address_external_id": self.address_external_id,
            "other_settlement": self.other_settlement,
        }


class GeocodingProvider(ABC):
    """Сменный источник подсказок адреса."""

    @abstractmethod
    def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]:
        """Найти адреса по строке пользователя."""


_MISSING = object()


class ThreadSafeTTLCache:
    """Небольшой потокобезопасный TTL/LRU-кэш ответов геокодера."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_size: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_size = max(1, int(max_size))
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, tuple[AddressSuggestion, ...]]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str):
        now = self._clock()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return _MISSING
            expires_at, value = entry
            if expires_at <= now:
                self._items.pop(key, None)
                return _MISSING
            self._items.move_to_end(key)
            return list(value)

    def set(self, key: str, value: list[AddressSuggestion]) -> None:
        with self._lock:
            self._items[key] = (self._clock() + self.ttl_seconds, tuple(value))
            self._items.move_to_end(key)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)


class StartRateLimiter:
    """Ограничивает частоту начала внешних запросов между всеми потоками."""

    def __init__(
        self,
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval_seconds = max(0.0, float(interval_seconds))
        self._clock = clock
        self._sleep = sleeper
        self._next_start = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                delay = self._next_start - now
                if delay <= 0:
                    self._next_start = now + self.interval_seconds
                    return
            self._sleep(delay)


class NominatimGeocodingProvider(GeocodingProvider):
    """Серверный клиент Nominatim с обязательным User-Agent и таймаутом."""

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout_seconds: float,
        cache_ttl_seconds: float,
        cache_max_size: int,
        rate_limit_seconds: float,
        viewbox: str | None = None,
        opener=urlopen,
    ) -> None:
        user_agent = (user_agent or "").strip()
        if not user_agent:
            raise ValueError("Для Nominatim обязателен непустой User-Agent.")
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.viewbox = (viewbox or "").strip() or None
        self._opener = opener
        self._cache = ThreadSafeTTLCache(
            ttl_seconds=cache_ttl_seconds,
            max_size=cache_max_size,
        )
        self._rate_limiter = StartRateLimiter(rate_limit_seconds)

    def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]:
        cleaned = " ".join((query or "").split())
        if not cleaned:
            return []
        safe_limit = min(max(int(limit), 1), 20)
        cache_key = f"{cleaned.casefold()}|{safe_limit}"
        cached = self._cache.get(cache_key)
        if cached is not _MISSING:
            return cached

        query_params = {
            "q": cleaned,
            "format": "jsonv2",
            "addressdetails": "1",
            "countrycodes": "ru",
            "accept-language": "ru",
            "dedupe": "1",
            "limit": str(safe_limit),
        }
        if self.viewbox:
            query_params["viewbox"] = self.viewbox
            query_params["bounded"] = "1"
        params = urlencode(query_params)
        req = Request(
            f"{self.base_url}/search?{params}",
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        self._rate_limiter.wait()
        try:
            with self._opener(req, timeout=self.timeout_seconds) as response:
                raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise GeocodingError("Ответ геокодера превышает допустимый размер.")
            payload = json.loads(raw.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise GeocodingError("Сервис адресов временно недоступен.") from exc

        if not isinstance(payload, list):
            raise GeocodingError("Геокодер вернул неожиданный формат ответа.")
        results = [
            suggestion
            for item in payload
            if isinstance(item, dict) and (suggestion := self._parse_item(cleaned, item)) is not None
        ]
        self._cache.set(cache_key, results)
        return list(results)

    @staticmethod
    def _parse_item(query: str, item: dict) -> AddressSuggestion | None:
        display_name = str(item.get("display_name") or "").strip()
        address = item.get("address")
        if not display_name or not isinstance(address, dict):
            return None
        try:
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            return None

        settlement = next(
            (
                str(address[key]).strip()
                for key in ("city", "town", "village", "municipality", "hamlet")
                if address.get(key)
            ),
            None,
        )
        street = next(
            (
                str(address[key]).strip()
                for key in ("road", "pedestrian", "residential", "suburb", "quarter")
                if address.get(key)
            ),
            None,
        )
        osm_type = str(item.get("osm_type") or "").strip()
        osm_id = str(item.get("osm_id") or "").strip()
        external_id = f"{osm_type}/{osm_id}" if osm_type and osm_id else None
        district = (
            str(
                address.get("city_district")
                or address.get("suburb")
                or address.get("county")
                or address.get("state_district")
                or ""
            ).strip()
            or None
        )
        return AddressSuggestion(
            original_address=query,
            normalized_address=display_name,
            region=str(address.get("state") or "").strip() or None,
            district=district,
            settlement=settlement,
            street=street,
            house=str(address.get("house_number") or "").strip() or None,
            latitude=latitude,
            longitude=longitude,
            address_source="nominatim",
            address_external_id=external_id,
        )


class HeuristicGeocodingProvider(GeocodingProvider):
    """Локальный справочник улиц Кирова: тип, район, исправление опечаток."""

    def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]:
        from app.core.address.catalog import search_streets

        cleaned = " ".join((query or "").split())
        if not cleaned:
            return []
        return [
            AddressSuggestion(
                original_address=cleaned,
                normalized_address=hit.normalized_address,
                region="Кировская область",
                district=hit.district,
                settlement="Киров",
                street=hit.street_label,
                house=hit.house or None,
                address_source="catalog",
            )
            for hit in search_streets(cleaned, limit=limit)
        ]
