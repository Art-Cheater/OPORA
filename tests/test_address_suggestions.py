"""Адресные подсказки: провайдер, fallback, ранжирование и защита API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from app.core.address import (
    AddressSuggestion,
    AddressSuggestionService,
    GeocodingError,
    GeocodingProvider,
    NominatimGeocodingProvider,
)
from app.extensions import db
from app.models.auth.user import User
from app.models.requests.request_status import RequestStatus
from app.modules.requests.services import RequestPayload, RequestService
from app.modules.requests.workflow import STATUS_NEW


class StubProvider(GeocodingProvider):
    def __init__(self, results=None, error: Exception | None = None):
        self.results = results or []
        self.error = error
        self.queries: list[str] = []

    def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.results[:limit]


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


def test_nominatim_uses_user_agent_timeout_and_cache():
    calls = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            [
                {
                    "display_name": "Лепсе, 79, Киров, Кировская область, Россия",
                    "lat": "58.603",
                    "lon": "49.668",
                    "osm_type": "way",
                    "osm_id": 123,
                    "address": {
                        "state": "Кировская область",
                        "city": "Киров",
                        "city_district": "Ленинский район",
                        "road": "улица Лепсе",
                        "house_number": "79",
                    },
                }
            ]
        )

    provider = NominatimGeocodingProvider(
        base_url="https://example.test",
        user_agent="OPORA-test/1.0 (test@example.test)",
        timeout_seconds=1.25,
        cache_ttl_seconds=60,
        cache_max_size=10,
        rate_limit_seconds=0,
        opener=opener,
    )

    first = provider.search("Лепсе 79", limit=5)
    second = provider.search("Лепсе 79", limit=5)

    assert len(calls) == 1
    assert calls[0][1] == 1.25
    assert calls[0][0].get_header("User-agent") == "OPORA-test/1.0 (test@example.test)"
    assert first == second
    assert first[0].address_external_id == "way/123"
    assert first[0].street == "улица Лепсе"
    assert first[0].district == "Ленинский район"


def test_service_prioritizes_kirov_and_marks_other_settlement():
    provider = StubProvider(
        [
            AddressSuggestion(
                original_address="provider query",
                normalized_address="Советская, 1, Слободской, Кировская область",
                region="Кировская область",
                settlement="Слободской",
                address_source="nominatim",
            ),
            AddressSuggestion(
                original_address="provider query",
                normalized_address="Лепсе, 79, Киров, Кировская область",
                region="Кировская область",
                settlement="Киров",
                address_source="nominatim",
            ),
        ]
    )
    service = AddressSuggestionService(provider)

    results = service.suggest("Лепсе 79")

    assert provider.queries == ["Лепсе 79, Кировская область"]
    assert [item.settlement for item in results] == ["Киров", "Слободской"]
    assert results[0].other_settlement is False
    assert results[1].other_settlement is True
    assert all(item.original_address == "Лепсе 79" for item in results)


def test_service_falls_back_without_blocking_on_provider_error():
    service = AddressSuggestionService(
        StubProvider(error=GeocodingError("offline"))
    )

    results = service.suggest("Лепсе 79")

    assert len(results) == 1
    assert results[0].normalized_address == "Киров, улица Лепсе, дом 79"
    assert results[0].address_source == "heuristic"
    assert results[0].latitude is None


def test_service_returns_heuristic_when_provider_is_slow():
    import time

    class SlowProvider(GeocodingProvider):
        def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]:
            time.sleep(1.5)
            return []

    service = AddressSuggestionService(SlowProvider(), provider_timeout_seconds=0.15)
    started = time.monotonic()
    results = service.suggest("Лепсе 79")
    elapsed = time.monotonic() - started

    assert elapsed < 0.8
    assert results
    assert results[0].address_source == "heuristic"
    assert results[0].normalized_address == "Киров, улица Лепсе, дом 79"


def test_address_suggestions_endpoint_requires_login(client):
    response = client.get("/requests/api/address-suggestions?q=Лепсе")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_address_suggestions_endpoint_returns_structured_results(admin_client):
    service = AddressSuggestionService(
        StubProvider(
            [
                AddressSuggestion(
                    original_address="unused",
                    normalized_address="Лепсе, 79, Киров, Кировская область",
                    region="Кировская область",
                    settlement="Киров",
                    street="улица Лепсе",
                    house="79",
                    latitude=58.603,
                    longitude=49.668,
                    address_source="test",
                    address_external_id="way/123",
                )
            ]
        )
    )
    admin_client.application.extensions["address_suggestion_service"] = service

    response = admin_client.get("/requests/api/address-suggestions?q=Лепсе+79")

    assert response.status_code == 200
    suggestion = response.get_json()["suggestions"][0]
    assert suggestion["normalized_address"].startswith("Лепсе")
    assert suggestion["latitude"] == 58.603
    assert suggestion["other_settlement"] is False


def test_request_service_persists_selected_address_metadata(app):
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "admin@opora.ru"))
        status = db.session.scalar(
            db.select(RequestStatus).where(RequestStatus.code == STATUS_NEW)
        )
        payload = RequestPayload(
            number="ADDR-001",
            title="",
            description=None,
            address="Киров, улица Лепсе, дом 79",
            original_address="лепсе 79",
            normalized_address="Киров, улица Лепсе, дом 79",
            region="Кировская область",
            district=None,
            settlement="Киров",
            street="улица Лепсе",
            house="79",
            address_source="nominatim",
            address_external_id="way/123",
            pp=None,
            received_at=datetime.now(timezone.utc),
            dispatcher_name="Диспетчер QA",
            latitude=Decimal("58.6030000"),
            longitude=Decimal("49.6680000"),
            phone=None,
            applicant_name="—",
            priority="medium",
            status_id=status.id,
            responsible_id=None,
            executor_id=None,
        )

        created = RequestService.create_request(payload, user.id)

        assert created.address == "Киров, улица Лепсе, дом 79"
        assert created.original_address == "лепсе 79"
        assert created.address_source == "nominatim"
        assert created.address_external_id == "way/123"
        assert created.latitude == Decimal("58.6030000")
