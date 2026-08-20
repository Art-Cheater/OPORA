"""Матчинг адресов ЕИС, идемпотентный импорт и RBAC окна ЕИС."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.integrations.zakupki.models import EisContract, EisOrder, EisSupplier
from app.integrations.zakupki.runner import EisParseResult
from app.models.auth.user import User
from app.models.contractors.contractor import Contractor
from app.models.contracts.contract import Contract
from app.models.contracts.contract_object import ContractObject
from app.models.eis.eis_import_event import EisImportEvent
from app.models.enums import TenderApplicationStatus, WorkObjectKind, WorkObjectStatus
from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_project import TenderProject
from app.models.work_objects.work_object import WorkObject
from app.modules.eis.matching import distinctive_tokens, match_work_objects
from app.modules.eis.services import EisImportService
from app.modules.objects.services import ObjectPayload, ObjectService


def _admin_id():
    return db.session.scalar(db.select(User.id).where(User.email == "admin@opora.ru"))


def _object(user_id, address: str, name: str | None = None) -> WorkObject:
    return ObjectService.create(
        ObjectPayload(
            name=name or f"Устройство наружного освещения {address}",
            work_type="Устройство наружного освещения",
            object_kind=WorkObjectKind.PLANNED.value,
            address=address,
            plan_year=2026,
            work_deadline=None,
            contract_number=None,
            contract_date=None,
            contractor_name=None,
            contract_amount=None,
            budget_amount=None,
            court_decision_number=None,
            result_text=None,
            source_sheet=None,
            notes=None,
            status=WorkObjectStatus.FREE.value,
        ),
        user_id,
    )


def _parse_result(*, matched: bool = True) -> EisParseResult:
    title = (
        "Выполнение работ по устройству наружного освещения в д. Студенец"
        if matched
        else "Выполнение работ по устройству наружного освещения в д. Небылица"
    )
    contract = EisContract(
        reestr_number="3434528856325000213",
        url="https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=3434528856325000213",
        number="Ф.2025.001724",
        contract_date=date(2025, 10, 27),
        start_date=date(2025, 10, 27),
        end_date=date(2026, 8, 22),
        amount=Decimal("2511041.28"),
        subject=title,
        delivery_place="Российская Федерация, обл Кировская, г.о. город Киров, д Студенец",
        stage="Исполнение",
        suppliers=[
            EisSupplier(
                name='ООО "ВПС"',
                inn="4345463078",
                kpp="434501001",
            )
        ],
    )
    order = EisOrder(
        reg_number="0740300000126000802",
        url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0740300000126000802",
        status="Определение поставщика завершено",
        nmck=Decimal("1781331.13"),
        object_title=title,
        published_at=date(2026, 7, 21),
        results_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/supplier-results.html?regNumber=0740300000126000802",
        contract_reestr_numbers=["3434528856325000213"],
        contracts=[contract],
    )
    return EisParseResult(orders=[order], contracts=[])


def test_distinctive_tokens_take_settlement_and_street():
    tokens = distinctive_tokens(
        "Выполнение работ по устройству наружного освещения ул. Гоголя, п. Чистые Пруды"
    )
    assert "гоголя" in tokens
    assert "чистые" in tokens or "пруды" in tokens
    assert "уды" not in tokens
    glued = distinctive_tokens("ул.Портовая в п. Сидоровка")
    assert "портовая" in glued
    assert "сидоровка" in glued


def test_match_unique_village(app):
    with app.app_context():
        user_id = _admin_id()
        obj = _object(user_id, "д. Студенец")
        hit = match_work_objects(
            ["Выполнение работ по устройству наружного освещения в д. Студенец"],
            [obj],
        )
        assert hit.work_object is not None
        assert hit.work_object.id == obj.id


def test_match_ambiguous_or_missing(app):
    with app.app_context():
        user_id = _admin_id()
        obj = _object(user_id, "д. Студенец")
        miss = match_work_objects(
            ["Выполнение работ по устройству освещения в д. Небылица"],
            [obj],
        )
        assert miss.work_object is None


def test_import_creates_chain_and_is_idempotent(app):
    with app.app_context():
        user_id = _admin_id()
        obj = _object(user_id, "д. Студенец")
        service = EisImportService()
        first = service.sync(trigger="manual", user_id=user_id, parse_result=_parse_result())
        assert first.status == "success"
        tenders = list(
            db.session.scalars(
                db.select(TenderApplication).where(TenderApplication.active_filter())
            )
        )
        contracts = list(db.session.scalars(db.select(Contract).where(Contract.active_filter())))
        contractors = list(
            db.session.scalars(db.select(Contractor).where(Contractor.active_filter()))
        )
        assert len(tenders) == 1
        assert tenders[0].eis_reg_number == "0740300000126000802"
        assert tenders[0].status == TenderApplicationStatus.WON.value
        assert tenders[0].nmck == Decimal("1781331.13")
        assert len(contracts) == 1
        assert contracts[0].number == "Ф.2025.001724"
        assert contracts[0].eis_reestr_number == "3434528856325000213"
        assert len(contractors) == 1
        assert contractors[0].inn == "4345463078"
        obj = db.session.get(WorkObject, obj.id)
        assert obj.status == WorkObjectStatus.IN_CONTRACT.value
        assert obj.budget_amount == Decimal("1781331.13")

        second = service.sync(trigger="manual", user_id=user_id, parse_result=_parse_result())
        assert second.status == "success"
        assert db.session.scalar(db.select(db.func.count(TenderApplication.id))) == 1
        assert db.session.scalar(db.select(db.func.count(Contract.id))) == 1
        assert second.summary["created_tenders"] == 0
        assert second.summary["updated_tenders"] >= 1


def test_import_unmatched_goes_to_journal(app):
    with app.app_context():
        user_id = _admin_id()
        _object(user_id, "д. Студенец")
        run = EisImportService().sync(
            trigger="manual",
            user_id=user_id,
            parse_result=_parse_result(matched=False),
        )
        events = list(
            db.session.scalars(
                db.select(EisImportEvent).where(
                    EisImportEvent.run_id == run.id,
                    EisImportEvent.kind == "unmatched",
                )
            )
        )
        assert events
        assert db.session.scalar(db.select(db.func.count(TenderApplication.id))) == 0


def test_import_matches_purchase_objects_not_header(app):
    with app.app_context():
        user_id = _admin_id()
        portovaya = _object(user_id, "п. Сидоровка, ул. Портовая")
        gogol = _object(user_id, "ул. Гоголя, п. Чистые Пруды")
        result = _parse_result()
        result.orders[0].object_title = "Выполнение работ по устройству наружного освещения"
        result.orders[0].purchase_objects = [
            "Устройство наружного освещения по ул.Портовая в п. Сидоровка",
            "ул. Космонавтов",
            "проезд между ул. Космонавтов и ул. Братьев Васнецовых",
            "Устройство наружного освещения ул. Гоголя, п. Чистые Пруды",
        ]
        run = EisImportService().sync(
            trigger="manual",
            user_id=user_id,
            parse_result=result,
        )
        assert run.status == "success"
        tenders = list(
            db.session.scalars(
                db.select(TenderApplication).where(TenderApplication.active_filter())
            )
        )
        assert len(tenders) == 1
        project_links = list(
            db.session.scalars(
                db.select(TenderProject).where(TenderProject.tender_id == tenders[0].id)
            )
        )
        assert len(project_links) == 2
        contract = db.session.scalar(db.select(Contract).where(Contract.active_filter()))
        assert contract is not None
        contract_ids = {
            row.object_id
            for row in db.session.scalars(
                db.select(ContractObject).where(ContractObject.contract_id == contract.id)
            )
        }
        assert contract_ids == {portovaya.id, gogol.id}
        portovaya = db.session.get(WorkObject, portovaya.id)
        gogol = db.session.get(WorkObject, gogol.id)
        assert portovaya.budget_amount is None
        assert gogol.budget_amount is None
        unmatched = list(
            db.session.scalars(
                db.select(EisImportEvent).where(
                    EisImportEvent.run_id == run.id,
                    EisImportEvent.kind == "unmatched",
                )
            )
        )
        assert any("Космонавтов" in event.message or "Васнецовых" in event.message for event in unmatched)


def test_eis_window_admin_ok(admin_client):
    ok = admin_client.get("/eis/")
    assert ok.status_code == 200
    assert "Импорт ЕИС".encode("utf-8") in ok.data


def test_eis_window_executor_denied(client):
    client.post(
        "/auth/login",
        data={"email": "executor@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    denied = client.get("/eis/")
    assert denied.status_code == 403
    run = client.post("/eis/run", follow_redirects=False)
    assert run.status_code == 403


def test_contractors_module_crud(admin_client, app):
    created = admin_client.post(
        "/contractors/new",
        data={
            "name": 'ООО "ТестСвет"',
            "inn": "4345000000",
            "kpp": "434501001",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert created.status_code in {302, 303}
    listing = admin_client.get("/contractors/")
    assert listing.status_code == 200
    assert "ТестСвет".encode("utf-8") in listing.data
    with app.app_context():
        contractor = db.session.scalar(
            db.select(Contractor).where(Contractor.inn == "4345000000")
        )
        assert contractor is not None
        card = admin_client.get(f"/contractors/{contractor.id}")
        assert card.status_code == 200
