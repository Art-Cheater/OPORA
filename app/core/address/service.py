"""Оркестрация адресных подсказок и выбор провайдера из конфигурации."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import replace

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.address.providers import (
    AddressSuggestion,
    GeocodingError,
    GeocodingProvider,
    HeuristicGeocodingProvider,
    NominatimGeocodingProvider,
)

ProviderFactory = Callable[[Mapping[str, object]], GeocodingProvider]
_ADDRESS_TOKEN_SALT = "opora-address-selection-v1"


def _nominatim_factory(config: Mapping[str, object]) -> GeocodingProvider:
    return NominatimGeocodingProvider(
        base_url=str(config.get("NOMINATIM_BASE_URL") or "https://nominatim.openstreetmap.org"),
        user_agent=str(config.get("NOMINATIM_USER_AGENT") or ""),
        timeout_seconds=float(config.get("GEOCODING_TIMEOUT_SECONDS") or 2.5),
        cache_ttl_seconds=float(config.get("GEOCODING_CACHE_TTL_SECONDS") or 600),
        cache_max_size=int(config.get("GEOCODING_CACHE_MAX_SIZE") or 512),
        rate_limit_seconds=float(config.get("NOMINATIM_RATE_LIMIT_SECONDS") or 1.0),
        viewbox=str(
            config.get("NOMINATIM_VIEWBOX")
            or "41.17,61.07,53.92,56.03"
        ),
    )


_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "nominatim": _nominatim_factory,
    "heuristic": lambda _config: HeuristicGeocodingProvider(),
}
_SERVICE_INIT_LOCK = threading.Lock()


def register_geocoding_provider(name: str, factory: ProviderFactory) -> None:
    """Зарегистрировать другой провайдер без изменения routes/service."""

    key = (name or "").strip().casefold()
    if not key:
        raise ValueError("Имя провайдера не может быть пустым.")
    _PROVIDER_FACTORIES[key] = factory


def _selection_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt=_ADDRESS_TOKEN_SALT,
    )


def make_address_selection_token(suggestion: AddressSuggestion) -> str:
    """Подписать структурированный результат, чтобы не доверять hidden-полям JS."""

    return _selection_serializer().dumps(suggestion.as_dict())


def load_address_selection_token(token: str | None) -> dict[str, object] | None:
    """Проверить подпись/срок результата геокодера и вернуть безопасные данные."""

    if not token:
        return None
    max_age = int(current_app.config.get("ADDRESS_SELECTION_TOKEN_MAX_AGE", 3600))
    try:
        payload = _selection_serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    normalized = payload.get("normalized_address")
    if not isinstance(normalized, str) or not normalized.strip():
        return None
    return payload


class AddressSuggestionService:
    """Возвращает Киров первым, затем остальные адреса Кировской области."""

    def __init__(
        self,
        provider: GeocodingProvider,
        *,
        fallback: GeocodingProvider | None = None,
        default_limit: int = 8,
    ) -> None:
        self.provider = provider
        self.fallback = fallback or HeuristicGeocodingProvider()
        self.default_limit = min(max(int(default_limit), 1), 20)

    def suggest(self, query: str, *, limit: int | None = None) -> list[AddressSuggestion]:
        cleaned = " ".join((query or "").split())
        if len(cleaned) < 3:
            return []
        safe_limit = min(max(int(limit or self.default_limit), 1), 20)
        regional_query = cleaned
        folded = cleaned.casefold()
        if "кировск" not in folded and "кировская область" not in folded:
            regional_query = f"{cleaned}, Кировская область"

        try:
            found = self.provider.search(regional_query, limit=safe_limit)
        except GeocodingError:
            found = []

        ranked = self._rank_region(found, cleaned)
        if ranked:
            return ranked[:safe_limit]
        return [
            replace(item.with_query(cleaned), other_settlement=False)
            for item in self.fallback.search(cleaned, limit=1)
        ]

    @classmethod
    def _rank_region(
        cls,
        suggestions: list[AddressSuggestion],
        original_query: str,
    ) -> list[AddressSuggestion]:
        unique: dict[tuple[object, ...], AddressSuggestion] = {}
        for item in suggestions:
            if not cls._is_kirov_region(item):
                continue
            other_settlement = not cls._is_kirov_city(item)
            normalized = replace(
                item.with_query(original_query),
                other_settlement=other_settlement,
            )
            key = (
                normalized.address_external_id,
                normalized.normalized_address.casefold(),
                normalized.latitude,
                normalized.longitude,
            )
            unique.setdefault(key, normalized)
        return sorted(
            unique.values(),
            key=lambda item: (
                item.other_settlement,
                (item.settlement or "").casefold(),
                item.normalized_address.casefold(),
            ),
        )

    @staticmethod
    def _is_kirov_region(item: AddressSuggestion) -> bool:
        region = (item.region or "").casefold().replace("ё", "е")
        normalized = item.normalized_address.casefold().replace("ё", "е")
        return "кировск" in region or "кировская область" in normalized

    @staticmethod
    def _is_kirov_city(item: AddressSuggestion) -> bool:
        settlement = (item.settlement or "").strip().casefold().replace("ё", "е")
        if settlement:
            return settlement in {"киров", "город киров"}
        normalized = item.normalized_address.casefold().replace("ё", "е")
        return normalized.startswith("киров,") or ", киров," in normalized


def get_address_suggestion_service() -> AddressSuggestionService:
    """Один сервис на Flask app: общий кэш и rate limiter для всех запросов."""

    extension_key = "address_suggestion_service"
    existing = current_app.extensions.get(extension_key)
    if existing is not None:
        return existing

    with _SERVICE_INIT_LOCK:
        existing = current_app.extensions.get(extension_key)
        if existing is not None:
            return existing
        provider_name = str(current_app.config.get("GEOCODING_PROVIDER") or "nominatim")
        factory = _PROVIDER_FACTORIES.get(provider_name.strip().casefold())
        if factory is None:
            raise RuntimeError(f"Неизвестный GEOCODING_PROVIDER: {provider_name}")
        provider = factory(current_app.config)
        service = AddressSuggestionService(
            provider,
            default_limit=int(current_app.config.get("ADDRESS_SUGGESTION_LIMIT", 8)),
        )
        current_app.extensions[extension_key] = service
        return service
