"""Confirmed CON10.4 phase A on the pilot board only.

Revision ID: 066_pilot_con10_phase_a
Revises: 067_irz_light_poles
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "066_pilot_con10_phase_a"
down_revision = "067_irz_light_poles"
branch_labels = None
depends_on = None


def upgrade():
    from app.models.devices.state import apply_pilot_phase_map

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, phase_input_map FROM devices WHERE device_id = 'ipp-001' AND deleted_at IS NULL")).fetchall()
    for row in rows:
        current = row.phase_input_map
        if isinstance(current, str):
            current = json.loads(current)
        updated = apply_pilot_phase_map("ipp-001", current if isinstance(current, dict) else None)
        payload = json.dumps(updated)
        if conn.dialect.name == "postgresql":
            conn.execute(
                sa.text("UPDATE devices SET phase_input_map = CAST(:mapping AS json) WHERE id = :id"),
                {"mapping": payload, "id": row.id},
            )
        else:
            conn.execute(
                sa.text("UPDATE devices SET phase_input_map = :mapping WHERE id = :id"),
                {"mapping": payload, "id": row.id},
            )


def downgrade():
    pass
