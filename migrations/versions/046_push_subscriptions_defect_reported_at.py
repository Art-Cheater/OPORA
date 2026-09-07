"""Web Push subscriptions and optional legacy-safe Defect report date/time.

Revision ID: 046_push_subscriptions_defect_reported_at
Revises: 045_contract_projects
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op
from app.models.types import GUID

revision = "046_push_subscriptions_defect_reported_at"
down_revision = "045_contract_projects"
branch_labels = None
depends_on = None

def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "push_subscriptions" not in tables:
        op.create_table("push_subscriptions", sa.Column("id", GUID(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_by", GUID()), sa.Column("updated_by", GUID()), sa.Column("deleted_at", sa.DateTime(timezone=True)), sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("endpoint", sa.Text(), nullable=False), sa.Column("p256dh", sa.Text(), nullable=False), sa.Column("auth", sa.Text(), nullable=False), sa.Column("user_agent", sa.String(500)), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("last_used_at", sa.DateTime(timezone=True)))
        op.create_index("uq_push_subscriptions_endpoint", "push_subscriptions", ["endpoint"], unique=True)
        op.create_index("ix_push_subscriptions_user_active", "push_subscriptions", ["user_id", "is_active"])
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("defects")}
    if "reported_date" not in columns: op.add_column("defects", sa.Column("reported_date", sa.Date(), nullable=True))
    if "reported_time" not in columns: op.add_column("defects", sa.Column("reported_time", sa.Time(), nullable=True))

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    defect_columns = {item["name"] for item in inspector.get_columns("defects")}
    if "reported_time" in defect_columns:
        op.drop_column("defects", "reported_time")
    if "reported_date" in defect_columns:
        op.drop_column("defects", "reported_date")
    if "push_subscriptions" in set(inspector.get_table_names()):
        indexes = {item["name"] for item in inspector.get_indexes("push_subscriptions")}
        if "ix_push_subscriptions_user_active" in indexes:
            op.drop_index("ix_push_subscriptions_user_active", table_name="push_subscriptions")
        if "uq_push_subscriptions_endpoint" in indexes:
            op.drop_index("uq_push_subscriptions_endpoint", table_name="push_subscriptions")
        op.drop_table("push_subscriptions")
