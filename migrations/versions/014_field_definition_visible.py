"""Добавление is_visible для встроенных полей (FieldDefinition).

Revision ID: 014_field_definition_visible
Revises: 013_request_workflow_statuses
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014_field_definition_visible"
down_revision = "013_request_workflow_statuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fields",
        sa.Column(
            "is_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("fields", "is_visible")
