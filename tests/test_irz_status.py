"""Operational lighting status ON / OFF / PROBLEM / CRITICAL computed by app.modules.irz.status."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.modules.irz import status

NOW = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)
COMMAND_OF = {"i": "current_phases", "p": "active_power", "q": "reactive_power", "s": "apparent_power"}


def _meter(values, *, age=timedelta(0), quality="GOOD", commands=None):
    """Merged meter state; each I/P/Q/S prefix present in `values` gets its command captured `age` ago."""
    prefixes = commands if commands is not None else {key.split("_")[0] for key in values if key.split("_")[0] in COMMAND_OF}
    captured = (NOW - age).isoformat()
    return SimpleNamespace(latest_snapshot={
        "values": values,
        "commands": {COMMAND_OF[prefix]: {"captured_at": captured, "quality": quality, "fields": []} for prefix in prefixes},
        "updated_at": captured,
    })


def _device(created=timedelta(days=30)):
    return SimpleNamespace(created_at=NOW - created)


def _status(meter, *, online=True, device=None):
    return status.get_irz_operational_status(device or _device(), meter, online=online, now=NOW)


def _phases(prefix, a, b, c):
    return {f"{prefix}_a": a, f"{prefix}_b": b, f"{prefix}_c": c}


def test_constants_are_single_source_of_truth():
    assert status.IRZ_LIGHT_ON_THRESHOLD == 1.0
    assert status.IRZ_CRITICAL_AFTER_SECONDS == 3600


def test_all_zero_is_off():
    result = _status(_meter({**_phases("i", 0, 0, 0), **_phases("p", 0, 0, 0), **_phases("q", 0, 0, 0), **_phases("s", 0, 0, 0)}))
    assert (result["code"], result["label"], result["reason"], result["no_data_seconds"]) == ("OFF", "Не горит", None, None)
    assert result["last_success_at"] == NOW.isoformat()


def test_all_values_at_or_below_threshold_is_off():
    assert _status(_meter({**_phases("i", 1.0, 0.5, 0.99), **_phases("p", 1000, 0, -1000)}))["code"] == "OFF"


def test_small_load_below_one_kilo_unit_is_off():
    """I 0.5 / 0.8 / 0 A gives ~115-185 VA per phase: P, Q, S stay below 1 kW / kvar / kVA."""
    values = {**_phases("i", 0.5, 0.8, 0), **_phases("p", 110.0, 175.0, 0), **_phases("q", -30.0, 40.0, 0),
              **_phases("s", 115.0, 184.0, 0)}
    assert _status(_meter(values))["code"] == "OFF"


@pytest.mark.parametrize("prefix,value", [("i", 1.01), ("p", 1010.0), ("q", 1010.0), ("s", 1010.0)])
def test_any_value_above_threshold_on_any_phase_is_on(prefix, value):
    values = {**_phases("i", 0, 0, 0), **_phases(prefix, 0, value, 0)}
    result = _status(_meter(values))
    assert (result["code"], result["label"]) == ("ON", "Горит")


def test_power_threshold_is_in_kilo_units():
    assert _status(_meter({**_phases("i", 0, 0, 0), **_phases("p", 999.0, 1000.0, 42.0)}))["code"] == "OFF"


def test_negative_reactive_power_counts_by_magnitude():
    assert _status(_meter({**_phases("i", 0, 0, 0), **_phases("q", -2500.0, 0, 0)}))["code"] == "ON"


@pytest.mark.parametrize("minutes", [10, 59])
def test_no_valid_answer_under_an_hour_is_problem(minutes):
    result = _status(_meter(_phases("i", 5, 5, 5), age=timedelta(minutes=minutes), quality="STALE"))
    assert (result["code"], result["reason"]) == ("PROBLEM", "Mercury не отвечает")
    assert result["no_data_seconds"] == minutes * 60
    assert result["last_success_at"] == (NOW - timedelta(minutes=minutes)).isoformat()


@pytest.mark.parametrize("minutes", [60, 180])
def test_no_valid_answer_for_an_hour_or_more_is_critical(minutes):
    result = _status(_meter(_phases("i", 5, 5, 5), age=timedelta(minutes=minutes), quality="STALE"))
    assert (result["code"], result["label"]) == ("CRITICAL", "Критическая проблема")
    assert result["no_data_seconds"] == minutes * 60


def test_old_good_snapshot_past_freshness_is_not_on():
    """Poll loop stopped: the last capture stays GOOD, but 20 minutes old is not current data."""
    assert _status(_meter(_phases("i", 5, 5, 5), age=timedelta(minutes=20)))["code"] == "PROBLEM"


def test_atm_online_but_mercury_silent_for_two_hours_is_critical():
    result = _status(_meter(_phases("i", 5, 5, 5), age=timedelta(hours=2), quality="STALE"), online=True)
    assert (result["code"], result["reason"]) == ("CRITICAL", "Mercury не отвечает")


def test_link_lost_never_keeps_old_on_status():
    result = _status(_meter(_phases("i", 5, 5, 5), age=timedelta(minutes=2)), online=False)
    assert (result["code"], result["reason"]) == ("PROBLEM", "ATM21 не на связи")


def test_partial_snapshot_with_one_value_above_threshold_is_on():
    assert _status(_meter({"i_a": 0.0, "i_b": None, "p_c": 4200.0}))["code"] == "ON"


def test_partial_snapshot_with_insufficient_data_is_problem():
    result = _status(_meter({"i_a": 0.2, "p_b": 0.0}))
    assert (result["code"], result["reason"]) == ("PROBLEM", "Недостаточно данных I/P/Q/S для определения")


def test_null_nan_and_text_are_not_zero():
    values = {"i_a": None, "i_b": float("nan"), "i_c": "0", "p_a": True, "p_b": 0.0, "p_c": 0.0}
    assert _status(_meter(values))["code"] == "PROBLEM"
    assert _status(_meter({**values, "p_a": 0}))["code"] == "OFF"


def test_failed_command_does_not_decide_while_other_command_is_current():
    meter = _meter({**_phases("i", 0, 0, 0), **_phases("p", 900, 900, 900)}, commands={"i"})
    meter.latest_snapshot["commands"]["active_power"] = {"captured_at": (NOW - timedelta(hours=3)).isoformat(),
                                                         "quality": "STALE", "fields": []}
    assert _status(meter)["code"] == "OFF"


def test_voltage_only_is_not_enough():
    meter = SimpleNamespace(latest_snapshot={"values": {"u_a": 230.0, "u_b": 231.0, "u_c": 229.0},
                                             "commands": {"voltage_phases": {"captured_at": NOW.isoformat(), "quality": "GOOD"}},
                                             "updated_at": NOW.isoformat()})
    assert _status(meter, device=_device(created=timedelta(minutes=5)))["code"] == "PROBLEM"
    result = _status(meter)
    assert (result["code"], result["last_success_at"]) == ("CRITICAL", None)


def test_never_polled_device_is_problem_then_critical_from_first_detection():
    fresh = _status(None, device=_device(created=timedelta(minutes=24)))
    assert (fresh["code"], fresh["reason"], fresh["no_data_seconds"]) == ("PROBLEM", "Mercury ещё не передал показания", 24 * 60)
    old = _status(None, device=_device(created=timedelta(hours=1, minutes=18)))
    assert (old["code"], old["no_data_seconds"]) == ("CRITICAL", 78 * 60)


def test_last_success_is_latest_light_command_capture():
    meter = _meter(_phases("i", 0, 0, 0), commands={"i"})
    meter.latest_snapshot["commands"]["active_power"] = {"captured_at": (NOW - timedelta(minutes=5)).isoformat(),
                                                         "quality": "STALE", "fields": []}
    assert status.last_successful_response(meter.latest_snapshot) == NOW


def test_naive_legacy_snapshot_without_commands_is_problem():
    meter = SimpleNamespace(latest_snapshot={"i_a": 5.0, "i_b": 5.0, "i_c": 5.0})
    assert _status(meter)["code"] in {"PROBLEM", "CRITICAL"}


def test_critical_threshold_comes_from_config(app):
    app.config["IRZ_CRITICAL_AFTER_SECONDS"] = 600
    with app.app_context():
        assert _status(_meter(_phases("i", 5, 5, 5), age=timedelta(minutes=11), quality="STALE"))["code"] == "CRITICAL"


@pytest.mark.parametrize("name,expected", [
    ("ИП Чехова 8", "IP"), ("  ип-12", "IP"), ("ПП Ленина", "PP"), ("пп 3", "PP"),
    ("ТП 12", "OTHER"), ("Пункт питания", "OTHER"), ("", "OTHER"), (None, "OTHER"),
])
def test_cabinet_type_by_name_prefix(name, expected):
    assert status.cabinet_type(name) == expected
