"""Единый геослой: справочник, карта, права, маршрут и проверка входа."""

from __future__ import annotations

import json
import socket
from decimal import Decimal
from urllib.error import URLError

from app.core.address.directory import search_directory
from app.core.address.directory_import import import_ndjson
from app.core.address.normalize import fold
from app.core.address.providers import AddressSuggestion
from app.core.geo.bbox import parse_bbox
from app.core.geo.payload import points_to_geojson
from app.extensions import db
from app.models.auth.constants import ROLE_IRZ_DISPLAY
from app.models.enums import Priority
from app.models.geo.directory import GeoEntrance, GeoStreet
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.auth.captcha import verify_turnstile_result
from app.modules.auth.login_throttle import LoginThrottle
from app.modules.auth.services import AuthService
from app.modules.requests.repositories import RequestRepository


def _login(client, email, password="pass12345"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )


def test_fold_treats_yo_and_case_as_the_same_address():
    assert fold("  Улица Ёлкина ") == fold("улица елкина")


def test_directory_import_is_idempotent_and_searchable(app, tmp_path):
    path = tmp_path / "geo.ndjson"
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "settlement", "external_id": "s1", "name": "Бахта", "region": "Кировская область"}),
                json.dumps({"type": "street", "external_id": "st1", "name": "Ленина", "kind": "улица", "settlement": "Киров", "settlement_external_id": "s1"}),
                json.dumps({"type": "house", "external_id": "h1", "number": "10", "street_external_id": "st1", "latitude": 58.6035, "longitude": 49.668}),
                json.dumps({"type": "entrance", "external_id": "e1", "house_external_id": "h1", "street": "Ленина", "house": "10", "ref": "1", "latitude": 58.60351, "longitude": 49.66801}),
                "{битая строка",
            ]
        ),
        encoding="utf-8",
    )
    with app.app_context():
        first = import_ndjson(path, source="gar")
        second = import_ndjson(path, source="gar")
        assert first["created"] == 4
        assert first["errors"] == 1
        assert second["created"] == 0
        assert second["updated"] == 4
        assert db.session.query(GeoStreet).count() == 1
        hits = search_directory("ул Ленина 10")
        assert hits and hits[0].house == "10"
        assert hits[0].precision == "EXACT"


def test_geojson_skips_empty_and_invalid_coordinates():
    payload = points_to_geojson(
        [
            {"id": "ok", "lat": "58.6", "lng": "49.6"},
            {"id": "empty", "lat": None, "lng": None},
            {"id": "nan", "lat": "NaN", "lng": 49},
            {"id": "range", "lat": 120, "lng": 49},
        ]
    )
    assert payload["type"] == "FeatureCollection"
    assert [item["properties"]["id"] for item in payload["features"]] == ["ok"]
    try:
        parse_bbox({"min_lat": "1"})
    except ValueError as exc:
        assert "четыре" in str(exc)


def test_geo_api_requires_a_module_permission(client, app):
    assert client.get("/api/geo/search?q=ленина").status_code in {302, 401}
    with app.app_context():
        AuthService.create_user("kiosk-geo@test.local", "pass12345", "Экран", ROLE_IRZ_DISPLAY)
    _login(client, "kiosk-geo@test.local")
    assert client.get("/api/geo/search?q=ленина").status_code == 403
    assert client.get("/defects/map.json").status_code == 403
    assert client.get("/requests/map.json").status_code == 403
    screen = client.get("/irz/map-display")
    assert screen.status_code == 200
    html = screen.get_data(as_text=True)
    assert "js/map/core.js" in html
    assert "js/irz-map.js" in html
    assert "vendor/leaflet/leaflet.js" not in html


def test_geo_search_reverse_entrances_and_route_contract(admin_client, app, monkeypatch):
    suggestion = AddressSuggestion(
        original_address="Ленина 10",
        normalized_address="Киров, улица Ленина, дом 10",
        settlement="Киров",
        street="Ленина",
        house="10",
        latitude=58.6035,
        longitude=49.668,
        address_source="nominatim",
        precision="EXACT",
    )

    class Stub:
        def suggest(self, query, limit=None):
            return [suggestion]

        def suggest_settlement(self, query, limit=None):
            return [suggestion]

        def reverse(self, latitude, longitude):
            return suggestion

    monkeypatch.setattr("app.core.address.get_address_suggestion_service", lambda: Stub())
    first = admin_client.get("/api/geo/search?q=Ленина 10")
    assert first.status_code == 200
    body = first.get_json()
    assert body["suggestions"][0]["precision"] == "EXACT"
    assert body["cached"] is False
    second = admin_client.get("/api/geo/search?q=Ленина 10")
    assert second.get_json()["cached"] is True

    reverse = admin_client.get("/api/geo/reverse?lat=58.6035&lon=49.668")
    assert reverse.status_code == 200
    assert reverse.get_json()["suggestion"]["house"] == "10"
    assert admin_client.get("/api/geo/reverse?lat=нет").status_code == 400

    with app.app_context():
        for index in range(600):
            db.session.add(
                GeoEntrance(
                    source="test",
                    external_id=f"ent-{index}",
                    latitude=Decimal("58.610000") + Decimal(index) / Decimal("1000000"),
                    longitude=Decimal("49.670000"),
                    street_name="Ленина",
                    house_number="10",
                    ref="2" if index == 0 else None,
                )
            )
        db.session.commit()
    hidden = admin_client.get("/api/geo/entrances?min_lat=58.6&max_lat=58.62&min_lon=49.66&max_lon=49.68&zoom=16")
    assert hidden.get_json()["hidden"] is True
    assert hidden.get_json()["geojson"]["features"] == []
    shown = admin_client.get("/api/geo/entrances?min_lat=58.6&max_lat=58.62&min_lon=49.66&max_lon=49.68&zoom=18")
    features = shown.get_json()["geojson"]["features"]
    assert shown.get_json()["hidden"] is False
    assert 1 <= len(features) <= 500
    assert features[0]["properties"]["street"] == "Ленина"

    plain = admin_client.post("/api/routes", json={"points": [{"lat": 58.6, "lon": 49.66}, {"lat": 58.61, "lon": 49.67}], "mode": "driving"})
    assert plain.get_json()["code"] == "routing_not_configured"
    optimized = admin_client.post("/api/routes", json={"optimize": True, "points": []})
    assert optimized.status_code == 409
    assert optimized.get_json()["code"] == "optimization_not_configured"


def test_request_map_limits_bbox_and_skips_missing_coordinates(admin_client, app):
    with app.app_context():
        status = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        journal_id = RequestRepository.get_default_journal().id
        rows = [
            Request(
                number=f"GEO-{index:04d}",
                title="Точка",
                address=f"ул. Ленина, {index}",
                applicant_name="QA",
                priority=Priority.MEDIUM.value,
                status_id=status.id,
                journal_id=journal_id,
                latitude=Decimal("58.603000") + (Decimal(index) / Decimal("100000")),
                longitude=Decimal("49.668000"),
            )
            for index in range(1000)
        ]
        rows.append(
            Request(
                number="GEO-NONE",
                title="Без точки",
                address="ул. Ленина, без координат",
                applicant_name="QA",
                priority=Priority.MEDIUM.value,
                status_id=status.id,
                journal_id=journal_id,
            )
        )
        rows.append(
            Request(
                number="GEO-MSK",
                title="Далеко",
                address="Москва",
                applicant_name="QA",
                priority=Priority.MEDIUM.value,
                status_id=status.id,
                journal_id=journal_id,
                latitude=Decimal("55.750000"),
                longitude=Decimal("37.620000"),
            )
        )
        db.session.add_all(rows)
        db.session.commit()
    full = admin_client.get("/requests/map.json")
    assert full.status_code == 200
    payload = full.get_json()
    assert len(payload["points"]) <= 500
    assert payload["geojson"]["type"] == "FeatureCollection"
    assert len(payload["geojson"]["features"]) == len(payload["points"])
    assert "GEO-NONE" not in {point["number"] for point in payload["points"]}
    near = admin_client.get("/requests/map.json?min_lat=58.5&max_lat=58.7&min_lon=49.5&max_lon=49.8")
    numbers = {point["number"] for point in near.get_json()["points"]}
    assert "GEO-MSK" not in numbers
    assert numbers
    broken = admin_client.get("/requests/map.json?min_lat=58.5")
    assert broken.status_code == 400


def test_village_suggestions_use_settlement_search(admin_client, app, monkeypatch):
    suggestion = AddressSuggestion(
        original_address="Бахта",
        normalized_address="Кировская область, Бахта",
        settlement="Бахта",
        region="Кировская область",
        address_source="nominatim",
        precision="SETTLEMENT",
    )

    class Stub:
        def suggest_settlement(self, query, limit=None):
            return [suggestion]

        def suggest(self, query, limit=None):
            raise AssertionError("городской поиск не должен вызываться для деревень")

    monkeypatch.setattr("app.core.address.get_address_suggestion_service", lambda: Stub())
    with app.app_context():
        journal = RequestRepository.get_journal_by_code("oktyabrsky_villages")
        journal_id = str(journal.id)
    response = admin_client.get(f"/requests/api/address-suggestions?q=Бахта&journal_id={journal_id}")
    body = response.get_json()
    assert body["scope"] == "settlement"
    assert body["suggestions"][0]["settlement"] == "Бахта"
    assert body["suggestions"][0]["precision"] == "SETTLEMENT"


class _Body:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.raw


def _enable_captcha(app):
    app.config["CAPTCHA_ENABLED"] = True
    app.config["TURNSTILE_SECRET_KEY"] = "test-secret-not-for-logs"
    app.config["TURNSTILE_SITE_KEY"] = "test-site-key"
    LoginThrottle._attempts.clear()
    LoginThrottle._blocked_until.clear()


def test_login_rejects_missing_invalid_and_unavailable_captcha(client, app, monkeypatch):
    _enable_captcha(app)
    missing = client.post(
        "/auth/login",
        data={"email": "admin@opora.ru", "password": "admin123", "submit": "Войти"},
    )
    text = missing.get_data(as_text=True)
    assert "Подтвердите проверку" in text
    assert "cf-turnstile" in text
    assert "js/login-captcha.js" in text
    assert "test-secret-not-for-logs" not in text

    monkeypatch.setattr("app.modules.auth.captcha.urlopen", lambda *_a, **_k: _Body(b'{"success": false}'))
    invalid = client.post(
        "/auth/login",
        data={"email": "admin@opora.ru", "password": "admin123", "cf-turnstile-response": "bad", "submit": "Войти"},
    )
    assert "Проверка не пройдена" in invalid.get_data(as_text=True)

    def raise_timeout(*_args, **_kwargs):
        raise socket.timeout()

    monkeypatch.setattr("app.modules.auth.captcha.urlopen", raise_timeout)
    timed_out = client.post(
        "/auth/login",
        data={"email": "other@opora.ru", "password": "admin123", "cf-turnstile-response": "slow", "submit": "Войти"},
    )
    assert "не ответил вовремя" in timed_out.get_data(as_text=True)

    def raise_unavailable(*_args, **_kwargs):
        raise URLError("down")

    monkeypatch.setattr("app.modules.auth.captcha.urlopen", raise_unavailable)
    down = client.post(
        "/auth/login",
        data={"email": "third@opora.ru", "password": "admin123", "cf-turnstile-response": "down", "submit": "Войти"},
    )
    assert "временно недоступен" in down.get_data(as_text=True)
    assert "Вход выполнен" not in down.get_data(as_text=True)


def test_login_accepts_captcha_verified_by_provider(client, app, monkeypatch):
    _enable_captcha(app)
    monkeypatch.setattr("app.modules.auth.captcha.urlopen", lambda *_a, **_k: _Body(b'{"success": true}'))
    response = client.post(
        "/auth/login",
        data={"email": "admin@opora.ru", "password": "admin123", "cf-turnstile-response": "ok-token", "submit": "Войти"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    with app.app_context():
        verdict = verify_turnstile_result("ok-token", "127.0.0.1")
    assert verdict.ok is True
    assert verdict.code == "ok"
