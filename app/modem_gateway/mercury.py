"""Mercury V2 commands transported over an already connected ATM21 session."""
from __future__ import annotations

import importlib
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.modules.irz.commands import get_command, normalize_result, poll_commands

# The meter closes an open channel after 240 s of silence (§2.2.2).
CHANNEL_TTL_SECONDS = 200.0
MAX_CONSECUTIVE_TIMEOUTS = 2


class MercuryGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status
        self.duration_ms: int | None = None
        self.tx_raw = ""
        self.rx_raw = ""
        self.exchanges: list[dict[str, str]] = []


class ATM21SessionTransport:
    """mercury-base transport adapter using the inbound ATM21 TCP socket."""
    def __init__(self, session: Any, timeout: float = 5.0):
        self.session, self.timeout = session, timeout
        self.port = f"ATM21:{session.imei}"
        self.tx_raw = b""
        self.rx_raw = b""
        self.expected_length: int | None = None
        self.redact: tuple[int, int] | None = None
        self.exchanges: list[dict[str, str]] = []

    def _logged_tx(self) -> bytes:
        if not self.redact:
            return self.tx_raw
        start, end = self.redact
        return self.tx_raw[:start] + b"\x2A" * (end - start) + self.tx_raw[end:]

    def ask(self, package: bytes) -> bytes:
        self.tx_raw = bytes(package)
        self.rx_raw = b""
        logged = self._logged_tx()
        self.exchanges.append({"tx": logged.hex(" ").upper(), "rx": ""})
        try:
            self.rx_raw = self.session.ask_mercury(self.tx_raw, timeout=self.timeout,
                                                   expected_length=self.expected_length, log_package=logged)
        except TimeoutError as exc:
            error = MercuryGatewayError("MERCURY_TIMEOUT", "Mercury не ответил за установленное время", 504)
            error.tx_raw = logged.hex(" ").upper()
            raise error from exc
        except RuntimeError as exc:
            code = getattr(exc, "code", "PROTOCOL_ERROR")
            messages = {"CRC_ERROR": "Некорректный CRC ответа Mercury", "WRONG_ADDRESS": "Получен ответ от другого адреса",
                        "INCOMPLETE_RESPONSE": "Получен неполный ответ Mercury"}
            error = MercuryGatewayError(code, messages.get(code, "Ошибка протокола Mercury"), 502)
            error.tx_raw = logged.hex(" ").upper()
            error.rx_raw = bytes(getattr(exc, "raw", b"") or b"").hex(" ").upper()
            raise error from exc
        except OSError as exc:
            raise MercuryGatewayError("DEVICE_OFFLINE", "ATM21 отключён", 409) from exc
        self.exchanges[-1]["rx"] = self.rx_raw.hex(" ").upper()
        return self.rx_raw

    def logged_tx_hex(self) -> str:
        return self._logged_tx().hex(" ").upper()


class V2MeterAdapter:
    """V2 facade avoiding mercury-base's broken automatic driver discovery."""
    def __init__(self, address: int, transport: ATM21SessionTransport, mercury_module: Any,
                 response_length: int | None = None):
        self.transport = transport
        self.response_length = response_length
        self.driver = mercury_module.mercury_v2
        try:
            self.address = self.driver.prepare_address(address)
            self.driver.format_address(self.address)
        except (TypeError, ValueError) as exc:
            raise MercuryGatewayError("INVALID_ADDRESS", "Некорректный сетевой адрес Mercury", 400) from exc
        crc = importlib.import_module("modbus_crc")
        self._add_crc, self._check_crc = crc.add_crc, crc.check_crc

    def send_command(self, *params: int, response_length: int | None = None, redact: tuple[int, int] | None = None):
        from app.modem_gateway.mercury230 import MercuryStatusError

        expected = response_length if response_length is not None else self.response_length
        self.transport.expected_length = expected + 3 if expected else None
        self.transport.redact = redact
        answer = self.transport.ask(self._add_crc(self.driver.format_address(self.address) + bytes(params)))
        if not answer or not self._check_crc(answer):
            raise MercuryGatewayError("CRC_ERROR", "Ответ Mercury имеет неверную CRC")
        if self.driver.extract_address(answer) != self.address:
            raise MercuryGatewayError("WRONG_ADDRESS", "Ответ получен от другого сетевого адреса")
        data = self.driver.extract_data(answer)
        if len(data) == 1 and expected != 1:
            raise MercuryStatusError(data[0])
        return data


class MercurySessionManager:
    """Execute allow-listed read-only commands against live registry sessions."""
    def __init__(self, registry: Any, module_loader=None, password: str | None = None, password_encoding: str | None = None):
        self.registry = registry
        self._module_loader = module_loader or (lambda: importlib.import_module("mercury_base"))
        # Factory level-1 password (appendix В); production overrides it via .env.
        self._password = password if password is not None else (os.getenv("MERCURY_LEVEL1_PASSWORD") or "111111")
        self._password_encoding = (password_encoding or os.getenv("MERCURY_PASSWORD_ENCODING") or "auto").strip().lower()
        self._channels: dict[tuple[str, int], tuple[int, float, int]] = {}
        self._lock = threading.Lock()

    def _session(self, imei: str):
        session = self.registry.get(imei)
        if session is None:
            raise MercuryGatewayError("DEVICE_OFFLINE", "ATM21 не подключён", 409)
        return session

    def _channel_is_open(self, imei: str, address: int, session: Any) -> bool:
        with self._lock:
            entry = self._channels.get((imei, address))
        return bool(entry and entry[0] == id(session) and time.monotonic() - entry[1] < CHANNEL_TTL_SECONDS)

    def _remember_channel(self, imei: str, address: int, session: Any, encoding_index: int | None = None) -> None:
        with self._lock:
            previous = self._channels.get((imei, address))
            index = encoding_index if encoding_index is not None else (previous[2] if previous else 0)
            self._channels[(imei, address)] = (id(session), time.monotonic(), index)

    def _forget_channel(self, imei: str, address: int) -> None:
        with self._lock:
            self._channels.pop((imei, address), None)

    def open_channel(self, imei: str, address: int) -> dict[str, Any]:
        """Open access level 1 (read-only «потребитель», §2.2.2). The password is masked in logs."""
        from app.modem_gateway.mercury230 import open_channel_request, password_candidates

        session = self._session(imei)
        try:
            candidates = password_candidates(self._password, self._password_encoding)
        except ValueError as exc:
            raise MercuryGatewayError("INVALID_PASSWORD", "Пароль первого уровня Mercury задан некорректно", 500) from exc
        with self._lock:
            previous = self._channels.get((imei, address))
        if previous and previous[2] < len(candidates):
            order = [previous[2]] + [index for index in range(len(candidates)) if index != previous[2]]
        else:
            order = list(range(len(candidates)))
        transport = ATM21SessionTransport(session, 5.0)
        meter = V2MeterAdapter(address, transport, self._module_loader())
        started = time.monotonic()
        for index in order:
            try:
                data = meter.send_command(*open_channel_request(1, candidates[index]), response_length=1, redact=(3, 9))
            except MercuryGatewayError as exc:
                exc.duration_ms = round((time.monotonic() - started) * 1000)
                exc.tx_raw = exc.tx_raw or transport.logged_tx_hex()
                exc.exchanges = transport.exchanges
                raise
            if data[0] & 0x0F == 0:
                self._remember_channel(imei, address, session, index)
                return {"success": True, "duration_ms": round((time.monotonic() - started) * 1000),
                        "tx_raw": transport.logged_tx_hex(), "rx_raw": transport.rx_raw.hex(" ").upper(),
                        "exchanges": transport.exchanges}
        error = MercuryGatewayError("ACCESS_DENIED", "Счётчик отклонил открытие канала первого уровня", 502)
        error.duration_ms = round((time.monotonic() - started) * 1000)
        error.tx_raw, error.rx_raw = transport.logged_tx_hex(), transport.rx_raw.hex(" ").upper()
        error.exchanges = transport.exchanges
        raise error

    def execute(self, imei: str, address: int, command_id: object, params: dict | None = None,
                *, reopen: bool = True) -> dict[str, Any]:
        try:
            command = get_command(command_id)
        except KeyError as exc:
            raise MercuryGatewayError("INVALID_COMMAND", "Неизвестная команда", 404) from exc
        except ValueError as exc:
            raise MercuryGatewayError("COMMAND_NOT_SUPPORTED", "Команда не поддерживается", 400) from exc
        session = self._session(imei)
        try:
            return self._run(session, imei, address, command, params)
        except MercuryGatewayError as exc:
            if exc.code != "CHANNEL_NOT_OPEN" or not command.needs_channel or not reopen:
                raise
        self._forget_channel(imei, address)
        self.open_channel(imei, address)
        return self._run(session, imei, address, command, params)

    def _run(self, session: Any, imei: str, address: int, command, params: dict | None) -> dict[str, Any]:
        from app.modem_gateway.mercury230 import MercuryStatusError, execute

        transport = ATM21SessionTransport(session, command.timeout)
        meter = V2MeterAdapter(address, transport, self._module_loader(), command.response_length)
        started = time.monotonic()

        def fail(error: MercuryGatewayError) -> MercuryGatewayError:
            error.duration_ms = round((time.monotonic() - started) * 1000)
            error.tx_raw = error.tx_raw or transport.logged_tx_hex()
            error.rx_raw = error.rx_raw or transport.rx_raw.hex(" ").upper()
            error.exchanges = transport.exchanges
            return error

        try:
            if command.mercury_command.startswith("ext:"):
                result = execute(meter, command.id, params)
            else:
                result = getattr(meter.driver.commands, command.mercury_command)(meter)
        except MercuryStatusError as exc:
            raise fail(MercuryGatewayError(exc.code, str(exc), 409 if exc.code == "CHANNEL_NOT_OPEN" else 502)) from exc
        except KeyError as exc:
            raise fail(MercuryGatewayError("INVALID_PARAMETERS", "Некорректные параметры команды", 400)) from exc
        except ValueError as exc:
            raise fail(MercuryGatewayError("UNKNOWN_RESPONSE_FORMAT", "Ответ Mercury имеет неизвестный формат", 502)) from exc
        except MercuryGatewayError as exc:
            raise fail(exc)
        if command.needs_channel:
            self._remember_channel(imei, address, session)
        return {"success": True, "imei": imei, "command": command.id,
                "mercury_command": command.mercury_command,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "received_at": datetime.now(timezone.utc).isoformat(),
                "data": normalize_result(result), "tx_raw": transport.logged_tx_hex(),
                "rx_raw": transport.rx_raw.hex(" ").upper(), "exchanges": transport.exchanges}

    @staticmethod
    def _error_payload(command_id: str, exc: MercuryGatewayError) -> dict[str, Any]:
        return {"command": command_id, "error_code": exc.code, "message": str(exc),
                "duration_ms": exc.duration_ms, "tx_raw": exc.tx_raw, "rx_raw": exc.rx_raw}

    def poll(self, imei: str, address: int) -> dict[str, Any]:
        """Run the default realtime set once; one failed command never discards the others."""
        results, errors = {}, []
        consecutive_timeouts, abort_code = 0, None
        channel_checked = channel_failed = False
        for command in poll_commands():
            if abort_code:
                errors.append({"command": command.id, "error_code": abort_code,
                               "message": "Команда пропущена: счётчик или ATM21 не отвечает",
                               "duration_ms": None, "tx_raw": "", "rx_raw": ""})
                continue
            if command.needs_channel and not channel_checked:
                channel_checked = True
                try:
                    if not self._channel_is_open(imei, address, self._session(imei)):
                        self.open_channel(imei, address)
                except MercuryGatewayError as exc:
                    channel_failed = True
                    errors.append(self._error_payload("open_channel", exc))
                    if exc.code == "DEVICE_OFFLINE":
                        abort_code = "DEVICE_OFFLINE"
                        continue
                    if exc.code == "MERCURY_TIMEOUT":
                        consecutive_timeouts += 1
                        if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                            abort_code = "SKIPPED"
                            continue
            try:
                results[command.id] = self.execute(imei, address, command.id, reopen=not channel_failed)
                consecutive_timeouts = 0
            except MercuryGatewayError as exc:
                errors.append(self._error_payload(command.id, exc))
                if exc.code == "DEVICE_OFFLINE":
                    abort_code = "DEVICE_OFFLINE"
                elif exc.code == "MERCURY_TIMEOUT":
                    consecutive_timeouts += 1
                    if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                        abort_code = "SKIPPED"
                else:
                    consecutive_timeouts = 0
        return {"success": bool(results), "partial": bool(results) and bool(errors), "results": results, "errors": errors}
