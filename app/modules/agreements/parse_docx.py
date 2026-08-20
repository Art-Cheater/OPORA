"""Разбор Word-договоров на размещение кабеля на опорах НО."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_PERIOD_RE = re.compile(
    r"с\s*(\d{2}\.\d{2}\.\d{4})\s*г?\.?\s*по\s*(\d{2}\.\d{2}\.\d{4})",
    re.I,
)
_IN_CONTRACT_RE = re.compile(r"в\s+договор[ауе]?\s*№\s*(.+)$", re.I)
_CONTRACT_NUM_RE = re.compile(r"договор\s*№\s*(.+)$", re.I)
_CUSTOMER_RE = re.compile(
    r"и\s+(.+?)\s*,\s*\(далее\s*[-–—]\s*[«\"']?Заказчик",
    re.S | re.I,
)
_INN_RE = re.compile(r"ИНН[:\s]*(\d{10,12})", re.I)
_ORG_SHORT_RE = re.compile(
    r"(ПАО|АО|ООО|ИП)\s*[«\"][^»\"]+[»\"]",
    re.I,
)
_SPACE_RE = re.compile(r"\s+")
_POLE_HINTS = ("опор", "креплен", "волокон", "кабел", "освещен", "подвеск")

WRONG_AGREEMENT_MESSAGE = (
    "Договор не тот. Нужен договор или допсоглашение на оборудование на опорах "
    "наружного освещения, с таблицей адресной программы."
)


@dataclass
class ParsedSite:
    row_no: str | None
    address: str
    mounts_count: int | None = None
    poles_count: int | None = None
    note: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ParsedAgreement:
    number: str | None
    title: str
    subject: str | None
    customer_name: str | None
    customer_inn: str | None
    period_from: date | None
    period_to: date | None
    sites: list[ParsedSite]
    warnings: list[str] = field(default_factory=list)


def normalize_agreement_number(raw: str | None) -> str:
    """«10 / 24», «№1/24 от 11 декабря» → «1/24» для сравнения копий."""

    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"^№\s*", "", text, flags=re.I)
    text = re.split(r"\s+от\b", text, maxsplit=1, flags=re.I)[0]
    text = text.replace("\\", "/")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"[\s.]+", "", text)
    return text.casefold()


def _texts(el: ET.Element) -> str:
    parts = [node.text or "" for node in el.iter(f"{_W}t")]
    return _SPACE_RE.sub(" ", "".join(parts)).strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _int_cell(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _clean_number(raw: str) -> str:
    text = re.split(r"\s+от\b", raw.strip(), maxsplit=1, flags=re.I)[0]
    text = text.replace("\\", "/")
    text = re.sub(r"\s*/\s*", "/", text)
    text = _SPACE_RE.sub("", text).strip(" .;")
    return text


def _extract_number(paras: list[str]) -> str | None:
    early = paras[:24]
    for para in early:
        match = _IN_CONTRACT_RE.search(para)
        if match:
            return _clean_number(match.group(1)) or None
    for para in early:
        low = para.casefold()
        if low.startswith("приложение") or low.startswith("к договору"):
            continue
        match = _CONTRACT_NUM_RE.search(para)
        if match:
            return _clean_number(match.group(1)) or None
    return None


def _preferred_customer(raw: str) -> str:
    text = _SPACE_RE.sub(" ", raw).strip(" ,")
    short = _ORG_SHORT_RE.search(text)
    if short:
        return _SPACE_RE.sub(" ", short.group(0)).strip()
    return text


def _cell_map(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(header):
        key = raw.casefold()
        compact = key.replace(" ", "")
        if "п/п" in key or "пп" in compact or key.startswith("№") or key.strip() in {"n", "п"}:
            mapping.setdefault("row_no", idx)
        elif "адрес" in key:
            mapping.setdefault("address", idx)
        elif "креплен" in key:
            mapping.setdefault("mounts", idx)
        elif "опор" in key:
            mapping.setdefault("poles", idx)
        elif "примечан" in key:
            mapping.setdefault("note", idx)
    return mapping


def _is_address_header(cells: list[str]) -> bool:
    joined = " ".join(cells).casefold()
    return "адрес" in joined and ("опор" in joined or "креплен" in joined)


def _customer_from_cell(text: str) -> tuple[str | None, str | None]:
    raw = text.strip()
    if not raw.casefold().startswith("заказчик"):
        return None, None
    rest = raw[8:].lstrip(" :")
    inn_match = _INN_RE.search(rest)
    inn = inn_match.group(1) if inn_match else None
    org = _ORG_SHORT_RE.search(rest) or re.search(
        r"(?:ПАО|АО|ООО|ИП|Публичное акционерное общество|Общество с ограниченной ответственностью)\s*[«\"][^»\"]+[»\"]",
        rest,
        re.I,
    )
    if org:
        return _preferred_customer(org.group(0)), inn
    name_part = re.split(r"ИНН|Юридический|РФ,|\d{6}\s*,", rest, maxsplit=1)[0]
    name = _SPACE_RE.sub(" ", name_part).strip(" ,.;")
    return (name or None), inn


def _read_document_xml(source: Path | bytes) -> ET.Element:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    with zipfile.ZipFile(BytesIO(data)) as archive:
        xml = archive.read("word/document.xml")
    return ET.fromstring(xml)


def _sites_from_tables(tables: list[ET.Element]) -> list[ParsedSite]:
    sites: list[ParsedSite] = []
    for table in tables:
        rows = table.findall(f"{_W}tr")
        if not rows:
            continue
        header = [_texts(cell) for cell in rows[0].findall(f"{_W}tc")]
        if not _is_address_header(header):
            continue
        mapping = _cell_map(header)
        addr_idx = mapping.get("address")
        if addr_idx is None:
            continue
        for row in rows[1:]:
            cells = [_texts(cell) for cell in row.findall(f"{_W}tc")]
            address = cells[addr_idx].strip() if addr_idx < len(cells) else ""
            if not address or address.casefold().startswith("итого"):
                continue
            extra = {
                header[i]: cells[i]
                for i in range(len(header))
                if i < len(cells) and i not in mapping.values() and cells[i]
            }
            row_no = None
            if "row_no" in mapping and mapping["row_no"] < len(cells):
                row_no = cells[mapping["row_no"]].strip(" .") or None
            sites.append(
                ParsedSite(
                    row_no=row_no,
                    address=address,
                    mounts_count=(
                        _int_cell(cells[mapping["mounts"]])
                        if "mounts" in mapping and mapping["mounts"] < len(cells)
                        else None
                    ),
                    poles_count=(
                        _int_cell(cells[mapping["poles"]])
                        if "poles" in mapping and mapping["poles"] < len(cells)
                        else None
                    ),
                    note=(
                        cells[mapping["note"]].strip() or None
                        if "note" in mapping and mapping["note"] < len(cells)
                        else None
                    ),
                    extra=extra,
                )
            )
    return sites


def _looks_like_pole_document(paras: list[str], sites: list[ParsedSite]) -> bool:
    if sites:
        return True
    blob = " ".join(paras[:40]).casefold()
    return sum(1 for hint in _POLE_HINTS if hint in blob) >= 2


def parse_agreement_docx(source: Path | bytes) -> ParsedAgreement:
    root = _read_document_xml(source)
    paras = [_texts(para) for para in root.iter(f"{_W}p")]
    paras = [item for item in paras if item]

    number = _extract_number(paras)
    subject_parts: list[str] = []
    for para in paras[:12]:
        low = para.casefold()
        if number and normalize_agreement_number(para) == normalize_agreement_number(number):
            continue
        if _IN_CONTRACT_RE.search(para) or (low.startswith("договор") and "№" in para):
            continue
        if low.startswith("г. киров") or low.startswith("муниципальное"):
            break
        if "мку" in low and "дирекция" in low and len(para) < 80:
            continue
        subject_parts.append(para)
    subject = " ".join(subject_parts).strip() or None

    preamble = next(
        (item for item in paras if "далее" in item.casefold() and "заказчик" in item.casefold()),
        "",
    )
    customer_name = None
    cust_match = _CUSTOMER_RE.search(preamble)
    if cust_match:
        customer_name = _preferred_customer(cust_match.group(1))

    customer_inn = None
    tables = list(root.iter(f"{_W}tbl"))
    for table in tables:
        rows = table.findall(f"{_W}tr")
        if not rows:
            continue
        cells = [_texts(cell) for cell in rows[0].findall(f"{_W}tc")]
        for cell in cells:
            name, inn = _customer_from_cell(cell)
            if inn:
                customer_inn = customer_inn or inn
            if name and not customer_name:
                customer_name = name

    period_from = period_to = None
    for para in paras:
        period_match = _PERIOD_RE.search(para)
        if period_match:
            period_from = _parse_date(period_match.group(1))
            period_to = _parse_date(period_match.group(2))
            break

    sites = _sites_from_tables(tables)
    warnings: list[str] = []
    if not _looks_like_pole_document(paras, sites) or not sites:
        warnings.append(WRONG_AGREEMENT_MESSAGE)

    title_bits = ["Договор"]
    if number:
        title_bits.append(f"№ {number}")
    if customer_name:
        title_bits.append(customer_name)
    elif subject:
        title_bits.append(subject)
    title = " ".join(title_bits)[:500]

    return ParsedAgreement(
        number=number,
        title=title,
        subject=subject,
        customer_name=customer_name,
        customer_inn=customer_inn,
        period_from=period_from,
        period_to=period_to,
        sites=sites,
        warnings=warnings,
    )
