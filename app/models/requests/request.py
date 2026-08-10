"""Модель заявки."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from app.models.types import GUID, JSONType, SearchVectorType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import Priority

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.requests.request_material import RequestMaterial
    from app.models.projects.project import Project
    from app.models.requests.request_history import RequestHistory
    from app.models.requests.request_status import RequestStatus


class Request(BaseModel):
    """Заявка в системе."""

    __tablename__ = "requests"
    __table_args__ = (
        Index("ix_requests_status_id", "status_id"),
        Index("ix_requests_project_id", "project_id"),
        Index("ix_requests_responsible_id", "responsible_id"),
        Index("ix_requests_executor_id", "executor_id"),
        Index("ix_requests_priority", "priority"),
        Index("ix_requests_due_date", "due_date"),
        Index("ix_requests_address", "address"),
        Index("ix_requests_number", "number", unique=True),
        Index("ix_requests_received_at", "received_at"),
        Index("ix_requests_dispatcher_name", "dispatcher_name"),
    )

    number: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    pp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatcher_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    applicant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    has_barrier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    barrier_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    repeat_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repeat_dates: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    priority: Mapped[str] = mapped_column(
        String(20),
        default=Priority.MEDIUM.value,
        nullable=False,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    search_vector: Mapped[str | None] = mapped_column(SearchVectorType, nullable=True)

    status_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("request_statuses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    responsible_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    executor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[RequestStatus] = relationship(
        "RequestStatus",
        back_populates="requests",
        foreign_keys=[status_id],
    )
    project: Mapped[Project | None] = relationship(
        "Project",
        back_populates="requests",
        foreign_keys=[project_id],
    )
    responsible: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[responsible_id],
    )
    executor: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[executor_id],
    )
    history: Mapped[list[RequestHistory]] = relationship(
        "RequestHistory",
        back_populates="request",
        foreign_keys="RequestHistory.request_id",
        # select, не selectin: в списке заявок история не нужна
        lazy="select",
        order_by="RequestHistory.created_at.desc()",
    )
    materials: Mapped[list[RequestMaterial]] = relationship(
        "RequestMaterial",
        back_populates="request",
        foreign_keys="RequestMaterial.request_id",
        lazy="select",
        order_by="RequestMaterial.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Request {self.number}>"
