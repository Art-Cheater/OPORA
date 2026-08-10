"""Расширение журнала действий.

Revision ID: 009_audit_journal
Revises: 008_unified_search
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009_audit_journal"
down_revision = "008_unified_search"
branch_labels = None
depends_on = None

AUDIT_TRIGGER = """
CREATE OR REPLACE FUNCTION audit_log_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', coalesce(NEW.action, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(NEW.entity_type, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(NEW.ip_address, '')), 'B') ||
    setweight(to_tsvector('russian', coalesce(NEW.description, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(NEW.description, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade():
    op.add_column(
        "audit_log",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("audit_log", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
    op.create_index(
        "ix_audit_log_search_vector_gin",
        "audit_log",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    op.execute(AUDIT_TRIGGER)
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_search_vector ON audit_log")
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_search_vector
        BEFORE INSERT OR UPDATE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_search_vector_update()
        """
    )
    op.execute("UPDATE audit_log SET description = COALESCE(description, action) WHERE description = '' OR description IS NULL")

    op.execute(
        sa.text(
            """
            INSERT INTO permissions (id, created_at, updated_at, code, name, module, is_active)
            SELECT gen_random_uuid(), NOW(), NOW(), 'audit.export', 'Экспорт журнала аудита', 'audit', true
            WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'audit.export' AND deleted_at IS NULL)
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, created_at, updated_at, role_id, permission_id)
            SELECT gen_random_uuid(), NOW(), NOW(), r.id, p.id
            FROM roles r
            JOIN permissions p ON p.code = 'audit.export'
            WHERE r.code IN ('admin', 'director')
              AND r.deleted_at IS NULL AND p.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted_at IS NULL
              )
            """
        )
    )


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = 'audit.export')"
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE code = 'audit.export'"))

    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_search_vector ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_search_vector_update()")
    op.drop_index("ix_audit_log_search_vector_gin", table_name="audit_log")
    op.drop_column("audit_log", "search_vector")
    op.drop_column("audit_log", "description")
