"""Репозитории модуля ролей."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_

from app.extensions import db
from app.models.auth.associations import RolePermission, UserRole
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.auth.role_field_permission import RoleFieldPermission


@dataclass
class RoleFilter:
    q: str = ""
    sort_by: str = "name"
    sort_dir: str = "asc"


class RoleRepository:
    SORT_FIELDS = {
        "name": Role.name,
        "code": Role.code,
        "created_at": Role.created_at,
    }

    @staticmethod
    def get_by_id(role_id: uuid.UUID | str) -> Role | None:
        if isinstance(role_id, str):
            try:
                role_id = uuid.UUID(role_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Role).where(Role.id == role_id, Role.active_filter())
        )

    @staticmethod
    def get_by_code(code: str) -> Role | None:
        return db.session.scalar(
            db.select(Role).where(Role.code == code.strip().lower(), Role.active_filter())
        )

    @staticmethod
    def get_all_permissions() -> list[Permission]:
        return list(
            db.session.scalars(
                db.select(Permission)
                .where(Permission.active_filter(), Permission.is_active.is_(True))
                .order_by(Permission.module.asc(), Permission.name.asc())
            )
        )

    @staticmethod
    def get_permission_ids(role: Role) -> list[uuid.UUID]:
        return list(
            db.session.scalars(
                db.select(RolePermission.permission_id).where(
                    RolePermission.role_id == role.id,
                    RolePermission.deleted_at.is_(None),
                    RolePermission.permission_id.is_not(None),
                )
            )
        )

    @staticmethod
    def get_field_rules(role: Role) -> list[RoleFieldPermission]:
        return list(
            db.session.scalars(
                db.select(RoleFieldPermission).where(
                    RoleFieldPermission.role_id == role.id,
                    RoleFieldPermission.deleted_at.is_(None),
                )
            )
        )

    @staticmethod
    def users_count(role: Role) -> int:
        return db.session.scalar(
            db.select(func.count())
            .select_from(UserRole)
            .where(UserRole.role_id == role.id, UserRole.active_filter())
        ) or 0

    @classmethod
    def paginated_list(cls, filters: RoleFilter, page: int = 1, per_page: int = 20):
        stmt = db.select(Role).where(Role.active_filter())
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(or_(Role.name.ilike(q), Role.code.ilike(q)))
        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Role.name)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, Role.name.asc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @classmethod
    def list_all(cls, filters: RoleFilter) -> list[Role]:
        stmt = db.select(Role).where(Role.active_filter())
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(or_(Role.name.ilike(q), Role.code.ilike(q)))
        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Role.name)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, Role.name.asc())
        return list(db.session.scalars(stmt))
