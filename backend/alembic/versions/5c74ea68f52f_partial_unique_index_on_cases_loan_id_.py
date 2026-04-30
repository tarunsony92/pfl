"""partial unique index on cases.loan_id excluding deleted

Revision ID: 5c74ea68f52f
Revises: b2f148d48781
Create Date: 2026-04-18 21:51:22.168306

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c74ea68f52f'
down_revision: Union[str, Sequence[str], None] = 'b2f148d48781'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop the full unique index created by the previous migration
    op.drop_index("ix_cases_loan_id", table_name="cases")
    # Create a partial unique index that allows reuse of soft-deleted loan_ids
    op.create_index(
        "ix_cases_loan_id",
        "cases",
        ["loan_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_cases_loan_id", table_name="cases")
    op.create_index("ix_cases_loan_id", "cases", ["loan_id"], unique=True)
