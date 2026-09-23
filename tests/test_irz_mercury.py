from types import SimpleNamespace

import pytest
from modbus_crc import add_crc

from app.extensions import db
from app.models.irz import IRZOperationLog
from app.models.irz import IRZDevice, IRZMeter, IRZMeterSnapshot
from app.modem_gateway.mercury import MercuryGatewayError, MercurySessionManager
from app.modules.irz import service
from app.modules.irz.commands import COMMANDS, normalize_result


def fake_mercury_module():
    driver = SimpleNamespace(prepare_address=lambda value: int(value), format_address=lambda value: bytes((value,)),
                             extract_address=lambda package: package[0], extract_data=lambda package: list(package[1:-2]))
    class Commands:
        @staticmethod
        def get_serial_number_and_date_of_manufacture(meter):
            data = meter.send_command(0x08, 0x00)
            return {"serial_number": "".join(f"{item:02X}" for item in data[:4])}
        @staticmethod
        def get_firmware_version(meter): return meter.send_command(0x08, 0x03)
        @staticmethod
        def get_transformation_ratios(meter): return meter.send_command(0x08, 0x02)
        @staticmethod
        def get_additional_timeout_multiplier(meter): return meter.send_command(0x08, 0x04)
        @staticmethod
        def get_main_timeout_multiplier(meter): return meter.send_command(0x08, 0x05)
    driver.commands = Commands
    return SimpleNamespace(mercury_v2=driver)


class FakeSession:
    imei = "123456789012345"
    def __init__(self, response=None): self.response, self.requests = response, []
    def ask_mercury(self, package, timeout):
        self.requests.append(package)
        if self.response is None: raise TimeoutError
        return self.response


class Registry:
    def __init__(self, session=None): self.session = session
    def get(self, imei): return self.session if self.session and imei == self.session.imei else None


def test_registry_covers_safe_v2_commands():
    assert COMMANDS["serial_and_manufacture"].available
    assert COMMANDS["passport"].available is False
    assert all(item.mode == "read" and not item.dangerous for item in COMMANDS.values())


def test_result_normalizer_handles_protocol_types():
    from datetime import date
    from decimal import Decimal
    assert normalize_result({"number": Decimal("1.20"), "day": date(2026, 9, 22), "raw": b"\x01\xff"}) == {
        "number": "1.20", "day": "2026-09-22", "raw": "01 FF"}


def test_manager_uses_existing_session_and_exact_known_tx():
    session = FakeSession(add_crc(bytes.fromhex("01 12 34 56 78")))
    result = MercurySessionManager(Registry(session), fake_mercury_module).execute(session.imei, 1, "serial_and_manufacture")
    assert session.requests == [bytes.fromhex("01 08 00 27 C0")]
    assert result["data"]["serial_number"] == "12345678"


def test_manager_rejects_offline_timeout_then_recovers():
    with pytest.raises(MercuryGatewayError) as offline:
        MercurySessionManager(Registry(), fake_mercury_module).execute("123456789012345", 1, "firmware_version")
    assert offline.value.code == "DEVICE_OFFLINE"
    session = FakeSession(); manager = MercurySessionManager(Registry(session), fake_mercury_module)
    with pytest.raises(MercuryGatewayError) as timeout: manager.execute(session.imei, 1, "firmware_version")
    assert timeout.value.code == "MERCURY_TIMEOUT"
    session.response = add_crc(bytes.fromhex("01 01 02 03"))
    assert manager.execute(session.imei, 1, "firmware_version")["success"]


def test_wrong_address_and_crc_are_rejected():
    for response, code in ((bytes.fromhex("01 01 02 00 00"), "CRC_ERROR"), (add_crc(bytes.fromhex("02 01")), "WRONG_ADDRESS")):
        manager = MercurySessionManager(Registry(FakeSession(response)), fake_mercury_module)
        with pytest.raises(MercuryGatewayError) as error: manager.execute("123456789012345", 1, "firmware_version")
        assert error.value.code == code


def test_web_devices_derive_from_gateway_and_command_targets_imei(app, admin_client, monkeypatch):
    live = {"imei": "123456789012345", "ip": "127.0.0.1", "port": 4567, "online": True, "dev": "ATM21",
            "ver": "01", "rev": "04", "bld": "024.254", "csq": "16", "int": "485+232",
            "connected_at": "2026-09-22T10:00:00+00:00", "last_seen_at": "2026-09-22T10:01:00+00:00"}
    calls = []
    def gateway(path, **kwargs):
        calls.append((path, kwargs.get("payload")))
        if path == "/devices": return [live]
        return {"success": True, "command": "firmware_version", "duration_ms": 12, "data": "1.2.3", "tx_raw": "01 08", "rx_raw": "01 02"}
    monkeypatch.setattr(service, "_gateway_request", gateway)
    item = admin_client.get("/irz/api/mercury/devices").get_json()[0]
    assert item["imei"] == live["imei"] and item["online"] is True and item["csq"] == 16
    assert item["network_address"] == 0
    response = admin_client.post(f"/irz/api/mercury/devices/{item['id']}/commands/firmware_version", json={})
    assert response.status_code == 200
    assert calls[-1][1]["imei"] == live["imei"] and "host" not in calls[-1][1]
    assert calls[-1][1]["network_address"] == 0
    with app.app_context():
        assert db.session.scalar(db.select(IRZOperationLog)).status == "SUCCESS"
        device = db.session.scalar(db.select(IRZDevice).where(IRZDevice.imei == live["imei"]))
        assert device.last_firmware_version == "1.2.3"
        assert device.last_mercury_seen_at is not None
    refreshed = admin_client.get("/irz/api/mercury/devices").get_json()[0]
    assert refreshed["mercury_responding"] is True
    assert refreshed["last_values"]["firmware_version"] == "1.2.3"


def test_irz_and_discovered_meter_can_be_renamed(app, admin_client):
    with app.app_context():
        device = IRZDevice(imei="123456789012345", name="ATM21 123456789012345", model="ATM21", enabled=True)
        db.session.add(device); db.session.flush()
        db.session.commit()
        service._store_operation(device, None, "serial_and_manufacture", "COMMAND", result={
            "data": {"serial_number": 36790160, "date_of_manufacture": "2019-02-10"},
            "duration_ms": 1200, "tx_raw": "00 08 00 76 00", "rx_raw": "00 24 4F 01 3C 0A 02 13 7B 09",
        })
        meter = db.session.scalar(db.select(IRZMeter).where(IRZMeter.serial_number == "36790160"))
        assert meter is not None
        device_id = str(device.id)
    response = admin_client.patch(f"/irz/api/mercury/devices/{device_id}/identity", json={"name": "Котельная №3"})
    assert response.status_code == 200
    assert response.get_json()["name"] == "Котельная №3"
    response = admin_client.patch(f"/irz/api/mercury/devices/{device_id}/meter",
                                  json={"custom_name": "Главный ввод", "model": "Mercury 230 ART"})
    assert response.status_code == 200
    assert response.get_json()["display_name"] == "Главный ввод"
    assert response.get_json()["model_source"] == "MANUAL"


def test_poll_creates_one_logical_snapshot_for_discovered_meter(app, monkeypatch):
    with app.app_context():
        device = IRZDevice(imei="123456789012345", name="ATM21", model="ATM21", enabled=True, network_address=0)
        db.session.add(device); db.session.flush()
        meter = IRZMeter(irz_device_id=device.id, serial_number="36790160")
        db.session.add(meter); db.session.commit()
        monkeypatch.setattr(service, "_gateway_request", lambda *args, **kwargs: {
            "success": True, "partial": False,
            "results": {"firmware_version": {"data": "2.3.5", "duration_ms": 10, "tx_raw": "00", "rx_raw": "00"}},
            "errors": [],
        })
        service.poll_device(device, user_id=None)
        snapshots = list(db.session.scalars(db.select(IRZMeterSnapshot)))
        assert len(snapshots) == 1
        assert snapshots[0].meter_id == meter.id
        assert snapshots[0].quality == "GOOD"
        assert snapshots[0].values == {"firmware_version": "2.3.5"}


def test_manual_mercury_crud_is_not_exposed(admin_client):
    assert admin_client.post("/irz/api/mercury/devices", json={}).status_code == 405


@pytest.mark.parametrize("result,partial", [
    ({"success": True, "partial": True, "results": {"firmware_version": {"data": "2.3.5", "duration_ms": 596, "tx_raw": "00 08 03 36 01", "rx_raw": "00 02 03 05 61 17"}},
      "errors": [{"command": "main_timeout_multiplier", "error_code": "MERCURY_TIMEOUT", "message": "Mercury не ответил за 5 секунд", "duration_ms": 5000, "tx_raw": "00 08 1D", "rx_raw": ""}]}, True),
    ({"success": False, "partial": False, "results": {}, "errors": [{"command": "firmware_version", "error_code": "MERCURY_TIMEOUT", "message": "Mercury не ответил за 5 секунд"}]}, False),
])
def test_poll_persists_each_result_and_survives_individual_errors(app, admin_client, monkeypatch, result, partial):
    live = {"imei": "123456789012345", "ip": "127.0.0.1", "port": 5009, "connected_at": "2026-09-22T10:00:00+00:00", "last_seen_at": "2026-09-22T10:01:00+00:00"}
    monkeypatch.setattr(service, "_gateway_request", lambda path, **kwargs: [live] if path == "/devices" else result)
    device = admin_client.get("/irz/api/mercury/devices").get_json()[0]
    response = admin_client.post(f"/irz/api/mercury/devices/{device['id']}/poll", json={})
    assert response.status_code == 200 and response.get_json()["partial"] is partial
    with app.app_context():
        stored = db.session.get(IRZDevice, device["id"])
        assert stored.last_polled_at is not None
        if result["results"]:
            assert stored.last_firmware_version == "2.3.5"
        assert db.session.scalar(db.select(db.func.count(IRZOperationLog.id))) == len(result["results"]) + len(result["errors"])
