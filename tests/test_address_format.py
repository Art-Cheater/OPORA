"""Тесты нормализации адресов заявок."""

from app.modules.requests.address_format import format_address, normalize_address


def test_format_simple_street_house():
    assert format_address("лепсе 79") == "Киров, улица Лепсе, дом 79"
    assert format_address("Лепсе 79а") == "Киров, улица Лепсе, дом 79а"
    assert format_address("лепсе79") == "Киров, улица Лепсе, дом 79"


def test_format_with_prefixes():
    assert format_address("ул. Лепсе д. 79") == "Киров, улица Лепсе, дом 79"
    assert format_address("пр. Октябрьский 12") == "Киров, проспект Октябрьский, дом 12"
    assert format_address("Киров, улица Лепсе, дом 79") == "Киров, улица Лепсе, дом 79"


def test_normalize_matches_variants():
    a = normalize_address("лепсе 79")
    b = normalize_address("ул. Лепсе, д.79")
    c = normalize_address("Киров, улица Лепсе, дом 79")
    assert a == b == c
