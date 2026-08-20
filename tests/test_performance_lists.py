"""Query budgets for list pages: no implicit documents/history/members."""

from __future__ import annotations

import uuid
from datetime import date

from app.core.performance import count_queries
from app.extensions import db
from app.models.auth.position import Position
from app.models.auth.user import User
from app.models.enums import (
    ContractStatus,
    ContractType,
    ProjectStatus,
    TenderApplicationStatus,
    TenderDocumentType,
    WorkObjectStatus,
)
from app.models.tenders.tender_document import TenderDocument
from app.modules.auth.repositories import UserRepository
from app.modules.contracts.repositories import ContractFilter, ContractRepository
from app.modules.contracts.services import ContractPayload, ContractService
from app.modules.objects.repositories import ObjectFilter, ObjectRepository
from app.modules.objects.services import ObjectPayload, ObjectService
from app.modules.projects.repositories import ProjectFilter, ProjectRepository
from app.modules.projects.services import ProjectPayload, ProjectService
from app.modules.tenders.repositories import TenderFilter, TenderRepository
from app.modules.tenders.services import TenderPayload, TenderService


def _admin(app) -> User:
    return db.session.scalar(db.select(User).where(User.email == "admin@opora.ru"))


def _seed_tender_with_documents(user_id):
    obj = ObjectService.create(
        ObjectPayload(
            name="Объект для списка торгов",
            address="ул. Быстрая, 1",
            plan_year=2026,
            notes="основание",
            status=WorkObjectStatus.FREE.value,
        ),
        user_id,
    )
    project = ProjectService.create_project(
        ProjectPayload(
            code=f"PRJ-PERF-{uuid.uuid4().hex[:6].upper()}",
            name="Проект для списка торгов",
            description="описание",
            status=ProjectStatus.ACTIVE.value,
            progress_percent=10,
            start_date=None,
            end_date=None,
            responsible_id=user_id,
            executor_ids=[user_id],
            object_id=obj.id,
        ),
        user_id,
    )
    tender = TenderService.create(
        TenderPayload(
            number=f"ТРГ-PERF-{uuid.uuid4().hex[:6].upper()}",
            title="Торги для списка",
            description=None,
            status=TenderApplicationStatus.DRAFT.value,
            responsible_id=user_id,
            project_ids=[project.id],
            object_id=obj.id,
        ),
        user_id,
    )
    db.session.add_all(
        [
            TenderDocument(
                tender_id=tender.id,
                title=f"Документ торгов {index}",
                document_type=TenderDocumentType.OTHER.value,
                created_by=user_id,
                updated_by=user_id,
            )
            for index in range(20)
        ]
    )
    db.session.commit()
    return tender.id, project.id, obj.id


def test_tenders_list_does_not_load_documents_or_project_links(app):
    with app.app_context():
        admin = _admin(app)
        _seed_tender_with_documents(admin.id)
        db.session.expunge_all()

        with count_queries(db.engine) as counter:
            pagination = TenderRepository.paginated_list(TenderFilter(), page=1, per_page=20)
            labels = []
            for tender in pagination.items:
                labels.append(tender.number)
                if tender.work_object:
                    labels.append(tender.work_object.display_address)
                else:
                    labels.append(tender.title)

        assert labels
        assert counter.count <= 4
        loaded = pagination.items[0]
        with count_queries(db.engine) as extra:
            documents = list(loaded.documents)
            links = list(loaded.project_links)
        assert extra.count == 0
        assert documents == []
        assert links == []


def test_tender_detail_still_loads_composition_and_documents(app):
    with app.app_context():
        admin = _admin(app)
        tender_id, _, _ = _seed_tender_with_documents(admin.id)
        db.session.expunge_all()

        tender = TenderRepository.get_by_id(tender_id)
        with count_queries(db.engine) as counter:
            assert tender.project_links
            assert tender.project_links[0].project is not None
            assert any(doc.title.startswith("Документ торгов") for doc in tender.documents)
            _ = TenderService.linked_project_documents(tender)
        assert counter.count == 0


def test_projects_and_contracts_lists_skip_history_and_documents(app):
    with app.app_context():
        admin = _admin(app)
        _, project_id, _ = _seed_tender_with_documents(admin.id)
        ContractService.create_contract(
            ContractPayload(
                contract_type=ContractType.WORK.value,
                number=f"CTR-PERF-{uuid.uuid4().hex[:6].upper()}",
                title="Договор для списка",
                description="текст",
                status=ContractStatus.DRAFT.value,
                contract_date=None,
                end_date=date(2026, 12, 31),
                responsible_id=admin.id,
                contractor_name="ООО Подрядчик",
                amount=1000,
            ),
            admin.id,
        )
        db.session.expunge_all()

        with count_queries(db.engine) as project_counter:
            projects = ProjectRepository.paginated_list(ProjectFilter(), page=1, per_page=20)
            for project in projects.items:
                _ = project.code, project.name, project.status
                _ = project.responsible.full_name if project.responsible else None
                _ = [executor.full_name for executor in project.executors]
        assert projects.items
        assert project_counter.count <= 5
        with count_queries(db.engine) as extra:
            history = list(projects.items[0].history)
            documents = list(projects.items[0].documents)
        assert extra.count == 0
        assert history == []
        assert documents == []

        with count_queries(db.engine) as contract_counter:
            contracts = ContractRepository.paginated_list(ContractFilter(), page=1, per_page=20)
            for contract in contracts.items:
                _ = contract.number, contract.title, contract.amount
                _ = contract.responsible.full_name if contract.responsible else None
        assert contracts.items
        assert contract_counter.count <= 4
        with count_queries(db.engine) as extra:
            history = list(contracts.items[0].history)
            documents = list(contracts.items[0].documents)
            links = list(contracts.items[0].object_links)
        assert extra.count == 0
        assert history == []
        assert documents == []
        assert links == []

        detail = ProjectRepository.get_by_id(project_id)
        with count_queries(db.engine) as detail_counter:
            _ = detail.history
            _ = detail.documents
            _ = detail.executors
        assert detail_counter.count == 0


def test_objects_list_stays_within_query_budget(app):
    with app.app_context():
        admin = _admin(app)
        _seed_tender_with_documents(admin.id)
        db.session.expunge_all()

        with count_queries(db.engine) as counter:
            pagination = ObjectRepository.paginated_list(ObjectFilter(), page=1, per_page=20)
            for obj in pagination.items:
                _ = obj.display_address, obj.status, obj.contract_number
        assert pagination.items
        assert counter.count <= 3
        with count_queries(db.engine) as extra:
            projects = list(pagination.items[0].projects)
        assert extra.count == 0
        assert projects == []


def test_user_loader_does_not_pull_position_colleagues_or_permission_graph(app):
    with app.app_context():
        admin = _admin(app)
        position = db.session.scalars(db.select(Position).limit(1)).first()
        assert position is not None
        admin.position_id = position.id
        peer = db.session.scalar(db.select(User).where(User.email == "dispatcher@test.local"))
        assert peer is not None
        peer.position_id = position.id
        db.session.commit()
        admin_id = admin.id
        peer_id = peer.id
        db.session.expunge_all()

        loaded = UserRepository.get_by_id(admin_id)
        assert loaded is not None
        assert loaded.position_ref is not None
        with count_queries(db.engine) as extra:
            colleagues = list(loaded.position_ref.users)
            permission = loaded.user_roles[0].role.role_permissions[0].permission
            related = list(permission.role_permissions)
        assert extra.count == 0
        assert peer_id not in {user.id for user in colleagues}
        assert related == []
        with count_queries(db.engine) as counter:
            assert loaded.has_permission("tenders.view")
        assert counter.count == 0


def test_project_user_choices_do_not_strip_admin_roles(app):
    with app.app_context():
        admin = _admin(app)
        assert admin.has_permission("projects.create")
        names = ProjectRepository.get_users()
        assert names
        assert admin.has_permission("projects.create")
        assert admin.has_permission("projects.view")


def test_sqlite_uses_wal_and_busy_timeout(app):
    with app.app_context():
        with db.engine.connect() as conn:
            journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
        assert str(journal).lower() == "wal"
        assert int(timeout) >= 15000


def test_choice_lists_are_capped_and_keep_extra_ids(app, admin_client):
    with app.app_context():
        admin = _admin(app)
        created = []
        for index in range(45):
            created.append(
                ObjectService.create(
                    ObjectPayload(
                        name=f"Объект выбора {index:03d}",
                        address=f"ул. Выборная, {index:03d}",
                        plan_year=2026,
                        notes="основание",
                        status=WorkObjectStatus.FREE.value,
                    ),
                    admin.id,
                )
            )
        last = created[-1]
        last_id = last.id
        admin_id = admin.id
        db.session.expunge_all()

        choices = ObjectRepository.list_choices(limit=40)
        assert len(choices) <= 40
        assert last_id not in {item.id for item in choices}

        with_extra = ObjectRepository.list_choices(limit=40, extra_ids=[last_id])
        assert last_id in {item.id for item in with_extra}

        found = ObjectRepository.list_choices(q="044", limit=40)
        assert last_id in {item.id for item in found}

    ajax = {"X-Requested-With": "XMLHttpRequest"}
    listed = admin_client.get("/objects/api/choices")
    assert listed.status_code == 200, listed.get_data(as_text=True)[:1000]
    payload = listed.get_json()
    assert payload and len(payload["items"]) <= 40

    searched = admin_client.get("/objects/api/choices?q=044")
    assert searched.status_code == 200
    search_ids = {item["id"] for item in searched.get_json()["items"]}
    assert str(last_id) in search_ids

    create_form = admin_client.get("/tenders/new", headers=ajax)
    html = create_form.get_data(as_text=True)
    assert create_form.status_code == 200
    assert "data-choice-url" in html
    assert str(last_id) not in html

    saved = admin_client.post(
        "/tenders/new",
        data={
            "number": f"ТРГ-CHOICE-{uuid.uuid4().hex[:6].upper()}",
            "title": "Торги с объектом вне первых 40",
            "status": TenderApplicationStatus.DRAFT.value,
            "object_id": str(last_id),
            "responsible_id": str(admin_id),
        },
        headers=ajax,
    )
    assert saved.status_code == 200, saved.get_data(as_text=True)[:2000]
    body = saved.get_json()
    assert body and body.get("success") is True
