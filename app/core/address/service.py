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
        provider_timeout_seconds: float = 0.45,
    ) -> None:
        self.provider = provider
        self.fallback = fallback or HeuristicGeocodingProvider()
        self.default_limit = min(max(int(default_limit), 1), 20)
        self.provider_timeout_seconds = max(0.0, float(provider_timeout_seconds))

    def _search_provider(self, query: str, limit: int) -> list[AddressSuggestion]:
        found: list[AddressSuggestion] = []

        def run() -> None:
            try:
                found.extend(self.provider.search(query, limit=limit))
            except GeocodingError:
                return

        timeout = self.provider_timeout_seconds
        if timeout <= 0:
            run()
            return found
        worker = threading.Thread(target=run, daemon=True, name="opora-geocode")
        worker.start()
        worker.join(timeout)
        return found

    def suggest(self, query: str, *, limit: int | None = None) -> list[AddressSuggestion]:
        from app.modules.requests.address_format import split_address_query

        cleaned = " ".join((query or "").split())
        if len(cleaned) < 3:
            return []
        safe_limit = min(max(int(limit or self.default_limit), 1), 20)
        _kind, _name, house = split_address_query(cleaned)
        catalog = [
            replace(item.with_query(cleaned), other_settlement=False)
            for item in self.fallback.search(cleaned, limit=safe_limit)
        ]

        # С номером дома район нельзя брать «все варианты улицы» — уточняем по OSM.
        if house:
            # Nominatim плохо понимает «…, дом 74» — формат «улица X 74, Киров».
            regional_query = self._nominatim_house_query(cleaned)
            house_timeout = self.provider_timeout_seconds
            if house_timeout >= 0.4:
                house_timeout = max(house_timeout, 2.5)
            old_timeout = self.provider_timeout_seconds
            self.provider_timeout_seconds = house_timeout
            try:
                found = self._search_provider(regional_query, safe_limit)
            finally:
                self.provider_timeout_seconds = old_timeout
            ranked = self._rank_region(found, cleaned)
            house_hits = self._house_suggestions(ranked, catalog, cleaned, house)
            if house_hits:
                return house_hits[:safe_limit]
            # Геокодер молчит: не клонируем один дом во все районы улицы
            fallback_hits = self._catalog_house_fallback(catalog, cleaned, house)
            if fallback_hits:
                return fallback_hits[:safe_limit]

        if catalog:
            return catalog[:safe_limit]

        # Внешний геокодер только если улицы нет в справочнике Кирова.
        regional_query = cleaned
        folded = cleaned.casefold()
        if "кировск" not in folded and "кировская область" not in folded:
            regional_query = f"{cleaned}, Кировская область"
        found = self._search_provider(regional_query, safe_limit)
        return self._rank_region(found, cleaned)[:safe_limit]

    @staticmethod
    def _nominatim_house_query(cleaned: str) -> str:
        from app.modules.requests.address_format import split_address_query

        kind, name, house = split_address_query(cleaned)
        street = f"{kind or 'улица'} {name}".strip()
        return f"{street} {house}, Киров, Кировская область"

    @classmethod
    def _catalog_house_fallback(
        cls,
        catalog: list[AddressSuggestion],
        original_query: str,
        house: str,
    ) -> list[AddressSuggestion]:
        """Запасной вариант без OSM: один городской район + отдельно Нововятский, если есть."""
        from app.core.address.catalog import resolve_catalog_district
        from app.modules.requests.address_format import split_address_query
        from app.modules.requests.districts import long_district_name, normalize_request_district

        if not catalog:
            return []
        kind, name, _house = split_address_query(original_query)
        street_label = catalog[0].street or f"{kind or 'улица'} {name}"
        districts = []
        seen: set[str] = set()
        for item in catalog:
            short = normalize_request_district(item.district)
            if not short or short in seen:
                continue
            seen.add(short)
            districts.append(short)

        city = [d for d in districts if d != "Нововятский"]
        novo = [d for d in districts if d == "Нововятский"]
        chosen: list[str] = []
        if len(city) == 1:
            chosen.extend(city)
        elif len(city) > 1:
            primary = resolve_catalog_district(name, kind or "улица")
            primary_short = normalize_request_district(primary)
            if primary_short and primary_short in city:
                chosen.append(primary_short)
            else:
                chosen.append(city[0])
        chosen.extend(novo)

        out: list[AddressSuggestion] = []
        for short in chosen:
            long_name = long_district_name(short) or f"{short} район"
            title = f"Киров, {street_label}, дом {house}"
            if len(chosen) > 1:
                title = f"{title} ({short})"
            out.append(
                AddressSuggestion(
                    original_address=original_query,
                    normalized_address=title,
                    region="Кировская область",
                    district=long_name,
                    settlement="Киров",
                    street=street_label,
                    house=house,
                    address_source="catalog",
                    other_settlement=False,
                )
            )
        return out

    @classmethod
    def _house_suggestions(
        cls,
        nominatim: list[AddressSuggestion],
        catalog: list[AddressSuggestion],
        original_query: str,
        house: str,
    ) -> list[AddressSuggestion]:
        """Подсказки с домом: район из OSM, адрес в формате справочника."""
        from app.modules.requests.districts import long_district_name, normalize_request_district

        house_fold = house.casefold().replace("ё", "е")
        catalog_street = next((item.street for item in catalog if item.street), None)
        candidates: list[AddressSuggestion] = []

        for item in nominatim:
            if not cls._is_kirov_region(item):
                continue
            item_house = (item.house or "").casefold().replace("ё", "е").replace(" ", "")
            if item_house and item_house != house_fold:
                display = item.normalized_address.casefold().replace("ё", "е")
                if house_fold not in display.replace(" ", ""):
                    continue
            district_long = long_district_name(item.district)
            if not district_long:
                continue

            street_label = catalog_street or item.street or ""
            if street_label and not street_label.casefold().startswith(
                ("улица", "проспект", "переулок", "бульвар", "площадь", "шоссе")
            ):
                street_label = f"улица {street_label}"
            if street_label:
                normalized = f"Киров, {street_label}, дом {house}"
            else:
                normalized = item.normalized_address
            candidates.append(
                replace(
                    item.with_query(original_query),
                    normalized_address=normalized,
                    region=item.region or "Кировская область",
                    district=district_long,
                    settlement="Киров",
                    street=street_label or item.street,
                    house=house,
                    other_settlement=False,
                )
            )

        # Один дом — один городской район; Нововятский оставляем отдельной локацией.
        by_district: dict[str, AddressSuggestion] = {}
        for item in candidates:
            short = normalize_request_district(item.district) or ""
            if short and short not in by_district:
                by_district[short] = item

        city = {k: v for k, v in by_district.items() if k != "Нововятский"}
        novo = by_district.get("Нововятский")
        out: list[AddressSuggestion] = []
        if len(city) == 1:
            out.extend(city.values())
        elif len(city) > 1:
            # Несколько «городских» районов на один дом — берём с координатами / первый стабильный
            ranked_city = sorted(
                city.items(),
                key=lambda pair: (
                    0 if pair[1].latitude is not None else 1,
                    {"Ленинский": 0, "Октябрьский": 1, "Первомайский": 2}.get(pair[0], 9),
                ),
            )
            out.append(ranked_city[0][1])
        if novo is not None:
            out.append(novo)

        if len(out) > 1:
            decorated: list[AddressSuggestion] = []
            for item in out:
                short = normalize_request_district(item.district) or ""
                base = item.normalized_address
                if short and f"({short})" not in base:
                    base = f"{base} ({short})"
                decorated.append(replace(item, normalized_address=base))
            out = decorated
        return out

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
            provider_timeout_seconds=float(
                current_app.config.get("GEOCODING_SUGGEST_TIMEOUT_SECONDS") or 2.5
            ),
        )
        current_app.extensions[extension_key] = service
        return service
