"""Репозитории модуля сотрудников."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_

from app.extensions import db
from app.models.auth.associations import UserRole
from app.models.auth.position import Position
from app.models.auth.role import Role
from app.models.auth.user import User


@dataclass
class EmployeeFilter:
    q: str = ""
    role_id: str = ""
    status: str = ""
    department: str = ""
    sort_by: str = "full_name"
    sort_dir: str = "asc"


class EmployeeRepository:
    """Чтение и запись сотрудников."""

    SORT_FIELDS = {
        "full_name": User.full_name,
        "created_at": User.created_at,
        "email": User.email,
        "department": User.department,
        "position": User.position,
    }

    @staticmethod
    def get_by_id(user_id: uuid.UUID | str) -> User | None:
        if isinstance(user_id, str):
            try:
                user_id = uuid.UUID(user_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(User).where(User.id == user_id, User.active_filter())
        )

    @staticmethod
    def get_positions() -> list[Position]:
        return list(
            db.session.scalars(
                db.select(Position)
                .where(Position.active_filter(), Position.is_active.is_(True))
                .order_by(Position.sort_order.asc(), Position.name.asc())
            )
        )

    @staticmethod
    def get_roles() -> list[Role]:
        return list(
            db.session.scalars(
                db.select(Role)
                .where(Role.active_filter(), Role.is_active.is_(True))
                .order_by(Role.name.asc())
            )
        )

    @classmethod
    def paginated_list(cls, filters: EmployeeFilter, page: int = 1, per_page: int = 20):
        stmt = db.select(User).where(User.active_filter())

        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    User.full_name.ilike(q),
                    User.email.ilike(q),
                    User.phone.ilike(q),
                    User.position.ilike(q),
                    User.department.ilike(q),
                )
            )

        if filters.department:
            stmt = stmt.where(User.department.ilike(f"%{filters.department.strip()}%"))

        if filters.status == "active":
            stmt = stmt.where(User.is_active.is_(True), User.is_blocked.is_(False))
        elif filters.status == "blocked":
            stmt = stmt.where(User.is_blocked.is_(True))
        elif filters.status == "inactive":
            stmt = stmt.where(User.is_active.is_(False))

        if filters.role_id:
            try:
                role_uuid = uuid.UUID(filters.role_id)
                stmt = stmt.where(
                    User.id.in_(
                        db.select(UserRole.user_id).where(
                            UserRole.role_id == role_uuid,
                            UserRole.active_filter(),
                        )
                    )
                )
            except ValueError:
                pass

        sort_col = cls.SORT_FIELDS.get(filters.sort_by, User.full_name)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, User.full_name.asc())

        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_role_ids(user: User) -> list[uuid.UUID]:
        return [
            ur.role_id
            for ur in user.user_roles
            if ur.deleted_at is None and ur.role_id is not None
        ]
