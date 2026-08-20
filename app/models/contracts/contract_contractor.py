"""Связь контракта с подрядчиками."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.contractors.contractor import Contractor
    from app.models.contracts.contract import Contract


class ContractContractor(BaseModel):
    """Подрядчик, указанный в контракте (их может быть несколько)."""

    __tablename__ = "contract_contractors"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            "contractor_id",
            name="uq_contract_contractors_pair",
        ),
        Index("ix_contract_contractors_contract_id", "contract_id"),
        Index("ix_contract_contractors_contractor_id", "contractor_id"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    contractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("contractors.id", ondelete="CASCADE"),
        nullable=False,
    )

    contract: Mapped[Contract] = relationship(
        "Contract",
        back_populates="contractor_links",
        foreign_keys=[contract_id],
    )
    contractor: Mapped[Contractor] = relationship(
        "Contractor",
        back_populates="contract_links",
        foreign_keys=[contractor_id],
    )

    def __repr__(self) -> str:
        return f"<ContractContractor contract={self.contract_id} contractor={self.contractor_id}>"
