"""ATM21 inbound TCP gateway and internal control API."""
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

from app.modem_gateway.mercury import MercuryGatewayError, MercurySessionManager

LOG = logging.getLogger("opora.modem_sniffer")
IMEI_RE = re.compile(rb"AT\$IMEI=(\d{15})(?:,|\s|$)")
HEARTBEAT = bytes.fromhex("B5 BC BD BE BF")
IDENT_KEYS = ("IMEI", "TYP", "DEV", "VER", "REV", "BLD", "HDW", "SIM", "CSQ", "ATP", "INT")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_chunk(data: bytes, ip: str = "", imei: str | None = None) -> str:
    del ip
    text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data)
    return f"IRZ RX\nIMEI={imei or '?'}\nLEN={len(data)}\nHEX={data.hex(' ').upper()}\nASCII={text}"


def parse_identification(data: bytes) -> dict[str, str] | None:
    match = IMEI_RE.search(data)
    if not match:
        return None
    text = data.decode("ascii", "ignore")
    values = {}
    for item in text.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.removeprefix("AT$").strip().upper()
            if key in IDENT_KEYS:
                values[key.lower()] = value.strip()
    values["imei"] = match.group(1).decode("ascii")
    return values


def emit_exchange(callback, imei, direction, data, packet_type):
    if not callback:
        return
    try:
        callback(imei, direction, data, packet_type)
    except TypeError:
        callback(imei, direction, data)


@dataclass(slots=True)
class PendingMercury:
    address_byte: int
    data: bytearray = field(default_factory=bytearray)
    response: bytes | None = None
    disconnected: bool = False


class PendingResponseError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class DeviceConnection:
    imei: str
    remote_ip: str
    remote_port: int
    connected_at: datetime
    last_seen_at: datetime
    socket: socket.socket
    metadata: dict[str, str] = field(default_factory=dict)
    send_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    response_condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    pending: PendingMercury | None = field(default=None, repr=False)
    log_exchange: Callable[[str | None, str, bytes], None] | None = field(default=None, repr=False)

    @property
    def last_rx_at(self) -> datetime:
        return self.last_seen_at

    def public_dict(self) -> dict[str, Any]:
        return {"imei": self.imei, "ip": self.remote_ip, "port": self.remote_port,
                "connected_at": self.connected_at.isoformat(), "last_seen_at": self.last_seen_at.isoformat(),
                "online": True, **{key.lower(): self.metadata.get(key.lower()) for key in IDENT_KEYS if key != "IMEI"}}

    def feed_mercury_candidate(self, data: bytes) -> bool:
        """Accumulate pending response until a valid CRC frame for this address exists."""
        with self.response_condition:
            if self.pending is None:
                return False
            self.pending.data.extend(data)
            try:
                from modbus_crc import check_crc
            except ImportError:
                return False
            raw = bytes(self.pending.data)
            for end in range(3, len(raw) + 1):
                candidate = raw[:end]
                if candidate[0] == self.pending.address_byte and check_crc(candidate):
                    self.pending.response = candidate
                    self.response_condition.notify_all()
                    return True
            return False

    def ask_mercury(self, package: bytes, timeout: float) -> bytes:
        """Serialize a command and wait for a classified, CRC-valid response."""
        address_byte = package[0]
        with self.send_lock:
            with self.response_condition:
                self.pending = PendingMercury(address_byte)
            try:
                self.socket.sendall(package)
                emit_exchange(self.log_exchange, self.imei, "TX", package, "MERCURY_REQUEST")
                LOG.info("IRZ TX\nIMEI=%s\nLEN=%s\nHEX=%s", self.imei, len(package), package.hex(" ").upper())
                deadline = time.monotonic() + timeout
                with self.response_condition:
                    while self.pending and self.pending.response is None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            if self.pending.data:
                                if self.pending.data[0] != address_byte:
                                    raise PendingResponseError("WRONG_ADDRESS")
                                if len(self.pending.data) < 3:
                                    raise PendingResponseError("INCOMPLETE_RESPONSE")
                                raise PendingResponseError("CRC_ERROR")
                            raise TimeoutError
                        self.response_condition.wait(remaining)
                    if self.pending is None or self.pending.response is None:
                        raise TimeoutError
                    if self.pending.disconnected:
                        raise OSError("ATM21 disconnected")
                    return self.pending.response
            finally:
                with self.response_condition:
                    self.pending = None

    def disconnect_pending(self) -> None:
        with self.response_condition:
            if self.pending:
                self.pending.disconnected = True
                self.pending.response = b""
                self.response_condition.notify_all()


class ConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, DeviceConnection] = {}
        self._lock = threading.RLock()

    def register(self, connection: DeviceConnection) -> None:
        with self._lock:
            previous = self._connections.get(connection.imei)
            self._connections[connection.imei] = connection
        if previous and previous is not connection:
            try:
                previous.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

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
            return [self._connections[key].public_dict() for key in sorted(self._connections)]


class ModemTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address, daemon_threads = True, True

    def __init__(self, address, registry, log_exchange=None, identification_callback=None):
        self.registry, self.log_exchange = registry, log_exchange
        self.identification_callback = identification_callback
        super().__init__(address, ModemRequestHandler)


class ModemRequestHandler(socketserver.BaseRequestHandler):
    server: ModemTCPServer

    def handle(self) -> None:
        remote_ip, remote_port = self.client_address[:2]
        connection = None
        identification_buffer = bytearray()
        LOG.info("MODEM CONNECT IP=%s PORT=%s", remote_ip, remote_port)
        try:
            while data := self.request.recv(4096):
                if connection is None:
                    identification_buffer.extend(data)
                    identification_buffer[:] = identification_buffer[-8192:]
                    metadata = parse_identification(bytes(identification_buffer))
                    if metadata:
                        connection = DeviceConnection(metadata["imei"], str(remote_ip), int(remote_port), utcnow(), utcnow(), self.request,
                                                      metadata=metadata, log_exchange=self.server.log_exchange)
                        self.server.registry.register(connection)
                        emit_exchange(self.server.log_exchange, connection.imei, "RX", b"", "CONNECT")
                        if self.server.identification_callback:
                            self.server.identification_callback(connection.public_dict())
                    packet_type = "ATM21_IDENTIFICATION" if metadata else "UNKNOWN_RAW"
                else:
                    self.server.registry.touch(connection)
                    if identification_buffer.startswith(b"AT$") and all(byte in (10, 13) or 32 <= byte < 127 for byte in data):
                        identification_buffer.extend(data)
                        metadata = parse_identification(bytes(identification_buffer))
                        if metadata:
                            connection.metadata.update(metadata)
                            if self.server.identification_callback:
                                self.server.identification_callback(connection.public_dict())
                        packet_type = "ATM21_IDENTIFICATION"
                    else:
                        packet_type = self._classify(connection, data)
                emit_exchange(self.server.log_exchange, connection.imei if connection else None, "RX", data, packet_type)
                LOG.info("IRZ TYPE=%s\n%s", packet_type, format_chunk(data, imei=connection.imei if connection else None))
        finally:
            if connection:
                connection.disconnect_pending()
                self.server.registry.remove(connection)
                emit_exchange(self.server.log_exchange, connection.imei, "RX", b"", "DISCONNECT")
            LOG.info("MODEM DISCONNECT IP=%s PORT=%s", remote_ip, remote_port)

    def _classify(self, connection: DeviceConnection, data: bytes) -> str:
        if data == HEARTBEAT:
            if os.getenv("ATM21_HEARTBEAT_ACK", "0") == "1":
                connection.socket.sendall(HEARTBEAT)
            return "ATM21_HEARTBEAT"
        candidate = data.replace(HEARTBEAT, b"")
        if candidate.startswith(b"AT$"):
            # ATM21 identification/status messages are comma-delimited. Preserve
            # binary bytes coalesced by TCP after their terminating comma.
            end = candidate.rfind(b",")
            candidate = candidate[end + 1:] if end >= 0 else b""
            if not candidate:
                return "ATM21_IDENTIFICATION"
        if candidate and connection.feed_mercury_candidate(candidate):
            return "MERCURY_RESPONSE"
        return "UNKNOWN_RAW"


class ControlHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, registry, log_exchange=None, mercury_manager=None):
        self.registry, self.log_exchange = registry, log_exchange
        self.mercury_manager = mercury_manager or MercurySessionManager(registry)
        super().__init__(address, ControlRequestHandler)


class ControlRequestHandler(BaseHTTPRequestHandler):
    server: ControlHTTPServer
    def log_message(self, fmt, *args): LOG.info("HTTP %s", fmt % args)
    def _json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65536: raise ValueError
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict): raise ValueError
        return value
    def do_GET(self):
        if self.path == "/health": self._json(200, {"status": "ok"})
        elif self.path == "/devices": self._json(200, self.server.registry.devices())
        else: self._json(404, {"error": "not found"})
    def do_POST(self):
        try: payload = self._payload()
        except (ValueError, TypeError, json.JSONDecodeError): self._json(400, {"error": "invalid request"}); return
        if self.path in {"/send", "/test-command"}:
            self._raw_send(payload); return
        if self.path in {"/mercury/command", "/mercury/test", "/mercury/poll"}:
            self._mercury(payload); return
        self._json(404, {"error": "not found"})
    def _raw_send(self, payload):
        try:
            imei, text = payload["imei"], payload["hex"]
            if not isinstance(imei, str) or len(imei) != 15 or not imei.isdigit(): raise ValueError
            data = bytes.fromhex(text)
            if not data: raise ValueError
        except (KeyError, ValueError, TypeError): self._json(400, {"error": "invalid request"}); return
        session = self.server.registry.get(imei)
        if session is None: self._json(404, {"error": "device not connected"}); return
        try:
            if self.path == "/test-command":
                # Raw laboratory has no protocol correlation; retain legacy first-RX behavior separately.
                with session.send_lock:
                    session.socket.sendall(data)
                    emit_exchange(self.server.log_exchange, imei, "TX", data, "UNKNOWN_RAW")
                result = {"status": "sent", "response_hex": "", "response_ascii": "", "success": True}
            else:
                with session.send_lock: session.socket.sendall(data)
                emit_exchange(self.server.log_exchange, imei, "TX", data, "UNKNOWN_RAW")
                result = {"status": "sent"}
        except OSError: self.server.registry.remove(session); self._json(503, {"error": "send failed"}); return
        self._json(200, {**result, "imei": imei, "bytes": len(data)})
    def _mercury(self, payload):
        try:
            imei, address = str(payload["imei"]), int(payload["network_address"])
            if self.path == "/mercury/poll": result = self.server.mercury_manager.poll(imei, address)
            else: result = self.server.mercury_manager.execute(imei, address, payload.get("command_id") or "serial_and_manufacture")
        except (KeyError, ValueError, TypeError): self._json(400, {"success": False, "error_code": "INVALID_PARAMETERS", "message": "Некорректный запрос"}); return
        except MercuryGatewayError as exc:
            self._json(exc.status, {"success": False, "error_code": exc.code, "message": str(exc), "duration_ms": exc.duration_ms, "tx_raw": exc.tx_raw, "rx_raw": exc.rx_raw}); return
        self._json(200, result)


def create_servers(host=None, tcp_port=None, http_port=None, log_exchange=None, mercury_manager=None, identification_callback=None):
    bind = host or os.getenv("MODEM_GATEWAY_HOST", "0.0.0.0")
    registry = ConnectionRegistry()
    tcp = ModemTCPServer((bind, tcp_port if tcp_port is not None else int(os.getenv("MODEM_SNIFFER_PORT", "5009"))), registry, log_exchange, identification_callback)
    http = ControlHTTPServer((bind, http_port if http_port is not None else int(os.getenv("MODEM_CONTROL_PORT", "5010"))), registry, log_exchange, mercury_manager)
    return tcp, http


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app import create_app
    from app.extensions import db
    from app.modules.irz.service import record_exchange, upsert_atm21
    app = create_app()
    def persist(imei, direction, data, packet_type=None):
        try:
            with app.app_context(): record_exchange(imei, direction, data, packet_type)
        except Exception:
            with app.app_context(): db.session.rollback()
            LOG.exception("IRZ LOG STORE FAILED")
    def identify(metadata):
        try:
            with app.app_context(): upsert_atm21(metadata)
        except Exception:
            with app.app_context(): db.session.rollback()
            LOG.exception("ATM21 METADATA STORE FAILED")
    tcp, http = create_servers(log_exchange=persist, identification_callback=identify)
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    try: tcp.serve_forever()
    finally: tcp.server_close(); http.shutdown(); http.server_close()


if __name__ == "__main__": main()
