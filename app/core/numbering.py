"""Порядковые номера вида PREFIX-YY-N."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select

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
