"""Normalisation helpers for backward-compatible controller state payloads."""

from __future__ import annotations

from typing import Any


OUTPUT_RELAYS = ("C6", "C7", "C8")
PHASES = ("A", "B", "C")
# Each connector is wired A B C A B C. bit0 is pin 1.
PIN_PHASES = ("A", "B", "C", "A", "B", "C")
CONNECTOR_MASKS = (("C9", "CON9"), ("C10", "CON10"), ("C11", "CON11"))
CONNECTORS = ("CON9", "CON10", "CON11")
RAW_BANKS = ("U2", "U3")
_STATE_KEYS = {
    "outputs", "phases", "inputs", "raw", "connectors", "phase_summary",
    "raw_bits", "raw_bit_changes", *OUTPUT_RELAYS, *PHASES,
}


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


def decode_raw_bank(encoded: str | None) -> dict[str, int] | None:
    """Split one U2/U3 hex byte into bits 0..7. bit0 is the least significant bit."""
    if not isinstance(encoded, str) or len(encoded) != 2:
        return None
    try:
        mask = int(encoded, 16)
    except ValueError:
        return None
    if not 0 <= mask <= 0xFF:
        return None
    return {str(bit): (mask >> bit) & 1 for bit in range(8)}


def decode_raw_bits(raw: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    source = raw if isinstance(raw, dict) else {}
    bits: dict[str, dict[str, int]] = {}
    for bank in RAW_BANKS:
        decoded = decode_raw_bank(source.get(bank) if isinstance(source.get(bank), str) else None)
        if decoded is not None:
            bits[bank] = decoded
    return bits


def observe_raw_bits(previous: dict[str, Any] | None, actual: dict[str, Any], changed_at: str) -> dict[str, Any]:
    """Remember each U2/U3 bit and the last 0/1 transition. No phase decision."""
    prior = previous if isinstance(previous, dict) else {}
    prior_bits = prior.get("raw_bits") if isinstance(prior.get("raw_bits"), dict) else {}
    changes = prior.get("raw_bit_changes") if isinstance(prior.get("raw_bit_changes"), dict) else {}
    changes = {bank: dict(bits) for bank, bits in changes.items() if isinstance(bits, dict)}
    current = decode_raw_bits(actual.get("raw") if isinstance(actual.get("raw"), dict) else None)
    for bank, bits in current.items():
        old_bits = prior_bits.get(bank) if isinstance(prior_bits.get(bank), dict) else {}
        bank_changes = dict(changes.get(bank) or {})
        for bit, value in bits.items():
            old = old_bits.get(bit)
            if old is not None and int(old) != int(value):
                bank_changes[bit] = {"from": int(old), "to": int(value), "at": changed_at}
        changes[bank] = bank_changes
    updated = dict(actual)
    if current:
        updated["raw_bits"] = current
    if any(changes.values()):
        updated["raw_bit_changes"] = changes
    return updated


def blank_phase_input_map() -> dict[str, dict[str, dict[str, Any]]]:
    """Eighteen connector pins, none tied to a raw bit until an operator confirms it."""
    return {
        connector: {
            pin: {"source": None, "bit": None, "phase": PIN_PHASES[int(pin) - 1], "active_level": None, "confirmed": False}
            for pin in ("1", "2", "3", "4", "5", "6")
        }
        for connector in CONNECTORS
    }


def normalize_phase_input_map(source: dict[str, Any] | None) -> dict[str, dict[str, dict[str, Any]]]:
    """Keep only valid U2/U3 references. Several pins may share one bit."""
    incoming = source if isinstance(source, dict) else {}
    result = blank_phase_input_map()
    for connector, pins in result.items():
        provided = incoming.get(connector) if isinstance(incoming.get(connector), dict) else {}
        for pin, blank in pins.items():
            item = provided.get(pin) if isinstance(provided.get(pin), dict) else {}
            raw_source = item.get("source")
            source_name = raw_source if raw_source in RAW_BANKS else None
            try:
                bit = int(item.get("bit"))
            except (TypeError, ValueError):
                bit = None
            if bit is not None and not 0 <= bit <= 7:
                bit = None
            try:
                level = int(item.get("active_level"))
            except (TypeError, ValueError):
                level = None
            if level not in (0, 1):
                level = None
            confirmed = bool(item.get("confirmed")) and source_name is not None and bit is not None and level is not None
            pins[pin] = {
                "source": source_name,
                "bit": bit,
                "phase": PIN_PHASES[int(pin) - 1],
                "active_level": level,
                "confirmed": confirmed,
            }
    return result


def phase_view_from_map(actual: dict[str, Any] | None, mapping: dict[str, Any] | None) -> dict[str, dict[str, dict[str, Any]]]:
    """Show a connector pin only after its raw bit and active level are confirmed."""
    bits = decode_raw_bits((actual or {}).get("raw") if isinstance((actual or {}).get("raw"), dict) else None)
    stored = (actual or {}).get("raw_bits") if isinstance((actual or {}).get("raw_bits"), dict) else {}
    if not bits and stored:
        bits = {bank: values for bank, values in stored.items() if isinstance(values, dict)}
    view: dict[str, dict[str, dict[str, Any]]] = {}
    for connector, pins in normalize_phase_input_map(mapping).items():
        view[connector] = {}
        for pin, item in pins.items():
            entry: dict[str, Any] = {"phase": item["phase"], "configured": False}
            if item["confirmed"]:
                bank_bits = bits.get(item["source"]) or {}
                raw_value = bank_bits.get(str(item["bit"]))
                entry["configured"] = True
                entry["source"] = item["source"]
                entry["bit"] = item["bit"]
                entry["active_level"] = item["active_level"]
                if raw_value is None:
                    entry["active"] = None
                else:
                    entry["raw"] = int(raw_value)
                    entry["active"] = int(raw_value) == int(item["active_level"])
            view[connector][pin] = entry
    return view


def normalize_actual_state(actual: dict[str, Any] | None) -> dict[str, Any]:
    """Convert legacy flat state into the extensible state representation."""
    source = actual if isinstance(actual, dict) else {}
    output_source = source.get("outputs") if isinstance(source.get("outputs"), dict) else source
    phase_source = source.get("phases") if isinstance(source.get("phases"), dict) else source
    input_source = source.get("inputs") if isinstance(source.get("inputs"), dict) else {}
    raw_source = source.get("raw") if isinstance(source.get("raw"), dict) else {}
    connectors = source.get("connectors") if isinstance(source.get("connectors"), dict) else None
    raw_bits = source.get("raw_bits") if isinstance(source.get("raw_bits"), dict) else None
    raw_bit_changes = source.get("raw_bit_changes") if isinstance(source.get("raw_bit_changes"), dict) else None

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
    if raw_bits:
        result["raw_bits"] = raw_bits
    if raw_bit_changes:
        result["raw_bit_changes"] = raw_bit_changes
    return result


def payload_matches_actual(payload: dict[str, Any] | None, actual: dict[str, Any] | None) -> bool:
    """Return true only when every requested output is reported by hardware."""
    if not payload:
        return False
    outputs = normalize_actual_state(actual).get("outputs", {})
    return all(str(outputs.get(key)) == str(value) for key, value in payload.items())
