"""История изменений контракта."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, Text
from app.models.types import GUID, JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.contracts.contract import Contract


class ContractHistory(BaseModel):
    """История изменений контракта."""

    __tablename__ = "contract_history"
    __table_args__ = (
        Index("ix_contract_history_contract_id", "contract_id"),
        Index("ix_contract_history_changed_by", "changed_by"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="update")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    contract: Mapped[Contract] = relationship(
        "Contract",
        back_populates="history",
        foreign_keys=[contract_id],
    )
    changed_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[changed_by],
    )

    def __repr__(self) -> str:
        return f"<ContractHistory contract={self.contract_id} action={self.action}>"
