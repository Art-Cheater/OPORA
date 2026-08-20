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


TableGrid = list[list[str]]

_ODT_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_ODT_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_ODT_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"


def _sites_from_grids(tables: list[TableGrid]) -> list[ParsedSite]:
    sites: list[ParsedSite] = []
    for rows in tables:
        if not rows:
            continue
        header = rows[0]
        if not _is_address_header(header):
            continue
        mapping = _cell_map(header)
        addr_idx = mapping.get("address")
        if addr_idx is None:
            continue
        for cells in rows[1:]:
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


def _docx_grids(root: ET.Element) -> list[TableGrid]:
    grids: list[TableGrid] = []
    for table in root.iter(f"{_W}tbl"):
        rows: TableGrid = []
        for row in table.findall(f"{_W}tr"):
            rows.append([_texts(cell) for cell in row.findall(f"{_W}tc")])
        if rows:
            grids.append(rows)
    return grids


def _odt_cell_text(cell: ET.Element) -> str:
    return _SPACE_RE.sub(" ", "".join(cell.itertext())).strip()


def _odt_repeat(el: ET.Element, attr: str) -> int:
    raw = el.attrib.get(attr) or el.attrib.get(attr.split("}")[-1]) or "1"
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _odt_grids(root: ET.Element) -> list[TableGrid]:
    grids: list[TableGrid] = []
    for table in root.iter(f"{_ODT_TABLE}table"):
        rows: TableGrid = []
        for row in table.findall(f"{_ODT_TABLE}table-row"):
            cells: list[str] = []
            for cell in row.findall(f"{_ODT_TABLE}table-cell"):
                text = _odt_cell_text(cell)
                for _ in range(_odt_repeat(cell, f"{_ODT_TABLE}number-columns-repeated")):
                    cells.append(text)
            for _ in range(_odt_repeat(row, f"{_ODT_TABLE}number-rows-repeated")):
                rows.append(list(cells))
        if rows:
            grids.append(rows)
    return grids


def _odt_paras(root: ET.Element) -> list[str]:
    paras: list[str] = []
    for el in root.iter():
        if el.tag not in {f"{_ODT_TEXT}p", f"{_ODT_TEXT}h"}:
            continue
        text = _SPACE_RE.sub(" ", "".join(el.itertext())).strip()
        if text:
            paras.append(text)
    return paras


def assemble_agreement(paras: list[str], tables: list[TableGrid]) -> ParsedAgreement:
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
    for rows in tables:
        for row in rows[:2]:
            for cell in row:
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

    sites = _sites_from_grids(tables)
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


def _looks_like_pole_document(paras: list[str], sites: list[ParsedSite]) -> bool:
    if sites:
        return True
    blob = " ".join(paras[:40]).casefold()
    return sum(1 for hint in _POLE_HINTS if hint in blob) >= 2


def parse_agreement_docx(source: Path | bytes) -> ParsedAgreement:
    root = _read_document_xml(source)
    paras = [_texts(para) for para in root.iter(f"{_W}p")]
    paras = [item for item in paras if item]
    return assemble_agreement(paras, _docx_grids(root))


def parse_agreement_odt(source: Path | bytes) -> ParsedAgreement:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    with zipfile.ZipFile(BytesIO(data)) as archive:
        xml = archive.read("content.xml")
    root = ET.fromstring(xml)
    return assemble_agreement(_odt_paras(root), _odt_grids(root))


def parse_agreement_file(source: Path | bytes) -> ParsedAgreement:
    """Docx сразу, odt из XML, остальное (.doc, .rtf, PDF) — через конвертер в docx."""

    import os
    import shutil
    import tempfile

    from app.core.exceptions import ValidationError
    from app.modules.agreements.convert import office_kind, to_docx_path

    own_tmp: Path | None = None
    converted: Path | None = None
    if isinstance(source, (bytes, bytearray)):
        handle, name = tempfile.mkstemp(suffix=".bin")
        os.close(handle)
        own_tmp = Path(name)
        own_tmp.write_bytes(bytes(source))
        path = own_tmp
    else:
        path = Path(source)

    try:
        kind = office_kind(path)
        if kind in {"docx", "docm"}:
            return parse_agreement_docx(path)
        if kind == "odt":
            parsed = parse_agreement_odt(path)
            if parsed.sites:
                return parsed
        converted = to_docx_path(path)
        return parse_agreement_docx(converted)
    except ValidationError:
        raise
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValidationError("Не удалось прочитать файл договора.") from exc
    finally:
        if converted is not None and converted != path:
            parent = converted.parent
            converted.unlink(missing_ok=True)
            if parent.name.startswith("opora-office-") or parent.name.startswith("opora-word-"):
                shutil.rmtree(parent, ignore_errors=True)
        if own_tmp is not None:
            own_tmp.unlink(missing_ok=True)
