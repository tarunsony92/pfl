"""m4 case_feedbacks — verdict + notes for AI learning

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-18 00:01:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE feedback_verdict AS ENUM ('APPROVE', 'NEEDS_REVISION', 'REJECT')"
    )
    op.create_table(
        "case_feedbacks",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "verdict",
            postgresql.ENUM(
                "APPROVE", "NEEDS_REVISION", "REJECT",
                name="feedback_verdict",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("phase", sa.String(length=32), nullable=False, server_default="phase1"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_case_feedbacks_actor_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_case_feedbacks_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_feedbacks")),
    )
    op.create_index(
        op.f("ix_case_feedbacks_case_id"), "case_feedbacks", ["case_id"], unique=False
    )
    op.create_index(
        op.f("ix_case_feedbacks_actor_user_id"),
        "case_feedbacks",
        ["actor_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_case_feedbacks_actor_user_id"), table_name="case_feedbacks")
    op.drop_index(op.f("ix_case_feedbacks_case_id"), table_name="case_feedbacks")
    op.drop_table("case_feedbacks")
    op.execute("DROP TYPE IF EXISTS feedback_verdict")
