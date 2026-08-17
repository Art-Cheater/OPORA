"""Отчёт по объектам и колонка статуса в сводной таблице."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import ContractStatus, ContractType, WorkObjectKind, WorkObjectStatus
from app.modules.contracts.services import ContractPayload, ContractService
from app.modules.objects.services import ObjectPayload, ObjectService
from app.modules.projects.services import ProjectPayload, ProjectService
from app.modules.reports.services import ReportsService, resolve_period


def _admin_id():
    return db.session.scalar(db.select(User.id).where(User.email == "admin@opora.ru"))


def test_objects_list_shows_status_column(admin_client):
    resp = admin_client.get("/objects/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Статус" in html
    assert "В закупках" in html
    assert "Расширенные фильтры" in html


def test_objects_report_page_and_totals(app, admin_client):
    with app.app_context():
        user_id = _admin_id()
        obj = ObjectService.create(
            ObjectPayload(
                name="Устройство наружного освещения ул. Отчётная",
                address="ул. Отчётная",
                object_kind=WorkObjectKind.PLANNED.value,
                plan_year=2026,
                budget_amount=Decimal("100000.00"),
                status=WorkObjectStatus.FREE.value,
            ),
            user_id,
        )
        project = ProjectService.create_project(
            ProjectPayload(
                code="TST-RPT-1",
                name=obj.display_address,
                description=None,
                status="draft",
                progress_percent=0,
                start_date=None,
                end_date=None,
                responsible_id=user_id,
                executor_ids=[],
                object_id=obj.id,
                sip_meters=Decimal("150.50"),
                poles_count=10,
                lights_count=12,
                shuno_count=1,
            ),
            user_id,
        )
        ContractService.create_contract(
            ContractPayload(
                contract_type=ContractType.WORK.value,
                number="К-ОТЧ-1",
                title=obj.name,
                description=None,
                status=ContractStatus.DRAFT.value,
                contract_date=date(2026, 1, 10),
                end_date=date(2026, 8, 31),
                responsible_id=user_id,
                contractor_name="ООО Подряд",
                amount=Decimal("80000.00"),
            ),
            user_id,
            object_id=obj.id,
        )
        project.sip_meters = Decimal("150.50")
        db.session.commit()

        period = resolve_period(
            "custom",
            date(2026, 1, 1),
            date(2026, 12, 31),
        )
        report = ReportsService.objects_report(period)
        assert len(report.rows) == 1
        row = report.rows[0]
        assert row.contract_number == "К-ОТЧ-1"
        assert row.sip_meters == Decimal("150.50")
        assert row.poles_count == 10
        assert row.lights_count == 12
        assert row.shuno_count == 1
        assert row.nmck == Decimal("100000.00")
        assert row.remainder == Decimal("20000.00")
        assert report.total_remainder == Decimal("20000.00")

    resp = admin_client.get("/reports/objects?period=custom&date_from=2026-01-01&date_to=2026-12-31")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "СИП, м" in html
    assert "К-ОТЧ-1" in html

    export = admin_client.get(
        "/reports/objects/export?period=custom&date_from=2026-01-01&date_to=2026-12-31"
    )
    assert export.status_code == 200
    assert "spreadsheetml" in (export.mimetype or "")
