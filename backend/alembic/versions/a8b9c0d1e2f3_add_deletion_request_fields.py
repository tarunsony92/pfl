"""Add deletion-request columns to cases for the MD-approval delete flow.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column("deletion_requested_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cases_deletion_requested_by_users",
        "cases",
        "users",
        ["deletion_requested_by"],
        ["id"],
    )
    op.add_column(
        "cases",
        sa.Column("deletion_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint("fk_cases_deletion_requested_by_users", "cases", type_="foreignkey")
    op.drop_column("cases", "deletion_reason")
    op.drop_column("cases", "deletion_requested_by")
    op.drop_column("cases", "deletion_requested_at")
