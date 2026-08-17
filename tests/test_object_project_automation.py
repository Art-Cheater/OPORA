"""Регрессии автоматического перехода объект → проект."""

from __future__ import annotations

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import ProjectStatus, WorkObjectKind, WorkObjectStatus
from app.models.projects.project import Project
from app.models.projects.project_history import ProjectHistory
from app.models.work_objects.work_object import WorkObject
from app.modules.objects.services import (
    AUTO_PROJECT_RESULT,
    ObjectPayload,
    ObjectService,
)


def _admin_id():
    return db.session.scalar(
        db.select(User.id).where(User.email == "admin@opora.ru")
    )


def _payload(address: str, result_text: str | None) -> ObjectPayload:
    return ObjectPayload(
        name=f"Устройство наружного освещения {address}",
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
        result_text=result_text,
        source_sheet=None,
        notes="Муниципальная программа",
        status=WorkObjectStatus.FREE.value,
    )


def _projects_for(obj: WorkObject) -> list[Project]:
    return list(
        db.session.scalars(
            db.select(Project).where(
                Project.object_id == obj.id,
                Project.active_filter(),
            )
        ).all()
    )


def test_exact_normalized_result_creates_project_with_history(app):
    with app.app_context():
        user_id = _admin_id()
        obj = ObjectService.create(
            _payload(
                "ул. Автоматическая, 1",
                "  обследование проведено, ТЗ подготовлено,\n"
                "локально-сметный расчет готов.  ",
            ),
            user_id,
        )

        projects = _projects_for(obj)
        assert obj.status == WorkObjectStatus.IN_PROJECT.value
        assert len(projects) == 1
        assert projects[0].status == ProjectStatus.DRAFT.value
        assert projects[0].object_id == obj.id
        assert db.session.scalar(
            db.select(db.func.count(ProjectHistory.id)).where(
                ProjectHistory.project_id == projects[0].id
            )
        ) == 1


def test_repeated_object_update_does_not_duplicate_project(app):
    with app.app_context():
        user_id = _admin_id()
        obj = ObjectService.create(
            _payload("ул. Идемпотентная, 2", "Обследование запланировано."),
            user_id,
        )

        target_payload = _payload("ул. Идемпотентная, 2", AUTO_PROJECT_RESULT)
        ObjectService.update(obj, target_payload, user_id)
        ObjectService.update(obj, target_payload, user_id)

        assert obj.status == WorkObjectStatus.IN_PROJECT.value
        assert len(_projects_for(obj)) == 1


def test_repeated_import_does_not_duplicate_project(app, tmp_path, monkeypatch):
    imported = {
        "name": "Устройство наружного освещения ул. Импортная, 3",
        "work_type": "Устройство наружного освещения",
        "object_kind": WorkObjectKind.PLANNED.value,
        "address": "ул. Импортная, 3",
        "plan_year": 2026,
        "work_deadline": None,
        "contract_number": None,
        "contract_date": None,
        "contractor_name": None,
        "contract_amount": None,
        "budget_amount": None,
        "court_decision_number": None,
        "result_text": AUTO_PROJECT_RESULT,
        "source_sheet": "План 2026",
        "notes": "Муниципальная программа",
        "status": WorkObjectStatus.FREE.value,
    }
    monkeypatch.setattr(
        ObjectService,
        "parse_lighting_plan_xlsx",
        staticmethod(lambda _path: [imported]),
    )
    import_path = tmp_path / "plan.xlsx"
    import_path.write_bytes(b"test")

    with app.app_context():
        user_id = _admin_id()
        first = ObjectService.import_from_lighting_plan(import_path, user_id)
        second = ObjectService.import_from_lighting_plan(import_path, user_id)
        obj = db.session.scalar(
            db.select(WorkObject).where(WorkObject.address == imported["address"])
        )

        assert first.created == 1
        assert second.updated == 1
        assert obj is not None
        assert obj.status == WorkObjectStatus.IN_PROJECT.value
        assert len(_projects_for(obj)) == 1


def test_object_full_page_and_modal_share_notes_label(admin_client):
    expected = "Основание для проведения работ"

    full_page = admin_client.get("/objects/new")
    modal = admin_client.get(
        "/objects/new",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert full_page.status_code == 200
    assert modal.status_code == 200
    assert expected in full_page.get_data(as_text=True)
    assert expected in modal.get_data(as_text=True)


def test_tz_alt_result_creates_project_in_project_status(app):
    with app.app_context():
        user_id = _admin_id()
        obj = ObjectService.create(
            _payload(
                "ул. ТЗ Альтернативная, 4",
                "Подготовлено техническое задание и локально-сметный расчет",
            ),
            user_id,
        )
        assert obj.status == WorkObjectStatus.IN_PROJECT.value
        assert len(_projects_for(obj)) == 1
        assert _projects_for(obj)[0].status == ProjectStatus.DRAFT.value


def test_procurement_result_creates_tender_draft(app):
    from app.models.tenders.tender_application import TenderApplication

    with app.app_context():
        user_id = _admin_id()
        obj = ObjectService.create(
            _payload("ул. Закупки, 5", "В закупках"),
            user_id,
        )
        tenders = list(
            db.session.scalars(
                db.select(TenderApplication).where(
                    TenderApplication.object_id == obj.id,
                    TenderApplication.active_filter(),
                )
            )
        )
        assert obj.status == WorkObjectStatus.IN_TENDER.value
        assert len(_projects_for(obj)) == 1
        assert len(tenders) == 1
        assert tenders[0].work_deadline_date is None


def test_contract_number_creates_full_chain_unless_accepted(app):
    from datetime import date

    from app.models.contracts.contract import Contract
    from app.models.contracts.contract_object import ContractObject
    from app.models.tenders.tender_application import TenderApplication

    with app.app_context():
        user_id = _admin_id()
        payload = _payload("ул. Контрактная, 6", "Работы ведутся")
        payload.contract_number = "К-100"
        payload.contractor_name = "ООО Свет"
        payload.contract_amount = None
        payload.budget_amount = None
        payload.work_deadline = "31.12.2026"
        obj = ObjectService.create(payload, user_id)

        tenders = list(
            db.session.scalars(
                db.select(TenderApplication).where(TenderApplication.object_id == obj.id)
            )
        )
        contracts = list(
            db.session.scalars(
                db.select(Contract)
                .join(ContractObject, ContractObject.contract_id == Contract.id)
                .where(ContractObject.object_id == obj.id)
            )
        )
        assert obj.status == WorkObjectStatus.IN_CONTRACT.value
        assert len(_projects_for(obj)) == 1
        assert len(tenders) == 1
        assert tenders[0].work_deadline_date == date(2026, 12, 31)
        assert len(contracts) == 1
        assert contracts[0].number == "К-100"

        ObjectService.update(obj, payload, user_id)
        assert len(_projects_for(obj)) == 1
        assert (
            db.session.scalar(db.select(db.func.count(Contract.id)).where(Contract.number == "К-100"))
            == 1
        )


def test_accepted_result_does_not_create_contract_draft(app):
    from app.models.contracts.contract import Contract
    from app.models.contracts.contract_object import ContractObject

    with app.app_context():
        user_id = _admin_id()
        payload = _payload("ул. Принятая, 7", "Объект принят заказчиком")
        payload.contract_number = "К-200"
        payload.status = WorkObjectStatus.COMPLETED.value
        obj = ObjectService.create(payload, user_id)
        contracts = list(
            db.session.scalars(
                db.select(Contract)
                .join(ContractObject, ContractObject.contract_id == Contract.id)
                .where(ContractObject.object_id == obj.id)
            )
        )
        assert obj.status == WorkObjectStatus.COMPLETED.value
        assert contracts == []
        assert _projects_for(obj) == []
