"""Структуры данных парсера ЕИС."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


@dataclass
class EisSupplier:
    name: str
    inn: str | None = None
    kpp: str | None = None
    kpp_largest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EisContract:
    reestr_number: str
    url: str
    number: str | None = None
    contract_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    amount: Decimal | None = None
    amount_raw: str | None = None
    subject: str | None = None
    delivery_place: str | None = None
    stage: str | None = None
    suppliers: list[EisSupplier] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return _jsonable(data)


@dataclass
class EisOrder:
    reg_number: str
    url: str
    status: str | None = None
    nmck: Decimal | None = None
    nmck_raw: str | None = None
    object_title: str | None = None
    purchase_objects: list[str] = field(default_factory=list)
    published_at: date | None = None
    results_url: str | None = None
    contract_reestr_numbers: list[str] = field(default_factory=list)
    contracts: list[EisContract] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return _jsonable(data)


@dataclass
class ParseIssue:
    """То, что не удалось разобрать или скачать. Позже покажем в Опоре."""

    kind: str
    message: str
    url: str | None = None
    number: str | None = None
    http_status: int | None = None
    attempts: int | None = None
    missing: list[str] | None = None
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))
