"""Кросс-диалектные типы SQLAlchemy (PostgreSQL + SQLite)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, JSON, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PG_UUID


class GUID(TypeDecorator):
    """UUID: PostgreSQL UUID / SQLite CHAR(36)."""

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value) if not isinstance(value, str) else value

    def process_result_value(self, value: Any, dialect) -> uuid.UUID | None:
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONType(TypeDecorator):
    """JSON: PostgreSQL JSONB / SQLite JSON."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class SearchVectorType(TypeDecorator):
    """FTS-вектор: PostgreSQL TSVECTOR / SQLite TEXT (поиск через LIKE)."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(Text())
