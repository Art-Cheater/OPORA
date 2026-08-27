"""Скачивание выдачи ЕИС и сбор JSON без записи в базу Опоры."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.integrations.zakupki.client import EisClient, EisFetchError
from app.integrations.zakupki.config import (
    EIS_YEAR_FROM,
    EIS_YEAR_TO,
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
    pages_fetched: int = 0
    cards_found: int = 0
    cards_parsed: int = 0
    partial_parse: int = 0
    fetch_errors: int = 0
    parse_errors: int = 0
    pagination_limit_reached: bool = False
    last_page: int = 0

    def to_dict(self) -> dict:
        return {
            "contract_total": self.contract_total,
            "order_total": self.order_total,
            "skipped_old": self.skipped_old,
            "pages_fetched": self.pages_fetched,
            "cards_found": self.cards_found,
            "cards_parsed": self.cards_parsed,
            "partial_parse": self.partial_parse,
            "fetch_errors": self.fetch_errors,
            "parse_errors": self.parse_errors,
            "pagination_limit_reached": self.pagination_limit_reached,
            "last_page": self.last_page,
            "contracts": [item.to_dict() for item in self.contracts],
            "orders": [item.to_dict() for item in self.orders],
            "import_errors": [item.to_dict() for item in self.issues],
        }


def _issue_from_fetch(exc: EisFetchError, *, url: str | None = None, number: str | None = None) -> ParseIssue:
    return ParseIssue(
        kind="fetch",
        message=str(exc),
        url=exc.url or url,
        number=number,
        http_status=exc.status,
        attempts=exc.attempts,
    )


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
        result: EisParseResult | None = None,
    ) -> tuple[list[EisContract], list[ParseIssue], int | None, int]:
        contracts: list[EisContract] = []
        issues: list[ParseIssue] = []
        total: int | None = None
        remaining = limit
        skipped_old = 0
        seen_pages: set[int] = set()
        last_has_next = False
        last_page = 0
        page_limit = max(1, int(pages))

        for page in range(1, page_limit + 1):
            if page in seen_pages:
                issues.append(
                    ParseIssue(
                        kind="page_limit",
                        message=f"Обнаружен цикл пагинации на странице {page}",
                        extra={"page": page},
                    )
                )
                break
            seen_pages.add(page)
            url = contract_search_url(
                page=page, per_page=per_page, year_from=year_from, year_to=year_to
            )
            try:
                html = self.client.get(url)
            except EisFetchError as exc:
                issues.append(_issue_from_fetch(exc, url=url))
                if result is not None:
                    result.fetch_errors += 1
                break
            if result is not None:
                result.pages_fetched += 1
                result.last_page = page
            last_page = page
            listing = parse_contract_search(html)
            if total is None:
                total = listing["total"]
            last_has_next = bool(listing.get("has_next"))
            items = listing["items"]
            if result is not None:
                result.cards_found += len(items)
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
                    if contract.missing_fields:
                        issues.append(
                            ParseIssue(
                                kind="partial",
                                message=(
                                    "Карточка контракта разобрана частично: "
                                    + ", ".join(contract.missing_fields)
                                ),
                                url=item["url"],
                                number=item["reestr_number"],
                                missing=list(contract.missing_fields),
                            )
                        )
                        if result is not None:
                            result.partial_parse += 1
                    elif not contract.number and not contract.suppliers:
                        issues.append(
                            ParseIssue(
                                kind="parse",
                                message="Карточка контракта разобрана пустой",
                                url=item["url"],
                                number=item["reestr_number"],
                            )
                        )
                        if result is not None:
                            result.parse_errors += 1
                    contracts.append(contract)
                    if result is not None:
                        result.cards_parsed += 1
                except EisFetchError as exc:
                    issues.append(
                        _issue_from_fetch(
                            exc, url=item["url"], number=item["reestr_number"]
                        )
                    )
                    if result is not None:
                        result.fetch_errors += 1
                except Exception as exc:
                    issues.append(
                        ParseIssue(
                            kind="parse",
                            message=str(exc)[:2000],
                            url=item["url"],
                            number=item["reestr_number"],
                        )
                    )
                    if result is not None:
                        result.parse_errors += 1
            if remaining is not None:
                remaining -= len(items)
                if remaining <= 0:
                    break
            if not listing["has_next"] or not listing["items"]:
                last_has_next = False
                break
        else:
            # исчерпан лимит страниц без break по has_next
            if last_has_next or (
                total is not None and len(contracts) + skipped_old < total
            ):
                last_has_next = True

        if last_has_next and last_page >= page_limit:
            msg = (
                f"Достигнут лимит страниц ЕИС: total={total}, "
                f"downloaded={len(contracts)}, limit={page_limit}, last_page={last_page}"
            )
            issues.append(
                ParseIssue(
                    kind="page_limit",
                    message=msg,
                    extra={
                        "total": total,
                        "downloaded": len(contracts),
                        "limit": page_limit,
                        "last_page": last_page,
                        "source": "contracts",
                    },
                )
            )
            if result is not None:
                result.pagination_limit_reached = True

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
        result: EisParseResult | None = None,
    ) -> tuple[list[EisOrder], list[ParseIssue], int | None, int]:
        orders: list[EisOrder] = []
        issues: list[ParseIssue] = []
        total: int | None = None
        remaining = limit
        skipped_old = 0
        seen_pages: set[int] = set()
        last_has_next = False
        last_page = 0
        page_limit = max(1, int(pages))

        for page in range(1, page_limit + 1):
            if page in seen_pages:
                issues.append(
                    ParseIssue(
                        kind="page_limit",
                        message=f"Обнаружен цикл пагинации на странице {page}",
                        extra={"page": page, "source": "orders"},
                    )
                )
                break
            seen_pages.add(page)
            url = order_search_url(
                page=page, per_page=per_page, year_from=year_from, year_to=year_to
            )
            try:
                html = self.client.get(url)
            except EisFetchError as exc:
                issues.append(_issue_from_fetch(exc, url=url))
                if result is not None:
                    result.fetch_errors += 1
                break
            if result is not None:
                result.pages_fetched += 1
                result.last_page = max(result.last_page, page)
            last_page = page
            listing = parse_order_search(html)
            if total is None:
                total = listing["total"]
            last_has_next = bool(listing.get("has_next"))
            items = listing["items"]
            if result is not None:
                result.cards_found += len(items)
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
                    result=result,
                )
                orders.append(order)
                issues.extend(order_issues)
                if result is not None and order.reg_number:
                    # карточка извещения считаем разобранной, если нет fetch-ошибки целиком
                    if not any(
                        i.kind == "fetch" and i.number == order.reg_number
                        for i in order_issues
                    ):
                        result.cards_parsed += 1
            if remaining is not None:
                remaining -= len(items)
                if remaining <= 0:
                    break
            if not listing["has_next"] or not listing["items"]:
                last_has_next = False
                break
        else:
            if last_has_next or (
                total is not None and len(orders) + skipped_old < total
            ):
                last_has_next = True

        if last_has_next and last_page >= page_limit:
            issues.append(
                ParseIssue(
                    kind="page_limit",
                    message=(
                        f"Достигнут лимит страниц ЕИС (извещения): total={total}, "
                        f"downloaded={len(orders)}, limit={page_limit}, last_page={last_page}"
                    ),
                    extra={
                        "total": total,
                        "downloaded": len(orders),
                        "limit": page_limit,
                        "last_page": last_page,
                        "source": "orders",
                    },
                )
            )
            if result is not None:
                result.pagination_limit_reached = True

        return orders, issues, total, skipped_old

    def _load_order(
        self,
        item: dict,
        *,
        with_contracts: bool,
        year_from: int = EIS_YEAR_FROM,
        year_to: int = EIS_YEAR_TO,
        result: EisParseResult | None = None,
    ) -> tuple[EisOrder, list[ParseIssue]]:
        issues: list[ParseIssue] = []
        url = item["url"]
        number = item["reg_number"]
        try:
            html = self.client.get(url)
        except EisFetchError as exc:
            issues.append(_issue_from_fetch(exc, url=url, number=number))
            if result is not None:
                result.fetch_errors += 1
            return (
                EisOrder(
                    reg_number=number,
                    url=url,
                    status=item.get("status"),
                    object_title=item.get("object_title"),
                ),
                issues,
            )

        try:
            order = parse_order_notice(html, number, url)
        except Exception as exc:
            issues.append(
                ParseIssue(kind="parse", message=str(exc)[:2000], url=url, number=number)
            )
            if result is not None:
                result.parse_errors += 1
            return (
                EisOrder(
                    reg_number=number,
                    url=url,
                    status=item.get("status"),
                    object_title=item.get("object_title"),
                ),
                issues,
            )
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
                        "Определение поставщика завершено, "
                        "но ссылка на результаты не найдена"
                    ),
                    url=url,
                    number=number,
                )
            )
            if result is not None:
                result.parse_errors += 1
            return order, issues

        try:
            results_html = self.client.get(order.results_url)
        except EisFetchError as exc:
            issues.append(
                _issue_from_fetch(exc, url=order.results_url, number=number)
            )
            if result is not None:
                result.fetch_errors += 1
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
            if result is not None:
                result.parse_errors += 1
            return order, issues

        if not with_contracts:
            return order, issues

        for reestr in order.contract_reestr_numbers:
            if not keep_eis_listing(reestr, year_from=year_from, year_to=year_to):
                continue
            card_url = contract_card_url(reestr)
            try:
                card_html = self.client.get(card_url)
                contract = parse_contract_card(card_html, reestr, card_url)
                order.contracts.append(contract)
                if result is not None:
                    result.cards_parsed += 1
                    result.cards_found += 1
                if contract.missing_fields:
                    issues.append(
                        ParseIssue(
                            kind="partial",
                            message=(
                                "Карточка контракта разобрана частично: "
                                + ", ".join(contract.missing_fields)
                            ),
                            url=card_url,
                            number=reestr,
                            missing=list(contract.missing_fields),
                        )
                    )
                    if result is not None:
                        result.partial_parse += 1
            except EisFetchError as exc:
                issues.append(_issue_from_fetch(exc, url=card_url, number=reestr))
                if result is not None:
                    result.fetch_errors += 1
            except Exception as exc:
                issues.append(
                    ParseIssue(
                        kind="parse",
                        message=str(exc)[:2000],
                        url=card_url,
                        number=reestr,
                    )
                )
                if result is not None:
                    result.parse_errors += 1
        return order, issues

    def fetch_contract(self, reestr_number: str) -> tuple[EisContract | None, list[ParseIssue]]:
        url = contract_card_url(reestr_number)
        try:
            html = self.client.get(url)
        except EisFetchError as exc:
            return None, [_issue_from_fetch(exc, url=url, number=reestr_number)]
        try:
            return parse_contract_card(html, reestr_number, url), []
        except Exception as exc:
            return None, [
                ParseIssue(
                    kind="parse",
                    message=str(exc)[:2000],
                    url=url,
                    number=reestr_number,
                )
            ]

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
                    result.cards_parsed += 1
                    if contract.missing_fields:
                        result.partial_parse += 1
                else:
                    result.fetch_errors += sum(1 for i in issues if i.kind == "fetch")
                    result.parse_errors += sum(1 for i in issues if i.kind == "parse")
        elif not targeted and mode in {"both", "contracts"}:
            contracts, issues, total, skipped = self.fetch_contracts(
                pages=pages,
                limit=limit,
                per_page=per_page,
                year_from=year_from,
                year_to=year_to,
                result=result,
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
                result=result,
            )
            result.orders = orders
            result.issues.extend(issues)
            result.order_total = total
            result.skipped_old += skipped
        return result
