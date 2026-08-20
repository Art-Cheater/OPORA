"""Парсер ЕИС zakupki.gov.ru (тестовый контур, без записи в Опору)."""

from app.integrations.zakupki.models import EisContract, EisOrder, EisSupplier, ParseIssue
from app.integrations.zakupki.parse import (
    parse_contract_card,
    parse_contract_search,
    parse_order_notice,
    parse_order_results,
    parse_order_search,
    parse_purchase_objects,
    split_purchase_object_names,
)

__all__ = [
    "EisContract",
    "EisOrder",
    "EisSupplier",
    "ParseIssue",
    "parse_contract_card",
    "parse_contract_search",
    "parse_order_notice",
    "parse_order_results",
    "parse_order_search",
    "parse_purchase_objects",
    "split_purchase_object_names",
]
