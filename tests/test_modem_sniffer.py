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
    tcp_server, http_server = create_servers("127.0.0.1", 0, 0)
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
        assert devices == [{"imei": "123456789012345", "ip": "127.0.0.1", "port": client.getsockname()[1]}]

        assert _request(http_port, "POST", "/send", {"imei": "123456789012345", "hex": "01 02 FF"}) == (
            200,
            {"status": "sent", "imei": "123456789012345", "bytes": 3},
        )
        assert client.recv(3) == bytes((0x01, 0x02, 0xFF))

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
