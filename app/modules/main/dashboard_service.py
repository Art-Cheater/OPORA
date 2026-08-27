"""Данные рабочей панели (dashboard) — лёгкие агрегаты без N+1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.auth.constants import (
    PERM_CONTRACTS_CREATE,
    PERM_CONTRACTS_VIEW,
    PERM_EIS_VIEW,
    PERM_OBJECTS_VIEW,
    PERM_PROJECTS_CREATE,
    PERM_PROJECTS_VIEW,
    PERM_REQUESTS_CREATE,
    PERM_REQUESTS_VIEW,
)
from app.models.contracts.contract import Contract
from app.models.enums import ContractStatus, Priority, ProjectStatus
from app.models.projects.project import Project
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.contracts.forms import CONTRACT_STATUS_LABELS
from app.modules.projects.forms import PROJECT_STATUS_CHOICES
from app.modules.requests.workflow import (
    PRESET_AWAITING_MASTER,
    PRESET_FOR_EMERGENCY,
    PRESET_IN_PROGRESS,
    STATUS_ACCEPTED_BY_MASTER,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
    STATUS_EMERGENCY_DISPATCHED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
)

PROJECT_STATUS_LABELS = dict(PROJECT_STATUS_CHOICES)

ACTIVE_CONTRACT_STATUSES = frozenset(
    {
        ContractStatus.DRAFT.value,
        ContractStatus.ACTIVE.value,
        ContractStatus.WORK_DOCS_PENDING.value,
        ContractStatus.IN_PROGRESS.value,
        ContractStatus.KS2_PENDING.value,
    }
)

OPEN_PROJECT_STATUSES = frozenset(
    {
        ProjectStatus.DRAFT.value,
        ProjectStatus.ACTIVE.value,
        ProjectStatus.IN_TENDER.value,
        ProjectStatus.IN_CONTRACT.value,
        ProjectStatus.ON_HOLD.value,
    }
)


@dataclass
class MetricCard:
    key: str
    title: str
    value: int
    href: str
    icon: str
    tone: str = "orange"


@dataclass
class AttentionItem:
    key: str
    label: str
    count: int
    href: str
    tone: str  # danger | warning | orange | info


@dataclass
class QuickAction:
    key: str
    label: str
    href: str
    icon: str


@dataclass
class DashboardPayload:
    greeting: str
    subtitle: str
    now_date: str
    now_time: str
    position: str | None
    metrics: list[MetricCard] = field(default_factory=list)
    attention: list[AttentionItem] = field(default_factory=list)
    quick_actions: list[QuickAction] = field(default_factory=list)
    recent_requests: list[dict[str, Any]] = field(default_factory=list)
    recent_projects: list[dict[str, Any]] = field(default_factory=list)
    recent_contracts: list[dict[str, Any]] = field(default_factory=list)


class DashboardService:
    """Сбор обзорных данных главной страницы с учётом permissions."""

    @classmethod
    def build(cls, user, *, tz_name: str = "Europe/Moscow") -> DashboardPayload:
        now = cls._local_now(tz_name)
        greeting = cls._greeting(now.hour)
        first_name = (user.full_name or "").strip().split()[0] if user.full_name else "коллега"

        payload = DashboardPayload(
            greeting=f"{greeting}, {first_name}",
            subtitle="Вот что происходит в Опоре сегодня",
            now_date=now.strftime("%d.%m.%Y"),
            now_time=now.strftime("%H:%M"),
            position=getattr(user, "position_title", None) or user.position,
        )

        can_requests = user.has_permission(PERM_REQUESTS_VIEW)
        can_projects = user.has_permission(PERM_PROJECTS_VIEW)
        can_contracts = user.has_permission(PERM_CONTRACTS_VIEW)

        req_counts: dict[str, int] = {}
        if can_requests:
            req_counts = cls._request_status_counts()
            new_n = req_counts.get(STATUS_NEW, 0)
            in_work = (
                req_counts.get(STATUS_ACCEPTED_BY_MASTER, 0)
                + req_counts.get(STATUS_IN_PROGRESS, 0)
            )
            payload.metrics.append(
                MetricCard(
                    "requests_new",
                    "Новые заявки",
                    new_n,
                    f"/requests/?preset={PRESET_FOR_EMERGENCY}",
                    "clipboard-plus",
                    "orange",
                )
            )
            payload.metrics.append(
                MetricCard(
                    "requests_in_work",
                    "В работе",
                    in_work,
                    f"/requests/?preset={PRESET_IN_PROGRESS}",
                    "hourglass-split",
                    "yellow",
                )
            )
            payload.attention.extend(cls._request_attention(req_counts))
            payload.recent_requests = cls._recent_requests(limit=8)

        if can_projects:
            projects_n = cls._count_projects()
            payload.metrics.append(
                MetricCard(
                    "projects",
                    "Проекты",
                    projects_n,
                    "/projects/",
                    "folder2-open",
                    "green",
                )
            )
            without_contract = cls._projects_without_contract_count()
            payload.attention.append(
                AttentionItem(
                    "projects_no_contract",
                    "проектов без контракта",
                    without_contract,
                    "/projects/?status=active",
                    "orange",
                )
            )
            payload.recent_projects = cls._recent_projects(limit=5)

        if can_contracts:
            contracts_n = cls._count_contracts()
            payload.metrics.append(
                MetricCard(
                    "contracts",
                    "Контракты",
                    contracts_n,
                    "/contracts/",
                    "file-earmark-text",
                    "blue",
                )
            )
            ending = cls._contracts_ending_soon_count(days=30)
            today = date.today()
            end = today + timedelta(days=30)
            payload.attention.append(
                AttentionItem(
                    "contracts_ending",
                    "контрактов заканчиваются в ближайшие 30 дней",
                    ending,
                    f"/contracts/?end_date_from={today.isoformat()}&end_date_to={end.isoformat()}",
                    "warning",
                )
            )
            payload.recent_contracts = cls._recent_contracts(limit=5)

        payload.quick_actions = cls._quick_actions(user)
        return payload

    @staticmethod
    def _local_now(tz_name: str) -> datetime:
        from datetime import timedelta, timezone

        try:
            zone = ZoneInfo(tz_name or "Europe/Moscow")
        except Exception:
            zone = timezone(timedelta(hours=3))
        return datetime.now(zone)

    @staticmethod
    def _greeting(hour: int) -> str:
        if 5 <= hour < 12:
            return "Доброе утро"
        if 12 <= hour < 18:
            return "Добрый день"
        if 18 <= hour < 23:
            return "Добрый вечер"
        return "Доброй ночи"

    @staticmethod
    def _request_status_counts() -> dict[str, int]:
        rows = db.session.execute(
            select(RequestStatus.code, func.count(Request.id))
            .select_from(Request)
            .join(RequestStatus, Request.status_id == RequestStatus.id)
            .where(Request.deleted_at.is_(None))
            .group_by(RequestStatus.code)
        ).all()
        return {code: int(cnt) for code, cnt in rows}

    @staticmethod
    def _request_attention(counts: dict[str, int]) -> list[AttentionItem]:
        critical = int(
            db.session.scalar(
                select(func.count())
                .select_from(Request)
                .join(RequestStatus, Request.status_id == RequestStatus.id)
                .where(
                    Request.deleted_at.is_(None),
                    Request.priority == Priority.CRITICAL.value,
                    RequestStatus.code.notin_((STATUS_COMPLETED, STATUS_CANCELLED)),
                )
            )
            or 0
        )
        return [
            AttentionItem(
                "emergency",
                "аварийные заявки (критический приоритет)",
                critical,
                "/requests/?priority=critical",
                "danger",
            ),
            AttentionItem(
                "awaiting_master",
                "заявок ожидают мастера",
                counts.get(STATUS_EMERGENCY_DISPATCHED, 0),
                f"/requests/?preset={PRESET_AWAITING_MASTER}",
                "warning",
            ),
        ]

    @staticmethod
    def _count_projects() -> int:
        return int(
            db.session.scalar(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.deleted_at.is_(None),
                    Project.status.in_(tuple(OPEN_PROJECT_STATUSES)),
                )
            )
            or 0
        )

    @staticmethod
    def _count_contracts() -> int:
        return int(
            db.session.scalar(
                select(func.count())
                .select_from(Contract)
                .where(
                    Contract.deleted_at.is_(None),
                    Contract.status.in_(tuple(ACTIVE_CONTRACT_STATUSES)),
                )
            )
            or 0
        )

    @staticmethod
    def _projects_without_contract_count() -> int:
        has_contract = exists(
            select(Contract.id).where(
                Contract.project_id == Project.id,
                Contract.deleted_at.is_(None),
            )
        )
        return int(
            db.session.scalar(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.deleted_at.is_(None),
                    Project.status.in_(
                        (
                            ProjectStatus.DRAFT.value,
                            ProjectStatus.ACTIVE.value,
                            ProjectStatus.IN_TENDER.value,
                        )
                    ),
                    ~has_contract,
                )
            )
            or 0
        )

    @staticmethod
    def _contracts_ending_soon_count(*, days: int = 30) -> int:
        today = date.today()
        end = today + timedelta(days=days)
        return int(
            db.session.scalar(
                select(func.count())
                .select_from(Contract)
                .where(
                    Contract.deleted_at.is_(None),
                    Contract.end_date.is_not(None),
                    Contract.end_date >= today,
                    Contract.end_date <= end,
                    Contract.status.notin_(
                        (
                            ContractStatus.COMPLETED.value,
                            ContractStatus.TERMINATED.value,
                            ContractStatus.REJECTED.value,
                        )
                    ),
                )
            )
            or 0
        )

    @staticmethod
    def _recent_requests(*, limit: int = 8) -> list[dict[str, Any]]:
        rows = db.session.execute(
            select(Request)
            .options(joinedload(Request.status))
            .where(Request.deleted_at.is_(None))
            .order_by(
                func.coalesce(Request.received_at, Request.created_at).desc(),
                Request.created_at.desc(),
            )
            .limit(limit)
        ).scalars().unique().all()
        result = []
        for req in rows:
            status = req.status
            code = (status.code if status else "") or ""
            result.append(
                {
                    "id": req.id,
                    "number": req.number,
                    "address": req.address,
                    "title": req.title,
                    "description": (req.description or req.title or "")[:120],
                    "status_code": code,
                    "status_name": status.name if status else "—",
                    "status_color": getattr(status, "color", None) or "#68717D",
                    "date": req.received_at or req.created_at,
                    "href": f"/requests/{req.id}",
                }
            )
        return result

    @staticmethod
    def _recent_projects(*, limit: int = 5) -> list[dict[str, Any]]:
        rows = (
            db.session.execute(
                select(Project)
                .options(joinedload(Project.work_object))
                .where(Project.deleted_at.is_(None))
                .order_by(Project.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .unique()
            .all()
        )
        result = []
        for p in rows:
            obj = p.work_object
            obj_label = "—"
            if obj is not None:
                obj_label = getattr(obj, "address", None) or getattr(obj, "name", None) or "—"
            result.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "object": obj_label,
                    "status": p.status,
                    "status_label": PROJECT_STATUS_LABELS.get(p.status, p.status),
                    "href": f"/projects/{p.id}",
                }
            )
        return result

    @staticmethod
    def _recent_contracts(*, limit: int = 5) -> list[dict[str, Any]]:
        rows = (
            db.session.execute(
                select(Contract)
                .where(Contract.deleted_at.is_(None))
                .order_by(Contract.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        result = []
        for c in rows:
            amount = c.amount if isinstance(c.amount, Decimal) else Decimal(str(c.amount or 0))
            result.append(
                {
                    "id": c.id,
                    "number": c.number,
                    "contractor": c.contractor_name or "—",
                    "amount": amount,
                    "amount_fmt": f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₽",
                    "end_date": c.end_date,
                    "status": c.status,
                    "status_label": CONTRACT_STATUS_LABELS.get(c.status, c.status),
                    "href": f"/contracts/{c.id}",
                }
            )
        return result

    @staticmethod
    def _quick_actions(user) -> list[QuickAction]:
        actions: list[QuickAction] = []
        if user.has_permission(PERM_REQUESTS_CREATE):
            actions.append(
                QuickAction("create_request", "Создать заявку", "/requests/new", "plus-lg")
            )
        if user.has_permission(PERM_PROJECTS_CREATE):
            actions.append(
                QuickAction("create_project", "Создать проект", "/projects/new", "folder-plus")
            )
        if user.has_permission(PERM_CONTRACTS_CREATE):
            actions.append(
                QuickAction(
                    "create_contract", "Создать контракт", "/contracts/new", "file-earmark-plus"
                )
            )
        if user.has_permission(PERM_OBJECTS_VIEW):
            actions.append(
                QuickAction("find_object", "Найти объект", "/objects/", "geo-alt")
            )
        if user.has_permission(PERM_EIS_VIEW):
            actions.append(QuickAction("eis", "Открыть ЕИС", "/eis/", "cloud-download"))
        return actions
