import socket
import threading
import time
import csv
import io
from pathlib import Path

from app.extensions import db
from app.models.auth.associations import RolePermission
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.irz import IRZExchangeLog, IRZExperiment
from app.modules.auth.services import AuthService
from app.modules.irz import service
from app.modem_gateway.sniffer import create_servers


def _login(client, email, password="pass12345"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def test_irz_page_opens_and_appears_in_menu(admin_client):
    response = admin_client.get("/irz")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "IRZ · Мониторинг" in html
    assert 'href="/irz"' in html
    assert "Обновить показания" in html
    assert "Местоположение" in html
    assert "История опросов" in html
    assert "Инженерный режим" not in html
    assert "PROTOCOL LAB" not in html
    assert "HEX COMMAND" not in html
    assert "/static/js/irz.js?v=" in html
    assert "/static/js/irz-legacy.js?v=" not in html
    partial = admin_client.get("/irz", headers={"X-Opora-Nav": "1"})
    assert partial.status_code == 200
    assert "appShell" not in partial.get_data(as_text=True)
    script = Path("app/static/js/irz.js").read_text(encoding="utf-8")
    assert "DOMContentLoaded" in script
    assert "opora:navigated" in script
    assert "opora:before-navigate" in script
    assert "data-irz-monitor" in script
    assert "latest" in script


def test_irz_has_one_real_entrypoint_and_monitoring_assets(app):
    rules = [rule for rule in app.url_map.iter_rules() if rule.rule == "/irz"]
    assert [(rule.endpoint, sorted(rule.methods - {"HEAD", "OPTIONS"})) for rule in rules] == [("irz.index", ["GET"])]
    operator = Path("app/static/js/irz.js").read_text(encoding="utf-8")
    assert "data-irz-monitor" in operator
    assert "data-irz-legacy-root" not in operator


def test_irz_permissions_separate_view_and_send(app, client, monkeypatch):
    with app.app_context():
        AuthService.create_user("irz-view@test.local", "pass12345", "IRZ Viewer", "executor")
        role = db.session.scalar(db.select(Role).where(Role.code == "executor"))
        view = db.session.scalar(db.select(Permission).where(Permission.code == "irz.view"))
        db.session.add(RolePermission(role_id=role.id, permission_id=view.id))
        db.session.commit()
    _login(client, "irz-view@test.local")
    assert client.get("/irz").status_code == 200
    assert client.get("/irz/api/logs").status_code == 200
    assert client.post("/irz/api/send", json={"imei": "123456789012345", "hex": "01"}).status_code == 403


def test_irz_logs_returns_latest_entries(app, admin_client):
    with app.app_context():
        db.session.add_all(
            [
                IRZExchangeLog(imei="123456789012345", direction="RX", raw_hex="B5 BC", raw_ascii="..", raw_length=2),
                IRZExchangeLog(imei="123456789012345", direction="TX", raw_hex="01 02 FF", raw_ascii="...", raw_length=3),
            ]
        )
        db.session.commit()
    response = admin_client.get("/irz/api/logs?imei=123456789012345&limit=200")
    assert response.status_code == 200
    assert [(item["direction"], item["hex"], item["length"]) for item in response.get_json()] == [
        ("RX", "B5 BC", 2),
        ("TX", "01 02 FF", 3),
    ]


def test_irz_send_calls_modem_sniffer_client(admin_client, monkeypatch):
    called = {}

    def fake_send(imei, hex_value):
        called.update(imei=imei, hex=hex_value)
        return {"status": "sent", "imei": imei, "bytes": 3}

    monkeypatch.setattr(service, "send_command", fake_send)
    response = admin_client.post("/irz/api/send", json={"imei": "123456789012345", "hex": "01 02 FF"})
    assert response.status_code == 200
    assert response.get_json()["bytes"] == 3
    assert called == {"imei": "123456789012345", "hex": "01 02 FF"}


def test_irz_send_rejects_invalid_hex_before_gateway(admin_client, monkeypatch):
    called = False

    def fake_gateway_request(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(service, "_gateway_request", fake_gateway_request)
    response = admin_client.post("/irz/api/send", json={"imei": "123456789012345", "hex": "01 ZZ"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid HEX"}
    assert called is False


def test_irz_devices_reports_gateway_status(admin_client, monkeypatch):
    monkeypatch.setattr(
        service,
        "get_devices",
        lambda: [{"imei": "123456789012345", "ip": "127.0.0.1", "port": 4567, "last_seen_at": "2026-09-21T12:00:00+00:00"}],
    )
    response = admin_client.get("/irz/api/devices")
    assert response.status_code == 200
    assert response.get_json()["status"] == "online"
    assert response.get_json()["devices"][0]["imei"] == "123456789012345"


def test_irz_gateway_client_uses_modem_sniffer_http_api(app):
    tcp_server, http_server = create_servers("127.0.0.1", 0, 0)
    threads = [
        threading.Thread(target=tcp_server.serve_forever, daemon=True),
        threading.Thread(target=http_server.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    client = socket.create_connection(("127.0.0.1", tcp_server.server_address[1]), timeout=2)
    try:
        client.sendall(b"AT$IMEI=123456789012345,TYP=ATM,DEV=ATM21")
        with app.app_context():
            app.config["IRZ_GATEWAY_URL"] = f"http://127.0.0.1:{http_server.server_address[1]}"
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                devices = service.get_devices()
                if devices:
                    break
                time.sleep(0.01)
            assert devices[0]["imei"] == "123456789012345"
            assert service.send_command("123456789012345", "01 02 FF")["bytes"] == 3
        assert client.recv(3) == bytes((0x01, 0x02, 0xFF))
    finally:
        client.close()
        tcp_server.shutdown()
        http_server.shutdown()
        tcp_server.server_close()
        http_server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_irz_crc_generation_and_suffixes():
    assert service.modbus_crc16(b"123456789") == bytes.fromhex("37 4B")
    assert service.mercury_crc(b"123456789") == bytes.fromhex("37 4B")
    assert service.build_test_command("01 03 00 00 00 10", "modbus", "0d0a") == bytes.fromhex(
        "01 03 00 00 00 10 44 06 0D 0A"
    )
    assert service.build_test_command("01 03", "MERCURY CRC", "0D 0A").endswith(bytes.fromhex("0D 0A"))


def test_irz_test_command_logs_experiment(app, admin_client, monkeypatch):
    monkeypatch.setattr(
        service,
        "_gateway_request",
        lambda *args, **kwargs: {
            "status": "response",
            "response_hex": "01 03 02 12 34 B5 33",
            "response_ascii": "....4.3",
            "success": True,
        },
    )
    response = admin_client.post(
        "/irz/api/test-command",
        json={"imei": "123456789012345", "hex": "01 03 00 00 00 10", "crc": "modbus", "append": "none"},
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    with app.app_context():
        experiment = db.session.scalar(db.select(IRZExperiment))
        assert experiment.command_hex == "01 03 00 00 00 10 44 06"
        assert experiment.response_hex == "01 03 02 12 34 B5 33"
        assert experiment.response_ascii == "....4.3"
        assert experiment.success is True


def test_irz_session_csv_export(app, admin_client):
    with app.app_context():
        db.session.add(IRZExchangeLog(imei="123456789012345", direction="RX", raw_hex="01 02", raw_ascii="..", raw_length=2))
        db.session.commit()
    response = admin_client.get("/irz/api/export?imei=123456789012345")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    text = response.get_data(as_text=True).lstrip("\ufeff")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[0]["direction"] == "RX"
    assert rows[0]["hex"] == "01 02"
    assert rows[0]["ascii"] == ".."
