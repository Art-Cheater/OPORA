from decimal import Decimal

import pytest

from app.modem_gateway.mercury230 import execute


class Meter:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def send_command(self, *params):
        self.requests.append(params)
        return self.responses[params]


def test_voltage_current_frequency_exact_requests_and_scaling():
    meter = Meter({
        (0x08, 0x14, 0x11): [0x00, 0xD8, 0x59] * 3,
        (0x08, 0x14, 0x21): [0x00, 0xD2, 0x04] * 3,
        (0x08, 0x11, 0x40): [0x00, 0x87, 0x13],
    })
    assert execute(meter, "voltage_phases") == {"a": Decimal("230"), "b": Decimal("230"), "c": Decimal("230")}
    assert execute(meter, "current_phases") == {"a": Decimal("1.234"), "b": Decimal("1.234"), "c": Decimal("1.234")}
    assert execute(meter, "frequency") == {"value": Decimal("49.99")}
    assert meter.requests == [(0x08, 0x14, 0x11), (0x08, 0x14, 0x21), (0x08, 0x11, 0x40)]


def test_power_factor_and_power_byte_order_from_official_examples():
    meter = Meter({
        (0x08, 0x14, 0x30): [0x40, 0x2D, 0x02] * 4,
        (0x08, 0x14, 0x08): [0x00, 0x40, 0xE7, 0x29] * 4,
    })
    assert execute(meter, "power_factor")["total"] == Decimal("0.557")
    assert execute(meter, "apparent_power")["total"] == Decimal("107.27")


def test_phase_angles_are_individual_safe_reads():
    meter = Meter({
        (0x08, 0x11, 0x51): [0x00, 0xE0, 0x2E],
        (0x08, 0x11, 0x52): [0x00, 0xC0, 0x5D],
        (0x08, 0x11, 0x53): [0x00, 0xE0, 0x2E],
    })
    assert execute(meter, "phase_angles") == {"ab": Decimal("120"), "ac": Decimal("240"), "bc": Decimal("120")}


def test_short_or_unknown_response_is_rejected_without_fabricating_value():
    meter = Meter({(0x08, 0x14, 0x11): [0, 1]})
    with pytest.raises(ValueError, match="UNKNOWN_RESPONSE_FORMAT"):
        execute(meter, "voltage_phases")


def test_device_info_decodes_capabilities_but_not_a_guessed_marking():
    meter = Meter({(0x08, 0x12): [0xB4, 0xE3, 0xC2, 0x97, 0xDF, 0x58]})
    value = execute(meter, "device_info")
    assert meter.requests == [(0x08, 0x12)]
    assert value["raw"] == "B4 E3 C2 97 DF 58"
    assert value["three_phase"] is True
    assert value["profile_supported"] is True
    assert value["rs485"] is True
