"""Process-wide Mercury V2 connection manager used by the modem sidecar."""

from __future__ import annotations

import importlib
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.modules.irz.commands import COMMANDS, CommandSpec, get_command, normalize_result

SERIAL_PORT_RE = re.compile(r"^(?:COM[1-9]\d*|/dev/(?:tty[A-Za-z0-9._-]+|serial/by-id/[A-Za-z0-9._-]+))$", re.I)
MAX_RAW_BYTES = 4096


class MercuryGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status
        self.duration_ms: int | None = None
        self.tx_raw = ""
        self.rx_raw = ""


class TcpTransportAdapter:
    """Bounded synchronous TCP transport for mercury-base commands.

    simple-socket-client 1.5 busy-spins while idle and can hang its connect()
    loop after connection-refused, so it is not suitable for this sidecar.
    """

    def __init__(self, host: str, port: int, timeout: float):
        self.port = f"{host}:{port}"
        self._timeout = timeout
        self._socket = socket.create_connection((host, port), timeout=timeout)

    def ask(self, package: bytes) -> bytes:
        self._socket.settimeout(self._timeout)
        self._socket.sendall(package)
        return self._socket.recv(4096)

    def close(self) -> None:
        self._socket.close()


@dataclass
class TraceTransport:
    transport: Any
    tx_raw: bytes = b""
    rx_raw: bytes = b""

    @property
    def port(self):
        return self.transport.port

    def ask(self, package: bytes):
        self.tx_raw = bytes(package[:MAX_RAW_BYTES])
        try:
            answer = self.transport.ask(package)
        except TimeoutError as exc:
            raise MercuryGatewayError("MERCURY_TIMEOUT", "Устройство не ответило за установленное время", 504) from exc
        except OSError as exc:
            raise MercuryGatewayError("TRANSPORT_ERROR", "Соединение с устройством потеряно", 503) from exc
        self.rx_raw = bytes((answer or b"")[:MAX_RAW_BYTES])
        return answer

    def clear_trace(self) -> None:
        self.tx_raw = b""
        self.rx_raw = b""

    def close(self) -> None:
        if hasattr(self.transport, "close"):
            self.transport.close()
            return
        # mercury-base 1.6 exposes no public close(). These are the two
        # verified backing attributes in its Serial/TCP transports.
        for name in ("_SerialDataTransport__connection", "_TcpDataTransport__connection"):
            connection = getattr(self.transport, name, None)
            if connection is not None:
                if hasattr(connection, "close"):
                    connection.close()
                    return
                if hasattr(connection, "disconnect"):
                    connection.disconnect()
                    return


class V2MeterAdapter:
    """Minimal meter surface consumed by mercury_base.mercury_v2.commands.

    Meter itself cannot initialise V2 in 1.6 because it calls the V1-only
    get_serial_number. Framing/parsing remains delegated to mercury-base.
    """

    def __init__(self, address: int, transport: TraceTransport, mercury_module: Any):
        self.transport = transport
        self.driver = mercury_module.mercury_v2
        self.address = self.driver.prepare_address(address)
        self._add_crc = importlib.import_module("modbus_crc").add_crc
        self._check_crc = importlib.import_module("modbus_crc").check_crc

    def send_command(self, *params: int):
        try:
            body = self.driver.format_address(self.address) + bytes(params)
        except (TypeError, ValueError) as exc:
            raise MercuryGatewayError("PROTOCOL_ERROR", "mercury-base сформировал некорректную команду") from exc
        package = self._add_crc(body)
        answer = self.transport.ask(package)
        if not answer:
            raise MercuryGatewayError("MERCURY_TIMEOUT", "Устройство не ответило за установленное время", 504)
        if not self._check_crc(answer):
            raise MercuryGatewayError("PROTOCOL_ERROR", "Ответ устройства имеет неверную контрольную сумму")
        if self.driver.extract_address(answer) != self.address:
            raise MercuryGatewayError("PROTOCOL_ERROR", "Ответ получен от другого сетевого адреса")
        return self.driver.extract_data(answer)


@dataclass
class ManagedConnection:
    device_id: str
    signature: tuple[Any, ...]
    bus_key: str
    transport: TraceTransport
    meter: V2MeterAdapter
    state: str = "CONNECTED"
    connected_at: float = field(default_factory=time.time)
    last_success_at: float | None = None
    last_error_at: float | None = None
    last_latency_ms: int | None = None
    last_error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "state": self.state,
            "connected_at": self.connected_at,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_latency_ms": self.last_latency_ms,
            "last_error": self.last_error,
        }


class MercuryConnectionManager:
    def __init__(self, module_loader: Callable[[], Any] | None = None, transport_factory: Callable[[Any, str, tuple[Any, ...], dict[str, Any]], Any] | None = None):
        self._module_loader = module_loader or (lambda: importlib.import_module("mercury_base"))
        self._transport_factory = transport_factory
        self._connections: dict[str, ManagedConnection] = {}
        self._bus_locks: dict[str, threading.Lock] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _validated_config(config: dict[str, Any]) -> tuple[str, tuple[Any, ...], str]:
        transport = str(config.get("transport_type", "")).upper()
        try:
            address = int(config.get("network_address"))
        except (TypeError, ValueError) as exc:
            raise MercuryGatewayError("INVALID_PARAMETERS", "Сетевой адрес должен быть числом", 400) from exc
        if not 1 <= address <= 99999999:
            raise MercuryGatewayError("INVALID_PARAMETERS", "Сетевой адрес вне допустимого диапазона", 400)
        if transport == "SERIAL":
            port = str(config.get("serial_port") or "")
            if ".." in port or not SERIAL_PORT_RE.fullmatch(port):
                raise MercuryGatewayError("INVALID_PARAMETERS", "Недопустимое имя последовательного порта", 400)
            baudrate = int(config.get("baudrate") or 9600)
            if baudrate not in {1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200}:
                raise MercuryGatewayError("INVALID_PARAMETERS", "Недопустимая скорость порта", 400)
            signature = (transport, address, port, baudrate)
            return f"serial:{port}", signature, transport
        if transport == "TCP":
            host = str(config.get("host") or "").strip()
            if not host or len(host) > 253 or any(char.isspace() for char in host):
                raise MercuryGatewayError("INVALID_PARAMETERS", "Недопустимый hostname", 400)
            try:
                port = int(config.get("port"))
            except (TypeError, ValueError) as exc:
                raise MercuryGatewayError("INVALID_PARAMETERS", "Недопустимый TCP-порт", 400) from exc
            if not 1 <= port <= 65535:
                raise MercuryGatewayError("INVALID_PARAMETERS", "Недопустимый TCP-порт", 400)
            signature = (transport, address, host, port)
            return f"tcp:{host.lower()}:{port}", signature, transport
        raise MercuryGatewayError("INVALID_PARAMETERS", "Поддерживаются только SERIAL и TCP", 400)

    def connect(self, device_id: str, config: dict[str, Any]) -> dict[str, Any]:
        bus_key, signature, transport_type = self._validated_config(config)
        self.disconnect(device_id, missing_ok=True)
        mercury = self._module_loader()
        try:
            if self._transport_factory:
                raw_transport = self._transport_factory(mercury, transport_type, signature, config)
            elif transport_type == "SERIAL":
                raw_transport = mercury.SerialDataTransport(signature[2], baudrate=signature[3])
            else:
                raw_transport = TcpTransportAdapter(signature[2], signature[3], timeout=float(config.get("timeout") or 5))
        except Exception as exc:
            raise MercuryGatewayError("CONNECTION_ERROR", str(exc) or "Не удалось открыть транспорт", 503) from exc
        traced = TraceTransport(raw_transport)
        connection = ManagedConnection(
            device_id=device_id,
            signature=signature,
            bus_key=bus_key,
            transport=traced,
            meter=V2MeterAdapter(signature[1], traced, mercury),
        )
        with self._lock:
            self._connections[device_id] = connection
            self._bus_locks.setdefault(bus_key, threading.Lock())
        return connection.public_dict()

    def disconnect(self, device_id: str, *, missing_ok: bool = False) -> dict[str, Any]:
        with self._lock:
            connection = self._connections.pop(device_id, None)
        if connection is None:
            if missing_ok:
                return {"device_id": device_id, "state": "DISCONNECTED"}
            raise MercuryGatewayError("CONNECTION_ERROR", "Устройство не подключено", 409)
        try:
            connection.transport.close()
        except OSError as exc:
            raise MercuryGatewayError("TRANSPORT_ERROR", "Ошибка закрытия транспорта") from exc
        return {"device_id": device_id, "state": "DISCONNECTED"}

    def status(self, device_id: str) -> dict[str, Any]:
        with self._lock:
            connection = self._connections.get(device_id)
        return connection.public_dict() if connection else {"device_id": device_id, "state": "DISCONNECTED"}

    def statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            return [connection.public_dict() for connection in self._connections.values()]

    def execute(self, device_id: str, command_id: str) -> dict[str, Any]:
        try:
            spec = get_command(command_id)
        except KeyError as exc:
            raise MercuryGatewayError("INVALID_COMMAND", "Неизвестная команда", 404) from exc
        except ValueError as exc:
            raise MercuryGatewayError("COMMAND_NOT_SUPPORTED", "Команда недоступна в mercury-base 1.6", 409) from exc
        with self._lock:
            connection = self._connections.get(device_id)
            bus_lock = self._bus_locks.get(connection.bus_key) if connection else None
        if connection is None or bus_lock is None:
            raise MercuryGatewayError("CONNECTION_ERROR", "Устройство не подключено", 409)
        if not bus_lock.acquire(timeout=spec.timeout + 1):
            raise MercuryGatewayError("DEVICE_BUSY", "Физическая линия занята", 409)
        started = time.monotonic()
        connection.state = "BUSY"
        connection.transport.clear_trace()
        try:
            commands = connection.meter.driver.commands
            command = getattr(commands, spec.mercury_command)
            data = normalize_result(command(connection.meter))
            duration = round((time.monotonic() - started) * 1000)
            connection.state = "CONNECTED"
            connection.last_success_at = time.time()
            connection.last_latency_ms = duration
            connection.last_error = None
            return self._result(connection, spec, True, duration, data=data)
        except MercuryGatewayError as exc:
            exc.duration_ms = round((time.monotonic() - started) * 1000)
            exc.tx_raw = connection.transport.tx_raw.hex(" ").upper()
            exc.rx_raw = connection.transport.rx_raw.hex(" ").upper()
            self._mark_error(connection, exc)
            raise
        except Exception as exc:
            error = MercuryGatewayError("PROTOCOL_ERROR", "Не удалось разобрать ответ устройства")
            error.duration_ms = round((time.monotonic() - started) * 1000)
            error.tx_raw = connection.transport.tx_raw.hex(" ").upper()
            error.rx_raw = connection.transport.rx_raw.hex(" ").upper()
            self._mark_error(connection, error)
            raise error from exc
        finally:
            if connection.state == "BUSY":
                connection.state = "CONNECTED"
            bus_lock.release()

    def poll(self, device_id: str) -> dict[str, Any]:
        results: dict[str, Any] = {}
        errors: list[dict[str, str]] = []
        for spec in COMMANDS.values():
            if not spec.available or not spec.poll:
                continue
            try:
                results[spec.id] = self.execute(device_id, spec.id)
            except MercuryGatewayError as exc:
                errors.append({
                    "command": spec.id,
                    "error_code": exc.code,
                    "message": str(exc),
                    "duration_ms": exc.duration_ms,
                    "tx_raw": exc.tx_raw,
                    "rx_raw": exc.rx_raw,
                })
        return {"success": bool(results), "partial": bool(errors), "results": results, "errors": errors}

    @staticmethod
    def _mark_error(connection: ManagedConnection, error: MercuryGatewayError) -> None:
        connection.state = "ERROR"
        connection.last_error_at = time.time()
        connection.last_error = str(error)

    @staticmethod
    def _result(connection: ManagedConnection, spec: CommandSpec, success: bool, duration: int, *, data: Any) -> dict[str, Any]:
        return {
            "success": success,
            "command": spec.id,
            "mercury_command": spec.mercury_command,
            "device_id": connection.device_id,
            "duration_ms": duration,
            "data": data,
            "tx_raw": connection.transport.tx_raw.hex(" ").upper(),
            "rx_raw": connection.transport.rx_raw.hex(" ").upper(),
            "timestamp": time.time(),
        }
