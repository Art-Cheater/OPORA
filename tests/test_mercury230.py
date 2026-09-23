"""Mercury 230 read-only commands: exact TX, parsers, scaling and error handling.

Examples are taken from the official Incotex protocol description (06.2024).
"""
from decimal import Decimal

import mercury_base
import pytest
from modbus_crc import add_crc, check_crc

from app.modem_gateway.mercury import MercuryGatewayError, MercurySessionManager
from app.modem_gateway.mercury230 import MercuryStatusError, decode_status_word, execute
from app.modules.irz.commands import COMMANDS, poll_commands


class Meter:
    """Parser-level fake: responses keyed by the command bytes after the address."""

    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def send_command(self, *params, response_length=None):
        self.requests.append(params)
        answer = self.responses[params]
        if isinstance(answer, int):
            raise MercuryStatusError(answer)
        if isinstance(answer, Exception):
            raise answer
        return answer


class WireSession:
    """Wire-level fake ATM21 session: full TX frame (with CRC) → full RX frame."""
    imei = "123456789012345"

    def __init__(self, script):
        self.script = {bytes.fromhex(tx): rx for tx, rx in script.items()}
        self.sent, self.logged, self.expected = [], [], []

    def ask_mercury(self, package, timeout, expected_length=None, log_package=None):
        self.sent.append(bytes(package))
        self.logged.append(bytes(log_package or package))
        self.expected.append(expected_length)
        answer = self.script.get(bytes(package))
        if answer is None or isinstance(answer, Exception):
            raise answer or TimeoutError()
        return bytes.fromhex(answer) if isinstance(answer, str) else answer


class Registry:
    def __init__(self, session): self.session = session
    def get(self, imei): return self.session if self.session and imei == self.session.imei else None


def frame(hex_value):
    return add_crc(bytes.fromhex(hex_value)).hex(" ")


def manager(script):
    session = WireSession(script)
    return MercurySessionManager(Registry(session), lambda: mercury_base), session


# --- exact TX with CRC (address 0) -------------------------------------------------

EXACT_TX = {
    "voltage_phases": "00 08 16 11 4F 8A",
    "current_phases": "00 08 16 21 4F 9E",
    "active_power": "00 08 16 00 8F 86",
    "reactive_power": "00 08 16 04 8E 45",
    "apparent_power": "00 08 16 08 8E 40",
    "power_factor": "00 08 16 30 8F 92",
    "frequency": "00 08 11 40 8C 46",
    "phase_angles": "00 08 16 51 4E 7A",
    "energy_current": "00 05 00 00 10 25",
    "meter_time": "00 04 00 73 00",
    "status_word": "00 08 0A F6 07",
    "transformation_ratios": "00 08 02 F7 C1",
}


@pytest.mark.parametrize("command_id,tx", EXACT_TX.items())
def test_exact_tx_frame_and_crc(command_id, tx):
    assert check_crc(bytes.fromhex(tx))
    manager_, session = manager({})
    with pytest.raises(MercuryGatewayError):
        manager_.execute(session.imei, 0, command_id)
    assert session.sent[0] == bytes.fromhex(tx)
    assert session.expected[0] == COMMANDS[command_id].response_length + 3


# --- scaling and units -------------------------------------------------------------

def test_voltage_current_frequency_scaling():
    meter = Meter({
        (0x08, 0x16, 0x11): [0x00, 0xD8, 0x59] * 3,
        (0x08, 0x16, 0x21): [0x00, 0xD2, 0x04] * 3,
        (0x08, 0x11, 0x40): [0x00, 0x87, 0x13],
    })
    assert execute(meter, "voltage_phases") == {"a": Decimal("230"), "b": Decimal("230"), "c": Decimal("230")}
    assert execute(meter, "current_phases") == {"a": Decimal("1.234"), "b": Decimal("1.234"), "c": Decimal("1.234")}
    assert execute(meter, "frequency") == {"value": Decimal("49.99")}
    assert COMMANDS["voltage_phases"].units == "V" and COMMANDS["current_phases"].units == "A"
    assert COMMANDS["frequency"].units == "Hz"


def test_power_total_and_phases_with_direction_bits():
    meter = Meter({
        (0x08, 0x16, 0x00): [0x80, 0xE7, 0x29, 0x00, 0xE7, 0x29, 0x80, 0x10, 0x00, 0x00, 0x00, 0x00],
        (0x08, 0x16, 0x04): [0x40, 0xE7, 0x29] + [0x00, 0x00, 0x00] * 3,
        (0x08, 0x16, 0x08): [0x00, 0xE7, 0x29] * 4,
        (0x08, 0x16, 0x30): [0x40, 0x2D, 0x02] * 4,
    })
    active = execute(meter, "active_power")
    assert active == {"total": Decimal("-107.27"), "a": Decimal("107.27"), "b": Decimal("-0.16"), "c": Decimal("0")}
    assert execute(meter, "reactive_power")["total"] == Decimal("-107.27")
    assert execute(meter, "apparent_power")["c"] == Decimal("107.27")
    assert execute(meter, "power_factor")["total"] == Decimal("0.557")
    assert COMMANDS["active_power"].units == "W" and COMMANDS["reactive_power"].units == "var"
    assert COMMANDS["apparent_power"].units == "VA"


def test_zero_values_stay_zero_not_missing():
    meter = Meter({(0x08, 0x16, 0x21): [0x00, 0x00, 0x00] * 3})
    assert execute(meter, "current_phases") == {"a": 0, "b": 0, "c": 0}


def test_phase_angles_from_group_request():
    meter = Meter({(0x08, 0x16, 0x51): [0x00, 0xE0, 0x2E, 0x00, 0xC0, 0x5D, 0x00, 0xE0, 0x2E]})
    assert execute(meter, "phase_angles") == {"ab": Decimal("120"), "ac": Decimal("240"), "bc": Decimal("120")}


def test_unsupported_group_request_falls_back_to_single_phase_reads():
    meter = Meter({
        (0x08, 0x16, 0x11): 0x01,
        (0x08, 0x11, 0x11): [0x00, 0xD8, 0x59],
        (0x08, 0x11, 0x12): [0x00, 0xD8, 0x59],
        (0x08, 0x11, 0x13): [0x00, 0x00, 0x00],
        (0x08, 0x16, 0x00): 0x01,
        (0x08, 0x11, 0x00): [0x00, 0x10, 0x00],
        (0x08, 0x11, 0x01): [0x00, 0x10, 0x00],
        (0x08, 0x11, 0x02): [0x00, 0x00, 0x00],
        (0x08, 0x11, 0x03): [0x00, 0x00, 0x00],
    })
    assert execute(meter, "voltage_phases") == {"a": Decimal("230"), "b": Decimal("230"), "c": 0}
    assert execute(meter, "active_power")["total"] == Decimal("0.16")


def test_energy_totals_tariffs_and_masked_values():
    block = [0x00, 0x00, 0x2C, 0x36, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x2F, 0x07, 0x00, 0x00, 0x00, 0x00]
    meter = Meter({
        (0x05, 0x00, 0x00): block,
        (0x05, 0x00, 0x01): block, (0x05, 0x00, 0x02): block,
        (0x05, 0x00, 0x03): 0x01, (0x05, 0x00, 0x04): block,
    })
    assert execute(meter, "energy_current") == {"a_plus": 13868, "a_minus": None, "r_plus": 1839, "r_minus": 0}
    tariffs = execute(meter, "energy_tariffs")
    assert tariffs["t1"]["a_plus"] == 13868 and tariffs["t3"] is None and tariffs["t4"]["r_minus"] == 0


def test_energy_archive_request_bytes_and_parameter_validation():
    block = [0x00] * 16
    meter = Meter({(0x05, 0x33, 0x02): block, (0x05, 0x40, 0x00): block})
    assert execute(meter, "energy_archive", {"period": "month", "month": 3, "tariff": 2})["a_plus"] == 0
    assert execute(meter, "energy_archive", {"period": "day"})["period"] == "day"
    assert meter.requests == [(0x05, 0x33, 0x02), (0x05, 0x40, 0x00)]
    for params in ({"period": "week"}, {"period": "month", "month": 13}, {"period": "year", "tariff": 5}):
        with pytest.raises(KeyError):
            execute(meter, "energy_archive", params)


def test_meter_time_official_example():
    meter = Meter({(0x04, 0x00): [0x20, 0x55, 0x11, 0x01, 0x21, 0x01, 0x08, 0x01]})
    assert execute(meter, "meter_time") == {"value": "2008-01-21T11:55:20", "weekday": 1, "season": "winter"}


def test_meter_time_rejects_invalid_bcd():
    meter = Meter({(0x04, 0x00): [0x6A, 0x55, 0x11, 0x01, 0x21, 0x01, 0x08, 0x01]})
    with pytest.raises(ValueError, match="UNKNOWN_RESPONSE_FORMAT"):
        execute(meter, "meter_time")


def test_status_word_maps_self_diagnostics():
    assert decode_status_word([0] * 6) == {"raw": "00 00 00 00 00 00", "ok": True, "errors": []}
    decoded = decode_status_word([0x00, 0x00, 0x00, 0x00, 0x01, 0x00])
    assert decoded["ok"] is False and [item["code"] for item in decoded["errors"]] == ["E-01"]
    assert decoded["errors"][0]["text"]
    second_row = decode_status_word([0x00, 0x00, 0x00, 0x00, 0x00, 0x80])
    assert second_row["errors"][0]["code"] == "E-16"


def test_events_read_last_records_and_isolate_unsupported_journals():
    responses = {(0x04, number, 0xFF): 0x01 for number in range(0x00, 0x20)}
    responses[(0x04, 0x01, 0xFF)] = [0x00, 0x30, 0x10, 0x21, 0x01, 0x26, 0x05, 0x31, 0x10, 0x21, 0x01, 0x26, 0x07]
    responses[(0x04, 0x14, 0xFF)] = [0x00, 0x00, 0x09, 0x22, 0x09, 0x26, 0, 0, 0, 0, 0x01, 0, 0x02]
    result = execute(Meter(responses), "events")
    journals = {item["journal"]: item for item in result["journals"]}
    assert journals["meter_power"]["status"] == "GOOD"
    assert journals["meter_power"]["start"] == "2026-01-21T10:30:00"
    assert journals["meter_power"]["record"] == 7
    status_journal = next(item for item in result["journals"] if item["number"] == "14")
    assert status_journal["status_word"]["errors"][0]["code"] == "E-01"
    assert any(item["status"] == "UNSUPPORTED" for item in result["journals"])


def test_events_stop_after_two_consecutive_timeouts():
    timeout = MercuryGatewayError("MERCURY_TIMEOUT", "timeout", 504)
    meter = Meter({(0x04, number, 0xFF): timeout for number in range(0x00, 0x20)})
    assert len(execute(meter, "events")["journals"]) == 2


def test_events_propagate_closed_channel():
    meter = Meter({(0x04, number, 0xFF): 0x05 for number in range(0x00, 0x20)})
    with pytest.raises(MercuryStatusError) as error:
        execute(meter, "events")
    assert error.value.code == "CHANNEL_NOT_OPEN"


def test_short_response_is_rejected_without_fabricating_value():
    meter = Meter({(0x08, 0x16, 0x11): [0, 1]})
    with pytest.raises(ValueError, match="UNKNOWN_RESPONSE_FORMAT"):
        execute(meter, "voltage_phases")


def test_device_info_decodes_capabilities_but_not_a_guessed_marking():
    meter = Meter({(0x08, 0x12): [0xB4, 0xE3, 0xC2, 0x97, 0xDF, 0x58]})
    value = execute(meter, "device_info")
    assert meter.requests == [(0x08, 0x12)]
    assert value["raw"] == "B4 E3 C2 97 DF 58"
    assert value["three_phase"] is True and value["profile_supported"] is True and value["rs485"] is True


# --- wire level: valid RX, invalid CRC, short packet, timeout, status frames ------

def test_wire_voltage_valid_rx_is_parsed():
    manager_, session = manager({EXACT_TX["voltage_phases"]: frame("00 00 D8 59 00 D8 59 00 00 00")})
    result = manager_.execute(session.imei, 0, "voltage_phases")
    assert result["data"] == {"a": "230", "b": "230", "c": "0"}
    assert result["exchanges"] == [{"tx": EXACT_TX["voltage_phases"].upper(), "rx": frame("00 00 D8 59 00 D8 59 00 00 00").upper()}]


def test_wire_invalid_crc_is_rejected():
    broken = bytearray(bytes.fromhex(frame("00 00 D8 59 00 D8 59 00 00 00"))); broken[-1] ^= 0xFF
    manager_, session = manager({EXACT_TX["voltage_phases"]: bytes(broken)})
    with pytest.raises(MercuryGatewayError) as error:
        manager_.execute(session.imei, 0, "voltage_phases")
    assert error.value.code == "CRC_ERROR"


def test_wire_short_packet_is_rejected():
    manager_, session = manager({EXACT_TX["voltage_phases"]: frame("00 00 D8 59")})
    with pytest.raises(MercuryGatewayError) as error:
        manager_.execute(session.imei, 0, "voltage_phases")
    assert error.value.code == "UNKNOWN_RESPONSE_FORMAT"


def test_wire_timeout():
    manager_, session = manager({})
    with pytest.raises(MercuryGatewayError) as error:
        manager_.execute(session.imei, 0, "frequency")
    assert error.value.code == "MERCURY_TIMEOUT"


def test_wire_unsupported_status_frame():
    manager_, session = manager({EXACT_TX["frequency"]: frame("00 01")})
    with pytest.raises(MercuryGatewayError) as error:
        manager_.execute(session.imei, 0, "frequency")
    assert error.value.code == "UNSUPPORTED"


def test_closed_channel_is_opened_with_masked_password_and_retried(monkeypatch):
    monkeypatch.setenv("MERCURY_LEVEL1_PASSWORD", "111111")
    monkeypatch.setenv("MERCURY_PASSWORD_ENCODING", "hex")
    open_tx = frame("00 01 01 01 01 01 01 01 01")

    class Session(WireSession):
        opened = False
        def ask_mercury(self, package, timeout, expected_length=None, log_package=None):
            if bytes(package) == bytes.fromhex(open_tx):
                Session.opened = True
            elif bytes(package) == bytes.fromhex(EXACT_TX["frequency"]) and not Session.opened:
                self.sent.append(bytes(package)); self.logged.append(bytes(log_package or package)); self.expected.append(expected_length)
                return bytes.fromhex(frame("00 05"))
            return super().ask_mercury(package, timeout, expected_length, log_package)

    session = Session({open_tx: frame("00 00"), EXACT_TX["frequency"]: frame("00 00 87 13")})
    result = MercurySessionManager(Registry(session), lambda: mercury_base).execute(session.imei, 0, "frequency")
    assert result["data"] == {"value": "49.99"}
    assert session.sent == [bytes.fromhex(EXACT_TX["frequency"]), bytes.fromhex(open_tx), bytes.fromhex(EXACT_TX["frequency"])]
    masked = session.logged[1]
    assert masked[3:9] == b"\x2a" * 6 and masked[:3] == bytes.fromhex("00 01 01")
    assert all(b"\x01\x01\x01\x01\x01\x01" not in item for item in session.logged)


def test_poll_is_partial_and_keeps_successful_commands(monkeypatch):
    monkeypatch.setenv("MERCURY_PASSWORD_ENCODING", "hex")
    script = {
        frame("00 01 01 01 01 01 01 01 01"): frame("00 00"),
        "00 08 00 76 00": "00 24 4F 01 3C 0A 02 13 7B 09",
        "00 08 03 36 01": "00 02 03 05 61 17",
        EXACT_TX["voltage_phases"]: frame("00 00 D8 59 00 D8 59 00 D8 59"),
        EXACT_TX["frequency"]: frame("00 00 87 13"),
    }
    manager_, session = manager(script)
    result = manager_.poll(session.imei, 0)
    assert result["success"] is True and result["partial"] is True
    assert result["results"]["voltage_phases"]["data"]["a"] == "230"
    assert result["results"]["firmware_version"]["data"] == "2.3.5"
    assert result["results"]["frequency"]["data"] == {"value": "49.99"}
    errors = {item["command"]: item["error_code"] for item in result["errors"]}
    assert errors["transformation_ratios"] == "MERCURY_TIMEOUT" and errors["current_phases"] == "MERCURY_TIMEOUT"
    skipped = [item["command"] for item in result["errors"] if item["error_code"] == "SKIPPED"]
    assert skipped[0] == "apparent_power"


def test_poll_aborts_after_two_timeouts_and_skips_the_rest(monkeypatch):
    monkeypatch.setenv("MERCURY_PASSWORD_ENCODING", "hex")
    manager_, session = manager({"00 08 00 76 00": "00 24 4F 01 3C 0A 02 13 7B 09"})
    result = manager_.poll(session.imei, 0)
    assert list(result["results"]) == ["serial_and_manufacture"]
    skipped = [item["command"] for item in result["errors"] if item["error_code"] == "SKIPPED"]
    assert skipped and skipped[-1] == "status_word"
    assert len(session.sent) < len(poll_commands()) + 2


def test_poll_order_is_read_only_and_complete():
    ids = [command.id for command in poll_commands()]
    for command_id in ("voltage_phases", "current_phases", "active_power", "reactive_power", "apparent_power",
                       "power_factor", "frequency", "phase_angles", "energy_current", "energy_tariffs",
                       "meter_time", "status_word"):
        assert command_id in ids
    assert "events" not in ids and "energy_archive" not in ids
    assert all(COMMANDS[item].mode == "read" and not COMMANDS[item].dangerous for item in ids)
    assert all(COMMANDS[item].source for item in ids)
