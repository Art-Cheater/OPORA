"""Read-only Mercury 230 commands from the official Incotex protocol."""
from __future__ import annotations

from decimal import Decimal


def _u24(chunk: list[int]) -> int:
    if len(chunk) != 3:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    return ((chunk[0] & 0x3F) << 16) | (chunk[2] << 8) | chunk[1]


def _power_value(chunk: list[int], reactive: bool = False) -> Decimal:
    if len(chunk) != 4:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    raw = (chunk[0] << 16) | (chunk[3] << 8) | chunk[2]
    direction_bit = 0x40 if reactive else 0x80
    return Decimal(-raw if chunk[1] & direction_bit else raw) / Decimal(100)


def _groups(data: list[int], size: int, count: int) -> list[list[int]]:
    if len(data) != size * count:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    return [data[index:index + size] for index in range(0, len(data), size)]


def execute(meter, command_id: str):
    """Execute an allow-listed extension command through the existing V2 adapter."""
    if command_id == "voltage_phases":
        values = _groups(meter.send_command(0x08, 0x14, 0x11), 3, 3)
        return {phase: Decimal(_u24(raw)) / Decimal(100) for phase, raw in zip(("a", "b", "c"), values)}
    if command_id == "current_phases":
        values = _groups(meter.send_command(0x08, 0x14, 0x21), 3, 3)
        return {phase: Decimal(_u24(raw)) / Decimal(1000) for phase, raw in zip(("a", "b", "c"), values)}
    if command_id == "power_factor":
        values = _groups(meter.send_command(0x08, 0x14, 0x30), 3, 4)
        return {phase: Decimal(_u24(raw)) / Decimal(1000) for phase, raw in zip(("total", "a", "b", "c"), values)}
    if command_id == "frequency":
        return {"value": Decimal(_u24(meter.send_command(0x08, 0x11, 0x40))) / Decimal(100)}
    if command_id in {"active_power", "reactive_power", "apparent_power"}:
        bwri = {"active_power": 0x00, "reactive_power": 0x04, "apparent_power": 0x08}[command_id]
        values = _groups(meter.send_command(0x08, 0x14, bwri), 4, 4)
        reactive = command_id == "reactive_power"
        return {phase: _power_value(raw, reactive) for phase, raw in zip(("total", "a", "b", "c"), values)}
    if command_id == "phase_angles":
        result = {}
        for key, bwri in (("ab", 0x51), ("ac", 0x52), ("bc", 0x53)):
            result[key] = Decimal(_u24(meter.send_command(0x08, 0x11, bwri))) / Decimal(100)
        return result
    if command_id == "device_info":
        data = meter.send_command(0x08, 0x12)
        if len(data) not in (6, 8):
            raise ValueError("UNKNOWN_RESPONSE_FORMAT")
        return {
            "raw": bytes(data).hex(" ").upper(),
            "three_phase": not bool(data[1] & 0x10),
            "profile_supported": bool(data[1] & 0x20),
            "tariff_supported": bool(data[2] & 0x40),
            "reactive_energy_supported": not bool(data[2] & 0x20),
            "rs485": ((data[3] >> 2) & 0x03) == 1,
            "power_quality_supported": bool(data[4] & 0x02),
            "per_phase_energy_supported": bool(data[4] & 0x01),
        }
    raise KeyError("INVALID_COMMAND")
