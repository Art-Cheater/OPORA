"""Opt-in, parameter-free SQL and request performance profiling."""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator

from flask import Flask, g, has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.extensions import db


_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
_NUMBER_LITERAL = re.compile(r"\b\d+(?:\.\d+)?\b")


def _safe_statement(statement: str, limit: int = 500) -> str:
    """Return compact SQL without parameter values or inline literals."""
    compact = " ".join(str(statement).split())
    compact = _STRING_LITERAL.sub("'?'", compact)
    compact = _NUMBER_LITERAL.sub("?", compact)
    if len(compact) > limit:
        return compact[: limit - 1] + "…"
    return compact


@dataclass
class QueryCounter:
    """Mutable result returned by :func:`count_queries`."""

    count: int = 0
    total_seconds: float = 0.0
    statements: list[str] = field(default_factory=list)


@contextmanager
def count_queries(engine: Engine, *, capture_statements: bool = False) -> Iterator[QueryCounter]:
    """Count SQL statements in a small, explicit block (primarily for tests)."""
    result = QueryCounter()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._opora_query_counter_started_at = perf_counter()

    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started_at = getattr(context, "_opora_query_counter_started_at", None)
        result.count += 1
        if started_at is not None:
            result.total_seconds += perf_counter() - started_at
        if capture_statements:
            result.statements.append(_safe_statement(statement))

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    try:
        yield result
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine, "after_cursor_execute", after_cursor_execute)


def register_performance_profiler(app: Flask) -> None:
    """Register request-local SQL timings when explicitly enabled."""
    if not app.config.get("PERFORMANCE_PROFILER_ENABLED", False):
        return
    if app.extensions.get("opora_performance_profiler"):
        return

    with app.app_context():
        engine = db.engine
    slow_query_seconds = float(app.config.get("PERFORMANCE_SLOW_QUERY_MS", 100)) / 1000

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._opora_profiler_started_at = perf_counter()

    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started_at = getattr(context, "_opora_profiler_started_at", None)
        if started_at is None:
            return
        duration = perf_counter() - started_at
        if has_request_context() and hasattr(g, "_opora_performance"):
            profile = g._opora_performance
            profile["query_count"] += 1
            profile["db_seconds"] += duration
        if duration >= slow_query_seconds:
            app.logger.warning(
                "Slow SQL duration_ms=%.1f statement=%s",
                duration * 1000,
                _safe_statement(statement),
            )

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    app.extensions["opora_performance_profiler"] = {
        "engine": engine,
        "before_cursor_execute": before_cursor_execute,
        "after_cursor_execute": after_cursor_execute,
    }

    @app.before_request
    def _start_performance_profile() -> None:
        g._opora_performance = {
            "started_at": perf_counter(),
            "query_count": 0,
            "db_seconds": 0.0,
        }

    @app.after_request
    def _finish_performance_profile(response):
        profile = getattr(g, "_opora_performance", None)
        if profile is None:
            return response

        duration_ms = (perf_counter() - profile["started_at"]) * 1000
        db_ms = profile["db_seconds"] * 1000
        query_count = profile["query_count"]

        if app.config.get("PERFORMANCE_PROFILER_RESPONSE_HEADERS", False):
            response.headers["X-Performance-Duration-Ms"] = f"{duration_ms:.1f}"
            response.headers["X-Performance-Db-Ms"] = f"{db_ms:.1f}"
            response.headers["X-Performance-Queries"] = str(query_count)

        slow_request_ms = float(app.config.get("PERFORMANCE_SLOW_REQUEST_MS", 500))
        query_warning = int(app.config.get("PERFORMANCE_QUERY_COUNT_WARNING", 30))
        if (
            app.config.get("PERFORMANCE_PROFILER_LOG_ALL", False)
            or duration_ms >= slow_request_ms
            or query_count >= query_warning
        ):
            app.logger.warning(
                "Request performance method=%s path=%s status=%s duration_ms=%.1f "
                "db_ms=%.1f queries=%s",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                db_ms,
                query_count,
            )
        return response
