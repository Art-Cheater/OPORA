"""Focused regressions for performance instrumentation and bounded loading."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import InvalidRequestError

from app.core.performance import count_queries, register_performance_profiler
from app.extensions import db
from app.models.auth.user import User
from app.models.messenger.messenger_conversation import MessengerConversation
from app.models.messenger.messenger_message import MessengerMessage
from app.modules.employees.repositories import EmployeeFilter, EmployeeRepository
from app.modules.messenger.repositories import MessengerRepository
from app.modules.messenger.serializers import (
    serialize_conversation,
    serialize_search_result,
)
from app.modules.messenger.services import MessengerService


def _user(email: str) -> User:
    return db.session.scalar(db.select(User).where(User.email == email))


def _conversation(user_a: User, user_b: User) -> MessengerConversation:
    a_id, b_id = MessengerConversation.ordered_pair(user_a.id, user_b.id)
    conversation = MessengerConversation(
        participant_a_id=a_id,
        participant_b_id=b_id,
        created_by=user_a.id,
        updated_by=user_a.id,
    )
    db.session.add(conversation)
    db.session.flush()
    return conversation


def test_profiler_is_opt_in_and_can_expose_test_headers(app, client):
    assert "opora_performance_profiler" not in app.extensions
    app.config.update(
        PERFORMANCE_PROFILER_ENABLED=True,
        PERFORMANCE_PROFILER_RESPONSE_HEADERS=True,
    )
    register_performance_profiler(app)

    response = client.get("/auth/login")

    assert response.status_code == 200
    assert response.headers["X-Performance-Queries"].isdigit()
    assert float(response.headers["X-Performance-Duration-Ms"]) >= 0
    assert float(response.headers["X-Performance-Db-Ms"]) >= 0


def test_conversation_list_does_not_load_history_and_aggregates_unread(app):
    with app.app_context():
        admin = _user("admin@opora.ru")
        peer = _user("dispatcher@test.local")
        conversation = _conversation(admin, peer)
        db.session.add_all(
            [
                MessengerMessage(
                    conversation_id=conversation.id,
                    sender_id=peer.id,
                    body=f"message {index}",
                    created_by=peer.id,
                    updated_by=peer.id,
                )
                for index in range(75)
            ]
        )
        db.session.commit()
        conversation_id = conversation.id
        admin_id = admin.id
        db.session.expunge_all()

        with count_queries(db.engine) as counter:
            conversations = MessengerRepository.list_conversations(admin_id)
            unread = MessengerRepository.unread_counts_for_conversations(
                [item.id for item in conversations],
                admin_id,
            )

        assert counter.count <= 4
        loaded = next(item for item in conversations if item.id == conversation_id)
        assert unread[conversation_id] == 75
        with pytest.raises(InvalidRequestError):
            _ = loaded.messages

        with count_queries(db.engine) as serialization_queries:
            payload = serialize_conversation(
                loaded,
                admin_id,
                unread_count=unread[conversation_id],
            )
        assert serialization_queries.count == 0
        assert payload["unread_count"] == 75


def test_mark_read_uses_one_bulk_update(app):
    with app.app_context():
        admin = _user("admin@opora.ru")
        peer = _user("dispatcher@test.local")
        conversation = _conversation(admin, peer)
        db.session.add_all(
            [
                MessengerMessage(
                    conversation_id=conversation.id,
                    sender_id=peer.id,
                    body=f"unread {index}",
                    created_by=peer.id,
                    updated_by=peer.id,
                )
                for index in range(40)
            ]
        )
        db.session.commit()
        admin_id = admin.id
        _ = conversation.id

        with count_queries(db.engine) as counter:
            marked = MessengerService.mark_read(conversation, admin_id)

        assert marked == 40
        assert counter.count == 1
        assert MessengerRepository.unread_count_for_conversation(conversation.id, admin_id) == 0


def test_search_and_employee_roles_are_eager_loaded(app):
    with app.app_context():
        admin = _user("admin@opora.ru")
        peer = _user("dispatcher@test.local")
        conversation = _conversation(admin, peer)
        original = MessengerMessage(
            conversation_id=conversation.id,
            sender_id=peer.id,
            body="performance needle",
            created_by=peer.id,
            updated_by=peer.id,
        )
        db.session.add(original)
        db.session.flush()
        db.session.add(
            MessengerMessage(
                conversation_id=conversation.id,
                sender_id=admin.id,
                body="performance reply",
                reply_to_id=original.id,
                created_by=admin.id,
                updated_by=admin.id,
            )
        )
        db.session.commit()
        admin_id = admin.id
        db.session.expunge_all()

        messages = MessengerRepository.search_messages(admin_id, "performance")
        with count_queries(db.engine) as search_serialization_queries:
            results = [
                serialize_search_result(message, admin_id)
                for message in messages
            ]
        assert len(results) == 2
        assert search_serialization_queries.count == 0

        pagination = EmployeeRepository.paginated_list(
            EmployeeFilter(),
            page=1,
            per_page=20,
        )
        with count_queries(db.engine) as employee_role_queries:
            role_names = [employee.role_names for employee in pagination.items]
        assert role_names
        assert employee_role_queries.count == 0

        users = MessengerRepository.list_users(admin_id, limit=2)
        assert len(users) == 2
