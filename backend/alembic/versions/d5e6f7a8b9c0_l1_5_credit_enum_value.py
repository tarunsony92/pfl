"""Add L1_5_CREDIT to the verification_level_number enum.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insert L1_5_CREDIT after L1_ADDRESS so the enum's natural sort order
    # matches the gate sequence (L1 → L1.5 → L2 → L3 → L4).
    op.execute(
        "ALTER TYPE verification_level_number "
        "ADD VALUE IF NOT EXISTS 'L1_5_CREDIT' AFTER 'L1_ADDRESS'"
    )


def downgrade() -> None:
    # Postgres doesn't support removing a value from an enum safely when
    # rows may reference it. Downgrade is a no-op — the enum value stays.
    pass
