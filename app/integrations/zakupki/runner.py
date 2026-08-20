"""Скачивание выдачи ЕИС и сбор JSON без записи в базу Опоры."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.integrations.zakupki.client import EisClient, EisFetchError
from app.integrations.zakupki.config import (
    EIS_YEAR_FROM,
    EIS_YEAR_TO,
    STATUS_SUPPLIER_DEFINED,
    contract_card_url,
    contract_search_url,
    order_search_url,
)
from app.integrations.zakupki.models import EisContract, EisOrder, ParseIssue
from app.integrations.zakupki.parse import (
    is_supplier_defined,
    keep_eis_listing,
    parse_contract_card,
    parse_contract_search,
    parse_order_notice,
    parse_order_results,
    parse_order_search,
)


@dataclass
class EisParseResult:
    contracts: list[EisContract] = field(default_factory=list)
    orders: list[EisOrder] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    contract_total: int | None = None
    order_total: int | None = None
    skipped_old: int = 0

    def to_dict(self) -> dict:
        return {
            "contract_total": self.contract_total,
            "order_total": self.order_total,
            "skipped_old": self.skipped_old,
            "contracts": [item.to_dict() for item in self.contracts],
            "orders": [item.to_dict() for item in self.orders],
            "import_errors": [item.to_dict() for item in self.issues],
        }


class EisParser:
    def __init__(self, client: EisClient | None = None) -> None:
        self.client = client or EisClient()

    def fetch_contracts(
        self,
        *,
        pages: int = 1,
        limit: int | None = 3,
        per_page: str = "_10",
        year_from: int = EIS_YEAR_FROM,
        year_to: int = EIS_YEAR_TO,
    ) -> tuple[list[EisContract], list[ParseIssue], int | None, int]:
        contracts: list[EisContract] = []
        issues: list[ParseIssue] = []
        total: int | None = None
        remaining = limit
        skipped_old = 0

        for page in range(1, pages + 1):
            url = contract_search_url(
                page=page, per_page=per_page, year_from=year_from, year_to=year_to
            )
            try:
                html = self.client.get(url)
            except EisFetchError as exc:
                issues.append(ParseIssue(kind="fetch", message=str(exc), url=url))
                break
            listing = parse_contract_search(html)
            if total is None:
                total = listing["total"]
            items = listing["items"]
            if remaining is not None:
                items = items[:remaining]
            for item in items:
                if not keep_eis_listing(
                    item["reestr_number"], item.get("listed_date"), year_from, year_to
                ):
                    skipped_old += 1
                    continue
                try:
                    card_html = self.client.get(item["url"])
                    contract = parse_contract_card(
                        card_html, item["reestr_number"], item["url"]
                    )
                    contract.stage = item.get("stage")
                    if not contract.number and not contract.suppliers:
                        issues.append(
                            ParseIssue(
                                kind="parse",
                                message="Карточка контракта разобрана пустой",
                                url=item["url"],
                                number=item["reestr_number"],
                            )
                        )
                    contracts.append(contract)
                except EisFetchError as exc:
                    issues.append(
                        ParseIssue(
                            kind="fetch",
                            message=str(exc),
                            url=item["url"],
                            number=item["reestr_number"],
                        )
                    )
            if remaining is not None:
                remaining -= len(items)
                if remaining <= 0:
                    break
            if not listing["has_next"]:
                break
        return contracts, issues, total, skipped_old

    def fetch_orders(
        self,
        *,
        pages: int = 1,
        limit: int | None = 3,
        per_page: str = "_10",
        with_contracts: bool = True,
        year_from: int = EIS_YEAR_FROM,
        year_to: int = EIS_YEAR_TO,
    ) -> tuple[list[EisOrder], list[ParseIssue], int | None, int]:
        orders: list[EisOrder] = []
        issues: list[ParseIssue] = []
        total: int | None = None
        remaining = limit
        skipped_old = 0

        for page in range(1, pages + 1):
            url = order_search_url(
                page=page, per_page=per_page, year_from=year_from, year_to=year_to
            )
            try:
                html = self.client.get(url)
            except EisFetchError as exc:
                issues.append(ParseIssue(kind="fetch", message=str(exc), url=url))
                break
            listing = parse_order_search(html)
            if total is None:
                total = listing["total"]
            items = listing["items"]
            if remaining is not None:
                items = items[:remaining]
            for item in items:
                if not keep_eis_listing(
                    item["reg_number"], item.get("listed_date"), year_from, year_to
                ):
                    skipped_old += 1
                    continue
                order, order_issues = self._load_order(
                    item,
                    with_contracts=with_contracts,
                    year_from=year_from,
                    year_to=year_to,
                )
                orders.append(order)
                issues.extend(order_issues)
            if remaining is not None:
                remaining -= len(items)
                if remaining <= 0:
                    break
            if not listing["has_next"]:
                break
        return orders, issues, total, skipped_old

    def _load_order(
        self,
        item: dict,
        *,
        with_contracts: bool,
        year_from: int = EIS_YEAR_FROM,
        year_to: int = EIS_YEAR_TO,
    ) -> tuple[EisOrder, list[ParseIssue]]:
        issues: list[ParseIssue] = []
        url = item["url"]
        number = item["reg_number"]
        try:
            html = self.client.get(url)
        except EisFetchError as exc:
            issues.append(
                ParseIssue(kind="fetch", message=str(exc), url=url, number=number)
            )
            return (
                EisOrder(
                    reg_number=number,
                    url=url,
                    status=item.get("status"),
                    object_title=item.get("object_title"),
                ),
                issues,
            )

        order = parse_order_notice(html, number, url)
        if not order.object_title:
            order.object_title = item.get("object_title")
        if not order.status:
            order.status = item.get("status")

        if not is_supplier_defined(order.status):
            return order, issues

        if not order.results_url:
            issues.append(
                ParseIssue(
                    kind="parse",
                    message=(
                        f"Статус «{STATUS_SUPPLIER_DEFINED}», "
                        "но ссылка на результаты не найдена"
                    ),
                    url=url,
                    number=number,
                )
            )
            return order, issues

        try:
            results_html = self.client.get(order.results_url)
        except EisFetchError as exc:
            issues.append(
                ParseIssue(
                    kind="fetch",
                    message=str(exc),
                    url=order.results_url,
                    number=number,
                )
            )
            return order, issues

        order.contract_reestr_numbers = parse_order_results(results_html)
        if not order.contract_reestr_numbers:
            issues.append(
                ParseIssue(
                    kind="parse",
                    message="На странице результатов нет ссылки на контракт",
                    url=order.results_url,
                    number=number,
                )
            )
            return order, issues

        if not with_contracts:
            return order, issues

        for reestr in order.contract_reestr_numbers:
            if not keep_eis_listing(reestr, year_from=year_from, year_to=year_to):
                continue
            card_url = contract_card_url(reestr)
            try:
                card_html = self.client.get(card_url)
                order.contracts.append(parse_contract_card(card_html, reestr, card_url))
            except EisFetchError as exc:
                issues.append(
                    ParseIssue(
                        kind="fetch",
                        message=str(exc),
                        url=card_url,
                        number=reestr,
                    )
                )
        return order, issues

    def fetch_contract(self, reestr_number: str) -> tuple[EisContract | None, list[ParseIssue]]:
        url = contract_card_url(reestr_number)
        try:
            html = self.client.get(url)
        except EisFetchError as exc:
            return None, [ParseIssue(kind="fetch", message=str(exc), url=url, number=reestr_number)]
        return parse_contract_card(html, reestr_number, url), []

    def fetch_order(
        self, reg_number: str, *, with_contracts: bool = True, url: str | None = None
    ) -> tuple[EisOrder, list[ParseIssue]]:
        urls = (
            [url]
            if url
            else [
                f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={reg_number}",
                f"https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber={reg_number}",
            ]
        )
        last_issues: list[ParseIssue] = []
        for candidate in urls:
            item = {
                "reg_number": reg_number,
                "url": candidate,
                "status": None,
                "object_title": None,
            }
            order, issues = self._load_order(item, with_contracts=with_contracts)
            fetch_fail = issues and all(item.kind == "fetch" for item in issues)
            if not fetch_fail:
                return order, issues
            last_issues = issues
        return (
            EisOrder(reg_number=reg_number, url=urls[0]),
            last_issues,
        )

    def run(
        self,
        *,
        mode: str = "both",
        pages: int = 1,
        limit: int | None = 3,
        per_page: str = "_10",
        with_contracts: bool = True,
        contract_numbers: list[str] | None = None,
        order_numbers: list[str] | None = None,
        year_from: int = EIS_YEAR_FROM,
        year_to: int = EIS_YEAR_TO,
    ) -> EisParseResult:
        result = EisParseResult()
        targeted = bool(contract_numbers or order_numbers)
        if contract_numbers:
            for reestr in contract_numbers:
                contract, issues = self.fetch_contract(reestr)
                result.issues.extend(issues)
                if contract:
                    result.contracts.append(contract)
        elif not targeted and mode in {"both", "contracts"}:
            contracts, issues, total, skipped = self.fetch_contracts(
                pages=pages,
                limit=limit,
                per_page=per_page,
                year_from=year_from,
                year_to=year_to,
            )
            result.contracts = contracts
            result.issues.extend(issues)
            result.contract_total = total
            result.skipped_old += skipped
        if order_numbers:
            for number in order_numbers:
                order, issues = self.fetch_order(number, with_contracts=with_contracts)
                result.orders.append(order)
                result.issues.extend(issues)
        elif not targeted and mode in {"both", "orders"}:
            orders, issues, total, skipped = self.fetch_orders(
                pages=pages,
                limit=limit,
                per_page=per_page,
                with_contracts=with_contracts,
                year_from=year_from,
                year_to=year_to,
            )
            result.orders = orders
            result.issues.extend(issues)
            result.order_total = total
            result.skipped_old += skipped
        return result
