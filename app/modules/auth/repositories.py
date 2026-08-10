"""Репозиторий пользователей — слой доступа к данным."""

import uuid

from app.extensions import db
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
        return db.session.scalar(
            db.select(User).where(User.id == user_id, User.active_filter())
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
