"""Mercury V2 commands transported over an already connected ATM21 session."""
from __future__ import annotations

import importlib
import time
from typing import Any

from app.modules.irz.commands import COMMANDS, get_command, normalize_result


class MercuryGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status
        self.duration_ms: int | None = None
        self.tx_raw = ""
        self.rx_raw = ""


class ATM21SessionTransport:
    """mercury-base transport adapter using the inbound ATM21 TCP socket."""
    def __init__(self, session: Any, timeout: float = 5.0):
        self.session, self.timeout = session, timeout
        self.port = f"ATM21:{session.imei}"
        self.tx_raw = b""
        self.rx_raw = b""

    def ask(self, package: bytes) -> bytes:
        self.tx_raw = bytes(package)
        try:
            self.rx_raw = self.session.ask_mercury(self.tx_raw, timeout=self.timeout)
        except TimeoutError as exc:
            error = MercuryGatewayError("MERCURY_TIMEOUT", "Mercury не ответил за установленное время", 504)
            error.tx_raw = self.tx_raw.hex(" ").upper()
            raise error from exc
        except OSError as exc:
            raise MercuryGatewayError("DEVICE_OFFLINE", "ATM21 отключён", 409) from exc
        return self.rx_raw


class V2MeterAdapter:
    """V2 facade avoiding mercury-base's broken automatic driver discovery."""
    def __init__(self, address: int, transport: ATM21SessionTransport, mercury_module: Any):
        self.transport = transport
        self.driver = mercury_module.mercury_v2
        try:
            self.address = self.driver.prepare_address(address)
            self.driver.format_address(self.address)
        except (TypeError, ValueError) as exc:
            raise MercuryGatewayError("INVALID_ADDRESS", "Некорректный сетевой адрес Mercury", 400) from exc
        crc = importlib.import_module("modbus_crc")
        self._add_crc, self._check_crc = crc.add_crc, crc.check_crc

    def send_command(self, *params: int):
        answer = self.transport.ask(self._add_crc(self.driver.format_address(self.address) + bytes(params)))
        if not answer or not self._check_crc(answer):
            raise MercuryGatewayError("CRC_ERROR", "Ответ Mercury имеет неверную CRC")
        if self.driver.extract_address(answer) != self.address:
            raise MercuryGatewayError("WRONG_ADDRESS", "Ответ получен от другого сетевого адреса")
        return self.driver.extract_data(answer)


class MercurySessionManager:
    """Execute allow-listed V2 commands against live registry sessions."""
    def __init__(self, registry: Any, module_loader=None):
        self.registry = registry
        self._module_loader = module_loader or (lambda: importlib.import_module("mercury_base"))

    def execute(self, imei: str, address: int, command_id: object) -> dict[str, Any]:
        try:
            command = get_command(command_id)
        except KeyError as exc:
            raise MercuryGatewayError("INVALID_COMMAND", "Неизвестная команда", 404) from exc
        except ValueError as exc:
            raise MercuryGatewayError("COMMAND_NOT_SUPPORTED", "Команда не поддерживается", 400) from exc
        session = self.registry.get(imei)
        if session is None:
            raise MercuryGatewayError("DEVICE_OFFLINE", "ATM21 не подключён", 409)
        transport = ATM21SessionTransport(session, command.timeout)
        meter = V2MeterAdapter(address, transport, self._module_loader())
        started = time.monotonic()
        try:
            result = getattr(meter.driver.commands, command.mercury_command)(meter)
        except MercuryGatewayError as exc:
            exc.duration_ms = round((time.monotonic() - started) * 1000)
            exc.tx_raw = exc.tx_raw or transport.tx_raw.hex(" ").upper()
            exc.rx_raw = transport.rx_raw.hex(" ").upper()
            raise
        return {"success": True, "imei": imei, "command": command.id,
                "mercury_command": command.mercury_command,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "data": normalize_result(result), "tx_raw": transport.tx_raw.hex(" ").upper(),
                "rx_raw": transport.rx_raw.hex(" ").upper()}

    def poll(self, imei: str, address: int) -> dict[str, Any]:
        results, errors = {}, []
        for command in COMMANDS.values():
            if not command.available or not command.poll:
                continue
            try:
                results[command.id] = self.execute(imei, address, command.id)
            except MercuryGatewayError as exc:
                errors.append({"command": command.id, "error_code": exc.code, "message": str(exc)})
        return {"success": bool(results), "partial": bool(results) and bool(errors), "results": results, "errors": errors}
