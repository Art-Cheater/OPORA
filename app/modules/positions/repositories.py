"""Репозиторий должностей."""

from __future__ import annotations

from app.extensions import db
from app.models.auth.position import Position


class PositionRepository:
    @staticmethod
    def list_active() -> list[Position]:
        return list(
            db.session.scalars(
                db.select(Position)
                .where(Position.active_filter(), Position.is_active.is_(True))
                .order_by(Position.sort_order.asc(), Position.name.asc())
            )
        )

    @staticmethod
    def get_by_id(position_id) -> Position | None:
        return db.session.scalar(
            db.select(Position).where(Position.id == position_id, Position.active_filter())
        )
