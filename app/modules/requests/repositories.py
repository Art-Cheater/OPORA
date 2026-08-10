"""Репозитории модуля заявок."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import contains_eager, joinedload, load_only, noload

from app.extensions import db
from app.models.auth.associations import UserRole
from app.models.auth.position import Position
from app.models.auth.role import Role
from app.models.auth.user import User
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.workflow import (
    PRESET_AWAITING_MASTER,
    PRESET_COMPLETED,
    PRESET_FOR_EMERGENCY,
    PRESET_IN_PROGRESS,
    PRESET_MY,
    STATUS_ACCEPTED_BY_MASTER,
    STATUS_COMPLETED,
    STATUS_EMERGENCY_DISPATCHED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
)


@dataclass
class RequestFilter:
    q: str = ""
    status_id: str = ""
    priority: str = ""
    responsible_id: str = ""
    executor_id: str = ""
    preset: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class RequestRepository:
    """Чтение и запись заявок."""

    SORT_FIELDS = {
        "created_at": Request.created_at,
        "updated_at": Request.updated_at,
        "number": Request.number,
        "priority": Request.priority,
        "title": Request.title,
    }

    @staticmethod
    def get_by_id(request_id: uuid.UUID | str) -> Request | None:
        if isinstance(request_id, str):
            try:
                request_id = uuid.UUID(request_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Request).where(Request.id == request_id, Request.active_filter())
        )

    @staticmethod
    def get_statuses() -> list[RequestStatus]:
        return list(
            db.session.scalars(
                db.select(RequestStatus)
                .where(RequestStatus.active_filter(), RequestStatus.is_active.is_(True))
                .order_by(RequestStatus.sort_order.asc(), RequestStatus.name.asc())
            )
        )

    @staticmethod
    def get_status_by_code(code: str) -> RequestStatus | None:
        return db.session.scalar(
            db.select(RequestStatus).where(
                RequestStatus.code == code,
                RequestStatus.active_filter(),
                RequestStatus.is_active.is_(True),
            )
        )

    @staticmethod
    def get_users() -> list[User]:
        return list(
            db.session.scalars(
                db.select(User)
                .options(
                    load_only(
                        User.id,
                        User.full_name,
                        User.email,
                        User.is_active,
                        User.is_blocked,
                        User.deleted_at,
                    ),
                    noload(User.user_roles),
                    noload(User.login_logs),
                )
                .where(User.active_filter(), User.is_active.is_(True), User.is_blocked.is_(False))
                .order_by(User.full_name.asc())
            )
        )

    @staticmethod
    def get_masters() -> list[User]:
        """Активные сотрудники с должностью или ролью «Мастер»."""
        position_ids = db.select(Position.id).where(
            Position.code == "master",
            Position.active_filter(),
            Position.is_active.is_(True),
        )
        role_user_ids = (
            db.select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                Role.code == "master",
                Role.active_filter(),
                UserRole.active_filter(),
            )
        )
        return list(
            db.session.scalars(
                db.select(User)
                .options(
                    load_only(
                        User.id,
                        User.full_name,
                        User.email,
                        User.is_active,
                        User.is_blocked,
                        User.deleted_at,
                        User.position_id,
                    ),
                    noload(User.user_roles),
                    noload(User.login_logs),
                )
                .where(
                    User.active_filter(),
                    User.is_active.is_(True),
                    User.is_blocked.is_(False),
                    or_(User.position_id.in_(position_ids), User.id.in_(role_user_ids)),
                )
                .order_by(User.full_name.asc())
            )
        )

    @staticmethod
    def next_number() -> str:
        from datetime import datetime

        year = datetime.now().year
        prefix = f"REQ-{year}-"
        last = db.session.scalar(
            db.select(Request.number)
            .where(Request.number.ilike(f"{prefix}%"), Request.active_filter())
            .order_by(Request.number.desc())
            .limit(1)
        )
        if not last:
            return f"{prefix}001"
        try:
            seq = int(last.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
        return f"{prefix}{seq:03d}"

    @classmethod
    def _apply_preset(cls, stmt, preset: str, current_user_id: uuid.UUID | None):
        if not preset:
            return stmt

        if preset == PRESET_FOR_EMERGENCY:
            # Новые заявки (ожидают отметки выезда бригады)
            status = cls.get_status_by_code(STATUS_NEW)
            if status is None:
                return stmt.where(sa_false())
            return stmt.where(Request.status_id == status.id)

        if preset == PRESET_AWAITING_MASTER:
            # Жёлтые: выехала бригада, ещё не переданы мастеру
            status = cls.get_status_by_code(STATUS_EMERGENCY_DISPATCHED)
            if status is None:
                return stmt.where(sa_false())
            return stmt.where(Request.status_id == status.id)

        if preset == PRESET_MY and current_user_id is not None:
            return stmt.where(Request.responsible_id == current_user_id)

        if preset == PRESET_IN_PROGRESS:
            codes = (STATUS_ACCEPTED_BY_MASTER, STATUS_IN_PROGRESS)
            status_ids = db.select(RequestStatus.id).where(
                RequestStatus.code.in_(codes),
                RequestStatus.active_filter(),
            )
            q = stmt.where(Request.status_id.in_(status_ids))
            if current_user_id is not None:
                q = q.where(Request.responsible_id == current_user_id)
            return q

        if preset == PRESET_COMPLETED:
            status = cls.get_status_by_code(STATUS_COMPLETED)
            if status is None:
                return stmt.where(sa_false())
            q = stmt.where(Request.status_id == status.id)
            if current_user_id is not None:
                q = q.where(Request.responsible_id == current_user_id)
            return q

        return stmt

    @classmethod
    def paginated_list(
        cls,
        filters: RequestFilter,
        page: int = 1,
        per_page: int = 20,
        current_user_id: uuid.UUID | None = None,
    ):
        stmt = (
            db.select(Request)
            .where(Request.active_filter())
            .join(Request.status)
            .options(
                contains_eager(Request.status),
                joinedload(Request.responsible).options(
                    load_only(User.id, User.full_name, User.email, User.deleted_at, User.is_active),
                    noload(User.user_roles),
                    noload(User.login_logs),
                ),
                joinedload(Request.executor).options(
                    load_only(User.id, User.full_name, User.email, User.deleted_at, User.is_active),
                    noload(User.user_roles),
                    noload(User.login_logs),
                ),
                noload(Request.history),
                noload(Request.materials),
            )
        )

        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    Request.number.ilike(q),
                    Request.title.ilike(q),
                    Request.address.ilike(q),
                    Request.applicant_name.ilike(q),
                    Request.phone.ilike(q),
                )
            )

        if filters.status_id:
            try:
                stmt = stmt.where(Request.status_id == uuid.UUID(filters.status_id))
            except ValueError:
                pass

        if filters.priority:
            stmt = stmt.where(Request.priority == filters.priority)

        if filters.responsible_id:
            try:
                stmt = stmt.where(Request.responsible_id == uuid.UUID(filters.responsible_id))
            except ValueError:
                pass

        if filters.executor_id:
            try:
                stmt = stmt.where(Request.executor_id == uuid.UUID(filters.executor_id))
            except ValueError:
                pass

        stmt = cls._apply_preset(stmt, filters.preset, current_user_id)

        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Request.created_at)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, Request.created_at.desc())

        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)


def sa_false():
    """Условие, которое никогда не выполняется."""
    return Request.id.is_(None)
