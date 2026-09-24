"""Operational lighting status of an IRZ cabinet (ON / OFF / PROBLEM / CRITICAL), computed only here."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from flask import current_app

from app.models.irz import IRZDevice, IRZMeter
from app.modules.irz import service

IRZ_LIGHT_ON_THRESHOLD = 1.0
IRZ_CRITICAL_AFTER_SECONDS = 3600

ON = "ON"
OFF = "OFF"
PROBLEM = "PROBLEM"
CRITICAL = "CRITICAL"
LABELS = {ON: "Горит", OFF: "Не горит", PROBLEM: "Проблема", CRITICAL: "Критическая проблема"}
ORDER = {CRITICAL: 0, PROBLEM: 1, OFF: 2, ON: 3}

# Mercury command -> measurement prefix in the merged meter state (I, P, Q, S per phase).
LIGHT_COMMANDS = {"current_phases": "i", "active_power": "p", "reactive_power": "q", "apparent_power": "s"}
PHASES = ("a", "b", "c")

IP = "IP"
PP = "PP"
OTHER = "OTHER"


def cabinet_type(name: str | None) -> str:
    text = (name or "").strip().upper()
    if text.startswith("ИП"):
        return IP
    if text.startswith("ПП"):
        return PP
    return OTHER


def _measurement(value: object) -> float | None:
    """Only real numbers count; None, NaN, strings and booleans are «no measurement», never zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def last_successful_response(state: dict) -> datetime | None:
    """Latest capture time of I/P/Q/S; a failed command keeps the capture time of its last success."""
    moments = [service._parse_time((state.get("commands") or {}).get(command, {}).get("captured_at"))
               for command in LIGHT_COMMANDS]
    moments = [moment for moment in moments if moment is not None]
    return max(moments) if moments else None


def _current_measurements(state: dict, now: datetime, fresh_seconds: int) -> dict[str, list[float]]:
    """Valid phase values of commands that succeeded in the latest poll and are still fresh."""
    commands, values = state.get("commands") or {}, state.get("values") or {}
    current: dict[str, list[float]] = {}
    for command, prefix in LIGHT_COMMANDS.items():
        meta = commands.get(command) or {}
        captured = service._parse_time(meta.get("captured_at"))
        if meta.get("quality") != "GOOD" or captured is None or (now - captured).total_seconds() > fresh_seconds:
            continue
        current[prefix] = [number for phase in PHASES
                           if (number := _measurement(values.get(f"{prefix}_{phase}"))) is not None]
    return current


def _settings() -> tuple[int, int]:
    try:
        config = current_app.config
    except RuntimeError:
        return 900, IRZ_CRITICAL_AFTER_SECONDS
    return (int(config.get("IRZ_DATA_FRESH_SECONDS", 900)),
            int(config.get("IRZ_CRITICAL_AFTER_SECONDS", IRZ_CRITICAL_AFTER_SECONDS)))


def get_irz_operational_status(device: IRZDevice, meter: IRZMeter | None, *, online: bool,
                               now: datetime | None = None) -> dict:
    """ON: fresh data and any I/P/Q/S phase value above the threshold.
    OFF: fresh data, at least one of I/P/Q/S complete for all phases, nothing above the threshold.
    Otherwise PROBLEM, or CRITICAL once the last valid telemetry (or first detection) is an hour old.
    """
    now = now or datetime.now(timezone.utc)
    fresh_seconds, critical_after = _settings()
    state = service._current_state(meter.latest_snapshot) if meter is not None else {"values": {}, "commands": {}}
    last_ok = last_successful_response(state)
    reason = "ATM21 не на связи"
    if online:
        current = _current_measurements(state, now, fresh_seconds)
        measured = [value for values in current.values() for value in values]
        if any(abs(value) > IRZ_LIGHT_ON_THRESHOLD for value in measured):
            return _result(ON, None, last_ok, None)
        if any(len(values) == len(PHASES) for values in current.values()):
            return _result(OFF, None, last_ok, None)
        if current:
            reason = "Недостаточно данных I/P/Q/S для определения"
        elif last_ok is None:
            reason = "Mercury ещё не передал показания"
        else:
            reason = "Mercury не отвечает"
    reference = last_ok or (service._aware(device.created_at) if device.created_at else now)
    silence = max(0, int((now - reference).total_seconds()))
    return _result(CRITICAL if silence >= critical_after else PROBLEM, reason, last_ok, silence)


def _result(code: str, reason: str | None, last_ok: datetime | None, silence: int | None) -> dict:
    return {
        "code": code,
        "label": LABELS[code],
        "reason": reason,
        "last_success_at": last_ok.isoformat() if last_ok else None,
        "no_data_seconds": silence,
    }
