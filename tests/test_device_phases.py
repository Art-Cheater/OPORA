"""CON9/CON10/CON11 phase masks on protocol v2 and the boards page."""

from pathlib import Path

import pytest

from app.extensions import db
from app.models.base import utcnow
from app.models.devices import Device
from app.models.devices.state import (
    apply_input_test_sample,
    connector_pins,
    decode_raw_bank,
    describe_input_test,
    mark_input_switch,
    normalize_phase_input_map,
    observe_raw_bits,
    phase_summary_from_connectors,
    phase_view_from_map,
    start_input_test,
)
from app.tcp_gateway.protocol import parse_v2_state
from tests.test_devices_ui import _device


def test_v2_state_parses_connector_masks_and_keeps_outputs():
    actual, telemetry = parse_v2_state("STATE O=5 C9=2D C10=3F C11=00 CSQ=20".split()[1:])
    assert actual["outputs"] == {"C6": 1, "C7": 0, "C8": 1}
    assert actual["raw"]["C9"] == "2D"
    assert actual["raw"]["C10"] == "3F"
    assert actual["raw"]["C11"] == "00"
    assert actual["connectors"]["CON9"]["1"] == {"phase": "A", "value": 1}
    assert actual["connectors"]["CON9"]["2"] == {"phase": "B", "value": 0}
    assert actual["connectors"]["CON10"]["6"] == {"phase": "C", "value": 1}
    assert actual["connectors"]["CON11"]["1"] == {"phase": "A", "value": 0}
    assert telemetry == {"csq": 20}
    assert "c9" not in telemetry


def test_c9_bits_map_pin_and_phase():
    pins = connector_pins(0x2D)
    assert pins == {
        "1": {"phase": "A", "value": 1},
        "2": {"phase": "B", "value": 0},
        "3": {"phase": "C", "value": 1},
        "4": {"phase": "A", "value": 1},
        "5": {"phase": "B", "value": 0},
        "6": {"phase": "C", "value": 1},
    }


def test_phase_mask_above_six_bits_is_rejected():
    with pytest.raises(ValueError):
        parse_v2_state(["C9=40"])
    with pytest.raises(ValueError):
        parse_v2_state(["C10=FF"])


def test_state_without_connector_masks_stays_compatible():
    actual, telemetry = parse_v2_state("O=5 U2=EF U3=A6 CSQ=20 CREG=1 CGATT=1".split())
    assert "connectors" not in actual
    assert "phase_summary" not in actual
    assert actual["outputs"] == {"C6": 1, "C7": 0, "C8": 1}
    assert actual["raw"] == {"U2": "EF", "U3": "A6"}
    assert telemetry == {"csq": 20, "creg": 1, "cgatt": 1}


def test_phase_summary_counts_active_pins():
    actual, _telemetry = parse_v2_state(["C9=2D", "C10=3F", "C11=00"])
    assert actual["phase_summary"] == phase_summary_from_connectors(actual["connectors"])
    assert actual["phase_summary"] == {
        "A": {"active": 4, "total": 6},
        "B": {"active": 2, "total": 6},
        "C": {"active": 4, "total": 6},
    }


def test_status_api_returns_connectors_and_page_renders_pins(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.connection_state = "online"
        device.last_state_at = utcnow()
        actual, _telemetry = parse_v2_state(["O=5", "C9=2D", "C10=3F", "C11=00"])
        device.actual_state = actual
        db.session.commit()

    payload = admin_client.get("/devices/status").get_json()["devices"][0]
    assert payload["actual_state"]["raw"]["C9"] == "2D"
    assert payload["actual_state"]["connectors"]["CON9"]["1"]["phase"] == "A"
    assert payload["actual_state"]["phase_summary"]["A"] == {"active": 4, "total": 6}

    page = admin_client.get("/devices/").get_data(as_text=True)
    assert "Фазы / входы" in page
    for name in ("CON9", "CON10", "CON11"):
        assert name in page
    assert 'data-phase-pin="CON9.1"' in page
    assert "Pin 1" in page and "Не настроено" in page
    assert "RAW INPUT MAP" in page
    assert "Включить" in page


def test_missing_connector_data_does_not_break_the_boards_page(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.connection_state = "online"
        device.last_state_at = utcnow()
        device.actual_state = {"outputs": {"C6": 1, "C7": 0, "C8": 1}, "inputs": {"SW2": 0}, "raw": {"U2": "01"}}
        db.session.commit()
    page = admin_client.get("/devices/").get_data(as_text=True)
    assert "Фазы / входы" in page
    assert "Не настроено" in page
    assert "C6" in page and "C7" in page and "C8" in page
    payload = admin_client.get("/devices/status").get_json()["devices"][0]
    assert "connectors" not in payload["actual_state"]


def test_phase_ui_updates_from_the_existing_status_poll():
    script = Path("app/static/js/devices.js").read_text(encoding="utf-8")
    assert "function renderDiagnostics(" in script
    assert "renderDiagnostics(card, device);" in script
    assert "root.dataset.statusUrl" in script
    assert "dataset.phasePin" in script
    assert "is-changed" in script
    assert "location.reload" not in script


def test_u2_hex_decodes_to_bits():
    assert decode_raw_bank("EF") == {"0": 1, "1": 1, "2": 1, "3": 1, "4": 0, "5": 1, "6": 1, "7": 1}
    assert decode_raw_bank("00")["7"] == 0


def test_connector_map_can_share_one_raw_bit_and_honours_active_level():
    mapping = normalize_phase_input_map({
        "CON9": {"1": {"source": "U2", "bit": 3, "active_level": 0, "confirmed": True}},
        "CON10": {"4": {"source": "U2", "bit": 3, "active_level": 1, "confirmed": True}},
        "CON11": {"2": {"source": "U3", "bit": 1, "active_level": 1, "confirmed": False}},
    })
    assert mapping["CON9"]["1"]["bit"] == mapping["CON10"]["4"]["bit"] == 3
    assert mapping["CON9"]["1"]["phase"] == "A"
    assert mapping["CON10"]["4"]["phase"] == "A"
    assert mapping["CON11"]["2"]["confirmed"] is False
    view = phase_view_from_map({"raw": {"U2": "00", "U3": "FF"}}, mapping)
    assert view["CON9"]["1"]["active"] is True
    assert view["CON10"]["4"]["active"] is False
    assert view["CON11"]["2"]["configured"] is False
    assert view["CON9"]["2"]["configured"] is False


def test_unconfirmed_mapping_is_not_a_phase_display():
    mapping = normalize_phase_input_map({"CON9": {"1": {"source": "U2", "bit": 0, "active_level": 1, "confirmed": False}}})
    view = phase_view_from_map({"raw": {"U2": "01"}}, mapping)
    assert view["CON9"]["1"]["configured"] is False
    assert "active" not in view["CON9"]["1"]


def test_raw_bit_change_is_recorded_without_changing_state_words():
    first = observe_raw_bits(None, {"raw": {"U2": "01", "U3": "00"}, "outputs": {"C6": 1}}, "t1")
    second = observe_raw_bits(first, {"raw": {"U2": "00", "U3": "00"}, "outputs": {"C6": 1}}, "t2")
    assert second["raw_bits"]["U2"]["0"] == 0
    assert second["raw_bit_changes"]["U2"]["0"] == {"from": 1, "to": 0, "at": "t2"}
    assert second["outputs"] == {"C6": 1}


def test_saved_phase_map_drives_the_boards_page(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.connection_state = "online"
        device.last_state_at = utcnow()
        device.actual_state = {"outputs": {"C6": 0, "C7": 0, "C8": 0}, "raw": {"U2": "08", "U3": "00"}, "raw_bits": {"U2": decode_raw_bank("08")}}
        db.session.commit()
    saved = admin_client.post(
        f"/devices/{device_id}/phase-map",
        data={"CON9.1.source": "U2", "CON9.1.bit": "3", "CON9.1.active_level": "1", "CON9.1.confirmed": "1", "CON9.4.source": "U2", "CON9.4.bit": "3", "CON9.4.active_level": "1", "CON9.4.confirmed": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert saved.status_code == 200
    body = saved.get_json()
    assert body["phase_view"]["CON9"]["1"]["active"] is True
    assert body["phase_view"]["CON9"]["4"]["active"] is True
    assert body["phase_view"]["CON9"]["2"]["configured"] is False
    status = admin_client.get("/devices/status").get_json()["devices"][0]
    assert status["phase_view"]["CON9"]["1"]["active"] is True
    assert status["phase_view"]["CON9"]["4"]["source"] == "U2"
    page = admin_client.get("/devices/").get_data(as_text=True)
    assert 'data-phase-pin="CON9.1"' in page and "Не настроено" in page


def _feed(session, u2, u3, count, stamp):
    for index in range(count):
        session = apply_input_test_sample(session, {"U2": u2, "U3": u3}, f"{stamp}{index}")
    return session


def test_stable_baseline_needs_three_identical_states():
    session = start_input_test({"U2": "00", "U3": "00"}, "CON10", "4", "t0")
    assert describe_input_test(session)["baseline_ready"] is False
    session = _feed(session, "EF", "FF", 2, "b")
    assert session["phase"] == "baseline"
    session = _feed(session, "EF", "FF", 1, "c")
    view = describe_input_test(session)
    assert view["baseline_ready"] is True
    assert view["baseline_u2"] == "EF" and view["baseline_u3"] == "FF"


def test_single_stable_transition_offers_mapping_without_saving_it(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.actual_state = {"raw": {"U2": "EF", "U3": "FF"}}
        device.connection_state = "online"
        device.last_state_at = utcnow()
        db.session.commit()
    assert admin_client.post(f"/devices/{device_id}/input-test/start", data={"connector": "CON10", "pin": "4"}).status_code == 200
    with app.app_context():
        device = db.session.get(Device, device_id)
        session = _feed(device.input_test_session, "EF", "FF", 3, "b")
        assert session["phase"] == "armed"
        device.input_test_session = session
        db.session.commit()
    assert admin_client.post(f"/devices/{device_id}/input-test/capture").status_code == 200
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.actual_state = {"raw": {"U2": "EF", "U3": "FB"}}
        device.input_test_session = _feed(device.input_test_session, "EF", "FB", 3, "a")
        db.session.commit()
        assert device.phase_input_map is None
    view = admin_client.get("/devices/status").get_json()["devices"][0]["input_test"]["active"]
    assert view["verdict"] == "RESULT"
    assert view["stable"] == [{"label": "U3.bit2", "source": "U3", "bit": 2, "from": 1, "to": 0}]
    assert view["candidate"]["active_level"] == 0
    confirmed = admin_client.post(f"/devices/{device_id}/input-test/confirm", data={"active_level": "0"})
    assert confirmed.get_json()["phase_input_map"]["CON10"]["4"]["confirmed"] is True
    assert confirmed.get_json()["phase_input_map"]["CON10"]["4"]["bit"] == 2


def test_flicker_is_not_a_stable_change_and_several_bits_are_ambiguous():
    session = _feed(start_input_test({"U2": "EF", "U3": "FF"}, "CON10", "4", "t0"), "EF", "FF", 3, "b")
    session = mark_input_switch(session)
    session = apply_input_test_sample(session, {"U2": "EF", "U3": "FE"}, "n0")
    session = apply_input_test_sample(session, {"U2": "EF", "U3": "FF"}, "n1")
    session = apply_input_test_sample(session, {"U2": "EF", "U3": "FE"}, "n2")
    assert describe_input_test(session)["verdict"] == "NO CHANGE"
    assert describe_input_test(session)["lines"]
    noisy = _feed(start_input_test({"U2": "EF", "U3": "FF"}, "CON9", "1", "t0"), "EF", "FF", 3, "b")
    noisy = _feed(mark_input_switch(noisy), "EF", "F9", 3, "a")
    view = describe_input_test(noisy)
    assert view["verdict"] == "AMBIGUOUS"
    assert view["candidate"] is None
    assert {item["label"] for item in view["stable"]} == {"U3.bit1", "U3.bit2"}
