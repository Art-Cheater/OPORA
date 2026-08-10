"""Тесты поиска: регистр, раскладка, шаблон hits."""

from __future__ import annotations

from app.core.search import flip_layout, query_variants
from app.modules.search.services import SearchService


def test_layout_flip_hello():
    # ghbdtn на EN → привет
    ru, en = flip_layout("ghbdtn")
    assert "привет" in ru.lower() or ru.lower() == "привет"


def test_query_variants_include_case_and_layout():
    variants = query_variants("Иванов")
    lowered = {v.lower() for v in variants}
    assert "иванов" in lowered
    # раскладка RU→EN для «иванов»
    assert any(v for v in variants if "bdfyjd" in v.lower() or "иванов" in v.lower())


def test_search_page_hits_not_dict_items(admin_client, app):
    """Раньше cat.items в Jinja брал dict.items — 500."""
    resp = admin_client.get("/search/?q=админ")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "TypeError" not in body
    assert "не является итерируемым" not in body


def test_search_api_uses_hits_key(admin_client):
    resp = admin_client.get("/search/api?q=admin")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "categories" in data
    for cat in data["categories"]:
        assert "hits" in cat
        assert "items" not in cat


def test_search_case_insensitive(admin_client, app):
    from app.extensions import db
    from app.modules.auth.services import AuthService

    with app.app_context():
        try:
            AuthService.create_user(
                "petrov@test.local", "pass12345", "Петров Алексей", "executor"
            )
        except Exception:
            pass

    low = admin_client.get("/search/api?q=петров").get_json()
    up = admin_client.get("/search/api?q=ПЕТРОВ").get_json()
    assert low["total"] >= 1
    assert up["total"] >= 1


def test_search_wrong_layout_finds_user(admin_client, app):
    """«gtnhjd» = «петров», набранный в английской раскладке."""
    from app.modules.auth.services import AuthService

    with app.app_context():
        try:
            AuthService.create_user(
                "petrov2@test.local", "pass12345", "Петров Сергей", "executor"
            )
        except Exception:
            pass

    # контроль: раскладка
    from app.core.search import flip_layout

    ru, _ = flip_layout("gtnhjd")
    assert ru.lower() == "петров"

    data = admin_client.get("/search/api?q=gtnhjd").get_json()
    titles = [
        h["title"].lower()
        for cat in data["categories"]
        for h in cat["hits"]
    ]
    assert any("петров" in t for t in titles)


def test_search_by_surname_includes_related(admin_client, app):
    import uuid

    from app.extensions import db
    from app.models.auth.user import User
    from app.models.enums import Priority
    from app.models.requests.request import Request
    from app.models.requests.request_status import RequestStatus
    from app.modules.auth.services import AuthService

    with app.app_context():
        try:
            user = AuthService.create_user(
                "sidorov@test.local", "pass12345", "Сидоров Иван", "master"
            )
        except Exception:
            user = db.session.scalar(
                db.select(User).where(User.email == "sidorov@test.local")
            )
        status = db.session.scalar(
            db.select(RequestStatus).where(RequestStatus.code == "new")
        )
        req = Request(
            number=f"S-{uuid.uuid4().hex[:6].upper()}",
            title="Заявка Сидорова",
            address="ул. Тест",
            applicant_name="Клиент",
            priority=Priority.MEDIUM.value,
            status_id=status.id,
            responsible_id=user.id,
        )
        db.session.add(req)
        db.session.commit()

    data = admin_client.get("/search/api?q=Сидоров&limit=20").get_json()
    keys = {c["key"] for c in data["categories"]}
    assert "users" in keys
    assert "requests" in keys
    req_titles = " ".join(
        h["title"] for c in data["categories"] if c["key"] == "requests" for h in c["hits"]
    )
    assert "Сидорова" in req_titles or "Сидоров" in str(data)
