"""Add negative_area_pincodes table.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "negative_area_pincodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pincode", sa.String(6), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "source", sa.String(64), nullable=False, server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"),
        ),
        sa.Column(
            "uploaded_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.UniqueConstraint("pincode", name="uq_negative_area_pincode"),
    )
    op.create_index(
        "ix_negative_area_pincodes_pincode",
        "negative_area_pincodes",
        ["pincode"],
    )


def downgrade() -> None:
    op.drop_index("ix_negative_area_pincodes_pincode", table_name="negative_area_pincodes")
    op.drop_table("negative_area_pincodes")
