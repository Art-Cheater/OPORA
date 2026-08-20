"""Разбор HTML ЕИС по фикстурам, без сети и без записи в Опору."""

from pathlib import Path

from app.integrations.zakupki.parse import (
    eis_number_year,
    in_eis_year_range,
    is_supplier_defined,
    keep_eis_listing,
    parse_contract_card,
    parse_contract_search,
    parse_money,
    parse_order_notice,
    parse_order_results,
    parse_order_search,
    parse_purchase_objects,
    split_purchase_object_names,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "zakupki"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_contract_search_links_and_stage():
    listing = parse_contract_search(_html("contract_search.html"))
    assert listing["total"] == 137
    numbers = [item["reestr_number"] for item in listing["items"]]
    assert numbers[:2] == ["3434528856325000226", "3434528856326000110"]
    assert listing["items"][0]["stage"] == "Исполнение"
    assert listing["items"][0]["listed_date"].isoformat() == "2025-11-18"
    assert listing["items"][0]["url"].endswith(
        "common-info.html?reestrNumber=3434528856325000226"
    )


def test_parse_contract_card_fields_and_suppliers():
    contract = parse_contract_card(
        _html("contract_card.html"),
        "3434528856325000213",
        "https://zakupki.gov.ru/epz/contract/contractCard/common-info.html"
        "?reestrNumber=3434528856325000213",
    )
    assert contract.number == "Ф.2025.001724"
    assert contract.contract_date.isoformat() == "2025-10-27"
    assert contract.start_date.isoformat() == "2025-10-27"
    assert contract.end_date.isoformat() == "2026-08-22"
    assert contract.amount is not None
    assert str(contract.amount) == "2511041.28"
    assert "Студенец" in (contract.subject or "")
    assert "Студенец" in (contract.delivery_place or "")
    names = [item.name for item in contract.suppliers]
    assert any("КИРОВЭНЕРГО" in name for name in names)
    assert any("РОССЕТИ ЦЕНТР И ПРИВОЛЖЬЕ" in name for name in names)
    assert {item.inn for item in contract.suppliers} == {"5260200603"}
    assert len(contract.suppliers) == 2


def test_parse_order_search_object_and_status():
    listing = parse_order_search(_html("order_search.html"))
    assert listing["total"] == 145
    first = listing["items"][0]
    assert first["reg_number"] == "0740300000126000959"
    assert first["status"] == "Подача заявок"
    assert "Гоголя" in (first["object_title"] or "")
    assert "освещения" in (first["object_title"] or "")
    assert first["listed_date"].isoformat() == "2026-08-19"
    assert "common-info.html?regNumber=0740300000126000959" in first["url"]


def test_parse_completed_order_takes_results_link():
    order = parse_order_notice(
        _html("order_notice_completed.html"),
        "0740300000126000802",
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0740300000126000802",
    )
    assert is_supplier_defined(order.status)
    assert str(order.nmck) == "1781331.13"
    assert "Загоски" in (order.object_title or "")
    assert order.results_url and order.results_url.endswith(
        "supplier-results.html?regNumber=0740300000126000802"
    )


def test_parse_open_order_skips_results_link():
    order = parse_order_notice(
        _html("order_notice_open.html"),
        "0740300000126000959",
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0740300000126000959",
    )
    assert order.status == "Подача заявок"
    assert not is_supplier_defined(order.status)
    assert order.results_url is None
    assert str(order.nmck) == "623736.26"


def test_parse_order_results_contract_number():
    numbers = parse_order_results(_html("order_results.html"))
    assert numbers == ["3434528856326000110"]


def test_parse_purchase_objects_from_table_not_header():
    html = _html("order_notice_objects.html")
    names = parse_purchase_objects(html)
    assert any("Портовая" in item for item in names)
    assert any("Космонавтов" in item and "Портовая" not in item for item in names)
    assert any("Васнецовых" in item for item in names)
    assert any("Гоголя" in item for item in names)

    order = parse_order_notice(
        html,
        "000",
        "https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber=000",
    )
    assert order.object_title == "Выполнение работ по устройству наружного освещения"
    assert len(order.purchase_objects) >= 3
    assert "Портовая" not in (order.object_title or "")


def test_split_purchase_object_names_streets():
    parts = split_purchase_object_names(
        "Устройство наружного освещения по ул.Портовая в п. Сидоровка, "
        "ул. Космонавтов, проезд между ул. Космонавтов и ул. Братьев Васнецовых"
    )
    assert len(parts) == 3
    assert "Портовая" in parts[0]
    assert parts[1].startswith("ул.")
    assert "проезд" in parts[2].casefold()


def test_keep_eis_listing_from_2024_onward():
    assert eis_number_year("0740300000126000959") == 2026
    assert eis_number_year("3434528856325000226") == 2025
    assert eis_number_year("0740300000119000123") == 2019
    assert in_eis_year_range(2024)
    assert in_eis_year_range(2026)
    assert in_eis_year_range(2099)
    assert not in_eis_year_range(2019)
    assert not in_eis_year_range(2023)
    assert keep_eis_listing("0740300000126000959")
    assert not keep_eis_listing("0740300000119000123")


def test_parse_money_nbsp_and_ruble():
    assert str(parse_money("37&nbsp;628&nbsp;869,27 ₽")) == "37628869.27"
    assert str(parse_money("2 511 041,28")) == "2511041.28"
    assert str(parse_money("7 557 103,14\n \n Загрузка ...")) == "7557103.14"
