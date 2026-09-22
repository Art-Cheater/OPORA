import http.client
import json
import logging
import socket
import threading
import time

import pytest

from app.modem_gateway.sniffer import HEARTBEAT, ConnectionRegistry, DeviceConnection, create_servers, format_chunk, parse_identification, utcnow
from modbus_crc import add_crc


def _request(port, method, path, payload=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    body = json.dumps(payload) if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


def _wait_for_device(http_port, imei):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status, devices = _request(http_port, "GET", "/devices")
        if status == 200 and any(device["imei"] == imei for device in devices):
            return devices
        time.sleep(0.01)
    raise AssertionError("device was not registered")


def test_modem_sniffer_control_api_integration():
    exchanges = []
    tcp_server, http_server = create_servers("127.0.0.1", 0, 0, lambda imei, direction, data: exchanges.append((imei, direction, data)))
    threads = [
        threading.Thread(target=tcp_server.serve_forever, daemon=True),
        threading.Thread(target=http_server.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    tcp_port = tcp_server.server_address[1]
    http_port = http_server.server_address[1]
    client = socket.create_connection(("127.0.0.1", tcp_port), timeout=2)
    try:
        assert _request(http_port, "GET", "/health") == (200, {"status": "ok"})
        client.sendall(b"AT$IMEI=123456789012345,TYP=ATM,DEV=ATM21")
        devices = _wait_for_device(http_port, "123456789012345")
        assert len(devices) == 1
        assert devices[0]["imei"] == "123456789012345"
        assert devices[0]["ip"] == "127.0.0.1"
        assert devices[0]["port"] == client.getsockname()[1]
        assert devices[0]["last_seen_at"]

        assert _request(http_port, "POST", "/send", {"imei": "123456789012345", "hex": "01 02 FF"}) == (
            200,
            {"status": "sent", "imei": "123456789012345", "bytes": 3},
        )
        assert client.recv(3) == bytes((0x01, 0x02, 0xFF))
        assert ("123456789012345", "RX", b"AT$IMEI=123456789012345,TYP=ATM,DEV=ATM21") in exchanges
        assert ("123456789012345", "TX", bytes((0x01, 0x02, 0xFF))) in exchanges

        status, payload = _request(http_port, "POST", "/send", {"imei": "123456789012345", "hex": "01 ZZ"})
        assert status == 400
        assert payload == {"error": "invalid request"}
        client.shutdown(socket.SHUT_RDWR)
        client.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if _request(http_port, "GET", "/devices") == (200, []):
                break
            time.sleep(0.01)
        else:
            raise AssertionError("device was not removed after disconnect")
    finally:
        client.close()
        tcp_server.shutdown()
        http_server.shutdown()
        tcp_server.server_close()
        http_server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_raw_tcp_sniffer_formats_bytes():
    rendered = format_chunk(bytes([1, 2, 3, 4]), imei="123456789012345")
    assert "IRZ RX" in rendered
    assert "IMEI=123456789012345" in rendered
    assert "LEN=4" in rendered
    assert "HEX=01 02 03 04" in rendered


def test_real_session_fixture_identification_and_heartbeat_are_classified():
    import csv
    from pathlib import Path
    rows = list(csv.DictReader((Path(__file__).parent / "fixtures" / "irz_atm21_session.csv").open(encoding="utf-8")))
    identification = bytes.fromhex(rows[0]["hex"])
    metadata = parse_identification(identification[:18] + identification[18:])
    assert metadata == {"imei": "868441036775234", "typ": "ATM", "dev": "ATM21", "ver": "01", "rev": "04",
                        "bld": "024.254", "hdw": "2.0", "sim": "0", "csq": "16", "atp": "1.2", "int": "485+232"}
    assert bytes.fromhex(rows[1]["hex"]) == HEARTBEAT
    assert bytes.fromhex(rows[2]["hex"]) == bytes.fromhex("01 08 00 27 C0")


def test_registry_supports_two_sessions_and_reconnect_same_imei():
    class Sock:
        def __init__(self): self.shutdown_called = False
        def shutdown(self, _how): self.shutdown_called = True
    registry = ConnectionRegistry(); now = utcnow()
    first = DeviceConnection("111111111111111", "1.1.1.1", 1, now, now, Sock())
    second = DeviceConnection("222222222222222", "2.2.2.2", 2, now, now, Sock())
    replacement = DeviceConnection(first.imei, "3.3.3.3", 3, now, now, Sock())
    registry.register(first); registry.register(second)
    assert {item["imei"] for item in registry.devices()} == {first.imei, second.imei}
    registry.register(replacement)
    assert registry.get(first.imei) is replacement and first.socket.shutdown_called
    registry.remove(first)
    assert registry.get(first.imei) is replacement


def test_pending_lock_is_released_after_timeout_and_next_command_works():
    server_socket, client_socket = socket.socketpair()
    now = utcnow()
    session = DeviceConnection("123456789012345", "127.0.0.1", 1, now, now, server_socket)
    try:
        with pytest.raises(TimeoutError):
            session.ask_mercury(bytes.fromhex("01 08 00 27 C0"), 0.02)
        assert client_socket.recv(5) == bytes.fromhex("01 08 00 27 C0")
        result = []
        thread = threading.Thread(target=lambda: result.append(session.ask_mercury(bytes.fromhex("01 08 00 27 C0"), 1)))
        thread.start(); assert client_socket.recv(5) == bytes.fromhex("01 08 00 27 C0")
        response = add_crc(bytes.fromhex("01 12 34"))
        session.feed_mercury_candidate(response)
        thread.join(1)
        assert result == [response]
    finally:
        server_socket.close(); client_socket.close()


def test_inbound_session_mercury_acceptance_with_fragmentation_and_heartbeat():
    tcp_server, http_server = create_servers("127.0.0.1", 0, 0)
    threads = [
        threading.Thread(target=tcp_server.serve_forever, daemon=True),
        threading.Thread(target=http_server.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    client = socket.create_connection(("127.0.0.1", tcp_server.server_address[1]), timeout=2)
    result = []
    try:
        client.sendall(b"AT$IMEI=1234567")
        client.sendall(b"89012345,PSW=***,TYP=ATM,DEV=ATM21,VER=01,REV=04,BLD=024.254,HDW=2.0,SIM=0,CSQ=16,ATP=1.2,INT=485+232,")
        devices = _wait_for_device(http_server.server_address[1], "123456789012345")
        assert devices[0]["dev"] == "ATM21"
        assert devices[0]["csq"] == "16"
        request_thread = threading.Thread(
            target=lambda: result.append(
                _request(
                    http_server.server_address[1],
                    "POST",
                    "/mercury/command",
                    {"imei": "123456789012345", "network_address": 0, "command_id": "serial_and_manufacture"},
                )
            )
        )
        request_thread.start()
        assert client.recv(5) == bytes.fromhex("00 08 00 76 00")
        client.sendall(bytes.fromhex("B5 BC BD BE BF"))
        response = bytes.fromhex("00 24 4F 01 3C 0A 02 13 7B 09")
        client.sendall(response[:3])
        client.sendall(response[3:] + bytes.fromhex("B5 BC BD BE BF"))
        request_thread.join(timeout=2)
        assert result[0][0] == 200
        assert result[0][1]["data"] == {"serial_number": 36790160, "date_of_manufacture": "2019-02-10"}

        firmware_result = []
        firmware_thread = threading.Thread(target=lambda: firmware_result.append(_request(
            http_server.server_address[1], "POST", "/mercury/command",
            {"imei": "123456789012345", "network_address": 0, "command_id": "firmware_version"})))
        firmware_thread.start()
        assert client.recv(5) == bytes.fromhex("00 08 03 36 01")
        client.sendall(bytes.fromhex("00 02 03 05 61 17"))
        firmware_thread.join(timeout=2)
        assert firmware_result[0][1]["data"] == "2.3.5"
        client.shutdown(socket.SHUT_RDWR)
        client.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and _request(http_server.server_address[1], "GET", "/devices")[1]:
            time.sleep(0.01)
        assert _request(http_server.server_address[1], "GET", "/devices") == (200, [])
    finally:
        client.close()
        tcp_server.shutdown()
        http_server.shutdown()
        tcp_server.server_close()
        http_server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_client_reader_stays_alive_after_mercury_timeout(caplog):
    """The handler remains the sole reader and a command timeout must not close it."""
    exchanges = []
    tcp_server, http_server = create_servers(
        "127.0.0.1",
        0,
        0,
        lambda imei, direction, data, packet_type=None: exchanges.append(
            (imei, direction, data, packet_type)
        ),
    )
    threads = [
        threading.Thread(target=tcp_server.serve_forever, daemon=True),
        threading.Thread(target=http_server.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    client = socket.create_connection(("127.0.0.1", tcp_server.server_address[1]), timeout=2)
    imei = "123456789012345"
    try:
        with caplog.at_level(logging.INFO, logger="opora.modem_sniffer"):
            client.sendall(f"AT$IMEI={imei},TYP=ATM,DEV=ATM21,".encode())
            _wait_for_device(http_server.server_address[1], imei)
            session = tcp_server.registry.get(imei)
            assert session is not None

            timed_out = []
            command_thread = threading.Thread(
                target=lambda: _capture_timeout(
                    timed_out,
                    session,
                    bytes.fromhex("00 08 03 36 01"),
                )
            )
            command_thread.start()
            assert client.recv(5) == bytes.fromhex("00 08 03 36 01")
            command_thread.join(timeout=1)
            assert timed_out == [True]

            client.sendall(HEARTBEAT)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(item[3] == "ATM21_HEARTBEAT" for item in exchanges):
                    break
                time.sleep(0.01)
            assert any(item[3] == "ATM21_HEARTBEAT" for item in exchanges)
            assert any(item["imei"] == imei for item in tcp_server.registry.devices())

        messages = [record.getMessage() for record in caplog.records]
        assert any("CLIENT HANDLER START" in message for message in messages)
        assert any("RECV bytes=" in message for message in messages)
        assert any("IDENTIFICATION DETECTED" in message for message in messages)
        assert any("IMEI REGISTERED" in message for message in messages)
    finally:
        client.close()
        tcp_server.shutdown()
        http_server.shutdown()
        tcp_server.server_close()
        http_server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def _capture_timeout(result, session, package):
    try:
        session.ask_mercury(package, 0.05)
    except TimeoutError:
        result.append(True)
