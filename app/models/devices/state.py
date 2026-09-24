"""Normalisation helpers for backward-compatible controller state payloads."""

from __future__ import annotations

from typing import Any


OUTPUT_RELAYS = ("C6", "C7", "C8")
PHASES = ("A", "B", "C")
# Each connector is wired A B C A B C. bit0 is pin 1.
PIN_PHASES = ("A", "B", "C", "A", "B", "C")
CONNECTOR_MASKS = (("C9", "CON9"), ("C10", "CON10"), ("C11", "CON11"))
_STATE_KEYS = {"outputs", "phases", "inputs", "raw", "connectors", "phase_summary", *OUTPUT_RELAYS, *PHASES}


def connector_pins(mask: int) -> dict[str, dict[str, Any]]:
    """Decode one 6-bit connector mask into pin, phase and value."""
    return {
        str(index + 1): {"phase": PIN_PHASES[index], "value": (mask >> index) & 1}
        for index in range(6)
    }


def phase_summary_from_connectors(connectors: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Count active pins per phase. This is a field diagnostic, not an alarm."""
    summary = {phase: {"active": 0, "total": 0} for phase in PHASES}
    for pins in connectors.values():
        if not isinstance(pins, dict):
            continue
        for pin in pins.values():
            if not isinstance(pin, dict) or pin.get("phase") not in summary:
                continue
            summary[pin["phase"]]["total"] += 1
            summary[pin["phase"]]["active"] += 1 if int(pin.get("value") or 0) else 0
    return summary


def normalize_actual_state(actual: dict[str, Any] | None) -> dict[str, Any]:
    """Convert legacy flat state into the extensible state representation."""
    source = actual if isinstance(actual, dict) else {}
    output_source = source.get("outputs") if isinstance(source.get("outputs"), dict) else source
    phase_source = source.get("phases") if isinstance(source.get("phases"), dict) else source
    input_source = source.get("inputs") if isinstance(source.get("inputs"), dict) else {}
    raw_source = source.get("raw") if isinstance(source.get("raw"), dict) else {}
    connectors = source.get("connectors") if isinstance(source.get("connectors"), dict) else None

    outputs = {key: output_source[key] for key in OUTPUT_RELAYS if key in output_source}
    phases = {key: phase_source[key] for key in PHASES if key in phase_source}
    inputs = dict(input_source)
    for key, value in source.items():
        if key not in _STATE_KEYS:
            inputs.setdefault(key, value)

    result: dict[str, Any] = {"outputs": outputs}
    if phases:
        result["phases"] = phases
    if inputs:
        result["inputs"] = inputs
    if raw_source:
        result["raw"] = dict(raw_source)
    if connectors:
        result["connectors"] = connectors
        result["phase_summary"] = phase_summary_from_connectors(connectors)
    return result


def payload_matches_actual(payload: dict[str, Any] | None, actual: dict[str, Any] | None) -> bool:
    """Return true only when every requested output is reported by hardware."""
    if not payload:
        return False
    outputs = normalize_actual_state(actual).get("outputs", {})
    return all(str(outputs.get(key)) == str(value) for key, value in payload.items())
