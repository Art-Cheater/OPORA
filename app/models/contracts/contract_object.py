"""Связь контракта с объектами."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.contracts.contract import Contract
    from app.models.work_objects.work_object import WorkObject


class ContractObject(BaseModel):
    """Объект, входящий в контракт."""

    __tablename__ = "contract_objects"
    __table_args__ = (
        Index(
            "ix_contract_objects_pair_active",
            "contract_id",
            "object_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_contract_objects_contract_id", "contract_id"),
        Index("ix_contract_objects_object_id", "object_id"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("work_objects.id", ondelete="CASCADE"),
        nullable=False,
    )

    contract: Mapped[Contract] = relationship(
        "Contract",
        back_populates="object_links",
        foreign_keys=[contract_id],
    )
    work_object: Mapped[WorkObject] = relationship(
        "WorkObject",
        foreign_keys=[object_id],
    )

    def __repr__(self) -> str:
        return f"<ContractObject contract={self.contract_id} object={self.object_id}>"
