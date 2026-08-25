"""Разбор личных договоров/контрактов: название, описание, дата окончания.

Поддерживает PDF (текст и сканы через OCR), DOCX, DOC/RTF (через LibreOffice), TXT.
Типичные муниципальные контракты 44‑ФЗ: «Муниципальный контракт №…»,
«действует по «31» декабря 2026», «Сроки оказания услуг: с … по …».
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SPACE_RE = re.compile(r"\s+")

_MONTHS_RU: dict[str, int] = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

# 31.12.2026 / 31/12/2026
_DATE_NUM_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")
# «31» декабря 2026 / «_06»_августа 2026 / 01 сентября 2026 года
_DATE_VERBAL_RE = re.compile(
    r"[«\"'„_\s]*(\d{1,2})[»\"'“_\s]*\s*"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"\s+(\d{4})",
    re.I,
)

_TITLE_LINE_RE = re.compile(
    r"((?:муниципальн\w+\s+)?(?:государственн\w+\s+)?(?:договор|контракт|соглашени[ея])"
    r"(?:\s+(?:купл[ии]-продаж[ии]|аренды|поставки|оказания\s+услуг))?)"
    r"[^\n]{0,200}",
    re.I,
)
_SUBJECT_HEAD_RE = re.compile(
    r"(?:предмет\s+(?:договора|контракта)|1\.\s*предмет)"
    r"[^\n]{0,40}\n?(.{10,400})",
    re.I | re.S,
)
_ON_SUBJECT_RE = re.compile(
    r"^\s*на\s+(оказание|выполнение|поставку|предоставление|аренду|обслуживание|"
    r"ремонт|содержание|вывоз|перевозку|работы|услуги)[^\n]{5,200}",
    re.I,
)

# Игнорируем сроки действия сертификатов ЭП
_CERT_NOISE_RE = re.compile(
    r"действителен|сертификат|электронн\w+\s+подпис|идентификатор\s*:|оператор\s+эдо|"
    r"дата\s+и\s+время\s+подписания\s+документа",
    re.I,
)

_END_CONTEXT_RE = re.compile(
    r"(?:"
    r"срок(?:и)?\s+(?:действия|оказания|исполнения|выполнения)|"
    r"действует\s+по|"
    r"действует\s+до(?!\s+полного)|"
    r"окончани[ея]\s+(?:срока|договора|контракта)"
    r")",
    re.I,
)


@dataclass
class ParsedPersonalContract:
    title: str
    description: str | None
    ends_on: date | None
    warnings: list[str]


def _clean(text: str) -> str:
    return _SPACE_RE.sub(" ", (text or "").replace("\xa0", " ").replace("_", " ")).strip()


def _make_date(day: int, month: int, year: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_numeric_date(raw: str) -> date | None:
    match = _DATE_NUM_RE.search(raw or "")
    if not match:
        return None
    return _make_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _parse_verbal_date(raw: str) -> date | None:
    match = _DATE_VERBAL_RE.search(raw or "")
    if not match:
        return None
    month = _MONTHS_RU.get(match.group(2).casefold())
    if not month:
        return None
    return _make_date(int(match.group(1)), month, int(match.group(3)))


def _parse_any_date(raw: str) -> date | None:
    return _parse_verbal_date(raw) or _parse_numeric_date(raw)


def _is_plausible_end_date(value: date, window: str) -> bool:
    """Отсекает даты законов (2013) и сроки сертификатов."""
    if value.year < 2020:
        return False
    if re.search(r"закон|№\s*44\s*-?\s*фз|статьи\s+\d+", window, re.I):
        return False
    if _CERT_NOISE_RE.search(window):
        return False
    # слишком старая «дата окончания» почти наверняка мусор
    if value < date.today().replace(year=date.today().year - 1):
        return False
    return True


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


def _pdf_text_pypdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(BytesIO(data))
        # сроки часто не на 1-й странице; сканы/ЭП раздувают объём
        limit = min(len(reader.pages), 20)
        parts = [(page.extract_text() or "") for page in reader.pages[:limit]]
        return "\n".join(parts)
    except Exception:
        logger.debug("pypdf extract failed", exc_info=True)
        return ""


def _pdf_text_pymupdf(data: bytes) -> str:
    try:
        import pymupdf
    except ImportError:
        return ""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        limit = min(doc.page_count, 20)
        parts = [doc.load_page(i).get_text("text") or "" for i in range(limit)]
        doc.close()
        return "\n".join(parts)
    except Exception:
        logger.debug("pymupdf extract failed", exc_info=True)
        return ""


def _ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _pdf_text_ocr(data: bytes, *, max_pages: int = 3) -> str:
    """OCR первых страниц скана (нужны tesseract + pymupdf)."""
    if not _ocr_available():
        return ""
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return ""
    parts: list[str] = []
    try:
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            # 2× для лучшего OCR кириллицы
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            try:
                text = pytesseract.image_to_string(image, lang="rus+eng") or ""
            except pytesseract.TesseractError:
                text = pytesseract.image_to_string(image, lang="eng") or ""
            if text.strip():
                parts.append(text)
    finally:
        doc.close()
    return "\n".join(parts)


def _pdf_text(data: bytes) -> str:
    text = _pdf_text_pypdf(data)
    if len(_clean(text)) < 80:
        alt = _pdf_text_pymupdf(data)
        if len(_clean(alt)) > len(_clean(text)):
            text = alt
    if len(_clean(text)) < 80:
        ocr = _pdf_text_ocr(data)
        if len(_clean(ocr)) > len(_clean(text)):
            text = ocr
    return text


def _convert_office_to_docx(path: Path) -> Path | None:
    try:
        from app.modules.agreements.convert import to_docx_path
    except Exception:
        return None
    try:
        return to_docx_path(path)
    except Exception:
        logger.debug("office convert failed for %s", path, exc_info=True)
        return None


def _plain_text(path: Path, data: bytes) -> str:
    suffix = path.suffix.lower()
    if suffix in {".docx", ".docm"}:
        try:
            return "\n".join(_docx_paragraphs(data))
        except Exception:
            return ""
    if suffix == ".pdf":
        return _pdf_text(data)
    if suffix in {".txt"}:
        return data.decode("utf-8", errors="ignore")
    if suffix in {".doc", ".rtf", ".odt"} or (
        data[:8].startswith(b"\xd0\xcf\x11\xe0") or data[:5].startswith(b"{\\rtf")
    ):
        converted = _convert_office_to_docx(path)
        if converted is not None and converted.is_file():
            try:
                return "\n".join(_docx_paragraphs(converted.read_bytes()))
            except Exception:
                pass
            finally:
                # временный каталог конвертера — не трогаем исходник
                if converted.resolve() != path.resolve():
                    parent = converted.parent
                    try:
                        converted.unlink(missing_ok=True)
                        if parent.name.startswith("opora-"):
                            shutil.rmtree(parent, ignore_errors=True)
                    except OSError:
                        pass
        if suffix == ".rtf":
            return data.decode("utf-8", errors="ignore")
        # слабый fallback для .doc (OLE): вытащить читаемые куски
        try:
            chunk = data.decode("cp1251", errors="ignore")
            return "\n".join(line for line in chunk.splitlines() if len(_clean(line)) > 20)[:30000]
        except Exception:
            return ""
    try:
        return data.decode("utf-8", errors="ignore")[:30000]
    except Exception:
        return ""


def _title_from_filename(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    return stem[:500] if stem else "Договор"


def _pick_title(text: str, fallback: str) -> str:
    lines = [_clean(line) for line in text.splitlines()]
    lines = [line for line in lines if line and len(line) > 3]
    file_title = _title_from_filename(fallback)

    for index, line in enumerate(lines[:50]):
        match = _TITLE_LINE_RE.search(line)
        if not match:
            continue
        title = _clean(match.group(0))
        # следующая строка «на оказание услуг…»
        if index + 1 < len(lines) and _ON_SUBJECT_RE.match(lines[index + 1]):
            title = _clean(f"{title} {lines[index + 1]}")
        if len(title) >= 12:
            # дополним стороной из имени файла, если её нет в тексте заголовка
            for token in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", file_title):
                if token.casefold() not in title.casefold() and token.casefold() not in {
                    "услуги",
                    "договор",
                    "контракт",
                    "муниципальный",
                }:
                    if any(ch.isdigit() for ch in token):
                        continue
                    # короткие бренды вроде Куприт / Мегафон
                    if token[:1].isupper() or token.isupper():
                        title = f"{title} ({token})"
                        break
            return title[:500]

    return file_title or "Договор"


def _pick_description(text: str) -> str | None:
    match = _SUBJECT_HEAD_RE.search(text[:12000])
    if match:
        body = _clean(match.group(1))
        body = re.sub(r"^\d+(\.\d+)*\.?\s*", "", body)
        if len(body) > 20:
            return body[:800]

    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    for line in lines[:40]:
        if _ON_SUBJECT_RE.match(line):
            return line[:800]
    body = [
        line
        for line in lines[1:15]
        if len(line) > 30 and not _TITLE_LINE_RE.search(line) and not _CERT_NOISE_RE.search(line)
    ]
    if not body:
        return None
    return _clean(" ".join(body[:2]))[:800]


def _iter_end_candidates(text: str) -> list[date]:
    """Кандидаты даты окончания с приоритетом контекста «срок действия / действует по»."""
    found: list[tuple[int, date]] = []  # (priority, date) меньше = лучше
    # сроки часто на 2–4 странице; сертификаты ЭП тоже, их отфильтруем
    sample = text[:80000]

    patterns: list[tuple[int, re.Pattern[str]]] = [
        (
            1,
            re.compile(
                r"(?:действует\s+по|действует\s+до(?!\s+полного))\s+"
                r"([«\"'_\s]*\d{1,2}[»\"'_\s]*\s*(?:января|февраля|марта|апреля|мая|июня|июля|"
                r"августа|сентября|октября|ноября|декабря)\s+\d{4}"
                r"|\d{1,2}[./]\d{1,2}[./]\d{4})",
                re.I,
            ),
        ),
        (
            1,
            re.compile(
                r"срок(?:и)?\s+(?:оказания|действия|исполнения|выполнения)[^\n]{0,60}?"
                r"по\s+"
                r"([«\"'_\s]*\d{1,2}[»\"'_\s]*\s*(?:января|февраля|марта|апреля|мая|июня|июля|"
                r"августа|сентября|октября|ноября|декабря)\s+\d{4}"
                r"|\d{1,2}[./]\d{1,2}[./]\d{4})",
                re.I,
            ),
        ),
        (
            2,
            re.compile(
                r"с\s*"
                r"(?:[«\"'_\s]*\d{1,2}[»\"'_\s]*\s*(?:января|февраля|марта|апреля|мая|июня|июля|"
                r"августа|сентября|октября|ноября|декабря)\s+\d{4}|\d{1,2}[./]\d{1,2}[./]\d{4})"
                r"\s*(?:г\.?|года)?\s*по\s*"
                r"([«\"'_\s]*\d{1,2}[»\"'_\s]*\s*(?:января|февраля|марта|апреля|мая|июня|июля|"
                r"августа|сентября|октября|ноября|декабря)\s+\d{4}"
                r"|\d{1,2}[./]\d{1,2}[./]\d{4})",
                re.I,
            ),
        ),
    ]

    for priority, pattern in patterns:
        for match in pattern.finditer(sample):
            window_start = max(0, match.start() - 80)
            window = sample[window_start : match.end() + 20]
            if _CERT_NOISE_RE.search(window):
                continue
            if re.search(r"до\s+полного\s+исполнения", window, re.I):
                continue
            parsed = _parse_any_date(match.group(1))
            if parsed and _is_plausible_end_date(parsed, window):
                found.append((priority, parsed))

    # запасной: даты рядом с «срок действия»
    for match in _END_CONTEXT_RE.finditer(sample):
        window = sample[max(0, match.start() - 100) : match.start() + 220]
        if _CERT_NOISE_RE.search(window):
            continue
        if re.search(r"до\s+полного\s+исполнения", window, re.I):
            continue
        # предпочитаем последнюю дату в окне (конец периода)
        nums = list(_DATE_NUM_RE.finditer(window))
        verbals = list(_DATE_VERBAL_RE.finditer(window))
        last = None
        if verbals:
            last = _parse_verbal_date(verbals[-1].group(0))
        elif nums:
            last = _parse_numeric_date(nums[-1].group(0))
        if last and _is_plausible_end_date(last, window):
            found.append((3, last))

    found.sort(key=lambda item: (item[0], -item[1].toordinal()))
    # уникальные по убыванию приоритета
    seen: set[date] = set()
    ordered: list[date] = []
    for _, value in found:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _pick_ends_on(text: str) -> date | None:
    candidates = _iter_end_candidates(text)
    if not candidates:
        return None
    # лучший приоритет уже первый; при равных — самая поздняя в группе приоритета 1–2
    return candidates[0]


def parse_personal_contract_text(text: str, file_name: str = "contract.txt") -> ParsedPersonalContract:
    """Разбор уже извлечённого текста (удобно для тестов)."""
    warnings: list[str] = []
    cleaned = text or ""
    if not _clean(cleaned):
        return ParsedPersonalContract(
            title=_title_from_filename(file_name),
            description=None,
            ends_on=None,
            warnings=["Текст из файла не извлечён — заполните поля вручную."],
        )
    title = _pick_title(cleaned, file_name)
    description = _pick_description(cleaned)
    ends_on = _pick_ends_on(cleaned)
    if ends_on is None:
        warnings.append("Дата окончания не найдена — укажите вручную для напоминаний.")
    return ParsedPersonalContract(
        title=title,
        description=description,
        ends_on=ends_on,
        warnings=warnings,
    )


def parse_personal_contract_file(path: Path, file_name: str | None = None) -> ParsedPersonalContract:
    """Извлечь название, краткое описание и дату окончания из файла договора."""
    warnings: list[str] = []
    name = file_name or path.name
    try:
        data = path.read_bytes()
    except OSError:
        return ParsedPersonalContract(
            title=_title_from_filename(name),
            description=None,
            ends_on=None,
            warnings=["Не удалось прочитать файл."],
        )

    # если исходник .doc/.pdf без текста — копируем во временный файл с правильным именем
    work_path = path
    tmp_dir = None
    suffix = Path(name).suffix.lower() or path.suffix.lower()
    if path.suffix.lower() != suffix and suffix:
        tmp_dir = Path(tempfile.mkdtemp(prefix="opora-contract-"))
        work_path = tmp_dir / Path(name).name
        work_path.write_bytes(data)

    try:
        text = _plain_text(work_path, data)
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if not _clean(text):
        warnings.append(
            "Текст из файла не извлечён (возможно скан без OCR). "
            "Название взято из имени файла — дату укажите вручную."
        )
        if Path(name).suffix.lower() == ".pdf" and not _ocr_available():
            warnings.append("Для сканов PDF на сервере нужен Tesseract (OCR).")
        return ParsedPersonalContract(
            title=_title_from_filename(name),
            description=None,
            ends_on=None,
            warnings=warnings,
        )

    parsed = parse_personal_contract_text(text, name)
    parsed.warnings.extend(warnings)
    return parsed
