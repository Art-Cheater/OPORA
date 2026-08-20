"""Договора на опорах: разбор Word и поиск оборудования."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from app.extensions import db
from app.models.agreements.pole_agreement import PoleAgreement
from app.modules.agreements.parse_docx import parse_agreement_docx
from app.modules.agreements.services import AgreementService

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_REAL_FILES = [
    Path(r"e:\Договор_24.docx"),
    Path(r"e:\Проект договора на 2026(один год)  от  Ростелекома  (1).docx"),
    Path(r"e:\10-24 ДОГОВОР ТТК-Связь 3шт.docx"),
]
_ADDON_FILE = Path(r"c:\Users\fa220\Downloads\No6_02.03.2026__1934-1119231751._3674.docx")


def _p(text: str) -> str:
    return f'<w:p xmlns:w="{_W}"><w:r><w:t>{text}</w:t></w:r></w:p>'


def _tc(text: str) -> str:
    return f'<w:tc xmlns:w="{_W}"><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>'


def _tr(cells: list[str]) -> str:
    inner = "".join(_tc(item) for item in cells)
    return f'<w:tr xmlns:w="{_W}">{inner}</w:tr>'


def make_sample_docx(*extra_tables: list[list[str]]) -> bytes:
    tables = [
        [
            ["№ п/п", "Адрес", "Количество узлов крепления (шт.)", "Количество опор (шт.)", "Примечание"],
            ["1.", "ул. Карла Либкнехта", "1", "3", ""],
            ["", "Итого:", "", "3", ""],
        ]
    ]
    tables.extend(extra_tables)
    table_xml = "".join(
        f'<w:tbl xmlns:w="{_W}">' + "".join(_tr(row) for row in table) + "</w:tbl>"
        for table in tables
    )
    body = "".join(
        [
            _p("ДОГОВОР № 10 / 24"),
            _p("на обслуживание узлов крепления"),
            _p("для подвески волоконно-оптического кабеля"),
            _p("на опорах наружного освещения"),
            _p(
                "Муниципальное казенное учреждение «Дирекция благоустройства города Кирова» "
                "(далее – «Исполнитель»), и Общество с ограниченной ответственностью «ТТК-Связь» "
                "(ООО «ТТК-Связь»), (далее – «Заказчик»), заключили настоящий договор."
            ),
            _p("1.2. Срок оказания услуг: с 01.01.2024 г. по 31.12.2024 г."),
            table_xml,
        ]
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_parse_sample_address_program():
    parsed = parse_agreement_docx(make_sample_docx())
    assert parsed.number and "10" in parsed.number
    assert parsed.customer_name and "ТТК" in parsed.customer_name
    assert parsed.period_from.isoformat() == "2024-01-01"
    assert len(parsed.sites) == 1
    assert "Либкнехта" in parsed.sites[0].address
    assert parsed.sites[0].poles_count == 3


def make_wrong_docx() -> bytes:
    body = "".join(
        [
            _p("ДОГОВОР № 99/24"),
            _p("на поставку канцелярских товаров"),
            _p("Муниципальное казенное учреждение «Дирекция благоустройства города Кирова» и ООО «Бумага» заключили договор."),
        ]
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_parse_real_rostel_and_ttk_if_present():
    available = [path for path in _REAL_FILES if path.is_file()]
    if len(available) < 2:
        return
    parsed = [parse_agreement_docx(path) for path in available]
    assert any(item.sites for item in parsed)
    assert any(item.customer_name and "Ростелеком" in item.customer_name for item in parsed) or any(
        item.customer_name and "ТТК" in item.customer_name for item in parsed
    )


def test_upload_and_address_lookup(admin_client, app):
    resp = admin_client.get("/agreements/")
    assert resp.status_code == 200
    assert "Договора".encode("utf-8") in resp.data

    uploaded = admin_client.post(
        "/agreements/upload",
        data={
            "file": (io.BytesIO(make_sample_docx()), "ttk.docx"),
            "submit": "Загрузить",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert uploaded.status_code in {302, 303}

    with app.app_context():
        item = db.session.scalar(db.select(PoleAgreement))
        assert item is not None
        assert item.customer_name and "ТТК" in item.customer_name
        assert item.sites

    found = admin_client.get("/agreements/?q=Либкнехта")
    assert found.status_code == 200
    assert "Есть оборудование".encode("utf-8") in found.data
    assert "ТТК".encode("utf-8") in found.data

    missing = admin_client.get("/agreements/?q=улица Небылица")
    assert missing.status_code == 200
    assert "не видно".encode("utf-8") in missing.data


def test_geocode_query_strips_range_and_parens():
    from app.modules.agreements.geocode import geocode_query

    assert geocode_query("ул. Труда от ул. Ленина до ул. Владимирская") == "Киров, улица Труда"
    query = geocode_query("г. Киров, ул. Орловская (от ул. Орловская, 23 до ул. Орловская, 19)")
    assert "Орловская" in query
    assert "23" not in query
    assert geocode_query("по ул. Карла Либкнехта").endswith("Карла Либкнехта")


def test_map_markers_include_agreement(admin_client, app, monkeypatch):
    monkeypatch.setattr(
        "app.modules.agreements.services.geocode_address",
        lambda address: (58.6035, 49.668),
    )
    uploaded = admin_client.post(
        "/agreements/upload",
        data={
            "file": (io.BytesIO(make_sample_docx()), "ttk.docx"),
            "submit": "Загрузить",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert uploaded.status_code in {302, 303}

    with app.app_context():
        AgreementService.geocode_missing(limit=5)

    page = admin_client.get("/agreements/")
    assert page.status_code == 200
    assert b"agreementMap" in page.data
    assert "Оборудование на карте".encode("utf-8") in page.data

    payload = admin_client.get("/agreements/map.json")
    assert payload.status_code == 200
    data = payload.get_json()
    assert data["remaining"] == 0
    assert len(data["points"]) == 1
    point = data["points"][0]
    assert "Либкнехта" in point["address"]
    assert "ТТК" in point["customer"]
    assert point["number"]
    assert point["url"].startswith("/agreements/")
    assert point["file_url"].endswith("/file")
    assert point["period"] != "—"
    assert point["poles"] == 3

    with app.app_context():
        item = db.session.scalar(db.select(PoleAgreement))
        detail = admin_client.get(f"/agreements/{item.id}")
    assert detail.status_code == 200
    assert b"agreementMap" in detail.data


def test_parse_all_address_tables():
    parsed = parse_agreement_docx(
        make_sample_docx(
            [
                ["№ пп", "Адрес", "Кол-во узлов крепления, шт", "Кол-во опор, шт.", "Примечание"],
                ["1", "ул. Лепсе", "1", "16", ""],
                ["2", "ул. Профсоюзная", "1", "4", ""],
            ]
        )
    )
    assert len(parsed.sites) == 3
    assert parsed.number == "10/24"


def test_parse_addon_file_all_tables():
    if not _ADDON_FILE.is_file():
        return
    parsed = parse_agreement_docx(_ADDON_FILE)
    assert parsed.number == "1/24"
    assert parsed.customer_name and ("МТС" in parsed.customer_name or "ТелеСистем" in parsed.customer_name)
    assert len(parsed.sites) == 366
    assert any("Лепсе" in site.address for site in parsed.sites)
    assert any("Зянкина" in site.address for site in parsed.sites)


def test_upload_updates_same_number_and_rejects_wrong(admin_client, app):
    first = admin_client.post(
        "/agreements/upload",
        data={"file": (io.BytesIO(make_sample_docx()), "ttk.docx"), "submit": "Загрузить"},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert first.status_code == 200
    assert "Загружен".encode("utf-8") in first.data

    second = admin_client.post(
        "/agreements/upload",
        data={
            "file": (
                io.BytesIO(
                    make_sample_docx(
                        [
                            ["№ п/п", "Адрес", "Количество узлов крепления (шт.)", "Количество опор (шт.)", "Примечание"],
                            ["1.", "ул. Лепсе", "2", "5", ""],
                        ]
                    )
                ),
                "ttk-upd.docx",
            ),
            "submit": "Загрузить",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert second.status_code == 200
    assert "Обновлён".encode("utf-8") in second.data
    with app.app_context():
        rows = list(db.session.scalars(db.select(PoleAgreement).where(PoleAgreement.active_filter())))
        assert len(rows) == 1
        assert len(rows[0].sites) == 2

    wrong = admin_client.post(
        "/agreements/upload",
        data={"file": (io.BytesIO(make_wrong_docx()), "paper.docx"), "submit": "Загрузить"},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert wrong.status_code == 200
    assert "Договор не тот".encode("utf-8") in wrong.data


def test_index_hides_duplicate_numbers(admin_client, app):
    admin_client.post(
        "/agreements/upload",
        data={"file": (io.BytesIO(make_sample_docx()), "ttk.docx"), "submit": "Загрузить"},
        content_type="multipart/form-data",
    )
    with app.app_context():
        first = db.session.scalar(db.select(PoleAgreement).where(PoleAgreement.active_filter()))
        clone = PoleAgreement(
            title="Копия",
            number=first.number,
            customer_name=first.customer_name,
        )
        db.session.add(clone)
        db.session.commit()
        assert db.session.scalar(
            db.select(db.func.count()).select_from(PoleAgreement).where(PoleAgreement.active_filter())
        ) == 2

    page = admin_client.get("/agreements/")
    assert page.status_code == 200
    assert "Убраны повторы".encode("utf-8") in page.data
    with app.app_context():
        assert (
            db.session.scalar(
                db.select(db.func.count()).select_from(PoleAgreement).where(PoleAgreement.active_filter())
            )
            == 1
        )
