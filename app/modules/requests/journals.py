"""Справочник журналов заявок."""

from __future__ import annotations

JOURNAL_MAIN = "requests"
JOURNAL_OKTYABRSKY_VILLAGES = "oktyabrsky_villages"
JOURNAL_NOVOVYATSKY_VILLAGES = "novovyatsky_villages"
JOURNAL_LENINSKY_VILLAGES = "leninsky_villages"

# (code, name, sort_order)
REQUEST_JOURNALS: tuple[tuple[str, str, int], ...] = (
    (JOURNAL_MAIN, "Заявки", 10),
    (JOURNAL_OKTYABRSKY_VILLAGES, "Заявки в деревнях Октябрьского района", 20),
    (JOURNAL_NOVOVYATSKY_VILLAGES, "Заявки в деревнях Нововятского района", 30),
    (JOURNAL_LENINSKY_VILLAGES, "Заявки в деревнях Ленинского района", 40),
)
