"""CAM discrepancy resolutions + SystemCam edit approval requests

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-22 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- enum types ---
    op.execute("CREATE TYPE discrepancy_severity AS ENUM ('CRITICAL', 'WARNING')")
    op.execute(
        "CREATE TYPE discrepancy_resolution_kind AS ENUM "
        "('CORRECTED_CM_IL', 'SYSTEMCAM_EDIT_REQUESTED', 'JUSTIFIED')"
    )
    op.execute(
        "CREATE TYPE system_cam_edit_request_status AS ENUM "
        "('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN')"
    )

    # --- cam_discrepancy_resolutions ---
    op.create_table(
        "cam_discrepancy_resolutions",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("field_label", sa.String(length=128), nullable=False),
        sa.Column("system_cam_value_at_resolve", sa.Text(), nullable=True),
        sa.Column("cm_cam_il_value_at_resolve", sa.Text(), nullable=True),
        sa.Column(
            "severity_at_resolve",
            postgresql.ENUM(
                "CRITICAL", "WARNING", name="discrepancy_severity", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "CORRECTED_CM_IL",
                "SYSTEMCAM_EDIT_REQUESTED",
                "JUSTIFIED",
                name="discrepancy_resolution_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("resolved_by", sa.Uuid(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_cam_discrepancy_resolutions_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["users.id"],
            name=op.f("fk_cam_discrepancy_resolutions_resolved_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cam_discrepancy_resolutions")),
        sa.UniqueConstraint("case_id", "field_key", name="uq_cam_disc_res_case_field"),
    )
    op.create_index(
        op.f("ix_cam_discrepancy_resolutions_case_id"),
        "cam_discrepancy_resolutions",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cam_discrepancy_resolutions_resolved_by"),
        "cam_discrepancy_resolutions",
        ["resolved_by"],
        unique=False,
    )

    # --- system_cam_edit_requests ---
    op.create_table(
        "system_cam_edit_requests",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("resolution_id", sa.Uuid(), nullable=True),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("field_label", sa.String(length=128), nullable=False),
        sa.Column("current_system_cam_value", sa.Text(), nullable=True),
        sa.Column("requested_system_cam_value", sa.Text(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING",
                "APPROVED",
                "REJECTED",
                "WITHDRAWN",
                name="system_cam_edit_request_status",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_system_cam_edit_requests_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"],
            ["cam_discrepancy_resolutions.id"],
            name=op.f("fk_system_cam_edit_requests_resolution_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_system_cam_edit_requests_requested_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_system_cam_edit_requests_decided_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_cam_edit_requests")),
    )
    op.create_index(
        op.f("ix_system_cam_edit_requests_case_id"),
        "system_cam_edit_requests",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_cam_edit_requests_resolution_id"),
        "system_cam_edit_requests",
        ["resolution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_cam_edit_requests_requested_by"),
        "system_cam_edit_requests",
        ["requested_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_system_cam_edit_requests_requested_by"),
        table_name="system_cam_edit_requests",
    )
    op.drop_index(
        op.f("ix_system_cam_edit_requests_resolution_id"),
        table_name="system_cam_edit_requests",
    )
    op.drop_index(
        op.f("ix_system_cam_edit_requests_case_id"),
        table_name="system_cam_edit_requests",
    )
    op.drop_table("system_cam_edit_requests")

    op.drop_index(
        op.f("ix_cam_discrepancy_resolutions_resolved_by"),
        table_name="cam_discrepancy_resolutions",
    )
    op.drop_index(
        op.f("ix_cam_discrepancy_resolutions_case_id"),
        table_name="cam_discrepancy_resolutions",
    )
    op.drop_table("cam_discrepancy_resolutions")

    op.execute("DROP TYPE IF EXISTS system_cam_edit_request_status")
    op.execute("DROP TYPE IF EXISTS discrepancy_resolution_kind")
    op.execute("DROP TYPE IF EXISTS discrepancy_severity")
