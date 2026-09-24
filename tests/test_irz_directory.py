"""IRZ map / directory / wall display: statuses, search, permissions, kiosk role, 600 devices."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from flask import url_for
from sqlalchemy import event

from app.extensions import db
from app.models.auth.associations import RolePermission
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.irz import IRZDevice, IRZMeter
from app.modules.auth.services import AuthService
from app.modules.irz import directory, service
from app.seed.reference_data import ReferenceDataService

IMEI_OK = "861000000000001"
IMEI_NO_METER = "861000000000002"
IMEI_STALE = "861000000000003"
IMEI_PARTIAL = "861000000000004"
IMEI_OFFLINE = "861000000000005"
IMEI_DARK = "861000000000006"


def _login(client, email, password="pass12345"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def _user_with(app, email, codes):
    """A user whose only role holds exactly `codes`."""
    with app.app_context():
        role = Role(code=f"qa_{email.split('@')[0].replace('-', '_')}", name=email, description="QA")
        db.session.add(role)
        db.session.flush()
        for code in codes:
            perm = db.session.scalar(db.select(Permission).where(Permission.code == code))
            db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.session.commit()
        AuthService.create_user(email, "pass12345", email, role.code)


def _state(values, updated_at):
    """Merged meter state: U values from voltage_phases, I values from current_phases."""
    commands = {}
    for command, prefix in (("voltage_phases", "u_"), ("current_phases", "i_")):
        fields = sorted(key for key in values if key.startswith(prefix))
        if fields:
            commands[command] = {"captured_at": updated_at.isoformat(), "quality": "GOOD", "fields": fields}
    return {"values": values, "commands": commands, "updated_at": updated_at.isoformat()}


def _seed(app):
    now = datetime.now(timezone.utc)
    with app.app_context():
        ok = IRZDevice(imei=IMEI_OK, name="ПП Чехова 8", model="ATM21", enabled=True,
                       latitude=58.6, longitude=49.66, address_text="ул. Чехова, 8")
        no_meter = IRZDevice(imei=IMEI_NO_METER, name=f"ATM21 {IMEI_NO_METER}", model="ATM21", enabled=True)
        stale = IRZDevice(imei=IMEI_STALE, name="ТП Ленина", model="ATM21", enabled=True, latitude=58.61, longitude=49.67)
        partial = IRZDevice(imei=IMEI_PARTIAL, name="КТП Южная", model="ATM21", enabled=True, latitude=58.62, longitude=49.68)
        offline = IRZDevice(imei=IMEI_OFFLINE, name=f"ATM21 {IMEI_OFFLINE}", model="ATM21", enabled=True,
                            latitude=58.63, longitude=49.69)
        dark = IRZDevice(imei=IMEI_DARK, name="ИП Луговая 3", model="ATM21", enabled=True, latitude=58.64, longitude=49.7)
        db.session.add_all([ok, no_meter, stale, partial, offline, dark])
        db.session.flush()
        db.session.add_all([
            IRZMeter(irz_device_id=ok.id, serial_number="45211093", last_poll_status="SUCCESS", last_poll_at=now,
                     latest_snapshot=_state({"u_a": 231.8, "u_b": 229.1, "u_c": 230.4,
                                             "i_a": 2.5, "i_b": 2.4, "i_c": 2.6}, now)),
            IRZMeter(irz_device_id=stale.id, serial_number="45211094", last_poll_status="SUCCESS",
                     latest_snapshot=_state({"u_a": 220.0, "i_a": 5.0, "i_b": 5.0, "i_c": 5.0}, now - timedelta(hours=2))),
            IRZMeter(irz_device_id=partial.id, serial_number="45211095", last_poll_status="PARTIAL",
                     latest_snapshot=_state({"u_a": 225.0, "i_a": 0.2}, now)),
            IRZMeter(irz_device_id=dark.id, serial_number="45211096", last_poll_status="SUCCESS",
                     latest_snapshot=_state({"i_a": 0, "i_b": 0.4, "i_c": 1.0}, now)),
        ])
        db.session.commit()


@pytest.fixture()
def live(monkeypatch):
    sessions = [{"imei": imei, "ip": "10.0.0.1", "port": 5009, "last_seen_at": datetime.now(timezone.utc).isoformat()}
                for imei in (IMEI_OK, IMEI_NO_METER, IMEI_STALE, IMEI_PARTIAL, IMEI_DARK)]
    monkeypatch.setattr(service, "get_devices", lambda: list(sessions))
    return sessions


def test_directory_statuses_names_meter_and_counters(app, admin_client, live):
    _seed(app)
    payload = admin_client.get("/irz/api/directory").get_json()
    by_imei = {item["imei"]: item for item in payload["items"]}
    ok = by_imei[IMEI_OK]
    assert (ok["operational_status"], ok["operational_label"], ok["cabinet_type"], ok["online"]) == ("ON", "Горит", "PP", True)
    assert ok["problem"] is None and ok["no_data_seconds"] is None and ok["last_successful_meter_response"]
    assert ok["meter"] == {"serial": "45211093", "model": "Mercury 230"}
    assert ok["summary"] == {"u_a": 231.8, "u_b": 229.1, "u_c": 230.4, "i_a": 2.5, "i_b": 2.4, "i_c": 2.6}
    assert ok["title"] == "ПП Чехова 8" and ok["name"] == "ПП Чехова 8"
    assert (by_imei[IMEI_DARK]["operational_status"], by_imei[IMEI_DARK]["cabinet_type"]) == ("OFF", "IP")
    no_meter = by_imei[IMEI_NO_METER]
    assert no_meter["operational_status"] == "PROBLEM" and no_meter["meter"] is None
    assert no_meter["problem"] == "Mercury ещё не передал показания" and no_meter["last_successful_meter_response"] is None
    assert no_meter["name"] is None and no_meter["title"] == f"ATM21 {IMEI_NO_METER}" and no_meter["cabinet_type"] == "OTHER"
    assert no_meter["has_coordinates"] is False and no_meter["latitude"] is None
    stale = by_imei[IMEI_STALE]
    assert (stale["operational_status"], stale["data_state"], stale["cabinet_type"]) == ("CRITICAL", "STALE", "OTHER")
    assert 7100 <= stale["no_data_seconds"] <= 7300
    assert (by_imei[IMEI_PARTIAL]["operational_status"], by_imei[IMEI_PARTIAL]["data_state"]) == ("PROBLEM", "PARTIAL")
    offline = by_imei[IMEI_OFFLINE]
    assert (offline["operational_status"], offline["online"], offline["problem"]) == ("PROBLEM", False, "ATM21 не на связи")
    assert payload["counters"] == {"total": 6, "on": 1, "off": 1, "problem": 3, "critical": 1,
                                   "online": 5, "offline": 1, "no_coordinates": 1}
    assert [item["operational_status"] for item in payload["items"]] == ["CRITICAL", "PROBLEM", "PROBLEM", "PROBLEM", "OFF", "ON"]
    assert payload["gateway"] == "online"


def test_map_api_returns_only_located_devices_but_counts_all(app, admin_client, live):
    _seed(app)
    payload = admin_client.get("/irz/api/map").get_json()
    assert IMEI_NO_METER not in {item["imei"] for item in payload["items"]}
    assert len(payload["items"]) == 5 and payload["counters"]["total"] == 6
    assert payload["counters"]["no_coordinates"] == 1
    item = payload["items"][0]
    assert set(item) == {"id", "imei", "name", "title", "meter", "latitude", "longitude", "has_coordinates", "cabinet_type",
                         "online", "operational_status", "problem", "last_successful_meter_response", "no_data_seconds",
                         "last_seen_at", "summary"}
    assert set(item["summary"]) <= {"u_a", "u_b", "u_c"}


def test_gateway_outage_never_keeps_old_on_status(app, admin_client, monkeypatch):
    _seed(app)
    monkeypatch.setattr(service, "get_devices", lambda: (_ for _ in ()).throw(service.GatewayUnavailable("down")))
    payload = admin_client.get("/irz/api/directory").get_json()
    by_imei = {item["imei"]: item for item in payload["items"]}
    assert payload["gateway"] == "unavailable"
    assert by_imei[IMEI_OK]["operational_status"] == "PROBLEM" and by_imei[IMEI_OK]["problem"] == "Шлюз связи недоступен"
    assert by_imei[IMEI_STALE]["operational_status"] == "CRITICAL"
    assert payload["counters"]["on"] == 0 and payload["counters"]["online"] == 0 and payload["counters"]["offline"] == 6


def test_new_live_atm21_appears_automatically(app, admin_client, monkeypatch):
    monkeypatch.setattr(service, "get_devices", lambda: [{"imei": "861000000000099", "ip": "10.0.0.9"}])
    payload = admin_client.get("/irz/api/directory").get_json()
    assert [item["title"] for item in payload["items"]] == ["ATM21 861000000000099"]
    assert payload["items"][0]["operational_status"] == "PROBLEM" and payload["items"][0]["has_coordinates"] is False


@pytest.mark.parametrize("query,expected", [
    ("чехова", {IMEI_OK}),
    ("ЧЕХОВА 8", {IMEI_OK}),
    ("861000000000003", {IMEI_STALE}),
    ("45211095", {IMEI_PARTIAL}),
    ("ул. чехова", {IMEI_OK}),
    ("нет такого", set()),
])
def test_search_by_name_imei_meter_serial_and_address(app, admin_client, live, query, expected):
    _seed(app)
    payload = admin_client.get("/irz/api/directory", query_string={"q": query}).get_json()
    assert {item["imei"] for item in payload["items"]} == expected
    assert payload["counters"]["total"] == 6


def test_status_coordinates_filters_and_pagination(app, admin_client, live):
    _seed(app)
    get = lambda **params: admin_client.get("/irz/api/directory", query_string=params).get_json()
    imeis = lambda **params: {item["imei"] for item in get(**params)["items"]}
    assert imeis(status="on") == {IMEI_OK}
    assert imeis(status="off") == {IMEI_DARK}
    assert imeis(status="problem") == {IMEI_NO_METER, IMEI_PARTIAL, IMEI_OFFLINE}
    assert imeis(status="critical") == {IMEI_STALE}
    assert imeis(status="offline") == {IMEI_OFFLINE}
    assert len(get(status="online")["items"]) == 5
    assert imeis(status="no_coordinates") == {IMEI_NO_METER}
    assert len(get(has_coordinates="1")["items"]) == 5
    page = get(per_page=2, page=2)
    assert len(page["items"]) == 2 and page["pagination"] == {"page": 2, "per_page": 2, "pages": 3, "total": 6}
    assert admin_client.get("/irz/api/directory?status=bogus").status_code == 400


def test_device_page_resolves_id_and_imei_and_works_offline(app, admin_client, live):
    _seed(app)
    with app.app_context():
        device_id = str(db.session.scalar(db.select(IRZDevice.id).where(IRZDevice.imei == IMEI_OFFLINE)))
    page = admin_client.get(f"/irz/{device_id}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert f"ATM21 {IMEI_OFFLINE}" in html and 'aria-label="breadcrumb"' in html and "Назад к карте" in html
    assert f'data-imei="{IMEI_OFFLINE}"' in html
    redirect = admin_client.get(f"/irz/{IMEI_OFFLINE}")
    assert redirect.status_code == 302 and redirect.headers["Location"].endswith(f"/irz/{device_id}")
    assert "Статус освещения" in html and "Последний успешный ответ Mercury" in html
    detail = admin_client.get(f"/irz/api/devices/{IMEI_OFFLINE}").get_json()
    assert detail["online"] is False and detail["imei"] == IMEI_OFFLINE
    assert detail["operational"]["code"] == "PROBLEM" and detail["operational"]["reason"] == "ATM21 не на связи"
    lit = admin_client.get(f"/irz/api/devices/{IMEI_OK}").get_json()
    assert (lit["operational"]["code"], lit["operational"]["label"], lit["cabinet_type"]) == ("ON", "Горит", "PP")
    assert lit["operational"]["last_success_at"]
    assert admin_client.get("/irz/00000000-0000-0000-0000-000000000000").status_code == 404
    assert admin_client.get("/irz/not-a-device").status_code == 404


def test_viewer_reads_everything_but_cannot_edit_poll_or_open_wall_display(app, client, live, monkeypatch):
    _seed(app)
    _user_with(app, "irz-viewer@test.local", ["irz.view"])
    _login(client, "irz-viewer@test.local")
    with app.app_context():
        device_id = str(db.session.scalar(db.select(IRZDevice.id).where(IRZDevice.imei == IMEI_OK)))
    polled = []
    monkeypatch.setattr(service, "poll_device", lambda *a, **k: polled.append(1) or {})
    assert client.get("/irz").status_code == 200
    assert client.get("/irz/api/map").status_code == 200
    assert client.get("/irz/api/directory").status_code == 200
    page = client.get(f"/irz/{device_id}").get_data(as_text=True)
    assert "<form data-profile-form" not in page and "data-poll>" not in page and "data-read-events" not in page
    assert "data-profile-view" in page
    assert client.patch(f"/irz/api/devices/{IMEI_OK}", json={"name": "Взлом"}).status_code == 403
    assert client.post(f"/irz/api/devices/{IMEI_OK}/poll", json={}).status_code == 403
    assert client.post(f"/irz/api/devices/{IMEI_OK}/events", json={}).status_code == 403
    assert client.get("/irz/map-display").status_code == 403
    assert polled == []
    with app.app_context():
        assert db.session.scalar(db.select(IRZDevice.name).where(IRZDevice.imei == IMEI_OK)) == "ПП Чехова 8"


def test_editor_updates_metadata_with_validation(app, client, live):
    _seed(app)
    _user_with(app, "irz-editor@test.local", ["irz.view", "irz.edit"])
    _login(client, "irz-editor@test.local")
    url = f"/irz/api/devices/{IMEI_NO_METER}"
    assert client.patch(url, json={"name": "ПП Кирова 1", "latitude": "58,6035", "longitude": "49.668",
                                   "address_text": "ул. Кирова, 1"}).status_code == 200
    item = next(i for i in client.get("/irz/api/directory").get_json()["items"] if i["imei"] == IMEI_NO_METER)
    assert (item["title"], item["latitude"], item["longitude"], item["address"]) == ("ПП Кирова 1", 58.6035, 49.668, "ул. Кирова, 1")
    for payload, code in (({"latitude": 91}, "INVALID_LATITUDE"), ({"longitude": -181}, "INVALID_LONGITUDE"),
                          ({"latitude": "abc"}, "INVALID_LATITUDE"), ({"latitude": True}, "INVALID_LATITUDE"),
                          ({"latitude": ""}, "INCOMPLETE_COORDINATES")):
        response = client.patch(url, json=payload)
        assert response.status_code == 400 and response.get_json()["error_code"] == code
    assert client.patch(url, json={"name": ""}).status_code == 200
    item = next(i for i in client.get("/irz/api/directory").get_json()["items"] if i["imei"] == IMEI_NO_METER)
    assert item["name"] is None and item["title"] == f"ATM21 {IMEI_NO_METER}" and item["latitude"] == 58.6035
    assert client.patch(url, json={"latitude": None, "longitude": None}).status_code == 200
    item = next(i for i in client.get("/irz/api/directory").get_json()["items"] if i["imei"] == IMEI_NO_METER)
    assert item["has_coordinates"] is False
    assert client.post(f"/irz/api/devices/{IMEI_NO_METER}/poll", json={}).status_code == 403


def test_poll_permission_allows_manual_poll(app, client, live, monkeypatch):
    _seed(app)
    _user_with(app, "irz-poller@test.local", ["irz.view", "irz.poll"])
    _login(client, "irz-poller@test.local")
    monkeypatch.setattr(service, "poll_device", lambda device, **kwargs: {"success": True, "quality": "GOOD", "source": kwargs["source"]})
    response = client.post(f"/irz/api/devices/{IMEI_OK}/poll", json={})
    assert response.status_code == 200 and response.get_json()["source"] == "MANUAL"
    assert client.patch(f"/irz/api/devices/{IMEI_OK}", json={"name": "x"}).status_code == 403


def test_kiosk_role_sees_only_the_wall_display(app, client, live):
    _seed(app)
    with app.app_context():
        AuthService.create_user("irz-screen@test.local", "pass12345", "Карта", "irz_display")
        ReferenceDataService.sync_security_roles()
        role = db.session.scalar(db.select(Role).where(Role.code == "irz_display"))
        codes = {perm.code for perm in db.session.scalars(
            db.select(Permission).join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id, RolePermission.active_filter()))}
        device_id = str(db.session.scalar(db.select(IRZDevice.id).where(IRZDevice.imei == IMEI_OK)))
    assert codes == {"irz.map_display"}
    landing = _login(client, "irz-screen@test.local")
    assert landing.request.path == "/irz/map-display"
    html = landing.get_data(as_text=True)
    assert "IRZ · Состояние сети" in html and "Подписи" in html and 'data-detail-template=""' in html
    for forbidden in ("appShell", "sidebar", "data-profile-form", "data-poll", "Обновить показания"):
        assert forbidden not in html
    assert client.get("/irz/api/map").status_code == 200
    with app.test_request_context():
        other_modules = [url_for(endpoint) for endpoint in
                         ("requests.index", "employees.index", "documents.index", "messenger.index", "devices.index")]
    for path in ["/irz", "/irz/api/directory", f"/irz/{device_id}", f"/irz/api/devices/{IMEI_OK}", *other_modules]:
        assert client.get(path).status_code == 403, path
    assert client.patch(f"/irz/api/devices/{IMEI_OK}", json={"name": "x"}).status_code == 403
    assert client.post(f"/irz/api/devices/{IMEI_OK}/poll", json={}).status_code == 403


def test_wall_display_requires_login_and_has_no_url_token(client):
    response = client.get("/irz/map-display")
    assert response.status_code == 302 and "/auth/login" in response.headers["Location"]
    assert client.get("/irz/api/map").status_code in (302, 401)
    assert client.get("/irz/map-display?token=12345").status_code == 302


def test_dispatcher_with_view_and_display_gets_detail_link(app, client, live):
    _user_with(app, "irz-wall@test.local", ["irz.view", "irz.map_display"])
    _login(client, "irz-wall@test.local")
    html = client.get("/irz/map-display").get_data(as_text=True)
    assert 'data-detail-template="/irz/DEVICE_ID"' in html
    assert client.get("/").status_code == 200


def test_new_permissions_are_inherited_once_and_not_forced_back(app):
    with app.app_context():
        view = db.session.scalar(db.select(Permission).where(Permission.code == "irz.view"))
        dispatcher = db.session.scalar(db.select(Role).where(Role.code == "dispatcher"))
        db.session.add(RolePermission(role_id=dispatcher.id, permission_id=view.id))
        poll = db.session.scalar(db.select(Permission).where(Permission.code == "irz.poll"))
        db.session.execute(db.delete(RolePermission).where(RolePermission.permission_id == poll.id))
        db.session.delete(poll)
        db.session.commit()

        ReferenceDataService.sync_security_roles()
        poll = db.session.scalar(db.select(Permission).where(Permission.code == "irz.poll"))
        granted = lambda: {rp.role_id for rp in db.session.scalars(
            db.select(RolePermission).where(RolePermission.permission_id == poll.id, RolePermission.active_filter()))}
        admin = db.session.scalar(db.select(Role).where(Role.code == "admin"))
        assert {dispatcher.id, admin.id} <= granted()

        db.session.execute(db.delete(RolePermission).where(RolePermission.permission_id == poll.id,
                                                           RolePermission.role_id == dispatcher.id))
        db.session.commit()
        ReferenceDataService.sync_security_roles()
        assert dispatcher.id not in granted()
        admin_codes = {perm.code for perm in db.session.scalars(
            db.select(Permission).join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == admin.id))}
        assert {"irz.view", "irz.edit", "irz.poll", "irz.map_display", "irz.admin"} <= admin_codes


def test_roles_editor_lists_new_irz_permissions(app, admin_client):
    response = admin_client.get("/roles/editor/new")
    assert response.status_code == 200
    html = response.get_json()["html"]
    for name in ("IRZ: ручной опрос счётчика", "IRZ: полноэкранная карта (экран)", "IRZ · Мониторинг"):
        assert name in html
    with app.app_context():
        edit_id = str(db.session.scalar(db.select(Permission.id).where(Permission.code == "irz.edit")))
    assert f'value="{edit_id}"' in html


def _bulk_devices(count, *, start=0):
    now = datetime.now(timezone.utc)
    devices, meters = [], []
    for index in range(start, start + count):
        device = IRZDevice(imei=f"86200000{index:07d}", name=f"Объект {index}", model="ATM21", enabled=True,
                           latitude=58.5 + index / 10000 if index % 10 else None,
                           longitude=49.6 + index / 10000 if index % 10 else None)
        devices.append(device)
    db.session.add_all(devices)
    db.session.flush()
    for device in devices:
        meters.append(IRZMeter(irz_device_id=device.id, serial_number=f"9{device.imei[-8:]}", last_poll_status="SUCCESS",
                               last_seen_at=now, latest_snapshot=_state({"u_a": 230.0, "u_b": 231.0, "u_c": 229.0,
                                                                         "i_a": 3.0, "i_b": 3.1, "i_c": 2.9}, now)))
    db.session.add_all(meters)
    db.session.commit()


def _count_queries(app, action):
    statements = []
    listener = lambda *args: statements.append(args[2])
    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", listener)
    try:
        result = action()
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    return len(statements), result


def test_directory_for_600_devices_uses_constant_queries(app, admin_client, monkeypatch):
    stored = {"count": 0}
    monkeypatch.setattr(service, "get_devices", lambda: [{"imei": f"86200000{index:07d}"}
                                                         for index in range(0, stored["count"], 2)])
    admin_client.get("/irz/api/map")
    with app.app_context():
        _bulk_devices(5)
    stored["count"] = 5
    small, _ = _count_queries(app, lambda: admin_client.get("/irz/api/map"))
    with app.app_context():
        _bulk_devices(595, start=5)
        stored["count"] = 600
        count, items = _count_queries(app, lambda: directory.build_directory({}, True))
    assert count <= 2 and len(items) == 600
    started = time.perf_counter()
    large, response = _count_queries(app, lambda: admin_client.get("/irz/api/map"))
    elapsed = time.perf_counter() - started
    payload = response.get_json()
    assert large == small
    assert payload["counters"] == {"total": 600, "on": 300, "off": 0, "problem": 300, "critical": 0,
                                   "online": 300, "offline": 300, "no_coordinates": 60}
    assert len(payload["items"]) == 540
    assert elapsed < 5
