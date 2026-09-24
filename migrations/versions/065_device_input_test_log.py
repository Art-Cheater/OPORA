"""Field session log for U2/U3 connector pin tests.

Revision ID: 065_device_input_test_log
Revises: 064_device_phase_input_map
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "065_device_input_test_log"
down_revision = "064_device_phase_input_map"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("devices", sa.Column("input_test_session", JSONType(), nullable=True))
    op.create_table(
        "device_input_test_logs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID()),
        sa.Column("updated_by", GUID()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("device_id", GUID(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector", sa.String(8), nullable=False),
        sa.Column("pin", sa.String(1), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("ended_at", sa.String(40), nullable=False),
        sa.Column("start_u2", sa.String(2)),
        sa.Column("start_u3", sa.String(2)),
        sa.Column("end_u2", sa.String(2)),
        sa.Column("end_u3", sa.String(2)),
        sa.Column("changed_bits", JSONType()),
        sa.Column("transitions", JSONType()),
    )


def downgrade():
    op.drop_table("device_input_test_logs")
    op.drop_column("devices", "input_test_session")
