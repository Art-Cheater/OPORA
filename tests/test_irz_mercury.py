import threading
import time
import socketserver
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models.irz import IRZDevice, IRZOperationLog
from app.modem_gateway.mercury import MercuryConnectionManager, MercuryGatewayError
from app.modules.irz import service
from app.modules.irz.commands import COMMANDS, normalize_result


class FakeTransport:
    active = 0
    max_active = 0
    lock = threading.Lock()
    fail = False

    def __init__(self, *args, **kwargs):
        self.port = str(args[0])
        self.closed = False

    def ask(self, request):
        from modbus_crc import add_crc

        with self.lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            time.sleep(0.03)
            if type(self).fail:
                return None
            command = request[1]
            data = bytes.fromhex("01 02 03") if command == 0x03 else bytes.fromhex("12 34 56 78 01 02 23")
            return add_crc(bytes((request[0],)) + data)
        finally:
            with self.lock:
                type(self).active -= 1

    def close(self):
        self.closed = True


def fake_mercury_module():
    def prepare_address(value):
        return value % 1000

    driver = SimpleNamespace(
        prepare_address=prepare_address,
        format_address=lambda value: bytes((value,)),
        extract_address=lambda package: package[0],
        extract_data=lambda package: list(package[1:-2]),
    )

    class Commands:
        @staticmethod
        def get_serial_number_and_date_of_manufacture(meter):
            data = meter.send_command(0x08, 0x00)
            return {"serial_number": int("".join(f"{item:02d}" for item in data[:4])), "date_of_manufacture": "2023-02-01"}

        @staticmethod
        def get_firmware_version(meter):
            return ".".join(str(item) for item in meter.send_command(0x08, 0x03))

        @staticmethod
        def get_transformation_ratios(meter):
            return {"voltage": 1, "current": 1}

        @staticmethod
        def get_additional_timeout_multiplier(meter):
            return 1

        @staticmethod
        def get_main_timeout_multiplier(meter):
            return 1

    driver.commands = Commands
    return SimpleNamespace(SerialDataTransport=FakeTransport, TcpDataTransport=FakeTransport, mercury_v2=driver)


def fake_manager():
    return MercuryConnectionManager(fake_mercury_module, lambda _module, _kind, signature, _config: FakeTransport(signature[2]))


def test_registry_covers_every_mercury_v2_function_and_marks_library_defects():
    assert {item.mercury_command for item in COMMANDS.values()} == {
        "get_serial_number_and_date_of_manufacture", "get_passport", "get_transformation_ratios",
        "get_firmware_version", "get_additional_timeout_multiplier", "get_main_timeout_multiplier", "get_info",
    }
    assert COMMANDS["passport"].available is False
    assert COMMANDS["device_info"].available is False
    assert all(item.mode == "read" and not item.dangerous for item in COMMANDS.values())


def test_result_normalizer_handles_protocol_types():
    from datetime import date
    from decimal import Decimal

    assert normalize_result({"number": Decimal("1.20"), "day": date(2026, 9, 22), "raw": b"\x01\xff"}) == {
        "number": "1.20", "day": "2026-09-22", "raw": "01 FF"
    }


def test_manager_connect_execute_disconnect_and_rejects_arbitrary_method():
    manager = fake_manager()
    config = {"transport_type": "TCP", "host": "127.0.0.1", "port": 5001, "network_address": 1}
    assert manager.connect("one", config)["state"] == "CONNECTED"
    result = manager.execute("one", "firmware_version")
    assert result["success"] is True
    assert result["tx_raw"] and result["rx_raw"]
    with pytest.raises(MercuryGatewayError) as unknown:
        manager.execute("one", "__dict__")
    assert unknown.value.code == "INVALID_COMMAND"
    assert manager.disconnect("one")["state"] == "DISCONNECTED"


def test_real_mercury_base_tcp_command_path():
    from modbus_crc import add_crc

    class MercuryHandler(socketserver.BaseRequestHandler):
        def handle(self):
            request = self.request.recv(1024)
            self.request.sendall(add_crc(bytes((request[0], 1, 6, 2))))

    server = socketserver.TCPServer(("127.0.0.1", 0), MercuryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    manager = MercuryConnectionManager()
    try:
        manager.connect("real", {"transport_type": "TCP", "host": "127.0.0.1", "port": server.server_address[1], "network_address": 1})
        result = manager.execute("real", "firmware_version")
        assert result["data"] == "1.6.2"
        assert result["tx_raw"] and result["rx_raw"]
        manager.disconnect("real")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_physical_bus_operations_are_serialized_and_lock_recovers_after_timeout():
    FakeTransport.max_active = 0
    manager = fake_manager()
    config = {"transport_type": "SERIAL", "serial_port": "COM7", "baudrate": 9600, "network_address": 1}
    manager.connect("one", config)
    manager.connect("two", {**config, "network_address": 2})
    threads = [threading.Thread(target=manager.execute, args=(device, "firmware_version")) for device in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert FakeTransport.max_active == 1

    FakeTransport.fail = True
    with pytest.raises(MercuryGatewayError) as timeout:
        manager.execute("one", "firmware_version")
    assert timeout.value.code == "MERCURY_TIMEOUT"
    FakeTransport.fail = False
    assert manager.execute("two", "firmware_version")["success"] is True


def _device(user_id):
    return IRZDevice(
        name="Меркурий 230", model="230", network_address=1, transport_type="TCP",
        host="127.0.0.1", port=5001, baudrate=9600, enabled=True,
        created_by=user_id, updated_by=user_id,
    )


def test_mercury_api_crud_command_and_journal(app, admin_client, monkeypatch):
    created = admin_client.post("/irz/api/mercury/devices", json={
        "name": "Меркурий 230", "model": "230", "network_address": 1,
        "transport_type": "TCP", "host": "127.0.0.1", "port": 5001, "timeout": 2,
    })
    assert created.status_code == 201
    device_id = created.get_json()["id"]
    assert admin_client.get("/irz/api/mercury/devices").get_json()[0]["name"] == "Меркурий 230"

    monkeypatch.setattr(service, "_gateway_request", lambda *args, **kwargs: {
        "success": True, "command": "firmware_version", "mercury_command": "get_firmware_version",
        "device_id": device_id, "duration_ms": 12, "data": "1.2.3", "tx_raw": "01 08", "rx_raw": "01 02", "timestamp": 1,
    })
    response = admin_client.post(f"/irz/api/mercury/devices/{device_id}/commands/firmware_version", json={})
    assert response.status_code == 200
    with app.app_context():
        log = db.session.scalar(db.select(IRZOperationLog))
        assert log.status == "SUCCESS"
        assert log.duration_ms == 12
        assert log.tx_raw == "01 08"


def test_mercury_api_rejects_special_method(app, admin_client):
    with app.app_context():
        user_id = db.session.scalar(db.select(IRZDevice.created_by).limit(1))
        if user_id is None:
            from app.models.auth.user import User
            user_id = db.session.scalar(db.select(User.id).limit(1))
        device = _device(user_id)
        db.session.add(device)
        db.session.commit()
        device_id = str(device.id)
    response = admin_client.post(f"/irz/api/mercury/devices/{device_id}/commands/__class__", json={})
    assert response.status_code == 404
    assert response.get_json()["error_code"] == "INVALID_COMMAND"


def test_timeout_is_logged_with_user_duration_and_raw(app, admin_client, monkeypatch):
    with app.app_context():
        from app.models.auth.user import User
        user_id = db.session.scalar(db.select(User.id).limit(1))
        device = _device(user_id)
        db.session.add(device)
        db.session.commit()
        device_id = str(device.id)
    monkeypatch.setattr(service, "_gateway_request", lambda *args, **kwargs: (_ for _ in ()).throw(
        service.GatewayResponseError("Истёк тайм-аут", 504, "MERCURY_TIMEOUT", {"duration_ms": 1001, "tx_raw": "01 08", "rx_raw": ""})
    ))
    response = admin_client.post(f"/irz/api/mercury/devices/{device_id}/commands/firmware_version", json={})
    assert response.status_code == 504
    with app.app_context():
        log = db.session.scalar(db.select(IRZOperationLog))
        assert (log.status, log.error_code, log.duration_ms, log.tx_raw) == ("TIMEOUT", "MERCURY_TIMEOUT", 1001, "01 08")
        assert log.user_id is not None
