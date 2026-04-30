"""Add ``occupation`` column to cases.

Captured at wizard time and surfaced to the L1 commute judge as one
input in the rural/urban + business-type profile bundle (see
``docs/superpowers/specs/2026-04-22-l1-house-business-commute-design.md``
§7).

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("occupation", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cases", "occupation")
