"""m4 case wizard fields — loan_amount, loan_tenure_months, co_applicant_name

Revision ID: a1b2c3d4e5f6
Revises: b47f40f5fbcc
Create Date: 2026-04-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "b47f40f5fbcc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("loan_amount", sa.Integer(), nullable=True))
    op.add_column("cases", sa.Column("loan_tenure_months", sa.Integer(), nullable=True))
    op.add_column("cases", sa.Column("co_applicant_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "co_applicant_name")
    op.drop_column("cases", "loan_tenure_months")
    op.drop_column("cases", "loan_amount")
