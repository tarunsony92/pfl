"""Add L5_5_DEDUPE_TVR to the verification_level_number enum.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-04-25
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE verification_level_number "
        "ADD VALUE IF NOT EXISTS 'L5_5_DEDUPE_TVR' AFTER 'L5_SCORING'"
    )


def downgrade() -> None:
    # Postgres doesn't support removing a value from an enum safely when
    # rows may reference it. Downgrade is a no-op — the enum value stays.
    pass
