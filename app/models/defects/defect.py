"""Модель дефекта наружного освещения."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from app.models.types import GUID, SearchVectorType
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.defects.defect_category import DefectCategory
    from app.models.defects.defect_history import DefectHistory
    from app.models.defects.defect_status import DefectStatus


class Defect(BaseModel):
    """Дефект: может существовать без заявки."""

    __tablename__ = "defects"
    __table_args__ = (
        Index("ix_defects_number", "number", unique=True),
        Index("ix_defects_status_id", "status_id"),
        Index("ix_defects_category_id", "category_id"),
        Index("ix_defects_responsible_id", "responsible_id"),
        Index("ix_defects_address", "address"),
        Index("ix_defects_district", "district"),
        Index("ix_defects_settlement", "settlement"),
        Index("ix_defects_street_district", "street", "district"),
        Index("ix_defects_normalized_address", "normalized_address"),
        Index("ix_defects_lat_lng", "latitude", "longitude"),
        Index("ix_defects_deleted_created", "deleted_at", "created_at"),
        Index("ix_defects_deleted_status", "deleted_at", "status_id"),
    )

    number: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    original_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalized_address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    district: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settlement: Mapped[str | None] = mapped_column(String(255), nullable=True)
    street: Mapped[str | None] = mapped_column(String(500), nullable=True)
    house: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    search_vector: Mapped[str | None] = deferred(
        mapped_column(SearchVectorType, nullable=True)
    )

    status_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("defect_statuses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("defect_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    responsible_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[DefectStatus] = relationship(
        "DefectStatus",
        back_populates="defects",
        foreign_keys=[status_id],
    )
    category: Mapped[DefectCategory] = relationship(
        "DefectCategory",
        back_populates="defects",
        foreign_keys=[category_id],
    )
    responsible: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[responsible_id],
    )
    history: Mapped[list[DefectHistory]] = relationship(
        "DefectHistory",
        back_populates="defect",
        foreign_keys="DefectHistory.defect_id",
        lazy="select",
        order_by="DefectHistory.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Defect {self.number}>"
