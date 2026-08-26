"""Индексы целостности: EIS/EAV unique + soft-delete-aware junction uniques.

Revision ID: 035_integrity_indexes
Revises: 034_eis_event_url_len
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "035_integrity_indexes"
down_revision = "034_eis_event_url_len"
branch_labels = None
depends_on = None


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _drop_constraint_if_exists(table: str, name: str) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return
    names = {c["name"] for c in insp.get_unique_constraints(table)}
    if name in names:
        op.drop_constraint(name, table, type_="unique")


def upgrade() -> None:
    # Partial unique: активные номера ЕИС
    if not _has_index("contracts", "ix_contracts_eis_reestr_unique_active"):
        op.create_index(
            "ix_contracts_eis_reestr_unique_active",
            "contracts",
            ["eis_reestr_number"],
            unique=True,
            postgresql_where=sa.text(
                "deleted_at IS NULL AND eis_reestr_number IS NOT NULL AND eis_reestr_number != ''"
            ),
            sqlite_where=sa.text(
                "deleted_at IS NULL AND eis_reestr_number IS NOT NULL AND eis_reestr_number != ''"
            ),
        )
    if not _has_index("tender_applications", "ix_tender_applications_eis_reg_unique_active"):
        op.create_index(
            "ix_tender_applications_eis_reg_unique_active",
            "tender_applications",
            ["eis_reg_number"],
            unique=True,
            postgresql_where=sa.text(
                "deleted_at IS NULL AND eis_reg_number IS NOT NULL AND eis_reg_number != ''"
            ),
            sqlite_where=sa.text(
                "deleted_at IS NULL AND eis_reg_number IS NOT NULL AND eis_reg_number != ''"
            ),
        )
    if not _has_index("custom_field_values", "ix_custom_field_values_unique_active"):
        op.create_index(
            "ix_custom_field_values_unique_active",
            "custom_field_values",
            ["custom_field_id", "entity_type", "entity_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    # Junction: заменить абсолютный unique на partial (soft-delete + re-link)
    _drop_constraint_if_exists("tender_projects", "uq_tender_projects_tender_project")
    if not _has_index("tender_projects", "ix_tender_projects_pair_active"):
        op.create_index(
            "ix_tender_projects_pair_active",
            "tender_projects",
            ["tender_id", "project_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    _drop_constraint_if_exists("contract_objects", "uq_contract_objects_contract_object")
    if not _has_index("contract_objects", "ix_contract_objects_pair_active"):
        op.create_index(
            "ix_contract_objects_pair_active",
            "contract_objects",
            ["contract_id", "object_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    _drop_constraint_if_exists("contract_contractors", "uq_contract_contractors_pair")
    if not _has_index("contract_contractors", "ix_contract_contractors_pair_active"):
        op.create_index(
            "ix_contract_contractors_pair_active",
            "contract_contractors",
            ["contract_id", "contractor_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    for table, name in (
        ("contract_contractors", "ix_contract_contractors_pair_active"),
        ("contract_objects", "ix_contract_objects_pair_active"),
        ("tender_projects", "ix_tender_projects_pair_active"),
        ("custom_field_values", "ix_custom_field_values_unique_active"),
        ("tender_applications", "ix_tender_applications_eis_reg_unique_active"),
        ("contracts", "ix_contracts_eis_reestr_unique_active"),
    ):
        if _has_index(table, name):
            op.drop_index(name, table_name=table)
