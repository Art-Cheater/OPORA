"""Импорт заявок из Excel энергосервиса."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.extensions import db
from app.models.requests.request import Request
from app.modules.requests.energoservice_import import parse_energoservice_xlsx

REAL_FILE = Path(__file__).resolve().parent / "fixtures" / "energoservice.xlsx"


def _write_tmp(tmp_path, rows: list[tuple]) -> Path:
    path = tmp_path / "energo.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Лист1"
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    return path


def test_parse_street_and_yard_columns(tmp_path):
    path = _write_tmp(
        tmp_path,
        [
            ("Улица", "Двор", "кол-во", "№ заявки", "ПП", None, None, None),
            ("Заводская 8", None, 2, "101", "7", "срок исполнения до 10.02.2026 г.", None, None),
            (None, "Московская 163а", 1, 547, 1444, "срок исполнения до 6.02.2026", "сделано", None),
            (None, "Советская 92", 3, 882, 54, None, None, "шлагбаум"),
            (None, None, 1, 1, 1, None, None, None),
        ],
    )
    rows = parse_energoservice_xlsx(path)
    assert len(rows) == 3
    street = rows[0]
    assert street.kind == "street"
    assert street.raw_address == "Заводская 8"
    assert street.call_count == 2
    assert street.journal_numbers == "101"
    assert street.pp == "7"
    assert street.due_date == date(2026, 2, 10)
    yard = rows[1]
    assert yard.kind == "yard"
    assert yard.is_done is True
    assert yard.pp == "1444"
    barrier = rows[2]
    assert barrier.has_barrier is True
    assert barrier.call_count == 3


def test_import_creates_incomplete_requests(admin_client, app, tmp_path):
    path = _write_tmp(
        tmp_path,
        [
            ("Улица", "Двор", "кол-во", "№ заявки", "ПП"),
            ("Заводская 8", None, 2, "101", "7"),
            (None, "Казанская 107", 1, "811", "1313"),
        ],
    )
    with open(path, "rb") as handle:
        resp = admin_client.post(
            "/requests/import-energoservice",
            data={"file": (handle, "energo.xlsx")},
            follow_redirects=True,
        )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "создано 2" in body

    with app.app_context():
        imported = list(
            db.session.scalars(
                db.select(Request).where(
                    Request.active_filter(),
                    Request.address_source == "energoservice_xlsx",
                )
            )
        )
        assert len(imported) == 2
        first = next(item for item in imported if "Заводская" in (item.original_address or item.address))
        assert first.pp == "7"
        assert first.repeat_count == 2
        assert first.dispatcher_name is None
        assert first.applicant_name == "—"
        assert "Звонков по журналу: 2" in (first.description or "")

    with open(path, "rb") as handle:
        again = admin_client.post(
            "/requests/import-energoservice",
            data={"file": (handle, "energo.xlsx")},
            follow_redirects=True,
        )
    assert "пропущено 2" in again.get_data(as_text=True)


def test_parse_real_energoservice_file_if_present():
    if not REAL_FILE.exists():
        pytest.skip("локальная копия Excel энергосервиса не приложена")
    rows = parse_energoservice_xlsx(REAL_FILE)
    assert len(rows) >= 300
    assert any(row.kind == "street" for row in rows)
    assert any(row.kind == "yard" for row in rows)
    assert any(row.pp for row in rows)
    assert any(row.call_count >= 2 for row in rows)
