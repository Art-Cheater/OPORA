"""CRUD, валидация, история и AJAX-ошибки контрактов."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.audit.audit_log import AuditLog
from app.models.communication.comment import Comment
from app.models.contracts.contract import Contract
from app.models.contracts.contract_history import ContractHistory
from app.models.enums import EntityType


AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _contract_data(number: str | None = None, **overrides):
    data = {
        "contract_type": "work",
        "number": number or f"CTR-TEST-{uuid.uuid4().hex[:8].upper()}",
        "title": "Тестовый контракт",
        "description": "Первая строка\nВторая строка",
        "contractor_name": "ООО Подрядчик",
        "amount": "1234.56",
        "status": "draft",
        "contract_date": "2026-08-13",
        "end_date": "2026-12-31",
        "responsible_id": "",
        "submit": "Сохранить",
    }
    data.update(overrides)
    return data


def _create_contract(admin_client, **overrides) -> str:
    response = admin_client.post(
        "/contracts/new",
        data=_contract_data(**overrides),
        headers=AJAX_HEADERS,
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["success"] is True
    return payload["id"]


def test_contract_create_edit_serializes_audit_and_history(app, admin_client):
    contract_id = _create_contract(admin_client)

    response = admin_client.post(
        f"/contracts/{contract_id}/edit",
        data=_contract_data(
            number="CTR-EDITED",
            title="Обновлённый контракт",
            amount="9876.54",
            end_date="2027-01-15",
        ),
        headers=AJAX_HEADERS,
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    with app.app_context():
        contract = db.session.get(Contract, uuid.UUID(contract_id))
        assert contract is not None
        assert contract.amount == Decimal("9876.54")
        assert contract.end_date.isoformat() == "2027-01-15"

        history = db.session.scalars(
            db.select(ContractHistory)
            .where(ContractHistory.contract_id == contract.id)
            .order_by(ContractHistory.created_at.asc())
        ).all()
        assert [item.action for item in history] == ["create", "update"]
        assert history[0].details["created"]["amount"] == "1234.56"
        assert history[1].details["changes"]["amount"]["new"] == "9876.54"
        assert history[1].details["changes"]["end_date"]["new"] == "2027-01-15"

        audits = db.session.scalars(
            db.select(AuditLog).where(
                AuditLog.entity_type == EntityType.CONTRACT.value,
                AuditLog.entity_id == contract.id,
            )
        ).all()
        assert any(item.new_values and item.new_values.get("amount") == "1234.56" for item in audits)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"contractor_name": ""}, "Укажите подрядчика"),
        ({"amount": "0"}, "Сумма контракта должна быть больше нуля"),
        ({"amount": "не число"}, "Введите корректную сумму контракта"),
        ({"end_date": ""}, "Укажите дату окончания контракта"),
        ({"end_date": "31-12-2026"}, "Введите корректную дату"),
    ],
)
def test_contract_ajax_validation_errors(admin_client, overrides, expected):
    response = admin_client.post(
        "/contracts/new",
        data=_contract_data(**overrides),
        headers=AJAX_HEADERS,
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert expected in payload["message"]
    assert "html" in payload


def test_contract_modal_comment_and_history(app, admin_client):
    contract_id = _create_contract(admin_client)
    response = admin_client.post(
        f"/contracts/{contract_id}/comment",
        data={"body": "Комментарий из модального окна", "submit": "Добавить"},
        headers=AJAX_HEADERS,
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    modal = admin_client.get(f"/contracts/{contract_id}", headers=AJAX_HEADERS)
    body = modal.get_data(as_text=True)
    assert modal.status_code == 200
    assert "data-opora-detail-form" in body
    assert "Комментарий из модального окна" in body
    assert "Контракт создан" in body

    with app.app_context():
        contract_uuid = uuid.UUID(contract_id)
        assert db.session.scalar(
            db.select(Comment).where(
                Comment.entity_type == EntityType.CONTRACT.value,
                Comment.entity_id == contract_uuid,
                Comment.body == "Комментарий из модального окна",
            )
        )
        assert db.session.scalar(
            db.select(ContractHistory).where(
                ContractHistory.contract_id == contract_uuid,
                ContractHistory.action == "comment",
            )
        )


def test_ajax_500_is_json_not_html(app, client):
    endpoint = f"/_test/ajax-500-{uuid.uuid4().hex}"

    def fail():
        raise RuntimeError("private traceback marker")

    app.add_url_rule(endpoint, endpoint, fail)
    previous = app.config.get("PROPAGATE_EXCEPTIONS")
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        response = client.get(endpoint, headers=AJAX_HEADERS)
    finally:
        app.config["PROPAGATE_EXCEPTIONS"] = previous

    assert response.status_code == 500
    assert response.is_json
    payload = response.get_json()
    assert payload == {
        "success": False,
        "message": "Внутренняя ошибка сервера. Повторите попытку позже.",
    }
    assert "private traceback marker" not in response.get_data(as_text=True)
