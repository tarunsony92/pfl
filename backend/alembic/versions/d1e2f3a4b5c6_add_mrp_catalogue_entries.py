"""Add mrp_catalogue_entries table.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-04-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mrp_catalogue_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("business_type", sa.String(64), nullable=False),
        sa.Column("item_canonical", sa.String(255), nullable=False),
        sa.Column("item_description", sa.String(512), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("mrp_inr", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'AI_ESTIMATED'"),
        ),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("rationale", sa.String(512), nullable=True),
        sa.Column(
            "observed_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "business_type",
            "item_canonical",
            name="uq_mrp_business_type_item",
        ),
    )
    op.create_index(
        "ix_mrp_catalogue_entries_business_type",
        "mrp_catalogue_entries",
        ["business_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mrp_catalogue_entries_business_type", "mrp_catalogue_entries"
    )
    op.drop_table("mrp_catalogue_entries")
