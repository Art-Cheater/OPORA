"""Связь контракта с проектами."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.contracts.contract import Contract
    from app.models.projects.project import Project


class ContractProject(BaseModel):
    """Активная связь контракта и проекта; удаляется только мягко."""

    __tablename__ = "contract_projects"
    __table_args__ = (
        Index("ix_contract_projects_pair_active", "contract_id", "project_id", unique=True,
              postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL")),
        Index("ix_contract_projects_contract_id", "contract_id"),
        Index("ix_contract_projects_project_id", "project_id"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    contract: Mapped[Contract] = relationship("Contract", back_populates="project_links")
    project: Mapped[Project] = relationship("Project", back_populates="contract_links")
