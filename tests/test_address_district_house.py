"""Район по номеру дома: OSM, не все варианты улицы из справочника."""

from __future__ import annotations


def test_normalize_request_district_aliases():
    from app.modules.requests.districts import normalize_request_district

    assert normalize_request_district("Нововятск") == "Нововятский"
    assert normalize_request_district("Ленинский район") == "Ленинский"
    assert normalize_request_district("Дымково") == "Первомайский"


def test_house_suggestions_use_nominatim_districts_not_all_catalog():
    from app.core.address import AddressSuggestion, AddressSuggestionService
    from app.core.address.providers import HeuristicGeocodingProvider

    class HouseProvider:
        def search(self, query: str, *, limit: int = 8):
            return [
                AddressSuggestion(
                    original_address=query,
                    normalized_address="12, улица Ленина, Нововятск, Киров",
                    region="Кировская область",
                    district="Нововятский район",
                    settlement="Киров",
                    street="улица Ленина",
                    house="12",
                    address_source="nominatim",
                ),
                AddressSuggestion(
                    original_address=query,
                    normalized_address="12, улица Ленина, Дымково, Первомайский район, Киров",
                    region="Кировская область",
                    district="Первомайский район",
                    settlement="Киров",
                    street="улица Ленина",
                    house="12",
                    address_source="nominatim",
                ),
                AddressSuggestion(
                    original_address=query,
                    normalized_address="12, улица Ленина, Калуга",
                    region="Калужская область",
                    district=None,
                    settlement="Калуга",
                    street="улица Ленина",
                    house="12",
                    address_source="nominatim",
                ),
            ]

    service = AddressSuggestionService(HouseProvider(), fallback=HeuristicGeocodingProvider())
    service.provider_timeout_seconds = 0
    results = service.suggest("Ленина 12", limit=8)
    districts = {item.district for item in results}
    assert districts == {"Нововятский район", "Первомайский район"}
    assert all("дом 12" in (item.normalized_address or "") for item in results)
    assert "Октябрьский район" not in districts


def test_svobody_primary_is_pervomaysky():
    from app.core.address.catalog import search_streets

    hits = search_streets("Свободы")
    assert hits
    assert hits[0].district == "Первомайский район"
    assert any(h.district == "Октябрьский район" for h in hits)


def test_truda_74_does_not_duplicate_city_districts_from_catalog():
    """Без OSM один дом не должен появляться и в Ленинском, и в Октябрьском."""
    from app.core.address import AddressSuggestionService
    from app.core.address.providers import HeuristicGeocodingProvider

    class EmptyProvider:
        def search(self, query: str, *, limit: int = 8):
            return []

    service = AddressSuggestionService(EmptyProvider(), fallback=HeuristicGeocodingProvider())
    service.provider_timeout_seconds = 0
    results = service.suggest("труда 74", limit=8)
    assert results
    districts = {item.district for item in results}
    # Запасной каталог: один городской (Октябрьский — primary для Труда), без пары ЛН+ОК
    assert "Октябрьский район" in districts
    assert not ({"Ленинский район", "Октябрьский район"} <= districts)


def test_nominatim_house_query_format():
    from app.core.address import AddressSuggestionService

    assert AddressSuggestionService._nominatim_house_query("труда 74") == (
        "улица Труда 74, Киров, Кировская область"
    )
