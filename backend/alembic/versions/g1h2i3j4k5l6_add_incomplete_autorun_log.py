"""Add incomplete_autorun_log table.

Records auto-runs started while required artefacts were missing from the
case so admins can spot defaulters in the new sidebar tab.

Revision ID: g1h2i3j4k5l6
Revises: f7c8d9e0a1b2
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, Sequence[str], None] = "f7c8d9e0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incomplete_autorun_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "missing_subtypes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_incomplete_autorun_log_case_id",
        "incomplete_autorun_log",
        ["case_id"],
    )
    op.create_index(
        "ix_incomplete_autorun_log_user_id",
        "incomplete_autorun_log",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_incomplete_autorun_log_user_id",
        table_name="incomplete_autorun_log",
    )
    op.drop_index(
        "ix_incomplete_autorun_log_case_id",
        table_name="incomplete_autorun_log",
    )
    op.drop_table("incomplete_autorun_log")
