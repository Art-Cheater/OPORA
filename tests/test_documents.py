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
    assert health.get_json()["release"] == "20260825a"

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

def test_personal_contracts_feature_and_parse(admin_client, app):
    page = admin_client.get("/documents/")
    assert page.status_code == 200
    assert "Раздел «Договоры»".encode("utf-8") in page.data

    enabled = admin_client.post(
        "/documents/settings/contracts",
        data={"enabled": "y", "submit": "Сохранить"},
        follow_redirects=True,
    )
    assert enabled.status_code == 200
    assert "Договоры".encode("utf-8") in enabled.data

    sample = (
        "Договор поставки № 12/26\n"
        "Предмет договора: поставка кабеля для освещения дворов.\n"
        "Срок действия с 01.01.2026 по 31.12.2026\n"
    ).encode("utf-8")
    uploaded = admin_client.post(
        "/documents/contracts/upload",
        data={"files": (io.BytesIO(sample), "dogovor.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    assert "Договор".encode("utf-8") in uploaded.data or b"dogovor" in uploaded.data.lower()

    with app.app_context():
        from app.models.documents.personal_contract import PersonalContract

        row = db.session.scalar(db.select(PersonalContract).order_by(PersonalContract.created_at.desc()))
        assert row is not None
        assert row.ends_on is not None
        assert "договор" in row.title.casefold() or "поставк" in row.title.casefold()

    notify = admin_client.get("/notifications/api/unread")
    assert notify.status_code == 200
    assert "total" in notify.get_json()


def test_parse_personal_contract_dates():
    from pathlib import Path
    import tempfile

    from app.modules.documents.parse_contract import parse_personal_contract_file

    text = (
        "ДОГОВОР № 5/26 на оказание услуг\n"
        "Предмет договора: техническое обслуживание опор освещения.\n"
        "Действует с 01.03.2026 по 01.03.2027\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "c.txt"
        path.write_text(text, encoding="utf-8")
        parsed = parse_personal_contract_file(path, "c.txt")
    assert parsed.ends_on is not None
    assert parsed.ends_on.year == 2027
    assert parsed.title
    assert parsed.description
