"""ATM21 TCP sniffer with a small internal control API."""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import socketserver
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from app.modem_gateway.mercury import MercuryConnectionManager, MercuryGatewayError

LOG = logging.getLogger("opora.modem_sniffer")
IMEI_RE = re.compile(rb"AT\$IMEI=(\d{15})(?:,|\s|$)")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_chunk(data: bytes, ip: str = "", imei: str | None = None) -> str:
    """Format one received TCP chunk for stdout diagnostics."""
    del ip
    text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data)
    return f"IRZ RX\nIMEI={imei or '?'}\nLEN={len(data)}\nHEX={data.hex(' ').upper()}\nASCII={text}"


@dataclass(slots=True)
class DeviceConnection:
    imei: str
    remote_ip: str
    remote_port: int
    connected_at: datetime
    last_seen_at: datetime
    socket: socket.socket
    send_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    response_condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    response_sequence: int = field(default=0, repr=False)
    last_response: bytes | None = field(default=None, repr=False)

    def publish_response(self, data: bytes) -> None:
        with self.response_condition:
            self.last_response = data
            self.response_sequence += 1
            self.response_condition.notify_all()

    def wait_for_response(self, previous_sequence: int, timeout: float) -> bytes | None:
        deadline = time.monotonic() + timeout
        with self.response_condition:
            while self.response_sequence <= previous_sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.response_condition.wait(remaining)
            return self.last_response

    def public_dict(self) -> dict[str, Any]:
        return {
            "imei": self.imei,
            "ip": self.remote_ip,
            "port": self.remote_port,
            "last_seen_at": self.last_seen_at.isoformat(),
        }


class ConnectionRegistry:
    """Thread-safe registry of currently identified ATM21 connections."""

    def __init__(self) -> None:
        self._connections: dict[str, DeviceConnection] = {}
        self._lock = threading.RLock()

    def register(self, connection: DeviceConnection) -> None:
        with self._lock:
            self._connections[connection.imei] = connection

    def touch(self, connection: DeviceConnection) -> None:
        with self._lock:
            if self._connections.get(connection.imei) is connection:
                connection.last_seen_at = utcnow()

    def remove(self, connection: DeviceConnection) -> None:
        with self._lock:
            if self._connections.get(connection.imei) is connection:
                del self._connections[connection.imei]

    def get(self, imei: str) -> DeviceConnection | None:
        with self._lock:
            return self._connections.get(imei)

    def devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._connections[imei].public_dict() for imei in sorted(self._connections)]


class ModemTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], registry: ConnectionRegistry, log_exchange: Callable[[str | None, str, bytes], None] | None = None):
        self.registry = registry
        self.log_exchange = log_exchange
        super().__init__(address, ModemRequestHandler)


class ModemRequestHandler(socketserver.BaseRequestHandler):
    server: ModemTCPServer

    def handle(self) -> None:
        remote_ip, remote_port = self.client_address[:2]
        LOG.info("MODEM CONNECT IP=%s PORT=%s", remote_ip, remote_port)
        connection: DeviceConnection | None = None
        connected_at = utcnow()
        identification_buffer = b""
        try:
            while data := self.request.recv(4096):
                identification_buffer = (identification_buffer + data)[-8192:]
                if connection is None:
                    match = IMEI_RE.search(identification_buffer)
                    if match:
                        connection = DeviceConnection(
                            imei=match.group(1).decode("ascii"),
                            remote_ip=str(remote_ip),
                            remote_port=int(remote_port),
                            connected_at=connected_at,
                            last_seen_at=utcnow(),
                            socket=self.request,
                        )
                        self.server.registry.register(connection)
                else:
                    self.server.registry.touch(connection)
                if connection:
                    connection.publish_response(data)
                if self.server.log_exchange:
                    self.server.log_exchange(connection.imei if connection else None, "RX", data)
                LOG.info("%s", format_chunk(data, imei=connection.imei if connection else None))
        finally:
            if connection:
                self.server.registry.remove(connection)
            LOG.info("MODEM DISCONNECT IP=%s PORT=%s", remote_ip, remote_port)


class ControlHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], registry: ConnectionRegistry, log_exchange: Callable[[str | None, str, bytes], None] | None = None, mercury_manager: MercuryConnectionManager | None = None):
        self.registry = registry
        self.log_exchange = log_exchange
        self.mercury_manager = mercury_manager or MercuryConnectionManager()
        super().__init__(address, ControlRequestHandler)


class ControlRequestHandler(BaseHTTPRequestHandler):
    server: ControlHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info("HTTP %s", format % args)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        elif self.path == "/devices":
            self._json(200, self.server.registry.devices())
        elif self.path == "/mercury/status":
            self._json(200, self.server.mercury_manager.statuses())
        elif self.path.startswith("/mercury/status/"):
            device_id = self.path.removeprefix("/mercury/status/")
            self._json(200, self.server.mercury_manager.status(device_id))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.startswith("/mercury/"):
            self._handle_mercury()
            return
        if self.path not in {"/send", "/test-command"}:
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError("invalid content length")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("invalid json object")
            imei = payload.get("imei")
            hex_value = payload.get("hex")
            if not isinstance(imei, str) or not IMEI_RE.fullmatch(f"AT$IMEI={imei}".encode()):
                raise ValueError("invalid imei")
            if not isinstance(hex_value, str) or not hex_value.strip():
                raise ValueError("invalid hex")
            data = bytes.fromhex(hex_value)
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "invalid request"})
            return

        connection = self.server.registry.get(imei)
        if connection is None:
            self._json(404, {"error": "device not connected"})
            return
        try:
            with connection.send_lock:
                with connection.response_condition:
                    response_sequence = connection.response_sequence
                connection.socket.sendall(data)
                if self.server.log_exchange:
                    self.server.log_exchange(imei, "TX", data)
                LOG.info("IRZ TX\nIMEI=%s\nLEN=%s\nHEX=%s", imei, len(data), data.hex(" ").upper())
                response = connection.wait_for_response(response_sequence, 5.0) if self.path == "/test-command" else None
        except OSError:
            self.server.registry.remove(connection)
            self._json(503, {"error": "send failed"})
            return
        if self.path == "/test-command":
            response = response or b""
            ascii_value = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in response)
            self._json(
                200,
                {
                    "status": "response" if response else "timeout",
                    "imei": imei,
                    "bytes": len(data),
                    "response_hex": response.hex(" ").upper(),
                    "response_ascii": ascii_value,
                    "success": bool(response),
                },
            )
            return
        self._json(200, {"status": "sent", "imei": imei, "bytes": len(data)})

    def _handle_mercury(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or not isinstance(payload.get("device_id"), str):
                raise ValueError
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"success": False, "error_code": "INVALID_PARAMETERS", "message": "Некорректный запрос"})
            return
        action = self.path.removeprefix("/mercury/")
        device_id = payload["device_id"]
        try:
            if action in {"connect", "reconnect"}:
                result = self.server.mercury_manager.connect(device_id, payload.get("config") or {})
            elif action == "disconnect":
                result = self.server.mercury_manager.disconnect(device_id)
            elif action == "test":
                result = self.server.mercury_manager.execute(device_id, "serial_and_manufacture")
            elif action == "command":
                result = self.server.mercury_manager.execute(device_id, payload.get("command_id"))
            elif action == "poll":
                result = self.server.mercury_manager.poll(device_id)
            else:
                self._json(404, {"success": False, "error_code": "NOT_FOUND", "message": "not found"})
                return
        except MercuryGatewayError as exc:
            LOG.warning("MERCURY %s DEVICE=%s CODE=%s MESSAGE=%s", action.upper(), device_id, exc.code, exc)
            self._json(exc.status, {"success": False, "error_code": exc.code, "message": str(exc), "duration_ms": exc.duration_ms, "tx_raw": exc.tx_raw, "rx_raw": exc.rx_raw})
            return
        self._json(200, result)


def create_servers(host: str | None = None, tcp_port: int | None = None, http_port: int | None = None, log_exchange: Callable[[str | None, str, bytes], None] | None = None, mercury_manager: MercuryConnectionManager | None = None) -> tuple[ModemTCPServer, ControlHTTPServer]:
    bind_host = host or os.getenv("MODEM_GATEWAY_HOST", "0.0.0.0")
    registry = ConnectionRegistry()
    tcp_server = ModemTCPServer((bind_host, tcp_port if tcp_port is not None else int(os.getenv("MODEM_SNIFFER_PORT", "5009"))), registry, log_exchange)
    http_server = ControlHTTPServer((bind_host, http_port if http_port is not None else int(os.getenv("MODEM_CONTROL_PORT", "5010"))), registry, log_exchange, mercury_manager)
    return tcp_server, http_server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app import create_app
    from app.extensions import db
    from app.modules.irz.service import record_exchange

    app = create_app()

    def persist_exchange(imei: str | None, direction: str, data: bytes) -> None:
        try:
            with app.app_context():
                record_exchange(imei, direction, data)
        except Exception:
            with app.app_context():
                db.session.rollback()
            LOG.exception("IRZ LOG STORE FAILED IMEI=%s DIR=%s", imei or "?", direction)

    tcp_server, http_server = create_servers(log_exchange=persist_exchange)
    http_thread = threading.Thread(target=http_server.serve_forever, name="modem-control-api", daemon=True)
    http_thread.start()
    try:
        tcp_server.serve_forever()
    finally:
        tcp_server.server_close()
        http_server.shutdown()
        http_server.server_close()


if __name__ == "__main__":
    main()
