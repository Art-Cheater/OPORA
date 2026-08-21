"""Личные документы: только свои файлы, без чужих."""

from __future__ import annotations

import io

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import EntityType
from app.models.files.attachment import Attachment


def _login(client, email: str, password: str = "pass12345"):
    if email == "admin@opora.ru":
        password = "admin123"
    client.get("/auth/logout", follow_redirects=True)
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_personal_documents_own_files_only(admin_client, client, app):
    health = admin_client.get("/health")
    assert health.status_code == 200
    assert health.get_json()["release"] == "20260821c"

    page = admin_client.get("/documents/")
    assert page.status_code == 200
    assert "Личные документы".encode("utf-8") in page.data
    home = admin_client.get("/")
    assert "Личные документы".encode("utf-8") in home.data

    uploaded = admin_client.post(
        "/documents/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4 test"), "passport.pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    assert b"passport.pdf" in uploaded.data
    assert b"file-gallery" in uploaded.data

    with app.app_context():
        item = db.session.scalar(
            db.select(Attachment).where(
                Attachment.entity_type == EntityType.PERSONAL_DOCUMENT.value,
                Attachment.file_name == "passport.pdf",
            )
        )
        assert item is not None
        file_id = item.id
        owner_id = item.entity_id

    preview = admin_client.get(f"/documents/{file_id}?inline=1")
    assert preview.status_code == 200
    assert preview.data.startswith(b"%PDF-1.4")

    _login(client, "executor@test.local")
    foreign = client.get(f"/documents/{file_id}")
    assert foreign.status_code == 404
    own_page = client.get("/documents/")
    assert own_page.status_code == 200
    assert b"passport.pdf" not in own_page.data

    with app.app_context():
        stored = db.session.get(Attachment, file_id)
        assert stored is not None
        assert stored.entity_id == owner_id
