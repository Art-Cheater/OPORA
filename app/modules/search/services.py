"""Сервис глобального поиска."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from flask_login import AnonymousUserMixin

from app.core.search import DEFAULT_LIMIT, is_valid_query, normalize_query
from app.models.auth.constants import (
    PERM_CONTRACTS_VIEW,
    PERM_PROJECTS_VIEW,
    PERM_REQUESTS_VIEW,
    PERM_USERS_VIEW,
)
from app.modules.search.repositories import SearchHit, SearchRepository


@dataclass
class SearchCategory:
    key: str
    label: str
    icon: str
    hits: list[dict] = field(default_factory=list)
    total: int = 0


@dataclass
class SearchResponse:
    query: str
    took_ms: int
    categories: list[SearchCategory]
    total: int


class SearchService:
    """Единый поиск с категориями и проверкой прав."""

    CATEGORIES = (
        ("requests", "Заявки", "clipboard-check", PERM_REQUESTS_VIEW, SearchRepository.search_requests),
        ("projects", "Проекты", "folder2-open", PERM_PROJECTS_VIEW, SearchRepository.search_projects),
        ("contracts", "Контракты", "file-earmark-text", PERM_CONTRACTS_VIEW, SearchRepository.search_contracts),
        ("users", "Пользователи", "people", PERM_USERS_VIEW, SearchRepository.search_users),
        ("addresses", "Адреса", "geo-alt", PERM_REQUESTS_VIEW, SearchRepository.search_addresses),
        ("numbers", "Номера", "hash", None, SearchRepository.search_numbers),
        ("custom_fields", "Доп. поля", "ui-radios", None, SearchRepository.search_custom_fields),
    )

    _LABELS = {key: (label, icon) for key, label, icon, _, _ in CATEGORIES}

    @classmethod
    def _can(cls, user, permission: str | None) -> bool:
        if permission is None:
            return True
        if isinstance(user, AnonymousUserMixin):
            return False
        return user.has_permission(permission)

    @classmethod
    def _serialize_hit(cls, hit: SearchHit) -> dict:
        return {
            "id": str(hit.id),
            "title": hit.title,
            "subtitle": hit.subtitle,
            "url": hit.url,
            "rank": round(hit.rank, 4),
            "meta": hit.meta or {},
        }

    @classmethod
    def _merge_hits(
        cls,
        buckets: dict[str, list[dict]],
        key: str,
        new_hits: list[SearchHit],
        *,
        limit: int,
    ) -> None:
        if not new_hits:
            return
        existing = buckets.setdefault(key, [])
        seen = {item["id"] for item in existing}
        for hit in new_hits:
            sid = str(hit.id)
            if sid in seen:
                continue
            existing.append(cls._serialize_hit(hit))
            seen.add(sid)
            if len(existing) >= limit * 2:
                break

    @classmethod
    def search(cls, user, raw_query: str, *, limit: int = DEFAULT_LIMIT) -> SearchResponse:
        query = normalize_query(raw_query)
        if not is_valid_query(query):
            return SearchResponse(query=query, took_ms=0, categories=[], total=0)

        started = time.perf_counter()
        buckets: dict[str, list[dict]] = {}
        user_hits: list[SearchHit] = []

        for key, label, icon, permission, searcher in cls.CATEGORIES:
            if not cls._can(user, permission):
                continue

            if key == "numbers":
                if not (
                    cls._can(user, PERM_REQUESTS_VIEW)
                    or cls._can(user, PERM_PROJECTS_VIEW)
                    or cls._can(user, PERM_CONTRACTS_VIEW)
                ):
                    continue

            if key == "custom_fields":
                if not (
                    cls._can(user, PERM_REQUESTS_VIEW)
                    or cls._can(user, PERM_PROJECTS_VIEW)
                    or cls._can(user, PERM_CONTRACTS_VIEW)
                    or cls._can(user, PERM_USERS_VIEW)
                ):
                    continue
                hits = searcher(query, user, limit=limit)
            else:
                hits = searcher(query, limit=limit)

            if key == "users":
                user_hits = list(hits)

            if hits:
                buckets[key] = [cls._serialize_hit(h) for h in hits]

        # По фамилии/ФИО — подтянуть связанные заявки, проекты, контракты
        if user_hits and (
            cls._can(user, PERM_REQUESTS_VIEW)
            or cls._can(user, PERM_PROJECTS_VIEW)
            or cls._can(user, PERM_CONTRACTS_VIEW)
        ):
            ids = [h.id for h in user_hits]
            names = {h.id: h.title for h in user_hits}
            related = SearchRepository.search_related_to_users(
                ids, names=names, limit=max(limit, 8)
            )
            if cls._can(user, PERM_REQUESTS_VIEW):
                cls._merge_hits(buckets, "requests", related.get("requests", []), limit=limit)
            if cls._can(user, PERM_PROJECTS_VIEW):
                cls._merge_hits(buckets, "projects", related.get("projects", []), limit=limit)
            if cls._can(user, PERM_CONTRACTS_VIEW):
                cls._merge_hits(buckets, "contracts", related.get("contracts", []), limit=limit)

        # Стабильный порядок категорий как в CATEGORIES
        categories: list[SearchCategory] = []
        total = 0
        for key, label, icon, _, _ in cls.CATEGORIES:
            items = buckets.get(key) or []
            if not items:
                continue
            categories.append(
                SearchCategory(key=key, label=label, icon=icon, hits=items, total=len(items))
            )
            total += len(items)

        took_ms = int((time.perf_counter() - started) * 1000)
        return SearchResponse(query=query, took_ms=took_ms, categories=categories, total=total)

    @classmethod
    def to_dict(cls, response: SearchResponse) -> dict:
        return {
            "query": response.query,
            "took_ms": response.took_ms,
            "total": response.total,
            "categories": [
                {
                    "key": cat.key,
                    "label": cat.label,
                    "icon": cat.icon,
                    "total": cat.total,
                    "hits": cat.hits,
                }
                for cat in response.categories
            ],
        }
