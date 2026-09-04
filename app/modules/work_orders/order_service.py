"""Заполнение бланка-распоряжения на основе неизменяемого XLSX-шаблона."""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.styles import Alignment

TEMPLATE_PATH = Path(__file__).with_name("resources") / "order_template.xlsx"
WORK_ROWS = tuple(range(18, 31)) + tuple(range(36, 53))
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def excel_text(value: str | None) -> str:
    """Обычный пользовательский текст не должен становиться Excel-формулой."""
    text = (value or "").strip()
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def order_filename(number: str | None) -> str:
    safe_number = re.sub(r"[^0-9A-Za-zА-Яа-яЁё._-]+", "_", (number or "").strip()).strip("._") or "без_номера"
    date_label = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y")
    return f"Распоряжение_№{safe_number}_{date_label}.xlsx"


def build_order_workbook(plan: dict, fields: dict[str, str]) -> bytes:
    if not TEMPLATE_PATH.is_file():
        raise ValueError("Шаблон бланка-распоряжения не найден.")
    workbook = load_workbook(TEMPLATE_PATH)
    sheet = workbook["табель"]
    number = excel_text(fields.get("order_number"))
    sheet["D4"] = f"Бланк-распоряжение №{number}" if number else "Бланк-распоряжение №_____________"
    for cell, key in (("D7", "producer"), ("F7", "crew_lead"), ("F9", "crew_members"), ("F10", "lift_responsible")):
        if fields.get(key):
            sheet[cell] = excel_text(fields[key])
    if fields.get("crew_count"):
        sheet["D9"] = excel_text(fields["crew_count"])

    for row in WORK_ROWS:
        for col in range(1, 8):
            sheet.cell(row, col).value = None
    for index, item in enumerate(plan["items"]):
        if index >= len(WORK_ROWS):
            break
        row = WORK_ROWS[index]
        sheet.cell(row, 1).value = index + 1
        sheet.cell(row, 2).value = excel_text(item.get("pp") or "")
        sheet.cell(row, 3).value = excel_text(item.get("address") or "")
        sheet.cell(row, 4).value = excel_text(item.get("description") or "")
        for col in range(1, 8):
            cell = sheet.cell(row, col)
            cell.alignment = Alignment(horizontal="left" if col in {3, 4} else "center", vertical="top", wrap_text=True)
        text_size = max(len(str(item.get("address") or "")), len(str(item.get("description") or "")))
        sheet.row_dimensions[row].height = max(sheet.row_dimensions[row].height or 15, min(72, 18 + 12 * ((text_size + 28) // 29)))
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
