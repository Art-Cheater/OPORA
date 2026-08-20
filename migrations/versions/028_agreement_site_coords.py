"""Координаты строк адресной программы договоров на опорах.

Revision ID: 028_agreement_site_coords
Revises: 027_pole_agreements
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "028_agreement_site_coords"
down_revision = "027_pole_agreements"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("pole_agreement_sites", "latitude"):
        op.add_column("pole_agreement_sites", sa.Column("latitude", sa.Numeric(10, 7), nullable=True))
    if not _has_column("pole_agreement_sites", "longitude"):
        op.add_column("pole_agreement_sites", sa.Column("longitude", sa.Numeric(10, 7), nullable=True))


def downgrade() -> None:
    if _has_column("pole_agreement_sites", "longitude"):
        op.drop_column("pole_agreement_sites", "longitude")
    if _has_column("pole_agreement_sites", "latitude"):
        op.drop_column("pole_agreement_sites", "latitude")
