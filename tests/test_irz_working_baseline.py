"""Regression locks for the physically verified ATM21 -> Mercury path."""
import json
from pathlib import Path

import mercury_base
import pytest
from modbus_crc import check_crc

from app.modem_gateway.mercury import MercurySessionManager


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "irz_mercury_verified.json").read_text(encoding="utf-8"))


class VerifiedSession:
    imei = "868441036775234"

    def __init__(self, expected_tx: str, response: str):
        self.expected_tx = bytes.fromhex(expected_tx)
        self.response = bytes.fromhex(response)
        self.sent = []

    def ask_mercury(self, package: bytes, timeout: float) -> bytes:
        assert timeout == 5.0
        self.sent.append(package)
        assert package == self.expected_tx
        return self.response


class Registry:
    def __init__(self, session): self.session = session
    def get(self, imei): return self.session if imei == self.session.imei else None


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda item: item["command"])
def test_physically_verified_address_zero_packets_and_parsers(fixture):
    session = VerifiedSession(fixture["tx"], fixture["rx"])
    result = MercurySessionManager(Registry(session), lambda: mercury_base).execute(session.imei, 0, fixture["command"])
    assert check_crc(bytes.fromhex(fixture["tx"]))
    assert check_crc(bytes.fromhex(fixture["rx"]))
    assert result["data"] == fixture["expected"]


def test_broken_real_response_crc_is_rejected():
    fixture = FIXTURES[0]
    broken = bytearray.fromhex(fixture["rx"]); broken[-1] ^= 0xFF
    session = VerifiedSession(fixture["tx"], broken.hex(" "))
    with pytest.raises(Exception) as error:
        MercurySessionManager(Registry(session), lambda: mercury_base).execute(session.imei, 0, fixture["command"])
    assert getattr(error.value, "code", None) == "CRC_ERROR"


def test_board_and_irz_ports_remain_separate():
    root = Path(__file__).parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    production = (root / "docker-compose.timeweb.example.yml").read_text(encoding="utf-8")
    assert "tcp-gateway:" in production
    assert '"5000:5000"' in production
    assert 'app.tcp_gateway.main' in production
    assert "MODEM_SNIFFER_PORT: 5009" in compose
    assert '"5009:5009"' in compose
    assert "app.modem_gateway.sniffer" in compose
    assert '"5009:5009"' not in production
    assert "app.tcp_gateway" not in (Path(__file__).parents[1] / "app" / "modem_gateway" / "sniffer.py").read_text(encoding="utf-8")
