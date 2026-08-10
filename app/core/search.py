"""Утилиты полнотекстового поиска (PostgreSQL FTS / SQLite LIKE)."""

from __future__ import annotations

import re

from sqlalchemy import func, or_

from app.extensions import db

MIN_QUERY_LENGTH = 2
DEFAULT_LIMIT = 10
FTS_RUSSIAN = "russian"
FTS_SIMPLE = "simple"

# QWERTY ↔ ЙЦУКЕН (когда забыли сменить раскладку)
_EN = "`qwertyuiop[]asdfghjkl;'zxcvbnm,./~QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?"
_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю.ЁЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,"
EN_TO_RU = str.maketrans(_EN, _RU)
RU_TO_EN = str.maketrans(_RU, _EN)


def normalize_query(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", (raw or "").strip())
    return cleaned


def is_valid_query(query: str) -> bool:
    return len(normalize_query(query)) >= MIN_QUERY_LENGTH


def is_postgres() -> bool:
    return db.engine.dialect.name == "postgresql"


def flip_layout(text: str) -> tuple[str, str]:
    """Возвращает (как будто печатали EN→RU, как будто RU→EN)."""
    return text.translate(EN_TO_RU), text.translate(RU_TO_EN)


def query_variants(raw: str) -> list[str]:
    """Варианты запроса: регистр + обе раскладки."""
    q = normalize_query(raw)
    if not q:
        return []

    variants: set[str] = set()
    seeds = {q}
    en_as_ru, ru_as_en = flip_layout(q)
    seeds.add(en_as_ru)
    seeds.add(ru_as_en)

    for seed in seeds:
        if not seed:
            continue
        variants.add(seed)
        variants.add(seed.lower())
        variants.add(seed.casefold())
        # Первая заглавная (фамилии)
        if len(seed) > 1:
            variants.add(seed[:1].upper() + seed[1:].lower())
            variants.add(seed.capitalize())

    return [v for v in variants if len(v) >= MIN_QUERY_LENGTH]


def build_tsquery(query: str):
    """FTS-запрос с учётом вариантов раскладки/регистра."""
    parts = []
    for variant in query_variants(query):
        parts.append(func.websearch_to_tsquery(FTS_RUSSIAN, variant))
        parts.append(func.websearch_to_tsquery(FTS_SIMPLE, variant))
    if not parts:
        return func.websearch_to_tsquery(FTS_SIMPLE, normalize_query(query) or "x")
    combined = parts[0]
    for part in parts[1:]:
        combined = combined.op("||")(part)
    return combined


def ts_rank(search_vector, tsquery):
    return func.ts_rank_cd(search_vector, tsquery, 32)


def like_pattern(query: str) -> str:
    return f"%{normalize_query(query)}%"


def like_patterns(query: str) -> list[str]:
    return [f"%{v}%" for v in query_variants(query)]


def _column_matches(col, pattern: str):
    """Регистронезависимое сравнение колонки с шаблоном."""
    if is_postgres():
        return col.ilike(pattern)
    # SQLite: LOWER() не трогает кириллицу — полагаемся на варианты регистра в patterns
    return col.like(pattern)


def like_or(*columns, pattern: str | None = None, patterns: list[str] | None = None):
    """OR по нескольким колонкам (ILIKE / lower+LIKE) и вариантам запроса."""
    pats = list(patterns or [])
    if pattern:
        pats.append(pattern)
    if not pats:
        return True

    clauses = []
    for col in columns:
        if col is None:
            continue
        for pat in pats:
            clauses.append(_column_matches(col, pat))
    return or_(*clauses) if clauses else True
