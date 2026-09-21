import http.client
import json
import socket
import threading
import time

from app.modem_gateway.sniffer import create_servers, format_chunk


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


def test_protocol_test_waits_for_next_device_response():
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
        client.sendall(b"AT$IMEI=123456789012345,TYP=ATM,DEV=ATM21")
        _wait_for_device(http_server.server_address[1], "123456789012345")
        request_thread = threading.Thread(
            target=lambda: result.append(
                _request(
                    http_server.server_address[1],
                    "POST",
                    "/test-command",
                    {"imei": "123456789012345", "hex": "01 03 00 00"},
                )
            )
        )
        request_thread.start()
        assert client.recv(4) == bytes.fromhex("01 03 00 00")
        client.sendall(bytes.fromhex("01 03 02 12 34 B5 33"))
        request_thread.join(timeout=2)
        assert result == [
            (
                200,
                {
                    "status": "response",
                    "imei": "123456789012345",
                    "bytes": 4,
                    "response_hex": "01 03 02 12 34 B5 33",
                    "response_ascii": "....4.3",
                    "success": True,
                },
            )
        ]
    finally:
        client.close()
        tcp_server.shutdown()
        http_server.shutdown()
        tcp_server.server_close()
        http_server.server_close()
        for thread in threads:
            thread.join(timeout=2)
