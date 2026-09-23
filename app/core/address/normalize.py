"""Сравнение адресов: регистр, ё/е и лишние пробелы не создают другой адрес."""

from __future__ import annotations

import re

_SPACE = re.compile(r"\s+")


def fold(text: str | None) -> str:
    return _SPACE.sub(" ", (text or "").casefold().replace("ё", "е").replace("й", "и")).strip()
