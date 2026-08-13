"""Сервисы отчётов."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models.auth.user import User
from app.models.requests.request import Request
from app.models.requests.request_history import RequestHistory
from app.models.requests.request_status import RequestStatus
from app.modules.requests.workflow import STATUS_CANCELLED, STATUS_COMPLETED


@dataclass(frozen=True)
class PeriodRange:
    key: str
    date_from: date
    date_to: date
    label: str

    @property
    def dt_from(self) -> datetime:
        return datetime.combine(self.date_from, time.min, tzinfo=timezone.utc)

    @property
    def dt_to(self) -> datetime:
        return datetime.combine(self.date_to, time.max, tzinfo=timezone.utc)


@dataclass(frozen=True)
class StatusStat:
    code: str
    name: str
    color: str | None
    count: int


@dataclass(frozen=True)
class MasterStat:
    user_id: str
    full_name: str
    completed: int
    assigned_open: int


@dataclass(frozen=True)
class RequestsReport:
    period: PeriodRange
    created_count: int
    completed_count: int
    cancelled_count: int
    remaining_from_period: int
    open_total: int
    avg_hours_to_complete: float | None
    median_hours_to_complete: float | None
    by_status: list[StatusStat]
    by_master: list[MasterStat] = field(default_factory=list)


def resolve_period(
    period_key: str,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    today: date | None = None,
) -> PeriodRange:
    today = today or datetime.now(timezone.utc).date()
    key = (period_key or "week").strip().lower()

    if key == "month":
        start = today - timedelta(days=29)
        end = today
        label = "Прошедший месяц (30 дней)"
    elif key == "custom" and date_from and date_to:
        start, end = (date_from, date_to) if date_from <= date_to else (date_to, date_from)
        label = f"Свой период: {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"
        key = "custom"
    else:
        start = today - timedelta(days=6)
        end = today
        label = "Прошедшая неделя (7 дней)"
        key = "week"

    return PeriodRange(key=key, date_from=start, date_to=end, label=label)


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    delta = (end - start).total_seconds() / 3600.0
    return round(delta, 2) if delta >= 0 else None


class ReportsService:
    @classmethod
    def requests_report(cls, period: PeriodRange) -> RequestsReport:
        rows = db.session.execute(
            select(
                RequestStatus.code,
                RequestStatus.name,
                RequestStatus.color,
                func.count(Request.id),
            )
            .select_from(Request)
            .join(RequestStatus, RequestStatus.id == Request.status_id)
            .where(
                Request.active_filter(),
                Request.created_at >= period.dt_from,
                Request.created_at <= period.dt_to,
            )
            .group_by(
                RequestStatus.code,
                RequestStatus.name,
                RequestStatus.color,
                RequestStatus.sort_order,
            )
            .order_by(RequestStatus.sort_order)
        ).all()

        by_status = [
            StatusStat(code=code, name=name, color=color, count=int(count or 0))
            for code, name, color, count in rows
        ]
        created_count = sum(item.count for item in by_status)
        remaining_from_period = sum(
            item.count
            for item in by_status
            if item.code not in {STATUS_COMPLETED, STATUS_CANCELLED}
        )

        history_counts = {
            code: int(count or 0)
            for code, count in db.session.execute(
                select(RequestStatus.code, func.count(func.distinct(RequestHistory.request_id)))
                .select_from(RequestHistory)
                .join(RequestStatus, RequestStatus.id == RequestHistory.status_id)
                .join(Request, Request.id == RequestHistory.request_id)
                .where(
                    RequestHistory.active_filter(),
                    Request.active_filter(),
                    RequestStatus.code.in_([STATUS_COMPLETED, STATUS_CANCELLED]),
                    RequestHistory.created_at >= period.dt_from,
                    RequestHistory.created_at <= period.dt_to,
                )
                .group_by(RequestStatus.code)
            ).all()
        }
        completed_count = history_counts.get(STATUS_COMPLETED, 0)
        cancelled_count = history_counts.get(STATUS_CANCELLED, 0)

        open_total = db.session.scalar(
            select(func.count())
            .select_from(Request)
            .join(RequestStatus, RequestStatus.id == Request.status_id)
            .where(
                Request.active_filter(),
                RequestStatus.code.notin_([STATUS_COMPLETED, STATUS_CANCELLED]),
            )
        ) or 0

        # SLA: время от создания заявки до первого перехода в completed в периоде
        complete_hist = (
            select(
                RequestHistory.request_id.label("request_id"),
                func.min(RequestHistory.created_at).label("completed_at"),
            )
            .join(RequestStatus, RequestStatus.id == RequestHistory.status_id)
            .where(
                RequestHistory.active_filter(),
                RequestStatus.code == STATUS_COMPLETED,
                RequestHistory.created_at >= period.dt_from,
                RequestHistory.created_at <= period.dt_to,
            )
            .group_by(RequestHistory.request_id)
            .subquery()
        )
        sla_rows = db.session.execute(
            select(Request.created_at, complete_hist.c.completed_at)
            .select_from(complete_hist)
            .join(Request, Request.id == complete_hist.c.request_id)
            .where(Request.active_filter())
        ).all()
        hours_list = [
            h
            for created_at, completed_at in sla_rows
            if (h := _hours_between(created_at, completed_at)) is not None
        ]
        avg_hours = round(sum(hours_list) / len(hours_list), 2) if hours_list else None
        median_hours = None
        if hours_list:
            ordered = sorted(hours_list)
            mid = len(ordered) // 2
            if len(ordered) % 2:
                median_hours = ordered[mid]
            else:
                median_hours = round((ordered[mid - 1] + ordered[mid]) / 2, 2)

        # Нагрузка по мастерам: выполнено за период + сейчас открытых на них
        completed_by_master = (
            select(
                Request.responsible_id.label("user_id"),
                func.count(func.distinct(RequestHistory.request_id)).label("completed"),
            )
            .select_from(RequestHistory)
            .join(RequestStatus, RequestStatus.id == RequestHistory.status_id)
            .join(Request, Request.id == RequestHistory.request_id)
            .where(
                RequestHistory.active_filter(),
                Request.active_filter(),
                RequestStatus.code == STATUS_COMPLETED,
                RequestHistory.created_at >= period.dt_from,
                RequestHistory.created_at <= period.dt_to,
                Request.responsible_id.is_not(None),
            )
            .group_by(Request.responsible_id)
            .subquery()
        )
        open_by_master = (
            select(
                Request.responsible_id.label("user_id"),
                func.count(Request.id).label("assigned_open"),
            )
            .join(RequestStatus, RequestStatus.id == Request.status_id)
            .where(
                Request.active_filter(),
                Request.responsible_id.is_not(None),
                RequestStatus.code.notin_([STATUS_COMPLETED, STATUS_CANCELLED]),
            )
            .group_by(Request.responsible_id)
            .subquery()
        )
        master_rows = db.session.execute(
            select(
                User.id,
                User.full_name,
                func.coalesce(completed_by_master.c.completed, 0),
                func.coalesce(open_by_master.c.assigned_open, 0),
            )
            .select_from(User)
            .outerjoin(completed_by_master, completed_by_master.c.user_id == User.id)
            .outerjoin(open_by_master, open_by_master.c.user_id == User.id)
            .where(
                User.active_filter(),
                or_(
                    completed_by_master.c.completed.is_not(None),
                    open_by_master.c.assigned_open.is_not(None),
                ),
            )
            .order_by(
                func.coalesce(completed_by_master.c.completed, 0).desc(),
                User.full_name.asc(),
            )
        ).all()

        by_master = [
            MasterStat(
                user_id=str(uid),
                full_name=name,
                completed=int(completed or 0),
                assigned_open=int(open_cnt or 0),
            )
            for uid, name, completed, open_cnt in master_rows
        ]

        return RequestsReport(
            period=period,
            created_count=int(created_count),
            completed_count=int(completed_count),
            cancelled_count=int(cancelled_count),
            remaining_from_period=int(remaining_from_period),
            open_total=int(open_total),
            avg_hours_to_complete=avg_hours,
            median_hours_to_complete=median_hours,
            by_status=by_status,
            by_master=by_master,
        )

    @classmethod
    def requests_report_csv_rows(cls, report: RequestsReport) -> list[list[str]]:
        rows: list[list[str]] = [
            ["Метрика", "Значение"],
            ["Период", report.period.label],
            ["Создано", str(report.created_count)],
            ["Выполнено за период", str(report.completed_count)],
            ["Отменено за период", str(report.cancelled_count)],
            ["Осталось из созданных", str(report.remaining_from_period)],
            ["Всего открытых сейчас", str(report.open_total)],
            [
                "Среднее время до выполнения (ч)",
                "" if report.avg_hours_to_complete is None else str(report.avg_hours_to_complete),
            ],
            [
                "Медиана времени до выполнения (ч)",
                ""
                if report.median_hours_to_complete is None
                else str(report.median_hours_to_complete),
            ],
            [],
            ["Статус", "Количество"],
        ]
        for item in report.by_status:
            rows.append([item.name, str(item.count)])
        rows.extend([[], ["Мастер", "Выполнено за период", "Открыто сейчас"]])
        for m in report.by_master:
            rows.append([m.full_name, str(m.completed), str(m.assigned_open)])
        return rows
