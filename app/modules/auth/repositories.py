"""Репозиторий пользователей — слой доступа к данным."""

import uuid

from sqlalchemy.orm import joinedload, noload, selectinload

from app.extensions import db
from app.models.auth.associations import RolePermission, UserRole
from app.models.auth.permission import Permission
from app.models.auth.position import Position
from app.models.auth.role import Role
from app.models.auth.user import User


class UserRepository:
    """Репозиторий для работы с пользователями."""

    @staticmethod
    def get_by_id(user_id: uuid.UUID | str) -> User | None:
        if isinstance(user_id, str):
            try:
                user_id = uuid.UUID(user_id)
            except ValueError:
                return None
        # Eager RBAC: иначе sidebar делает десятки SELECT на каждое has_permission
        return db.session.scalar(
            db.select(User)
            .options(
                selectinload(User.user_roles)
                .joinedload(UserRole.role)
                .options(
                    selectinload(Role.role_permissions)
                    .joinedload(RolePermission.permission)
                    .options(
                        noload(Permission.role_permissions),
                        noload(Permission.system_module),
                    ),
                    noload(Role.field_permissions),
                    noload(Role.user_roles),
                ),
                joinedload(User.position_ref).options(noload(Position.users)),
                noload(User.login_logs),
            )
            .where(User.id == user_id, User.active_filter())
        )

    @staticmethod
    def get_by_email(email: str) -> User | None:
        return db.session.scalar(
            db.select(User).where(
                User.email == email.lower().strip(),
                User.active_filter(),
            )
        )

    @staticmethod
    def get_all_active() -> list[User]:
        return list(
            db.session.scalars(
                db.select(User)
                .where(User.is_active.is_(True), User.active_filter())
                .order_by(User.full_name)
            )
        )

    @staticmethod
    def save(user: User) -> User:
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def exists_by_email(email: str) -> bool:
        return db.session.scalar(
            db.select(db.exists().where(
                User.email == email.lower().strip(),
                User.active_filter(),
            ))
        )
