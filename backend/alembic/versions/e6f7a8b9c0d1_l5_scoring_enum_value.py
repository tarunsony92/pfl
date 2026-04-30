"""Add L5_SCORING to the verification_level_number enum.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE verification_level_number "
        "ADD VALUE IF NOT EXISTS 'L5_SCORING' AFTER 'L4_AGREEMENT'"
    )


def downgrade() -> None:
    pass
