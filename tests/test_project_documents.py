"""Документы проекта: единый механизм загрузки, тип «Прочее», права."""

from __future__ import annotations

import io
import uuid

from app.extensions import db
from app.models.auth.associations import RolePermission, UserRole
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.auth.user import User
from app.models.enums import ProjectDocumentType, ProjectStatus, WorkObjectStatus
from app.models.files.attachment import Attachment
from app.models.projects.project_document import ProjectDocument
from app.modules.objects.services import ObjectPayload, ObjectService
from app.modules.projects.services import ProjectPayload, ProjectService


def _admin(app) -> User:
    return db.session.scalar(db.select(User).where(User.email == "admin@opora.ru"))


def _grant_perms(app, email: str, codes: list[str]) -> None:
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == email))
        assert user is not None
        role = Role(
            code=f"prj_{uuid.uuid4().hex[:8]}",
            name="Project docs test",
            is_system=False,
            created_by=user.id,
            updated_by=user.id,
        )
        db.session.add(role)
        db.session.flush()
        perms = list(
            db.session.scalars(
                db.select(Permission).where(
                    Permission.active_filter(),
                    Permission.code.in_(codes),
                )
            )
        )
        assert len(perms) == len(codes), codes
        for perm in perms:
            db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()


def _login(client, email: str, password: str = "pass12345") -> None:
    client.post("/auth/logout", follow_redirects=True)
    client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )


def _seed_project(app, *, user_id=None):
    with app.app_context():
        admin = _admin(app)
        uid = user_id or admin.id
        obj = ObjectService.create(
            ObjectPayload(
                name=f"Объект док {uuid.uuid4().hex[:6]}",
                address=f"ул. Документов, {uuid.uuid4().hex[:4]}",
                plan_year=2026,
                notes="тест",
                status=WorkObjectStatus.FREE.value,
            ),
            uid,
        )
        project = ProjectService.create_project(
            ProjectPayload(
                code=f"PRJ-DOC-{uuid.uuid4().hex[:6].upper()}",
                name="Проект документов",
                description="описание",
                status=ProjectStatus.ACTIVE.value,
                progress_percent=10,
                start_date=None,
                end_date=None,
                responsible_id=uid,
                executor_ids=[uid],
                object_id=obj.id,
            ),
            uid,
        )
        return str(project.id), str(uid)


def test_viewer_can_open_project_without_edit(app, client):
    project_id, _ = _seed_project(app)
    _grant_perms(app, "executor@test.local", ["projects.view"])
    _login(client, "executor@test.local")
    resp = client.get(f"/projects/{project_id}?full=1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Документы проекта" in html
    assert "Добавить документ" not in html
    assert 'bi-paperclip' not in html


def test_without_view_cannot_open_project(app, client):
    project_id, _ = _seed_project(app)
    with app.app_context():
        from app.modules.auth.services import AuthService

        AuthService.create_user(
            "noview@test.local",
            "pass12345",
            "Без проектов",
            "dispatcher",
        )
        user = db.session.scalar(db.select(User).where(User.email == "noview@test.local"))
        assert user is not None
        # Убрать все роли, оставить только profile
        db.session.execute(db.delete(UserRole).where(UserRole.user_id == user.id))
        role = Role(
            code=f"noview_{uuid.uuid4().hex[:6]}",
            name="No projects",
            is_system=False,
            created_by=user.id,
            updated_by=user.id,
        )
        db.session.add(role)
        db.session.flush()
        profile = db.session.scalar(
            db.select(Permission).where(Permission.code == "profile.view")
        )
        assert profile is not None
        db.session.add(RolePermission(role_id=role.id, permission_id=profile.id))
        db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()

    _login(client, "noview@test.local")
    resp = client.get(f"/projects/{project_id}?full=1")
    assert resp.status_code in {302, 403}


def test_edit_can_upload_single_typed_document(app, admin_client):
    project_id, _ = _seed_project(app)
    resp = admin_client.post(
        f"/projects/{project_id}/document",
        data={
            "document_type": ProjectDocumentType.TECH_SPEC.value,
            "title": "",
            "files": (io.BytesIO(b"tz content"), "TZ_MOPRA.txt"),
            "submit": "Добавить документ",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Техническое задание" in html
    assert "TZ_MOPRA.txt" in html
    assert "Примечание" in html
    with app.app_context():
        docs = list(
            db.session.scalars(
                db.select(ProjectDocument).where(
                    ProjectDocument.project_id == uuid.UUID(project_id),
                    ProjectDocument.active_filter(),
                )
            )
        )
        assert len(docs) == 1
        assert docs[0].title == "Техническое задание"
        assert docs[0].document_type == ProjectDocumentType.TECH_SPEC.value


def test_manual_title_preserved(app, admin_client):
    project_id, _ = _seed_project(app)
    admin_client.post(
        f"/projects/{project_id}/document",
        data={
            "document_type": ProjectDocumentType.ESTIMATE.value,
            "title": "Смета по замене светильников",
            "files": (io.BytesIO(b"estimate"), "smeta.txt"),
            "submit": "Добавить документ",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    with app.app_context():
        doc = db.session.scalar(
            db.select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
                ProjectDocument.active_filter(),
            )
        )
        assert doc is not None
        assert doc.title == "Смета по замене светильников"


def test_normal_type_rejects_multiple_files(app, admin_client):
    project_id, _ = _seed_project(app)
    resp = admin_client.post(
        f"/projects/{project_id}/document",
        data={
            "document_type": ProjectDocumentType.TECH_SPEC.value,
            "title": "ТЗ",
            "files": [
                (io.BytesIO(b"a"), "a.txt"),
                (io.BytesIO(b"b"), "b.txt"),
            ],
            "submit": "Добавить документ",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "только один файл" in resp.get_data(as_text=True).lower()
    with app.app_context():
        count = db.session.scalar(
            db.select(db.func.count(ProjectDocument.id)).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
                ProjectDocument.active_filter(),
            )
        )
        assert count == 0


def test_other_type_creates_multiple_documents(app, admin_client):
    project_id, _ = _seed_project(app)
    resp = admin_client.post(
        f"/projects/{project_id}/document",
        data={
            "document_type": ProjectDocumentType.OTHER.value,
            "title": "",
            "files": [
                (io.BytesIO(b"\xff\xd8\xff\xe0" + b"p1"), "foto1.jpg"),
                (io.BytesIO(b"\xff\xd8\xff\xe0" + b"p2"), "foto2.jpg"),
                (io.BytesIO(b"%PDF-1.4 schema"), "schema.pdf"),
            ],
            "submit": "Добавить документ",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        docs = list(
            db.session.scalars(
                db.select(ProjectDocument)
                .where(
                    ProjectDocument.project_id == uuid.UUID(project_id),
                    ProjectDocument.active_filter(),
                )
                .order_by(ProjectDocument.file_name)
            )
        )
        assert len(docs) == 3
        titles = {d.title for d in docs}
        assert "foto1" in titles
        assert "foto2" in titles
        assert "schema" in titles
        assert all(d.document_type == ProjectDocumentType.OTHER.value for d in docs)


def test_without_edit_cannot_upload(app, client):
    project_id, _ = _seed_project(app)
    _grant_perms(app, "executor@test.local", ["projects.view"])
    _login(client, "executor@test.local")
    resp = client.post(
        f"/projects/{project_id}/document",
        data={
            "document_type": ProjectDocumentType.OTHER.value,
            "files": (io.BytesIO(b"x"), "x.txt"),
            "submit": "Добавить документ",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code in {302, 403}


def test_delete_requires_edit_permission(app, client):
    project_id, user_id = _seed_project(app)
    with app.app_context():
        doc = ProjectDocument(
            project_id=uuid.UUID(project_id),
            title="К удалению",
            document_type=ProjectDocumentType.OTHER.value,
            file_name="del.txt",
            mime_type="text/plain",
            storage_key=None,
            created_by=uuid.UUID(user_id),
            updated_by=uuid.UUID(user_id),
        )
        db.session.add(doc)
        db.session.commit()
        doc_id = str(doc.id)

    _grant_perms(app, "executor@test.local", ["projects.view"])
    _login(client, "executor@test.local")
    denied = client.post(
        f"/projects/{project_id}/document/{doc_id}/delete",
        follow_redirects=False,
    )
    assert denied.status_code in {302, 403}

    _login(client, "admin@opora.ru", "admin123")
    ok = client.post(
        f"/projects/{project_id}/document/{doc_id}/delete",
        follow_redirects=True,
    )
    assert ok.status_code == 200
    with app.app_context():
        gone = db.session.get(ProjectDocument, uuid.UUID(doc_id))
        assert gone is not None
        assert gone.deleted_at is not None


def test_legacy_attachment_listed_and_downloadable(app, admin_client):
    project_id, user_id = _seed_project(app)
    with app.app_context():
        att = Attachment(
            entity_type="project",
            entity_id=uuid.UUID(project_id),
            file_name="legacy_smeta.txt",
            mime_type="text/plain",
            file_size=4,
            storage_key=f"projects/{project_id}/legacy_smeta.txt",
            uploaded_by=uuid.UUID(user_id),
            created_by=uuid.UUID(user_id),
            updated_by=uuid.UUID(user_id),
        )
        db.session.add(att)
        db.session.commit()
        att_id = str(att.id)
        upload_root = app.config["UPLOAD_FOLDER"]
        path = upload_root / att.storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old!")

    page = admin_client.get(f"/projects/{project_id}?full=1")
    html = page.get_data(as_text=True)
    assert "legacy_smeta.txt" in html
    assert "Прочее (ранее «Файлы»)" in html
    assert "Документы проекта" in html

    dl = admin_client.get(f"/projects/{project_id}/attachment/{att_id}/download")
    assert dl.status_code == 200
    assert dl.data == b"old!"


def test_download_existing_document(app, admin_client):
    project_id, _ = _seed_project(app)
    admin_client.post(
        f"/projects/{project_id}/document",
        data={
            "document_type": ProjectDocumentType.PLAN.value,
            "title": "План работ",
            "files": (io.BytesIO(b"%PDF-1.4 plan-bytes"), "plan.pdf"),
            "submit": "Добавить документ",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    with app.app_context():
        doc = db.session.scalar(
            db.select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
                ProjectDocument.active_filter(),
            )
        )
        assert doc is not None
        doc_id = str(doc.id)

    page = admin_client.get(f"/projects/{project_id}?full=1")
    assert "План работ" in page.get_data(as_text=True)
    dl = admin_client.get(f"/projects/{project_id}/document/{doc_id}/download")
    assert dl.status_code == 200
    assert dl.data == b"%PDF-1.4 plan-bytes"


def test_attachment_post_redirects_to_documents(app, admin_client):
    project_id, _ = _seed_project(app)
    resp = admin_client.post(
        f"/projects/{project_id}/attachment",
        data={"files": (io.BytesIO(b"x"), "x.txt"), "submit": "Загрузить"},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Документы проекта" in resp.get_data(as_text=True)


def test_edit_document_updates_metadata(app, admin_client):
    project_id, user_id = _seed_project(app)
    with app.app_context():
        doc = ProjectDocument(
            project_id=uuid.UUID(project_id),
            title="Старое название",
            document_type=ProjectDocumentType.OTHER.value,
            document_number="1",
            file_name="old.txt",
            mime_type="text/plain",
            storage_key=None,
            created_by=uuid.UUID(user_id),
            updated_by=uuid.UUID(user_id),
        )
        db.session.add(doc)
        db.session.commit()
        doc_id = str(doc.id)

    page = admin_client.get(f"/projects/{project_id}?full=1")
    assert "Изменить" in page.get_data(as_text=True)

    resp = admin_client.post(
        f"/projects/{project_id}/document/{doc_id}/edit",
        data={
            "title": "Новое название документа",
            "document_type": ProjectDocumentType.ESTIMATE.value,
            "document_number": "СМ-42",
            "document_date": "2026-08-01",
            "description": "Обновлённое описание",
            "submit": "Сохранить",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Новое название документа" in html
    assert "Смета" in html
    with app.app_context():
        doc = db.session.get(ProjectDocument, uuid.UUID(doc_id))
        assert doc.title == "Новое название документа"
        assert doc.document_type == ProjectDocumentType.ESTIMATE.value
        assert doc.document_number == "СМ-42"
        assert str(doc.document_date) == "2026-08-01"
        assert doc.description == "Обновлённое описание"


def test_edit_document_requires_edit_permission(app, client):
    project_id, user_id = _seed_project(app)
    with app.app_context():
        doc = ProjectDocument(
            project_id=uuid.UUID(project_id),
            title="Без прав",
            document_type=ProjectDocumentType.OTHER.value,
            created_by=uuid.UUID(user_id),
            updated_by=uuid.UUID(user_id),
        )
        db.session.add(doc)
        db.session.commit()
        doc_id = str(doc.id)

    _grant_perms(app, "executor@test.local", ["projects.view"])
    _login(client, "executor@test.local")
    denied = client.post(
        f"/projects/{project_id}/document/{doc_id}/edit",
        data={
            "title": "Хакинг",
            "document_type": ProjectDocumentType.OTHER.value,
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert denied.status_code in {302, 403}
    with app.app_context():
        doc = db.session.get(ProjectDocument, uuid.UUID(doc_id))
        assert doc.title == "Без прав"
