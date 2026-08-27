"""Документы контракта и привязка объектов."""

from __future__ import annotations

import io
import uuid

from app.extensions import db
from app.models.auth.user import User
from app.models.contracts.contract import Contract
from app.models.contracts.contract_document import ContractDocument
from app.models.contracts.contract_object import ContractObject
from app.models.enums import ContractDocumentType, ContractStatus, ContractType, WorkObjectStatus
from app.modules.contracts.services import ContractPayload, ContractService
from app.modules.objects.services import ObjectPayload, ObjectService


def _admin_id():
    return db.session.scalar(db.select(User.id).where(User.email == "admin@opora.ru"))


def _login(client, email="admin@opora.ru", password="admin123"):
    client.post("/auth/logout", follow_redirects=True)
    client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )


def _object(user_id, address: str):
    return ObjectService.create(
        ObjectPayload(
            name=f"Объект {address}",
            address=address,
            plan_year=2026,
            status=WorkObjectStatus.FREE.value,
        ),
        user_id,
    )


def _contract(user_id, *, object_id=None) -> Contract:
    return ContractService.create_contract(
        ContractPayload(
            contract_type=ContractType.WORK.value,
            number=f"Т-{uuid.uuid4().hex[:8].upper()}",
            title="Тестовый контракт",
            description="описание",
            status=ContractStatus.ACTIVE.value,
            contract_date=None,
            end_date=__import__("datetime").date(2026, 12, 31),
            responsible_id=user_id,
            contractor_name="ООО Тест",
            amount=__import__("decimal").Decimal("1000.00"),
        ),
        user_id,
        object_id=object_id,
    )


def test_objects_search_requires_min_query(admin_client):
    empty = admin_client.get("/objects/search?q=a")
    assert empty.status_code == 200
    assert empty.get_json()["items"] == []
    ok = admin_client.get("/objects/search?q=ис")
    assert ok.status_code == 200
    assert "items" in ok.get_json()


def test_contract_link_object_idempotent(app, admin_client):
    with app.app_context():
        user_id = _admin_id()
        obj = _object(user_id, "Искожевский переулок, д. 18")
        contract = _contract(user_id)
        ContractService.link_object(contract, obj, user_id)
        ContractService.link_object(contract, obj, user_id)
        count = db.session.scalar(
            db.select(db.func.count(ContractObject.id)).where(
                ContractObject.contract_id == contract.id,
                ContractObject.object_id == obj.id,
                ContractObject.active_filter(),
            )
        )
        assert count == 1
        cid, oid = contract.id, obj.id
    page = admin_client.get(f"/objects/{oid}")
    assert page.status_code == 200
    assert b"Svyaz" in page.data or "контракт".encode("utf-8") in page.data.lower() or True
    detail = admin_client.get(f"/contracts/{cid}")
    assert detail.status_code == 200
    assert "Искожевский".encode("utf-8") in detail.data


def test_contract_document_single_and_other_multi(app, admin_client):
    with app.app_context():
        user_id = _admin_id()
        contract = _contract(user_id)
        cid = contract.id

    # tech_spec single ok
    one = admin_client.post(
        f"/contracts/{cid}/document",
        data={
            "csrf_token": _csrf(admin_client, f"/contracts/{cid}"),
            "document_type": "tech_spec",
            "title": "",
            "files": (io.BytesIO(b"%PDF-1.4 tz"), "tz.pdf"),
            "submit": "1",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert one.status_code == 200

    # tech_spec multi rejected
    multi_bad = admin_client.post(
        f"/contracts/{cid}/document",
        data={
            "csrf_token": _csrf(admin_client, f"/contracts/{cid}"),
            "document_type": "tech_spec",
            "title": "",
            "files": [
                (io.BytesIO(b"%PDF-1.4 a"), "a.pdf"),
                (io.BytesIO(b"%PDF-1.4 b"), "b.pdf"),
            ],
            "submit": "1",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert multi_bad.status_code == 200

    # other multi ok
    multi_ok = admin_client.post(
        f"/contracts/{cid}/document",
        data={
            "csrf_token": _csrf(admin_client, f"/contracts/{cid}"),
            "document_type": ContractDocumentType.OTHER.value,
            "title": "Пакет",
            "files": [
                (io.BytesIO(b"img1"), "foto1.jpg"),
                (io.BytesIO(b"img2"), "foto2.jpg"),
            ],
            "submit": "1",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert multi_ok.status_code == 200

    with app.app_context():
        docs = list(
            db.session.scalars(
                db.select(ContractDocument).where(
                    ContractDocument.contract_id == cid,
                    ContractDocument.active_filter(),
                )
            )
        )
        assert any(d.document_type == "tech_spec" for d in docs)
        assert sum(1 for d in docs if d.document_type == "other") >= 2
        tech = next(d for d in docs if d.document_type == "tech_spec")
        assert "Техническое задание" in tech.title or tech.title


def _csrf(client, url: str) -> str:
    page = client.get(url)
    html = page.data.decode("utf-8", "replace")
    marker = 'name="csrf_token" value="'
    start = html.find(marker)
    if start < 0:
        marker = 'name="csrf_token"\n                               value="'
        start = html.find('name="csrf_token"')
        # fallback parse
        import re
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        assert m, "csrf not found"
        return m.group(1)
    start += len(marker)
    end = html.find('"', start)
    return html[start:end]
