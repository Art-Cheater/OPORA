"""Репозиторий глобального поиска (PostgreSQL FTS / SQLite LIKE)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select

from app.core.search import (
    DEFAULT_LIMIT,
    build_tsquery,
    is_postgres,
    like_or,
    like_patterns,
    normalize_query,
    ts_rank,
)
from app.extensions import db
from app.models.auth.user import User
from app.models.contracts.contract import Contract
from app.models.projects.project import Project
from app.models.projects.project_member import ProjectMember
from app.models.requests.request import Request


@dataclass
class SearchHit:
    id: uuid.UUID
    title: str
    subtitle: str
    url: str
    rank: float
    meta: dict | None = None


class SearchRepository:
    """Поиск по сущностям системы."""

    @staticmethod
    def _fts_filter(model, tsquery):
        return model.search_vector.op("@@")(tsquery)

    @classmethod
    def search_requests(cls, query: str, *, limit: int = DEFAULT_LIMIT) -> list[SearchHit]:
        if is_postgres():
            tsquery = build_tsquery(query)
            rank_expr = ts_rank(Request.search_vector, tsquery).label("rank")
            stmt = (
                select(Request, rank_expr)
                .where(Request.active_filter(), cls._fts_filter(Request, tsquery))
                .order_by(rank_expr.desc(), Request.updated_at.desc())
                .limit(limit)
            )
            rows = db.session.execute(stmt)
            return [
                SearchHit(
                    id=req.id,
                    title=f"{req.number} — {req.title}",
                    subtitle=req.address,
                    url=f"/requests/{req.id}",
                    rank=float(rank or 0),
                    meta={"number": req.number, "address": req.address},
                )
                for req, rank in rows
            ]

        patterns = like_patterns(query)
        stmt = (
            select(Request)
            .where(
                Request.active_filter(),
                like_or(
                    Request.number,
                    Request.title,
                    Request.address,
                    Request.applicant_name,
                    Request.description,
                    Request.phone,
                    patterns=patterns,
                ),
            )
            .order_by(Request.updated_at.desc())
            .limit(limit)
        )
        return [
            SearchHit(
                id=req.id,
                title=f"{req.number} — {req.title}",
                subtitle=req.address,
                url=f"/requests/{req.id}",
                rank=1.0,
                meta={"number": req.number, "address": req.address},
            )
            for req in db.session.scalars(stmt)
        ]

    @classmethod
    def search_projects(cls, query: str, *, limit: int = DEFAULT_LIMIT) -> list[SearchHit]:
        if is_postgres():
            tsquery = build_tsquery(query)
            rank_expr = ts_rank(Project.search_vector, tsquery).label("rank")
            stmt = (
                select(Project, rank_expr)
                .where(Project.active_filter(), cls._fts_filter(Project, tsquery))
                .order_by(rank_expr.desc(), Project.updated_at.desc())
                .limit(limit)
            )
            return [
                SearchHit(
                    id=project.id,
                    title=f"{project.code} — {project.name}",
                    subtitle=project.description or "",
                    url=f"/projects/{project.id}",
                    rank=float(rank or 0),
                    meta={"code": project.code},
                )
                for project, rank in db.session.execute(stmt)
            ]

        patterns = like_patterns(query)
        stmt = (
            select(Project)
            .where(
                Project.active_filter(),
                like_or(Project.code, Project.name, Project.description, patterns=patterns),
            )
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
        return [
            SearchHit(
                id=project.id,
                title=f"{project.code} — {project.name}",
                subtitle=project.description or "",
                url=f"/projects/{project.id}",
                rank=1.0,
                meta={"code": project.code},
            )
            for project in db.session.scalars(stmt)
        ]

    @classmethod
    def search_contracts(cls, query: str, *, limit: int = DEFAULT_LIMIT) -> list[SearchHit]:
        if is_postgres():
            tsquery = build_tsquery(query)
            rank_expr = ts_rank(Contract.search_vector, tsquery).label("rank")
            stmt = (
                select(Contract, rank_expr)
                .where(Contract.active_filter(), cls._fts_filter(Contract, tsquery))
                .order_by(rank_expr.desc(), Contract.updated_at.desc())
                .limit(limit)
            )
            return [
                SearchHit(
                    id=contract.id,
                    title=f"{contract.number} — {contract.title}",
                    subtitle=contract.description or "",
                    url=f"/contracts/{contract.id}",
                    rank=float(rank or 0),
                    meta={"number": contract.number},
                )
                for contract, rank in db.session.execute(stmt)
            ]

        patterns = like_patterns(query)
        stmt = (
            select(Contract)
            .where(
                Contract.active_filter(),
                like_or(Contract.number, Contract.title, Contract.description, patterns=patterns),
            )
            .order_by(Contract.updated_at.desc())
            .limit(limit)
        )
        return [
            SearchHit(
                id=contract.id,
                title=f"{contract.number} — {contract.title}",
                subtitle=contract.description or "",
                url=f"/contracts/{contract.id}",
                rank=1.0,
                meta={"number": contract.number},
            )
            for contract in db.session.scalars(stmt)
        ]

    @classmethod
    def search_users(cls, query: str, *, limit: int = DEFAULT_LIMIT) -> list[SearchHit]:
        if is_postgres():
            tsquery = build_tsquery(query)
            rank_expr = ts_rank(User.search_vector, tsquery).label("rank")
            stmt = (
                select(User, rank_expr)
                .where(
                    User.active_filter(),
                    User.is_active.is_(True),
                    User.is_blocked.is_(False),
                    cls._fts_filter(User, tsquery),
                )
                .order_by(rank_expr.desc(), User.full_name.asc())
                .limit(limit)
            )
            hits: list[SearchHit] = []
            for user, rank in db.session.execute(stmt):
                subtitle = " · ".join(filter(None, [user.position, user.department, user.email]))
                hits.append(
                    SearchHit(
                        id=user.id,
                        title=user.full_name,
                        subtitle=subtitle,
                        url=f"/employees/{user.id}",
                        rank=float(rank or 0),
                        meta={"email": user.email},
                    )
                )
            # Дополнительно LIKE по вариантам раскладки (на случай пустого search_vector)
            patterns = like_patterns(query)
            extra_ids = {h.id for h in hits}
            for user in db.session.scalars(
                select(User)
                .where(
                    User.active_filter(),
                    User.is_active.is_(True),
                    User.is_blocked.is_(False),
                    like_or(
                        User.full_name,
                        User.email,
                        User.phone,
                        User.department,
                        User.position,
                        patterns=patterns,
                    ),
                    ~User.id.in_(extra_ids) if extra_ids else True,
                )
                .order_by(User.full_name.asc())
                .limit(limit)
            ):
                subtitle = " · ".join(filter(None, [user.position, user.department, user.email]))
                hits.append(
                    SearchHit(
                        id=user.id,
                        title=user.full_name,
                        subtitle=subtitle,
                        url=f"/employees/{user.id}",
                        rank=0.9,
                        meta={"email": user.email},
                    )
                )
            return hits[:limit]

        patterns = like_patterns(query)
        stmt = (
            select(User)
            .where(
                User.active_filter(),
                User.is_active.is_(True),
                User.is_blocked.is_(False),
                like_or(
                    User.full_name,
                    User.email,
                    User.phone,
                    User.department,
                    User.position,
                    patterns=patterns,
                ),
            )
            .order_by(User.full_name.asc())
            .limit(limit)
        )
        hits = []
        for user in db.session.scalars(stmt):
            subtitle = " · ".join(filter(None, [user.position, user.department, user.email]))
            hits.append(
                SearchHit(
                    id=user.id,
                    title=user.full_name,
                    subtitle=subtitle,
                    url=f"/employees/{user.id}",
                    rank=1.0,
                    meta={"email": user.email},
                )
            )
        return hits

    @classmethod
    def search_related_to_users(
        cls,
        user_ids: list[uuid.UUID],
        *,
        names: dict[uuid.UUID, str] | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, list[SearchHit]]:
        """Связанные заявки/проекты/контракты по найденным людям."""
        if not user_ids:
            return {"requests": [], "projects": [], "contracts": []}

        names = names or {}
        result: dict[str, list[SearchHit]] = {
            "requests": [],
            "projects": [],
            "contracts": [],
        }

        def person_label(uid: uuid.UUID | None) -> str:
            if uid is None:
                return ""
            return names.get(uid) or "сотрудник"

        for req in db.session.scalars(
            select(Request)
            .where(
                Request.active_filter(),
                or_(
                    Request.responsible_id.in_(user_ids),
                    Request.executor_id.in_(user_ids),
                ),
            )
            .order_by(Request.updated_at.desc())
            .limit(limit)
        ):
            who = []
            if req.responsible_id in user_ids:
                who.append(f"ответственный: {person_label(req.responsible_id)}")
            if req.executor_id in user_ids:
                who.append(f"исполнитель: {person_label(req.executor_id)}")
            subtitle = " · ".join(who)
            if req.address:
                subtitle = f"{subtitle} · {req.address}" if subtitle else req.address
            result["requests"].append(
                SearchHit(
                    id=req.id,
                    title=f"{req.number} — {req.title}",
                    subtitle=subtitle,
                    url=f"/requests/{req.id}",
                    rank=0.85,
                    meta={"related_user": True},
                )
            )

        member_project_ids = list(
            db.session.scalars(
                select(ProjectMember.project_id).where(
                    ProjectMember.active_filter(),
                    ProjectMember.user_id.in_(user_ids),
                )
            ).all()
        )
        project_filter = Project.manager_id.in_(user_ids)
        if member_project_ids:
            project_filter = or_(project_filter, Project.id.in_(member_project_ids))

        for project in db.session.scalars(
            select(Project)
            .where(Project.active_filter(), project_filter)
            .order_by(Project.updated_at.desc())
            .limit(limit)
        ):
            if project.manager_id in user_ids:
                role = f"руководитель: {person_label(project.manager_id)}"
            else:
                role = "участник проекта"
            result["projects"].append(
                SearchHit(
                    id=project.id,
                    title=f"{project.code} — {project.name}",
                    subtitle=role,
                    url=f"/projects/{project.id}",
                    rank=0.85,
                    meta={"related_user": True},
                )
            )

        for contract in db.session.scalars(
            select(Contract)
            .where(
                Contract.active_filter(),
                Contract.responsible_id.in_(user_ids),
            )
            .order_by(Contract.updated_at.desc())
            .limit(limit)
        ):
            result["contracts"].append(
                SearchHit(
                    id=contract.id,
                    title=f"{contract.number} — {contract.title}",
                    subtitle=f"ответственный: {person_label(contract.responsible_id)}",
                    url=f"/contracts/{contract.id}",
                    rank=0.85,
                    meta={"related_user": True},
                )
            )

        return result

    @classmethod
    def search_addresses(cls, query: str, *, limit: int = DEFAULT_LIMIT) -> list[SearchHit]:
        patterns = like_patterns(query)
        if is_postgres():
            tsquery = build_tsquery(query)
            rank_expr = ts_rank(Request.search_vector, tsquery).label("rank")
            stmt = (
                select(Request, rank_expr)
                .where(
                    Request.active_filter(),
                    or_(
                        cls._fts_filter(Request, tsquery),
                        like_or(Request.address, patterns=patterns),
                    ),
                    Request.address.isnot(None),
                    Request.address != "",
                )
                .order_by(rank_expr.desc(), Request.address.asc())
                .limit(limit * 3)
            )
            rows = db.session.execute(stmt)
        else:
            stmt = (
                select(Request)
                .where(
                    Request.active_filter(),
                    like_or(Request.address, patterns=patterns),
                    Request.address.isnot(None),
                    Request.address != "",
                )
                .order_by(Request.address.asc())
                .limit(limit * 3)
            )
            rows = ((req, 1.0) for req in db.session.scalars(stmt))

        seen: set[str] = set()
        hits: list[SearchHit] = []
        for req, rank in rows:
            if req.address in seen:
                continue
            seen.add(req.address)
            hits.append(
                SearchHit(
                    id=req.id,
                    title=req.address,
                    subtitle=f"Заявка {req.number}: {req.title}",
                    url=f"/requests/{req.id}",
                    rank=float(rank or 0),
                    meta={"request_id": str(req.id), "number": req.number},
                )
            )
            if len(hits) >= limit:
                break
        return hits

    @classmethod
    def search_numbers(cls, query: str, *, limit: int = DEFAULT_LIMIT) -> list[SearchHit]:
        hits: list[SearchHit] = []
        patterns = like_patterns(query)
        q = normalize_query(query)

        if is_postgres():
            tsquery = build_tsquery(q)
            for row, rank in db.session.execute(
                select(Request, ts_rank(Request.search_vector, tsquery).label("rank"))
                .where(
                    Request.active_filter(),
                    or_(
                        cls._fts_filter(Request, tsquery),
                        like_or(Request.number, patterns=patterns),
                    ),
                )
                .order_by(ts_rank(Request.search_vector, tsquery).desc())
                .limit(limit)
            ):
                hits.append(
                    SearchHit(
                        id=row.id,
                        title=row.number,
                        subtitle=f"Заявка: {row.title}",
                        url=f"/requests/{row.id}",
                        rank=float(rank or 0),
                        meta={"type": "request"},
                    )
                )
            for row, rank in db.session.execute(
                select(Project, ts_rank(Project.search_vector, tsquery).label("rank"))
                .where(
                    Project.active_filter(),
                    or_(
                        cls._fts_filter(Project, tsquery),
                        like_or(Project.code, patterns=patterns),
                    ),
                )
                .order_by(ts_rank(Project.search_vector, tsquery).desc())
                .limit(limit)
            ):
                hits.append(
                    SearchHit(
                        id=row.id,
                        title=row.code,
                        subtitle=f"Проект: {row.name}",
                        url=f"/projects/{row.id}",
                        rank=float(rank or 0),
                        meta={"type": "project"},
                    )
                )
            for row, rank in db.session.execute(
                select(Contract, ts_rank(Contract.search_vector, tsquery).label("rank"))
                .where(
                    Contract.active_filter(),
                    or_(
                        cls._fts_filter(Contract, tsquery),
                        like_or(Contract.number, patterns=patterns),
                    ),
                )
                .order_by(ts_rank(Contract.search_vector, tsquery).desc())
                .limit(limit)
            ):
                hits.append(
                    SearchHit(
                        id=row.id,
                        title=row.number,
                        subtitle=f"Контракт: {row.title}",
                        url=f"/contracts/{row.id}",
                        rank=float(rank or 0),
                        meta={"type": "contract"},
                    )
                )
        else:
            for row in db.session.scalars(
                select(Request)
                .where(Request.active_filter(), like_or(Request.number, patterns=patterns))
                .limit(limit)
            ):
                hits.append(
                    SearchHit(
                        id=row.id,
                        title=row.number,
                        subtitle=f"Заявка: {row.title}",
                        url=f"/requests/{row.id}",
                        rank=1.0,
                        meta={"type": "request"},
                    )
                )
            for row in db.session.scalars(
                select(Project)
                .where(Project.active_filter(), like_or(Project.code, patterns=patterns))
                .limit(limit)
            ):
                hits.append(
                    SearchHit(
                        id=row.id,
                        title=row.code,
                        subtitle=f"Проект: {row.name}",
                        url=f"/projects/{row.id}",
                        rank=1.0,
                        meta={"type": "project"},
                    )
                )
            for row in db.session.scalars(
                select(Contract)
                .where(Contract.active_filter(), like_or(Contract.number, patterns=patterns))
                .limit(limit)
            ):
                hits.append(
                    SearchHit(
                        id=row.id,
                        title=row.number,
                        subtitle=f"Контракт: {row.title}",
                        url=f"/contracts/{row.id}",
                        rank=1.0,
                        meta={"type": "contract"},
                    )
                )

            hits.sort(key=lambda h: h.rank, reverse=True)
        return hits[:limit]

    @classmethod
    def search_custom_fields(cls, query: str, user, *, limit: int = DEFAULT_LIMIT) -> list[SearchHit]:
        from app.core.custom_field_service import CustomFieldService

        raw = CustomFieldService.search_hits(query, user, limit=limit)
        return [
            SearchHit(
                id=uuid.UUID(item["id"]),
                title=item["title"],
                subtitle=item["subtitle"],
                url=item["url"],
                rank=item["rank"],
                meta=item.get("meta"),
            )
            for item in raw
        ]
