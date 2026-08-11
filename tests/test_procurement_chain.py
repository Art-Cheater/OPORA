"""Тесты закупочной цепочки: объект → проект → торги → контракт."""

from __future__ import annotations

import uuid

from app.extensions import db
from app.models.enums import (
    ContractStatus,
    ProjectStatus,
    TenderApplicationStatus,
    WorkObjectStatus,
)
from app.models.projects.project import Project
from app.models.tenders.tender_application import TenderApplication
from app.models.work_objects.work_object import WorkObject
from app.modules.contracts.services import ContractPayload, ContractService
from app.modules.objects.services import ObjectPayload, ObjectService
from app.modules.projects.services import ProjectPayload, ProjectService
from app.modules.tenders.services import TenderPayload, TenderService


def _admin_id(app):
    from app.models.auth.user import User

    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "admin@opora.ru"))
        if user is None:
            user = db.session.scalar(db.select(User).limit(1))
        return user.id


def test_procurement_chain_happy_path(app, admin_client):
    user_id = _admin_id(app)
    with app.app_context():
        obj = ObjectService.create(
            ObjectPayload(
                name="Устройство НО по ул. Тестовая",
                address="ул. Тестовая",
                plan_year=2026,
                notes=None,
                status=WorkObjectStatus.FREE.value,
            ),
            user_id,
        )
        assert obj.status == WorkObjectStatus.FREE.value

        project = ProjectService.create_project(
            ProjectPayload(
                code=f"PRJ-TEST-{uuid.uuid4().hex[:6].upper()}",
                name="Проект тест",
                description="",
                status=ProjectStatus.ACTIVE.value,
                progress_percent=0,
                start_date=None,
                end_date=None,
                responsible_id=user_id,
                executor_ids=[],
                object_id=obj.id,
            ),
            user_id,
        )
        obj = db.session.get(WorkObject, obj.id)
        assert obj.status == WorkObjectStatus.IN_PROJECT.value
        assert project.object_id == obj.id

        tender = TenderService.create(
            TenderPayload(
                number=f"ТРГ-TEST-{uuid.uuid4().hex[:6].upper()}",
                title="Торги тест",
                description=None,
                status=TenderApplicationStatus.DRAFT.value,
                responsible_id=user_id,
                project_ids=[project.id],
            ),
            user_id,
        )
        project = db.session.get(Project, project.id)
        obj = db.session.get(WorkObject, obj.id)
        assert project.status == ProjectStatus.IN_TENDER.value
        assert obj.status == WorkObjectStatus.IN_TENDER.value

        TenderService.set_status(tender, TenderApplicationStatus.WON.value, user_id)
        tender = db.session.get(TenderApplication, tender.id)

        contract = ContractService.create_from_tender(
            tender,
            ContractPayload(
                contract_type="work",
                number=f"CTR-TEST-{uuid.uuid4().hex[:6].upper()}",
                title="Контракт тест",
                description=None,
                status=ContractStatus.DRAFT.value,
                contract_date=None,
                responsible_id=user_id,
                contractor_name="ООО Тест",
                amount=1000,
            ),
            user_id,
        )
        assert len(contract.work_objects) == 1
        project = db.session.get(Project, project.id)
        obj = db.session.get(WorkObject, obj.id)
        assert project.status == ProjectStatus.IN_CONTRACT.value
        assert obj.status == WorkObjectStatus.IN_CONTRACT.value

        ContractService.transition(contract, ContractStatus.ACTIVE.value, user_id)
        ContractService.transition(contract, ContractStatus.WORK_DOCS_PENDING.value, user_id)
        ContractService.transition(contract, ContractStatus.IN_PROGRESS.value, user_id)
        ContractService.transition(contract, ContractStatus.KS2_PENDING.value, user_id)
        ContractService.transition(contract, ContractStatus.COMPLETED.value, user_id)

        obj = db.session.get(WorkObject, obj.id)
        project = db.session.get(Project, project.id)
        assert obj.status == WorkObjectStatus.COMPLETED.value
        assert project.status == ProjectStatus.COMPLETED.value


def test_objects_index_requires_login(client):
    resp = client.get("/objects/")
    assert resp.status_code in (302, 401)


def test_objects_and_tenders_pages(admin_client):
    assert admin_client.get("/objects/").status_code == 200
    assert admin_client.get("/tenders/").status_code == 200
