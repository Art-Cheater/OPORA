"""Связь заявки на торги с проектом."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.projects.project import Project
    from app.models.tenders.tender_application import TenderApplication


class TenderProject(BaseModel):
    """Связь заявки на торги с проектом."""

    __tablename__ = "tender_projects"
    __table_args__ = (
        Index(
            "ix_tender_projects_pair_active",
            "tender_id",
            "project_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_tender_projects_tender_id", "tender_id"),
        Index("ix_tender_projects_project_id", "project_id"),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("tender_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    tender: Mapped[TenderApplication] = relationship(
        "TenderApplication",
        back_populates="project_links",
        foreign_keys=[tender_id],
    )
    project: Mapped[Project] = relationship(
        "Project",
        foreign_keys=[project_id],
    )

    def __repr__(self) -> str:
        return f"<TenderProject tender={self.tender_id} project={self.project_id}>"
