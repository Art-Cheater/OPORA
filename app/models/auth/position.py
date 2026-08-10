"""Должность сотрудника (информационная, без влияния на права)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User


class Position(ActiveRecordMixin, BaseModel):
    """Справочник должностей."""

    __tablename__ = "positions"
    __table_args__ = (
        Index(
            "ix_positions_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_positions_sort_order", "sort_order"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    users: Mapped[list[User]] = relationship(
        "User",
        back_populates="position_ref",
        foreign_keys="User.position_id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Position {self.code}>"
