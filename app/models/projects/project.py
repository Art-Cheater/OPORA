"""Модель проекта."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text, text
from app.models.types import GUID, SearchVectorType
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.enums import ProjectMemberRole, ProjectStatus

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.projects.project_document import ProjectDocument
    from app.models.projects.project_history import ProjectHistory
    from app.models.projects.project_member import ProjectMember
    from app.models.requests.request import Request
    from app.models.contracts.contract import Contract
    from app.models.work_objects.work_object import WorkObject


class Project(ActiveRecordMixin, BaseModel):
    """Проект муниципального предприятия (1:1 с адресным объектом)."""

    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "ix_projects_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_projects_status", "status"),
        Index("ix_projects_manager_id", "manager_id"),
        Index("ix_projects_object_id", "object_id"),
        Index("ix_projects_start_date", "start_date"),
        Index("ix_projects_deleted_created", "deleted_at", "created_at"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default=ProjectStatus.DRAFT.value,
        nullable=False,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sip_meters: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    poles_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lights_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shuno_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sip_meters_fact: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    poles_count_fact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lights_count_fact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shuno_count_fact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    search_vector: Mapped[str | None] = deferred(
        mapped_column(SearchVectorType, nullable=True)
    )

    object_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("work_objects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    work_object: Mapped[WorkObject | None] = relationship(
        "WorkObject",
        back_populates="projects",
        foreign_keys=[object_id],
    )
    manager: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[manager_id],
    )
    members: Mapped[list[ProjectMember]] = relationship(
        "ProjectMember",
        back_populates="project",
        # select: иначе любой JOIN проекта (торги, формы) тянет участников
        lazy="select",
    )
    requests: Mapped[list[Request]] = relationship(
        "Request",
        back_populates="project",
        lazy="select",
    )
    contracts: Mapped[list[Contract]] = relationship(
        "Contract",
        back_populates="project",
        lazy="select",
    )
    history: Mapped[list[ProjectHistory]] = relationship(
        "ProjectHistory",
        back_populates="project",
        foreign_keys="ProjectHistory.project_id",
        lazy="select",
        order_by="ProjectHistory.created_at.desc()",
    )
    documents: Mapped[list[ProjectDocument]] = relationship(
        "ProjectDocument",
        back_populates="project",
        foreign_keys="ProjectDocument.project_id",
        lazy="select",
        order_by="ProjectDocument.created_at.desc()",
    )

    @property
    def responsible(self) -> User | None:
        return self.manager

    @property
    def responsible_id(self) -> uuid.UUID | None:
        return self.manager_id

    @property
    def active_members(self) -> list[ProjectMember]:
        return [member for member in self.members if member.deleted_at is None]

    @property
    def executors(self) -> list[User]:
        return [
            member.user
            for member in self.active_members
            if member.role_in_project == ProjectMemberRole.EXECUTOR.value and member.user is not None
        ]

    @property
    def cabinet_label(self) -> str:
        """ШУНО для освещения, шкафы — для техприсоединения."""
        from app.models.enums import WorkObjectKind

        kind = self.work_object.object_kind if self.work_object is not None else None
        if kind == WorkObjectKind.TECH_CONNECT.value:
            return "Шкафы, шт."
        return "ШУНО, шт."

    def __repr__(self) -> str:
        return f"<Project {self.code}>"
