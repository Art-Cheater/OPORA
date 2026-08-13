"""Структурированные поля адреса заявок.

Revision ID: 022_request_address_metadata
Revises: 021_object_kind_court
Create Date: 2026-08-13
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "022_request_address_metadata"
down_revision = "021_object_kind_court"
branch_labels = None
depends_on = None


ADDRESS_COLUMNS = (
    ("original_address", sa.Column("original_address", sa.String(length=500), nullable=True)),
    ("normalized_address", sa.Column("normalized_address", sa.String(length=1000), nullable=True)),
    ("region", sa.Column("region", sa.String(length=255), nullable=True)),
    ("district", sa.Column("district", sa.String(length=255), nullable=True)),
    ("settlement", sa.Column("settlement", sa.String(length=255), nullable=True)),
    ("street", sa.Column("street", sa.String(length=500), nullable=True)),
    ("house", sa.Column("house", sa.String(length=100), nullable=True)),
    ("address_source", sa.Column("address_source", sa.String(length=50), nullable=True)),
    ("address_external_id", sa.Column("address_external_id", sa.String(length=255), nullable=True)),
)

HIDDEN_ADDRESS_FIELDS = {
    "original_address",
    "normalized_address",
    "region",
    "settlement",
    "street",
    "house",
    "address_source",
    "address_external_id",
}

FIELD_ROWS = (
    ("original_address", "Исходный адрес", 940),
    ("normalized_address", "Нормализованный адрес", 950),
    ("region", "Регион адреса", 960),
    ("district", "Район", 22),
    ("settlement", "Населённый пункт", 980),
    ("street", "Улица", 990),
    ("house", "Дом", 1000),
    ("address_source", "Источник адреса", 1010),
    ("address_external_id", "Внешний ID адреса", 1020),
)


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def _indexes(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _columns("requests")
    for name, column in ADDRESS_COLUMNS:
        if name not in cols:
            op.add_column("requests", column)

    indexes = _indexes("requests")
    if "ix_requests_district" not in indexes:
        op.create_index("ix_requests_district", "requests", ["district"])
    if "ix_requests_settlement" not in indexes:
        op.create_index("ix_requests_settlement", "requests", ["settlement"])

    bind = op.get_bind()
    module_id = bind.execute(
        sa.text(
            "SELECT id FROM modules WHERE code = 'requests' AND deleted_at IS NULL LIMIT 1"
        )
    ).scalar()
    if module_id is None:
        return

    now = datetime.now(timezone.utc)
    for code, name, sort_order in FIELD_ROWS:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM fields WHERE module_id = :mid AND code = :code "
                "AND deleted_at IS NULL LIMIT 1"
            ),
            {"mid": str(module_id), "code": code},
        ).scalar()
        visible = code not in HIDDEN_ADDRESS_FIELDS
        if exists:
            bind.execute(
                sa.text(
                    """
                    UPDATE fields
                    SET name = :name, sort_order = :sort_order, is_visible = :is_visible
                    WHERE module_id = :mid AND code = :code AND deleted_at IS NULL
                    """
                ),
                {
                    "mid": str(module_id),
                    "code": code,
                    "name": name,
                    "sort_order": sort_order,
                    "is_visible": visible,
                },
            )
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO fields (
                    id, created_at, updated_at, created_by, updated_by, deleted_at,
                    module_id, code, name, sort_order, is_visible
                ) VALUES (
                    :id, :created_at, :updated_at, NULL, NULL, NULL,
                    :module_id, :code, :name, :sort_order, :is_visible
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "created_at": now,
                "updated_at": now,
                "module_id": str(module_id),
                "code": code,
                "name": name,
                "sort_order": sort_order,
                "is_visible": visible,
            },
        )


def downgrade() -> None:
    indexes = _indexes("requests")
    if "ix_requests_settlement" in indexes:
        op.drop_index("ix_requests_settlement", table_name="requests")
    if "ix_requests_district" in indexes:
        op.drop_index("ix_requests_district", table_name="requests")

    cols = _columns("requests")
    for name, _column in reversed(ADDRESS_COLUMNS):
        if name in cols:
            op.drop_column("requests", name)
