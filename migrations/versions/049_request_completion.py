"""Store the single completion record attached to a Request.

Revision ID: 049_request_completion
Revises: 048_work_map_points
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID


revision = "049_request_completion"
down_revision = "048_work_map_points"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    names = {column["name"] for column in inspector.get_columns("requests")}
    additions = (
        ("completion_at", sa.Column("completion_at", sa.DateTime(timezone=True), nullable=True)),
        ("completion_by_id", sa.Column("completion_by_id", GUID(), nullable=True)),
        ("completion_form_number", sa.Column("completion_form_number", sa.String(length=100), nullable=True)),
        ("completion_description", sa.Column("completion_description", sa.Text(), nullable=True)),
    )
    for name, column in additions:
        if name not in names:
            op.add_column("requests", column)
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("requests")}
    if op.get_bind().dialect.name != "sqlite" and "fk_requests_completion_by_users" not in foreign_keys:
        op.create_foreign_key(
            "fk_requests_completion_by_users",
            "requests",
            "users",
            ["completion_by_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("requests")}
    if op.get_bind().dialect.name != "sqlite" and "fk_requests_completion_by_users" in foreign_keys:
        op.drop_constraint("fk_requests_completion_by_users", "requests", type_="foreignkey")
    names = {column["name"] for column in inspector.get_columns("requests")}
    for name in ("completion_description", "completion_form_number", "completion_by_id", "completion_at"):
        if name in names:
            op.drop_column("requests", name)
