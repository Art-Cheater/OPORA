"""Normalisation helpers for backward-compatible controller state payloads."""

from __future__ import annotations

from typing import Any


OUTPUT_RELAYS = ("C6", "C7", "C8")
PHASES = ("A", "B", "C")


def normalize_actual_state(actual: dict[str, Any] | None) -> dict[str, Any]:
    """Convert legacy flat state into the extensible state representation."""
    source = actual if isinstance(actual, dict) else {}
    output_source = source.get("outputs") if isinstance(source.get("outputs"), dict) else source
    phase_source = source.get("phases") if isinstance(source.get("phases"), dict) else source
    input_source = source.get("inputs") if isinstance(source.get("inputs"), dict) else {}
    raw_source = source.get("raw") if isinstance(source.get("raw"), dict) else {}

    outputs = {key: output_source[key] for key in OUTPUT_RELAYS if key in output_source}
    phases = {key: phase_source[key] for key in PHASES if key in phase_source}
    inputs = dict(input_source)
    for key, value in source.items():
        if key not in {"outputs", "phases", "inputs", "raw", *OUTPUT_RELAYS, *PHASES}:
            inputs.setdefault(key, value)

    result: dict[str, Any] = {"outputs": outputs}
    if phases:
        result["phases"] = phases
    if inputs:
        result["inputs"] = inputs
    if raw_source:
        result["raw"] = dict(raw_source)
    return result


def payload_matches_actual(payload: dict[str, Any] | None, actual: dict[str, Any] | None) -> bool:
    """Return true only when every requested output is reported by hardware."""
    if not payload:
        return False
    outputs = normalize_actual_state(actual).get("outputs", {})
    return all(str(outputs.get(key)) == str(value) for key, value in payload.items())
