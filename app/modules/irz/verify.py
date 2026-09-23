"""Physical verification of read-only Mercury 230 commands through the live ATM21 session.

Runs inside the web container and talks to modem-sniffer's control API, so the
ATM21 socket (port 5009) stays the only path to the meter.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.modules.irz import service
from app.modules.irz.commands import COMMANDS, poll_commands

EXTRA_COMMANDS = ("device_info", "events")


def available_commands() -> list[str]:
    return [command.id for command in poll_commands()] + list(EXTRA_COMMANDS)


def _crc_ok(hex_value: str) -> bool | None:
    if not hex_value:
        return None
    data = bytes.fromhex(hex_value)
    return len(data) >= 4 and service.modbus_crc16(data[:-2]) == data[-2:]


def run(imei: str, address: int, command_ids: list[str]) -> list[dict]:
    report = []
    for command_id in command_ids:
        command = COMMANDS.get(command_id)
        if command is None or command.mode != "read" or command.dangerous or not command.available:
            report.append({"command": command_id, "status": "REJECTED", "message": "Команда не входит в read-only набор"})
            continue
        payload = {"imei": imei, "network_address": address, "command_id": command_id}
        try:
            result = service._gateway_request("/mercury/command", payload=payload,
                                              timeout=service.COMMAND_TIMEOUTS.get(command_id, 30))
            entry = {"command": command_id, "status": "OK", "duration_ms": result.get("duration_ms"),
                     "exchanges": result.get("exchanges") or [], "data": result.get("data"),
                     "normalized": service.normalize_command(command_id, result.get("data"), result)}
        except service.GatewayResponseError as exc:
            entry = {"command": command_id, "status": exc.error_code, "message": str(exc),
                     "duration_ms": exc.details.get("duration_ms"), "exchanges": exc.details.get("exchanges") or []}
        except service.GatewayUnavailable as exc:
            entry = {"command": command_id, "status": "CONNECTION_ERROR", "message": str(exc), "exchanges": []}
        for exchange in entry["exchanges"]:
            exchange["crc_ok"] = _crc_ok(exchange.get("rx", ""))
        report.append(entry)
    return report


def format_entry(entry: dict) -> str:
    lines = [f"== {entry['command']}: {entry['status']}" + (f" ({entry['duration_ms']} ms)" if entry.get("duration_ms") is not None else "")]
    for exchange in entry.get("exchanges", []):
        lines.append(f"   TX {exchange.get('tx')}")
        lines.append(f"   RX {exchange.get('rx') or '—'}   CRC {'OK' if exchange.get('crc_ok') else ('—' if exchange.get('crc_ok') is None else 'ОШИБКА')}")
    if entry.get("message"):
        lines.append(f"   {entry['message']}")
    if entry.get("normalized"):
        lines.append("   " + json.dumps(entry["normalized"], ensure_ascii=False, default=str))
    elif entry.get("data") is not None:
        lines.append("   " + json.dumps(entry["data"], ensure_ascii=False, default=str))
    return "\n".join(lines)


def fixture(address: int, report: list[dict]) -> dict:
    """Capture for tests: exchanges and parsed values only, without the IMEI."""
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "network_address": address,
        "commands": {entry["command"]: {key: entry.get(key) for key in ("status", "exchanges", "data", "normalized")}
                     for entry in report},
    }
