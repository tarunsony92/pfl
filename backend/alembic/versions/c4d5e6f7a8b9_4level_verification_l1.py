"""4-level pre-Phase-1 verification gate — Phase A (L1 Address) schema.

Creates:
- 6 Postgres enum types: verification_level_number, verification_level_status,
  level_issue_status, level_issue_severity, l1_doc_type, l1_party
- 3 tables: verification_results, l1_extracted_documents, level_issues
- 3 supporting indexes

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LEVEL_NUMBER_VALUES = ("L1_ADDRESS", "L2_BANKING", "L3_VISION", "L4_AGREEMENT")
_LEVEL_STATUS_VALUES = (
    "PENDING",
    "RUNNING",
    "PASSED",
    "PASSED_WITH_MD_OVERRIDE",
    "BLOCKED",
    "FAILED",
)
_ISSUE_STATUS_VALUES = ("OPEN", "ASSESSOR_RESOLVED", "MD_APPROVED", "MD_REJECTED")
_ISSUE_SEVERITY_VALUES = ("INFO", "WARNING", "CRITICAL")
_DOC_TYPE_VALUES = ("AADHAAR", "PAN", "RATION", "ELECTRICITY_BILL")
_PARTY_VALUES = ("APPLICANT", "CO_APPLICANT")


def upgrade() -> None:
    """Upgrade schema."""
    # Create the new enum types first (tables reference them).
    level_number_enum = postgresql.ENUM(
        *_LEVEL_NUMBER_VALUES, name="verification_level_number"
    )
    level_status_enum = postgresql.ENUM(
        *_LEVEL_STATUS_VALUES, name="verification_level_status"
    )
    issue_status_enum = postgresql.ENUM(*_ISSUE_STATUS_VALUES, name="level_issue_status")
    issue_severity_enum = postgresql.ENUM(
        *_ISSUE_SEVERITY_VALUES, name="level_issue_severity"
    )
    doc_type_enum = postgresql.ENUM(*_DOC_TYPE_VALUES, name="l1_doc_type")
    party_enum = postgresql.ENUM(*_PARTY_VALUES, name="l1_party")

    bind = op.get_bind()
    for e in (
        level_number_enum,
        level_status_enum,
        issue_status_enum,
        issue_severity_enum,
        doc_type_enum,
        party_enum,
    ):
        e.create(bind, checkfirst=True)

    # verification_results — one row per (case, level) run
    op.create_table(
        "verification_results",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column(
            "level_number",
            postgresql.ENUM(
                *_LEVEL_NUMBER_VALUES,
                name="verification_level_number",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                *_LEVEL_STATUS_VALUES,
                name="verification_level_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "sub_step_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "md_override_records",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_verification_results_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by"],
            ["users.id"],
            name=op.f("fk_verification_results_triggered_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_results")),
    )
    op.create_index(
        op.f("ix_verification_results_case_id"),
        "verification_results",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        "ix_verification_results_case_level_created",
        "verification_results",
        ["case_id", "level_number", "created_at"],
        unique=False,
    )

    # l1_extracted_documents — one row per scanned ID / address doc
    op.create_table(
        "l1_extracted_documents",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column(
            "doc_type",
            postgresql.ENUM(*_DOC_TYPE_VALUES, name="l1_doc_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "party",
            postgresql.ENUM(*_PARTY_VALUES, name="l1_party", create_type=False),
            nullable=False,
        ),
        sa.Column("extracted_name", sa.String(length=256), nullable=True),
        sa.Column("extracted_father_name", sa.String(length=256), nullable=True),
        sa.Column("extracted_address", sa.Text(), nullable=True),
        sa.Column("extracted_number", sa.String(length=32), nullable=True),
        sa.Column("extracted_dob", sa.Date(), nullable=True),
        sa.Column("extracted_gender", sa.String(length=16), nullable=True),
        sa.Column("raw_vision_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False, server_default="1.0"),
        sa.Column("model_used", sa.String(length=64), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_l1_extracted_documents_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["case_artifacts.id"],
            name=op.f("fk_l1_extracted_documents_artifact_id_case_artifacts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_l1_extracted_documents")),
    )
    op.create_index(
        op.f("ix_l1_extracted_documents_case_id"),
        "l1_extracted_documents",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        "ix_l1_extracted_documents_case_doctype_party",
        "l1_extracted_documents",
        ["case_id", "doc_type", "party"],
        unique=False,
    )

    # level_issues — one row per sub-step failure + resolution
    op.create_table(
        "level_issues",
        sa.Column("verification_result_id", sa.Uuid(), nullable=False),
        sa.Column("sub_step_id", sa.Text(), nullable=False),
        sa.Column(
            "severity",
            postgresql.ENUM(
                *_ISSUE_SEVERITY_VALUES,
                name="level_issue_severity",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                *_ISSUE_STATUS_VALUES,
                name="level_issue_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("assessor_user_id", sa.Uuid(), nullable=True),
        sa.Column("assessor_note", sa.Text(), nullable=True),
        sa.Column("assessor_resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("md_user_id", sa.Uuid(), nullable=True),
        sa.Column("md_rationale", sa.Text(), nullable=True),
        sa.Column("md_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["verification_result_id"],
            ["verification_results.id"],
            name=op.f("fk_level_issues_verification_result_id_verification_results"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assessor_user_id"],
            ["users.id"],
            name=op.f("fk_level_issues_assessor_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["md_user_id"],
            ["users.id"],
            name=op.f("fk_level_issues_md_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["case_artifacts.id"],
            name=op.f("fk_level_issues_artifact_id_case_artifacts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_level_issues")),
    )
    op.create_index(
        op.f("ix_level_issues_verification_result_id"),
        "level_issues",
        ["verification_result_id"],
        unique=False,
    )
    op.create_index(
        "ix_level_issues_result_status",
        "level_issues",
        ["verification_result_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema — drops tables and enum types."""
    op.drop_index("ix_level_issues_result_status", table_name="level_issues")
    op.drop_index(op.f("ix_level_issues_verification_result_id"), table_name="level_issues")
    op.drop_table("level_issues")

    op.drop_index(
        "ix_l1_extracted_documents_case_doctype_party",
        table_name="l1_extracted_documents",
    )
    op.drop_index(
        op.f("ix_l1_extracted_documents_case_id"),
        table_name="l1_extracted_documents",
    )
    op.drop_table("l1_extracted_documents")

    op.drop_index(
        "ix_verification_results_case_level_created",
        table_name="verification_results",
    )
    op.drop_index(
        op.f("ix_verification_results_case_id"), table_name="verification_results"
    )
    op.drop_table("verification_results")

    bind = op.get_bind()
    for enum_name in (
        "l1_party",
        "l1_doc_type",
        "level_issue_severity",
        "level_issue_status",
        "verification_level_status",
        "verification_level_number",
    ):
        bind.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
