"""Репозиторий журнала действий."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.search import (
    build_tsquery,
    is_postgres,
    is_valid_query,
    like_or,
    like_pattern,
    ts_rank,
)
from app.extensions import db
from app.models.audit.audit_log import AuditLog
from app.models.auth.user import User


@dataclass
class AuditFilter:
    q: str = ""
    user_id: str = ""
    action: str = ""
    entity_type: str = ""
    date_from: str = ""
    date_to: str = ""
    sort_dir: str = "desc"


class AuditRepository:
    """Чтение журнала действий (только чтение)."""

    @classmethod
    def _build_stmt(cls, filters: AuditFilter):
        stmt = (
            select(AuditLog)
            .where(AuditLog.deleted_at.is_(None))
            .options(joinedload(AuditLog.user))
        )
        if filters.q and is_valid_query(filters.q):
            if is_postgres():
                tsquery = build_tsquery(filters.q)
                rank_expr = ts_rank(AuditLog.search_vector, tsquery)
                stmt = stmt.where(AuditLog.search_vector.op("@@")(tsquery)).order_by(
                    rank_expr.desc(), AuditLog.created_at.desc()
                )
            else:
                pattern = like_pattern(filters.q)
                stmt = stmt.where(
                    like_or(
                        AuditLog.description,
                        AuditLog.action,
                        AuditLog.entity_type,
                        AuditLog.ip_address,
                        pattern=pattern,
                    )
                ).order_by(AuditLog.created_at.desc())
        else:
            stmt = stmt.order_by(
                AuditLog.created_at.desc()
                if filters.sort_dir == "desc"
                else AuditLog.created_at.asc()
            )

        if filters.user_id:
            try:
                stmt = stmt.where(AuditLog.user_id == uuid.UUID(filters.user_id))
            except ValueError:
                pass
        if filters.action:
            stmt = stmt.where(AuditLog.action == filters.action)
        if filters.entity_type:
            stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
        if filters.date_from:
            try:
                dt_from = datetime.combine(
                    date.fromisoformat(filters.date_from), time.min, tzinfo=timezone.utc
                )
                stmt = stmt.where(AuditLog.created_at >= dt_from)
            except ValueError:
                pass
        if filters.date_to:
            try:
                dt_to = datetime.combine(
                    date.fromisoformat(filters.date_to), time.max, tzinfo=timezone.utc
                )
                stmt = stmt.where(AuditLog.created_at <= dt_to)
            except ValueError:
                pass

        return stmt

    @classmethod
    def paginated_list(cls, filters: AuditFilter, page: int = 1, per_page: int = 30):
        stmt = cls._build_stmt(filters)
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @classmethod
    def export_list(cls, filters: AuditFilter, limit: int = 10000) -> list[AuditLog]:
        stmt = cls._build_stmt(filters).limit(limit)
        return list(db.session.scalars(stmt))

    @staticmethod
    def get_users_for_filter() -> list[User]:
        return list(
            db.session.scalars(
                select(User).where(User.active_filter()).order_by(User.full_name.asc())
            )
        )
