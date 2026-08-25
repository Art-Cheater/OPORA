"""Разбор личных договоров/контрактов: название, описание, дата окончания."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SPACE_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"(\d{2})[./](\d{2})[./](\d{4})")
_PERIOD_TO_RE = re.compile(
    r"(?:по|до|действует\s+до|срок\s+действия\s+до|окончани[ея]\s+(?:срока|договора|контракта)?\s*[:\-]?\s*)"
    r"\s*(\d{2}[./]\d{2}[./]\d{4})",
    re.I,
)
_PERIOD_RANGE_RE = re.compile(
    r"с\s*(\d{2}[./]\d{2}[./]\d{4})\s*г?\.?\s*по\s*(\d{2}[./]\d{2}[./]\d{4})",
    re.I,
)
_TITLE_RE = re.compile(
    r"(договор|контракт|соглашени[ея]|доп\.?\s*соглашени[ея])[^\n]{0,180}",
    re.I,
)
_SUBJECT_RE = re.compile(
    r"(предмет\s+(?:договора|контракта)\s*[:\-]\s*)([^\n]{10,300})",
    re.I,
)


@dataclass
class ParsedPersonalContract:
    title: str
    description: str | None
    ends_on: date | None
    warnings: list[str]


def _parse_date(raw: str) -> date | None:
    match = _DATE_RE.search(raw or "")
    if not match:
        return None
    day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _clean(text: str) -> str:
    return _SPACE_RE.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _docx_paragraphs(data: bytes) -> list[str]:
    with zipfile.ZipFile(BytesIO(data)) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    out: list[str] = []
    for para in root.iter(f"{_W}p"):
        text = _clean("".join(node.text or "" for node in para.iter(f"{_W}t")))
        if text:
            out.append(text)
    return out


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(BytesIO(data))
        parts = []
        for page in reader.pages[:8]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception:
        return ""


def _plain_text(path: Path, data: bytes) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            return "\n".join(_docx_paragraphs(data))
        except Exception:
            return ""
    if suffix == ".pdf":
        return _pdf_text(data)
    if suffix in {".txt", ".rtf"}:
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    # .doc / прочее — попытка UTF-8 / latin1 кусками
    try:
        return data.decode("utf-8", errors="ignore")[:20000]
    except Exception:
        return ""


def _pick_title(text: str, fallback: str) -> str:
    for line in text.splitlines()[:40]:
        line = _clean(line)
        if not line or len(line) < 8:
            continue
        match = _TITLE_RE.search(line)
        if match:
            return _clean(match.group(0))[:500]
    stem = Path(fallback).stem.replace("_", " ").strip()
    return (stem or "Договор")[:500]


def _pick_description(text: str) -> str | None:
    match = _SUBJECT_RE.search(text)
    if match:
        return _clean(match.group(2))[:800]
    # первые осмысленные строки после заголовка
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    body = [line for line in lines[1:12] if len(line) > 25 and not _TITLE_RE.fullmatch(line)]
    if not body:
        return None
    return _clean(" ".join(body[:2]))[:800]


def _pick_ends_on(text: str) -> date | None:
    range_match = _PERIOD_RANGE_RE.search(text)
    if range_match:
        return _parse_date(range_match.group(2))
    to_match = _PERIOD_TO_RE.search(text)
    if to_match:
        return _parse_date(to_match.group(1))
    # последняя дата в первых ~4к символов часто «по …»
    dates = [_parse_date(m.group(0)) for m in _DATE_RE.finditer(text[:8000])]
    dates = [d for d in dates if d is not None]
    if not dates:
        return None
    future = [d for d in dates if d >= date.today()]
    if future:
        return max(future)
    return max(dates)


def parse_personal_contract_file(path: Path, file_name: str | None = None) -> ParsedPersonalContract:
    """Извлечь название, краткое описание и дату окончания из файла договора."""
    warnings: list[str] = []
    name = file_name or path.name
    try:
        data = path.read_bytes()
    except OSError:
        return ParsedPersonalContract(
            title=Path(name).stem[:500] or "Договор",
            description=None,
            ends_on=None,
            warnings=["Не удалось прочитать файл."],
        )
    text = _plain_text(path, data)
    if not text.strip():
        warnings.append("Текст из файла не извлечён — заполните поля вручную.")
        return ParsedPersonalContract(
            title=Path(name).stem.replace("_", " ")[:500] or "Договор",
            description=None,
            ends_on=None,
            warnings=warnings,
        )
    title = _pick_title(text, name)
    description = _pick_description(text)
    ends_on = _pick_ends_on(text)
    if ends_on is None:
        warnings.append("Дата окончания не найдена — укажите вручную для напоминаний.")
    return ParsedPersonalContract(
        title=title,
        description=description,
        ends_on=ends_on,
        warnings=warnings,
    )
