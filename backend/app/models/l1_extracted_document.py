"""L1ExtractedDocument — one row per identity/address document scanned during L1.

Produced by the Claude-vision scanners (AadhaarScanner, PanScanner,
RationBillScanner). Persists the structured fields so Level 1's cross-checks
(applicant ↔ co-applicant, Aadhaar ↔ electricity bill, Aadhaar ↔ Equifax, etc.)
can run without re-invoking the vision model.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import DocType, Party
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class L1ExtractedDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A scanned identity / address document (Aadhaar / PAN / ration / bill)."""

    __tablename__ = "l1_extracted_documents"
    __table_args__ = (
        Index(
            "ix_l1_extracted_documents_case_doctype_party",
            "case_id",
            "doc_type",
            "party",
        ),
    )

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("case_artifacts.id", ondelete="SET NULL"), nullable=True
    )

    doc_type: Mapped[DocType] = mapped_column(
        PgEnum(
            DocType,
            name="l1_doc_type",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
    )
    party: Mapped[Party] = mapped_column(
        PgEnum(
            Party,
            name="l1_party",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
    )

    extracted_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    extracted_father_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    extracted_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extracted_dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    extracted_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)

    raw_vision_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<L1ExtractedDocument case_id={self.case_id} "
            f"doc_type={self.doc_type} party={self.party} "
            f"number={self.extracted_number}>"
        )
