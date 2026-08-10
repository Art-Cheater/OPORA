"""Расширение PostgreSQL Full Text Search.

Revision ID: 008_unified_search
Revises: 007_messenger
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "008_unified_search"
down_revision = "007_messenger"
branch_labels = None
depends_on = None

TABLES = ("requests", "projects", "contracts", "users")

REQUEST_TRIGGER = """
CREATE OR REPLACE FUNCTION requests_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', coalesce(NEW.number, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(NEW.phone, '')), 'B') ||
    setweight(to_tsvector('russian', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.address, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.applicant_name, '')), 'B') ||
    setweight(to_tsvector('russian', coalesce(NEW.description, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

PROJECT_TRIGGER = """
CREATE OR REPLACE FUNCTION projects_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', coalesce(NEW.code, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.name, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.description, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CONTRACT_TRIGGER = """
CREATE OR REPLACE FUNCTION contracts_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', coalesce(NEW.number, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.description, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

USER_TRIGGER = """
CREATE OR REPLACE FUNCTION users_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('russian', coalesce(NEW.full_name, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(NEW.email, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(NEW.phone, '')), 'B') ||
    setweight(to_tsvector('russian', coalesce(NEW.department, '')), 'B') ||
    setweight(to_tsvector('russian', coalesce(NEW.position, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
        op.create_index(
            f"ix_{table}_search_vector_gin",
            table,
            ["search_vector"],
            unique=False,
            postgresql_using="gin",
        )

    op.execute(REQUEST_TRIGGER)
    op.execute(PROJECT_TRIGGER)
    op.execute(CONTRACT_TRIGGER)
    op.execute(USER_TRIGGER)

    for table, func_name in (
        ("requests", "requests_search_vector_update"),
        ("projects", "projects_search_vector_update"),
        ("contracts", "contracts_search_vector_update"),
        ("users", "users_search_vector_update"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_search_vector ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_search_vector
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {func_name}()
            """
        )

    # Backfill
    op.execute("UPDATE requests SET number = number")
    op.execute("UPDATE projects SET code = code")
    op.execute("UPDATE contracts SET number = number")
    op.execute("UPDATE users SET email = email")

    op.execute(
        sa.text(
            """
            INSERT INTO permissions (id, created_at, updated_at, code, name, module, is_active)
            SELECT gen_random_uuid(), NOW(), NOW(), 'search.use', 'Глобальный поиск', 'search', true
            WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'search.use' AND deleted_at IS NULL)
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, created_at, updated_at, role_id, permission_id)
            SELECT gen_random_uuid(), NOW(), NOW(), r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND p.code = 'search.use'
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
            "(SELECT id FROM permissions WHERE code = 'search.use')"
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE code = 'search.use'"))

    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_search_vector ON {table}")

    op.execute("DROP FUNCTION IF EXISTS users_search_vector_update()")
    op.execute("DROP FUNCTION IF EXISTS contracts_search_vector_update()")
    op.execute("DROP FUNCTION IF EXISTS projects_search_vector_update()")
    op.execute("DROP FUNCTION IF EXISTS requests_search_vector_update()")

    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_search_vector_gin", table_name=table)
        op.drop_column(table, "search_vector")
