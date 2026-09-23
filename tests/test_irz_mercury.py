from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from modbus_crc import add_crc

from app.extensions import db
from app.models.irz import IRZOperationLog
from app.models.irz import IRZDevice, IRZMeter, IRZMeterSnapshot
from app.modem_gateway.mercury import MercuryGatewayError, MercurySessionManager
from app.modules.irz import service
from app.modules.irz.scheduler import schedule_offsets
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
    def ask_mercury(self, package, timeout, expected_length=None, log_package=None):
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


def test_command_results_are_mapped_to_monitoring_keys_without_losing_zero():
    values = service.normalize_poll_values({"results": {
        "voltage_phases": {"data": {"a": "231.83", "b": "239.41", "c": "234.29"}},
        "current_phases": {"data": {"a": 0, "b": "0", "c": "1.25"}},
        "active_power": {"data": {"total": "3.52", "a": "3.52"}},
        "reactive_power": {"data": {"a": "6.86"}},
        "power_factor": {"data": {"a": "0.000"}},
        "frequency": {"data": {"value": "49.99"}},
        "phase_angles": {"data": {"ab": "120", "ac": "240", "bc": "120"}},
        "energy_current": {"data": {"a_plus": 13868, "a_minus": None, "r_plus": 1839, "r_minus": 0}},
        "meter_time": {"data": {"value": "2026-09-23T12:00:00", "season": "summer"}},
    }})
    assert values["u_a"] == 231.83 and values["u_c"] == 234.29
    assert values["i_a"] == 0 and values["i_b"] == 0 and values["i_c"] == 1.25
    assert values["p_total"] == 3.52 and values["q_a"] == 6.86
    assert values["cos_phi_a"] == 0 and values["frequency"] == 49.99
    assert values["phase_angle_ab"] == 120 and values["phase_angle_ac"] == 240 and values["phase_angle_bc"] == 120
    assert values["energy_a_plus_total"] == 13868 and values["energy_a_minus_total"] is None
    assert values["energy_r_minus_total"] == 0
    assert values["meter_time"] == "2026-09-23T12:00:00" and isinstance(values["drift_seconds"], int)
    assert all(not isinstance(value, str) for key, value in values.items() if key[:2] in {"u_", "i_", "p_", "q_"})


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
        assert snapshots[0].values == {
            "commands": {"firmware_version": "2.3.5"}, "firmware_version": "2.3.5"
        }


def test_manual_mercury_crud_is_not_exposed(admin_client):
    assert admin_client.post("/irz/api/mercury/devices", json={}).status_code == 405


def test_monitoring_profile_latest_history_stale_and_delta(app, admin_client):
    with app.app_context():
        device = IRZDevice(imei="123456789012345", name="ТП-1", model="ATM21", enabled=True)
        db.session.add(device); db.session.flush()
        meter = IRZMeter(irz_device_id=device.id, serial_number="36790160")
        db.session.add(meter); db.session.flush()
        old = datetime.now(timezone.utc) - timedelta(minutes=20)
        db.session.add_all([
            IRZMeterSnapshot(meter_id=meter.id, captured_at=old - timedelta(minutes=10), values={"energy": 100}, quality="GOOD", source="AUTO", status="SUCCESS"),
            IRZMeterSnapshot(meter_id=meter.id, captured_at=old, values={"energy": 112.5}, quality="GOOD", source="MANUAL", status="SUCCESS"),
        ])
        db.session.commit()
    response = admin_client.patch("/irz/api/devices/123456789012345", json={
        "name": "Котельная", "latitude": 55.75, "longitude": 37.61, "address_text": "ул. Тестовая, 1"
    })
    assert response.status_code == 200
    payload = admin_client.get("/irz/api/devices/123456789012345").get_json()
    assert payload["name"] == "Котельная" and payload["location"]["latitude"] == 55.75
    assert payload["stale"] is True and payload["latest"]["delta"]["energy"] == 12.5
    history = admin_client.get("/irz/api/devices/123456789012345/snapshots?limit=20").get_json()
    assert [item["source"] for item in history] == ["MANUAL", "AUTO"]


def test_monitoring_rejects_invalid_coordinates(app, admin_client):
    with app.app_context():
        db.session.add(IRZDevice(imei="123456789012345", name="ATM21", model="ATM21", enabled=True)); db.session.commit()
    assert admin_client.patch("/irz/api/devices/123456789012345", json={"latitude": 91}).status_code == 400


def test_poll_lease_rejects_overlap_and_is_released_after_timeout(app, monkeypatch):
    with app.app_context():
        device = IRZDevice(imei="123456789012345", name="ATM21", model="ATM21", enabled=True,
                           poll_lock_until=datetime.now(timezone.utc) + timedelta(seconds=30))
        db.session.add(device); db.session.commit()
        with pytest.raises(ValueError, match="POLL_IN_PROGRESS"):
            service.poll_device(device, user_id=None)
        device.poll_lock_until = None; db.session.commit()
        monkeypatch.setattr(service, "_gateway_request", lambda *a, **k: (_ for _ in ()).throw(service.GatewayUnavailable("timeout")))
        with pytest.raises(service.GatewayUnavailable):
            service.poll_device(device, user_id=None)
        db.session.refresh(device)
        assert device.poll_lock_until is None


def test_six_hundred_devices_are_staggered_across_interval():
    offsets = schedule_offsets([f"{index:015d}" for index in range(600)], 600)
    assert sorted(offsets.values()) == list(range(600))


def test_poll_snapshot_latest_and_frontend_share_monitoring_schema(app, admin_client, monkeypatch):
    normalized = {
        "u_a": 231.83, "u_b": 239.41, "u_c": 234.29,
        "i_a": 0.03, "p_a": 3.52, "q_a": 6.86,
        "cos_phi_a": 0, "i_b": "0",
    }
    poll_result = {"success": True, "partial": False, "results": {}, "errors": [], "normalized": normalized}
    live = {"imei": "123456789012345", "ip": "127.0.0.1", "port": 5009}
    with app.app_context():
        device = IRZDevice(imei=live["imei"], name="ATM21", model="ATM21", enabled=True, network_address=0)
        db.session.add(device); db.session.flush()
        meter = IRZMeter(irz_device_id=device.id, serial_number="36790160")
        db.session.add(meter); db.session.commit()
    monkeypatch.setattr(service, "_gateway_request", lambda path, **kwargs: [live] if path == "/devices" else poll_result)
    response = admin_client.post(f"/irz/api/devices/{live['imei']}/poll", json={})
    assert response.status_code == 200
    assert response.get_json()["snapshot"]["values"] == normalized
    latest = admin_client.get(f"/irz/api/devices/{live['imei']}/latest")
    assert latest.status_code == 200
    assert latest.get_json()["values"] == normalized
    with app.app_context():
        snapshot = db.session.scalar(db.select(IRZMeterSnapshot))
        assert snapshot.values == normalized
        assert snapshot.status == "SUCCESS" and snapshot.source == "MANUAL"
    script = Path("app/static/js/irz.js").read_text(encoding="utf-8")
    for prefix in ("u", "i", "p", "q", "s", "cos_phi"):
        assert f"['{prefix}'" in script or f",'{prefix}'" in script
    assert "?? null" in script  # keeps numeric 0 and string "0" visible


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


def _energy(a_plus):
    return {"a_plus": a_plus, "a_minus": 0, "r_plus": 10, "r_minus": None}


def full_poll():
    return {"success": True, "partial": False, "errors": [], "results": {
        "serial_and_manufacture": {"data": {"serial_number": 36790160, "date_of_manufacture": "2019-02-10"}, "duration_ms": 300},
        "firmware_version": {"data": "2.3.5", "duration_ms": 280},
        "transformation_ratios": {"data": {"voltage": 1, "current": 1}},
        "voltage_phases": {"data": {"a": "230.1", "b": "229.5", "c": "231"}},
        "current_phases": {"data": {"a": "1.234", "b": "0", "c": "0.5"}},
        "frequency": {"data": {"value": "49.99"}},
        "active_power": {"data": {"total": "350.5", "a": "200", "b": "0", "c": "150.5"}},
        "reactive_power": {"data": {"total": "-10", "a": "-10", "b": "0", "c": "0"}},
        "apparent_power": {"data": {"total": "360", "a": "210", "b": "0", "c": "150"}},
        "power_factor": {"data": {"total": "0.97", "a": "0.95", "b": "0", "c": "1"}},
        "phase_angles": {"data": {"ab": "120", "ac": "240", "bc": "120"}},
        "energy_current": {"data": {"a_plus": 13868, "a_minus": None, "r_plus": 1839, "r_minus": 0}},
        "energy_tariffs": {"data": {"t1": _energy(10000), "t2": _energy(3868), "t3": None, "t4": _energy(0)}},
        "meter_time": {"data": {"value": "2026-09-23T15:00:30", "weekday": 3, "season": "winter"},
                       "received_at": "2026-09-23T12:00:00+00:00"},
        "status_word": {"data": {"raw": "00 00 00 00 01 00", "ok": False, "errors": [{"code": "E-01", "text": "Напряжение батареи"}]}},
    }}


def failed_poll(code="MERCURY_TIMEOUT", commands=None):
    from app.modules.irz.commands import poll_commands
    ids = commands or [command.id for command in poll_commands()]
    return {"success": False, "partial": False, "results": {},
            "errors": [{"command": command_id, "error_code": code, "message": "Mercury не ответил"} for command_id in ids]}


def test_full_poll_produces_every_canonical_key():
    values = service.normalize_poll_values(full_poll())
    for prefix in ("p", "q", "s", "cos_phi"):
        assert all(f"{prefix}_{phase}" in values for phase in ("a", "b", "c", "total"))
    assert all(f"{prefix}_{phase}" in values for prefix in ("u", "i") for phase in ("a", "b", "c"))
    assert values["q_total"] == -10 and values["p_b"] == 0 and values["cos_phi_c"] == 1
    assert values["energy_a_plus_total"] == 13868 and values["energy_a_plus_t1"] == 10000
    assert values["energy_a_plus_t3"] is None and values["energy_r_minus_t1"] is None
    assert values["drift_seconds"] == 30
    assert values["diagnostics"][0]["code"] == "E-01" and values["diagnostics_ok"] is False
    assert values["transformation_current"] == 1 and values["serial_number"] == 36790160


def _device(app, **kwargs):
    device = IRZDevice(imei="123456789012345", name="ТП-1", model="ATM21", enabled=True, network_address=0, **kwargs)
    db.session.add(device); db.session.commit()
    return device


def test_auto_poll_discovers_meter_and_failed_poll_keeps_values_as_stale(app, monkeypatch):
    with app.app_context():
        device = _device(app)
        responses = [full_poll(), failed_poll()]
        monkeypatch.setattr(service, "_gateway_request", lambda *a, **k: responses.pop(0))
        result = service.poll_device(device, user_id=None, source="AUTO", log_operations=False)
        assert result["quality"] == "GOOD"
        meter = db.session.scalar(db.select(IRZMeter))
        assert meter is not None and meter.serial_number == "36790160" and meter.firmware_version == "2.3.5"
        assert device.last_success_at is not None
        service.poll_device(device, user_id=None, source="AUTO", log_operations=False)
        snapshots = list(db.session.scalars(db.select(IRZMeterSnapshot).order_by(IRZMeterSnapshot.captured_at)))
        assert [(item.status, item.quality, item.source) for item in snapshots] == [("SUCCESS", "GOOD", "AUTO"), ("ERROR", "STALE", "AUTO")]
        current = service.serialize_current(meter)
        assert current["values"]["u_a"] == 230.1 and current["values"]["i_b"] == 0
        assert current["quality"]["u_a"] == "STALE" and current["quality"]["energy_a_plus_t1"] == "STALE"
        payload = service.serialize_device(device)
        assert payload["data_state"] == "STALE" and payload["current"]["values"]["p_total"] == 350.5
        assert db.session.scalar(db.select(db.func.count(IRZOperationLog.id))) == 0


def test_partial_poll_marks_only_failed_fields_stale(app, monkeypatch):
    with app.app_context():
        device = _device(app)
        partial = full_poll()
        partial["results"] = {key: value for key, value in partial["results"].items() if key != "current_phases"}
        partial["results"]["voltage_phases"] = {"data": {"a": "225", "b": "226", "c": "227"}}
        partial.update(partial=True, errors=[{"command": "current_phases", "error_code": "CRC_ERROR", "message": "CRC"}])
        responses = [full_poll(), partial]
        monkeypatch.setattr(service, "_gateway_request", lambda *a, **k: responses.pop(0))
        service.poll_device(device, user_id=None, source="AUTO", log_operations=False)
        result = service.poll_device(device, user_id=None, source="MANUAL", log_operations=False)
        assert result["quality"] == "PARTIAL" and result["snapshot"]["status"] == "PARTIAL"
        current = service.serialize_current(db.session.scalar(db.select(IRZMeter)))
        assert current["values"]["u_a"] == 225 and current["quality"]["u_a"] == "GOOD"
        assert current["values"]["i_a"] == 1.234 and current["quality"]["i_a"] == "STALE"


def test_unreachable_gateway_still_records_the_poll(app, monkeypatch):
    with app.app_context():
        device = _device(app)
        monkeypatch.setattr(service, "_gateway_request", lambda *a, **k: full_poll())
        service.poll_device(device, user_id=None)
        monkeypatch.setattr(service, "_gateway_request", lambda *a, **k: (_ for _ in ()).throw(service.GatewayUnavailable("down")))
        with pytest.raises(service.GatewayUnavailable):
            service.poll_device(device, user_id=None)
        meter = db.session.scalar(db.select(IRZMeter))
        assert meter.last_poll_status == "ERROR"
        current = service.serialize_current(meter)
        assert current["values"]["frequency"] == 49.99 and current["quality"]["frequency"] == "STALE"
        assert db.session.scalar(db.select(db.func.count(IRZMeterSnapshot.id))) == 2


def test_poll_quality_classification():
    assert service.poll_quality(failed_poll("CRC_ERROR", ["voltage_phases"])) == "CRC_ERROR"
    assert service.poll_quality(failed_poll("UNSUPPORTED", ["frequency"])) == "UNSUPPORTED"
    assert service.poll_quality(failed_poll("UNKNOWN_RESPONSE_FORMAT", ["frequency"])) == "INVALID"
    assert service.poll_quality(failed_poll()) == "STALE"
    ok = full_poll(); ok["errors"] = [{"command": "energy_tariffs", "error_code": "UNSUPPORTED"}]
    assert service.poll_quality(ok) == "GOOD"


def test_scheduler_polls_each_device_once_per_slot(app, monkeypatch):
    from app.modules.irz import scheduler
    base = 1_800_000_000 - 1_800_000_000 % 600
    now = datetime.fromtimestamp(base + 100, timezone.utc)
    with app.app_context():
        first = IRZDevice(imei="100000000000001", name="A", model="ATM21", enabled=True)
        second = IRZDevice(imei="100000000000002", name="B", model="ATM21", enabled=True)
        offline = IRZDevice(imei="100000000000003", name="C", model="ATM21", enabled=True)
        db.session.add_all([first, second, offline]); db.session.commit()
        online = {first.imei, second.imei}
        assert {item.imei for item in scheduler.due_devices(now, online)} == online
        first.last_polled_at = second.last_polled_at = datetime.fromtimestamp(base - 250, timezone.utc)
        db.session.commit()
        assert [item.imei for item in scheduler.due_devices(now, online)] == [first.imei]
        polled = []
        monkeypatch.setattr(service, "get_devices", lambda: [{"imei": imei} for imei in online])
        monkeypatch.setattr(service, "poll_device", lambda device, **kwargs: polled.append((device.imei, kwargs["source"])))
        assert scheduler.run_once(now)["polled"] == 1
        assert polled == [(first.imei, "AUTO")]


def test_events_and_energy_archive_endpoints_are_read_only_and_validated(app, admin_client, monkeypatch):
    with app.app_context():
        _device(app)
    calls = []
    def gateway(path, **kwargs):
        calls.append((path, kwargs.get("payload"), kwargs.get("timeout")))
        return {"success": True, "data": {"journals": []}, "duration_ms": 10}
    monkeypatch.setattr(service, "_gateway_request", gateway)
    assert admin_client.post("/irz/api/devices/123456789012345/events", json={}).status_code == 200
    assert calls[-1][1]["command_id"] == "events" and calls[-1][2] == 90
    bad = admin_client.post("/irz/api/devices/123456789012345/energy-archive", json={"period": "week"})
    assert bad.status_code == 400 and bad.get_json()["error_code"] == "INVALID_PARAMETERS"
    assert admin_client.post("/irz/api/devices/123456789012345/energy-archive", json={"period": "month", "month": "x"}).status_code == 400
    ok = admin_client.post("/irz/api/devices/123456789012345/energy-archive", json={"period": "month", "month": 3, "tariff": 1})
    assert ok.status_code == 200
    assert calls[-1][1]["params"] == {"period": "month", "month": 3, "tariff": 1}


def test_frontend_contract_uses_canonical_keys_and_hides_only_missing_values():
    script = Path("app/static/js/irz.js").read_text(encoding="utf-8")
    template = Path("app/modules/irz/templates/irz/device.html").read_text(encoding="utf-8")
    values = service.normalize_poll_values(full_poll())
    for prefix in service.PHASE_PREFIXES.values():
        assert f"['{prefix}'," in script
    for key in ("frequency", "meter_time", "drift_seconds", "diagnostics", "transformation_voltage", "transformation_current"):
        assert key in values and key in script
    assert "phase_angle_${k}" in script and all(f"phase_angle_{k}" in values for k in ("ab", "ac", "bc"))
    assert "energy_${key}_${tariff}" in script
    assert all(f"['{tariff}'," in script for tariff in ("total", "t1", "t2", "t3", "t4"))
    assert "Number.isNaN" in script and "'—'" in script and "?? null" in script
    assert "setInterval" not in script and "location.reload" not in script
    for header in ("U, В", "I, А", "P, кВт", "Q, квар", "S, кВА", "cos φ", "Прочитать журналы"):
        assert header in template
    for forbidden in ("Protocol Lab", "PROTOCOL LAB", "HEX", "RAW", "Инженерный"):
        assert forbidden not in template
