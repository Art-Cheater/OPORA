"""Разбор HTML страниц ЕИС по селекторам карточек и выдачи."""

from __future__ import annotations

import html
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.integrations.zakupki.config import (
    STATUS_SUPPLIER_DEFINED,
    absolute_url,
    contract_card_url,
)
from app.integrations.zakupki.models import EisContract, EisOrder, EisSupplier

_SPACE_TRANS = str.maketrans(
    {
        "\xa0": " ",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u2007": " ",
    }
)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
_STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")

_ENTRY_SPLIT_RE = re.compile(r'<div class="search-registry-entry-block[^"]*">')
_CONTRACT_LINK_RE = re.compile(
    r'href="(/epz/contract/contractCard/common-info\.html\?reestrNumber=(\d+))"'
)
_ORDER_LINK_RE = re.compile(
    r'href="((?:https://zakupki\.gov\.ru)?/epz/order/notice/'
    r'(?!printForm)[^"]*?/common-info\.html\?regNumber=(\d+))"'
)
_RESULTS_LINK_RE = re.compile(
    r'href="([^"]*supplier-results\.html\?regNumber=\d+[^"]*)"'
)
_SECTION_RE = re.compile(
    r'<span class="section__title"[^>]*>(.*?)</span>\s*'
    r'<span class="section__info"[^>]*>(.*?)</span>',
    re.S | re.I,
)
_SUPPLIER_TD_RE = re.compile(
    r'<td class="tableBlock__col tableBlock__col_first[^"]*">(.*?)</td>',
    re.S | re.I,
)
_STATE_RE = re.compile(
    r'<span class="cardMainInfo__state[^"]*">(.*?)</span>',
    re.S | re.I,
)
_PRICE_RE = re.compile(
    r'<span class="cardMainInfo__content cost">(.*?)</span>',
    re.S | re.I,
)
_OBJECT_RE = re.compile(
    r'Объект закупки</(?:span|div)>\s*'
    r'<(?:span|div) class="(?:cardMainInfo__content|registry-entry__body-value)[^"]*">(.*?)</(?:span|div)>',
    re.S | re.I,
)
_BODY_OBJECT_RE = re.compile(
    r'<div class="registry-entry__body-title">\s*Объект закупки\s*</div>\s*'
    r'<div class="registry-entry__body-value">(.*?)</div>',
    re.S | re.I,
)
_HEADER_TITLE_RE = re.compile(
    r'<div class="registry-entry__header-mid__title[^"]*">(.*?)</div>',
    re.S | re.I,
)
_TOTAL_RE = re.compile(r"(\d+)\s+запис")
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_PUBLISHED_RE = re.compile(
    r"Размещено</span>\s*<span class=\"cardMainInfo__content\">\s*(\d{2}\.\d{2}\.\d{4})",
    re.S | re.I,
)
_PAGINATOR_NEXT_RE = re.compile(r"paginator-button-next")
_PURCHASE_OBJECTS_BLOCK_RE = re.compile(
    r'<h2[^>]*class="[^"]*blockInfo__title[^"]*"[^>]*>\s*Информация об объекте закупки\s*</h2>(.*?)'
    r'(?=<h2[^>]*class="[^"]*blockInfo__title(?!_sub)|$)',
    re.S | re.I,
)
_TABLE_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TABLE_TD_RE = re.compile(
    r"<td(?![^>]*header)[^>]*class=\"[^\"]*tableBlock__col[^\"]*\"[^>]*>(.*?)</td>",
    re.S | re.I,
)
_ADDR_SPLIT_RE = re.compile(
    r",\s*(?=(?:ул\.?\s*|улица\s+|проезд\s+|пер\.?\s+|переулок\s+|"
    r"пр-т\.?\s*|проспект\s+|б-р\.?\s*|бульвар\s+|наб\.?\s+|шоссе\s+))",
    re.I,
)

_CONTRACT_FIELDS = {
    "дата заключения контракта": "contract_date",
    "номер контракта": "number",
    "цена контракта": "amount",
    "дата начала исполнения контракта": "start_date",
    "дата окончания исполнения контракта": "end_date",
    "предмет контракта": "subject",
    "место поставки товара, выполнения работы или оказания услуги": "delivery_place",
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = _SCRIPT_RE.sub(" ", value)
    text = _STYLE_RE.sub(" ", text)
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text).translate(_SPACE_TRANS)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip(" \n\t;,")


def parse_date(value: str | None) -> date | None:
    text = clean_text(value)
    match = _DATE_RE.search(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


_MONEY_RE = re.compile(
    r"(\d{1,3}(?:\s\d{3})+,\d{1,2}|\d+,\d{1,2}|\d{1,3}(?:\s\d{3})+|\d+)"
)


def parse_money(value: str | None) -> Decimal | None:
    """Первая сумма в тексте. Игнорирует хвост вроде «Загрузка ...» в подсказке ЕИС."""
    text = clean_text(value)
    if not text:
        return None
    match = _MONEY_RE.search(text.replace("₽", ""))
    if not match:
        return None
    number = match.group(1).replace(" ", "").replace(",", ".")
    try:
        return Decimal(number)
    except InvalidOperation:
        return None


def parse_total(html_text: str) -> int | None:
    match = _TOTAL_RE.search(html_text)
    return int(match.group(1)) if match else None


def has_next_page(html_text: str) -> bool:
    return bool(_PAGINATOR_NEXT_RE.search(html_text))


def _iter_entries(html_text: str) -> list[str]:
    parts = _ENTRY_SPLIT_RE.split(html_text)
    return parts[1:] if len(parts) > 1 else []


def parse_contract_search(html_text: str) -> dict:
    items: list[dict] = []
    seen: set[str] = set()
    for chunk in _iter_entries(html_text):
        match = _CONTRACT_LINK_RE.search(chunk)
        if not match:
            continue
        href, reestr = match.group(1), match.group(2)
        if reestr in seen:
            continue
        seen.add(reestr)
        title_match = _HEADER_TITLE_RE.search(chunk)
        items.append(
            {
                "reestr_number": reestr,
                "url": absolute_url(href),
                "stage": clean_text(title_match.group(1)) if title_match else None,
            }
        )
    return {
        "total": parse_total(html_text),
        "has_next": has_next_page(html_text),
        "items": items,
    }


def parse_order_search(html_text: str) -> dict:
    items: list[dict] = []
    seen: set[str] = set()
    for chunk in _iter_entries(html_text):
        match = _ORDER_LINK_RE.search(chunk)
        if not match:
            continue
        href, number = match.group(1), match.group(2)
        if number in seen:
            continue
        seen.add(number)
        title_match = _HEADER_TITLE_RE.search(chunk)
        object_match = _BODY_OBJECT_RE.search(chunk)
        items.append(
            {
                "reg_number": number,
                "url": absolute_url(href),
                "status": clean_text(title_match.group(1)) if title_match else None,
                "object_title": clean_text(object_match.group(1)) if object_match else None,
            }
        )
    return {
        "total": parse_total(html_text),
        "has_next": has_next_page(html_text),
        "items": items,
    }


def _section_map(html_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for title_html, value_html in _SECTION_RE.findall(html_text):
        title = clean_text(title_html).casefold()
        title = re.sub(r"\s+", " ", title)
        if title and title not in values:
            values[title] = clean_text(value_html)
    return values


def _labeled_value(cell_html: str, label: str) -> str | None:
    pattern = re.compile(
        rf"{re.escape(label)}</span>\s*<span>([^<]+)</span>",
        re.I,
    )
    match = pattern.search(cell_html)
    if not match:
        return None
    value = clean_text(match.group(1))
    return value or None


def parse_suppliers(html_text: str) -> list[EisSupplier]:
    start = html_text.find("Информация о поставщиках")
    block = html_text[start:] if start >= 0 else html_text
    suppliers: list[EisSupplier] = []
    seen: set[tuple[str, str | None]] = set()
    for cell in _SUPPLIER_TD_RE.findall(block):
        name_html = cell.split("<section", 1)[0].split("<br", 1)[0]
        name = clean_text(name_html)
        if not name:
            continue
        inn = _labeled_value(cell, "ИНН:")
        kpp = _labeled_value(cell, "КПП:")
        kpp_largest = _labeled_value(cell, "налогоплательщика:")
        key = (name, inn)
        if key in seen:
            continue
        seen.add(key)
        suppliers.append(
            EisSupplier(name=name, inn=inn, kpp=kpp, kpp_largest=kpp_largest)
        )
    return suppliers


def parse_contract_card(html_text: str, reestr_number: str, url: str | None = None) -> EisContract:
    sections = _section_map(html_text)
    mapped: dict[str, str] = {}
    for title, field_name in _CONTRACT_FIELDS.items():
        if title in sections:
            mapped[field_name] = sections[title]

    amount_raw = mapped.get("amount")
    if amount_raw:
        amount_raw = re.sub(r"\s*Загрузка \.\.\.\s*", " ", amount_raw).strip()
    contract = EisContract(
        reestr_number=reestr_number,
        url=url or contract_card_url(reestr_number),
        number=mapped.get("number") or None,
        contract_date=parse_date(mapped.get("contract_date")),
        start_date=parse_date(mapped.get("start_date")),
        end_date=parse_date(mapped.get("end_date")),
        amount=parse_money(amount_raw),
        amount_raw=amount_raw,
        subject=mapped.get("subject") or None,
        delivery_place=mapped.get("delivery_place") or None,
        suppliers=parse_suppliers(html_text),
    )
    return contract


def split_purchase_object_names(text: str) -> list[str]:
    """Один <td> может перечислять несколько адресов через запятую."""
    raw = clean_text(text)
    if not raw:
        return []
    parts = [item.strip(" .;") for item in _ADDR_SPLIT_RE.split(raw) if item.strip(" .;")]
    return parts or [raw]


def parse_purchase_objects(html_text: str) -> list[str]:
    """Имена объектов из таблицы «Информация об объекте закупки», не из шапки карточки."""
    block_match = _PURCHASE_OBJECTS_BLOCK_RE.search(html_text)
    if not block_match:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for row_html in _TABLE_ROW_RE.findall(block_match.group(1)):
        if "tableBlock__col_header" in row_html or "<th" in row_html.lower():
            continue
        cells = _TABLE_TD_RE.findall(row_html)
        if not cells:
            continue
        main = re.split(r'<div class="section__title"', cells[0], maxsplit=1)[0]
        for name in split_purchase_object_names(main):
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
    return names


def order_object_names(order: EisOrder) -> list[str]:
    if order.purchase_objects:
        return list(order.purchase_objects)
    if order.object_title:
        return [order.object_title]
    return []


def parse_order_notice(html_text: str, reg_number: str, url: str) -> EisOrder:
    state_match = _STATE_RE.search(html_text)
    price_match = _PRICE_RE.search(html_text)
    object_match = _OBJECT_RE.search(html_text)
    nmck_raw = clean_text(price_match.group(1)) if price_match else None
    status = clean_text(state_match.group(1)) if state_match else None
    results_url = None
    if status == STATUS_SUPPLIER_DEFINED:
        results_match = _RESULTS_LINK_RE.search(html_text)
        if results_match:
            results_url = absolute_url(results_match.group(1))
    published_match = _PUBLISHED_RE.search(html_text)
    purchase_objects = parse_purchase_objects(html_text)
    header_title = clean_text(object_match.group(1)) if object_match else None
    return EisOrder(
        reg_number=reg_number,
        url=url,
        status=status,
        nmck=parse_money(nmck_raw),
        nmck_raw=nmck_raw,
        object_title=header_title,
        purchase_objects=purchase_objects,
        published_at=parse_date(published_match.group(1)) if published_match else None,
        results_url=results_url,
    )


def parse_order_results(html_text: str) -> list[str]:
    numbers: list[str] = []
    seen: set[str] = set()
    for _, reestr in _CONTRACT_LINK_RE.findall(html_text):
        if reestr in seen:
            continue
        seen.add(reestr)
        numbers.append(reestr)
    return numbers


def is_supplier_defined(status: str | None) -> bool:
    return (status or "").strip() == STATUS_SUPPLIER_DEFINED
