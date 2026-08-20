"""Модель подрядчика (поставщика ЕИС / плана)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel

if TYPE_CHECKING:
    from app.models.contracts.contract_contractor import ContractContractor


class Contractor(ActiveRecordMixin, BaseModel):
    """Юрлицо-подрядчик. Уникальность — по ИНН среди активных записей."""

    __tablename__ = "contractors"
    __table_args__ = (
        Index(
            "ix_contractors_inn_unique_active",
            "inn",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND inn IS NOT NULL AND inn != ''"),
            sqlite_where=text("deleted_at IS NULL AND inn IS NOT NULL AND inn != ''"),
        ),
        Index("ix_contractors_name", "name"),
        Index("ix_contractors_deleted_created", "deleted_at", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    inn: Mapped[str | None] = mapped_column(String(12), nullable=True)
    kpp: Mapped[str | None] = mapped_column(String(9), nullable=True)
    kpp_largest: Mapped[str | None] = mapped_column(String(9), nullable=True)
    address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    contract_links: Mapped[list[ContractContractor]] = relationship(
        "ContractContractor",
        back_populates="contractor",
        foreign_keys="ContractContractor.contractor_id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Contractor {self.inn or self.name[:40]}>"
