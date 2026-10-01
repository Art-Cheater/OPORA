"""Сохранённый бланк-распоряжение плана или разового закрытия заявки."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.requests.request import Request
    from app.models.work_plans.work_plan import WorkPlan


class WorkOrderBlank(BaseModel):
    """Поля бланка. Номер необязателен: бланк может быть и без него."""

    __tablename__ = "work_order_blanks"
    __table_args__ = (
        Index("ix_work_order_blanks_plan_id", "plan_id"),
        Index("ix_work_order_blanks_request_id", "request_id"),
        Index("ix_work_order_blanks_closed_by_id", "closed_by_id"),
        Index(
            "uq_work_order_blanks_plan",
            "plan_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND plan_id IS NOT NULL"),
            sqlite_where=text("deleted_at IS NULL AND plan_id IS NOT NULL"),
        ),
        Index(
            "uq_work_order_blanks_request",
            "request_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND plan_id IS NULL AND request_id IS NOT NULL"),
            sqlite_where=text("deleted_at IS NULL AND plan_id IS NULL AND request_id IS NOT NULL"),
        ),
    )

    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("work_plans.id", ondelete="CASCADE"),
        nullable=True,
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=True,
    )
    order_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    producer: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    crew_count: Mapped[str | None] = mapped_column(String(20), nullable=True)
    crew_lead: Mapped[str | None] = mapped_column(String(255), nullable=True)
    crew_members: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lift_responsible: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    briefing_conductor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    needs_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    plan: Mapped[WorkPlan | None] = relationship("WorkPlan", foreign_keys=[plan_id])
    request: Mapped[Request | None] = relationship("Request", foreign_keys=[request_id])
    closed_by: Mapped[User | None] = relationship("User", foreign_keys=[closed_by_id])
