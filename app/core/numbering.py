"""Порядковые номера вида PREFIX-YY-N."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import Integer, case, cast, func, select

from app.extensions import db


def next_prefixed_number(model, prefix: str, *, column=None) -> str:
    """Следующий номер PREFIX-YY-N, учитывая и soft-deleted строки."""
    year_yy = datetime.now().year % 100
    token = f"{prefix}-{year_yy}-"
    pattern = re.compile(rf"^{re.escape(prefix)}-{year_yy}-(\d+)$")
    number_col = column if column is not None else model.number
    numbers = db.session.scalars(
        select(number_col).where(number_col.like(f"{token}%"))
    ).all()
    max_seq = 0
    for raw in numbers:
        match = pattern.fullmatch((raw or "").strip())
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    return f"{token}{max_seq + 1}"


def sql_number_sort_keys(number_col):
    """Год и порядковый номер для 26-15 / DF-26-15 / REQ-2025-001 без CAST-ошибок."""
    dialect = db.session.get_bind().dialect.name

    def as_int(expr):
        if dialect == "postgresql":
            return case((expr.op("~")("^[0-9]+$"), cast(expr, Integer)), else_=0)
        return func.coalesce(cast(expr, Integer), 0)

    if dialect == "postgresql":
        part1 = func.split_part(number_col, "-", 1)
        part2 = func.split_part(number_col, "-", 2)
        part3 = func.split_part(number_col, "-", 3)
        year_expr = as_int(case((part3 != "", part2), else_=part1))
        seq_expr = as_int(case((part3 != "", part3), else_=part2))
    else:
        dash1 = func.instr(number_col, "-")
        rest = func.substr(number_col, dash1 + 1)
        dash2 = func.instr(rest, "-")
        year_expr = as_int(
            case(
                (dash2 > 0, func.substr(rest, 1, dash2 - 1)),
                else_=func.substr(number_col, 1, dash1 - 1),
            )
        )
        seq_expr = as_int(
            case(
                (dash2 > 0, func.substr(rest, dash2 + 1)),
                else_=rest,
            )
        )
    return year_expr, seq_expr, number_col
