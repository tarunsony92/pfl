"""Case-completeness checker — what required artefacts are missing on a
case at the moment the user wants to start an auto-run.

Used by the auto-run gate: the FE calls
``GET /cases/:id/missing-required-artifacts`` before posting the auto-run
request. If the response is non-empty the FE shows a modal listing the
missing artefacts and offers either "upload now" or "skip + log" — the
latter records an entry in ``IncompleteAutorunLog`` so audit can follow up.

Required-set
------------
A loan file is considered "complete" when it carries the canonical PFL
microfinance bundle: KYC, address proof, bureau pull, bank statement,
income proof, business + house photos, the CAM and PD sheets, and the
loan-agreement bundle. Co-applicant documents are required only when the
case actually has a co-applicant; this is detected from
``case.co_applicant_name`` so an applicant-only case doesn't false-flag
on missing co-applicant artefacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ArtifactSubtype
from app.models.case import Case
from app.models.case_artifact import CaseArtifact


# Required for every PFL microfinance file — these are the canonical
# document types the credit committee expects to see at the time of a
# pre-disbursal review.
_REQUIRED_BASE: tuple[ArtifactSubtype, ...] = (
    ArtifactSubtype.KYC_AADHAAR,
    ArtifactSubtype.KYC_PAN,
    ArtifactSubtype.AUTO_CAM,
    ArtifactSubtype.PD_SHEET,
    ArtifactSubtype.BANK_STATEMENT,
    ArtifactSubtype.EQUIFAX_HTML,
    ArtifactSubtype.HOUSE_VISIT_PHOTO,
    ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
    ArtifactSubtype.LAGR,
    ArtifactSubtype.LAPP,
    ArtifactSubtype.DPN,
    ArtifactSubtype.NACH,
)


# Address-proof is satisfied by EITHER a ration card OR an electricity bill.
# Modeled as a "one-of" group so the checker reports a single
# ``ADDRESS_PROOF`` slot rather than two separate misses (and disappears
# the moment EITHER subtype lands on the case).
_ADDRESS_PROOF_GROUP: tuple[ArtifactSubtype, ...] = (
    ArtifactSubtype.RATION_CARD,
    ArtifactSubtype.ELECTRICITY_BILL,
)


# Required additionally when the case has a co-applicant on record.
_REQUIRED_IF_COAPP: tuple[ArtifactSubtype, ...] = (
    ArtifactSubtype.CO_APPLICANT_AADHAAR,
    ArtifactSubtype.CO_APPLICANT_PAN,
)


@dataclass
class MissingArtifact:
    """One missing-document slot."""

    subtype: str  # ArtifactSubtype value, or the synthetic "ADDRESS_PROOF" slot
    label: str
    optional_alternatives: list[str] | None = None  # for the one-of group

    def to_dict(self) -> dict[str, object]:
        return {
            "subtype": self.subtype,
            "label": self.label,
            "optional_alternatives": self.optional_alternatives,
        }


_LABELS: dict[str, str] = {
    ArtifactSubtype.KYC_AADHAAR.value: "Applicant Aadhaar",
    ArtifactSubtype.KYC_PAN.value: "Applicant PAN",
    ArtifactSubtype.CO_APPLICANT_AADHAAR.value: "Co-applicant Aadhaar",
    ArtifactSubtype.CO_APPLICANT_PAN.value: "Co-applicant PAN",
    ArtifactSubtype.AUTO_CAM.value: "AutoCAM sheet",
    ArtifactSubtype.PD_SHEET.value: "PD sheet (personal-discussion notes)",
    ArtifactSubtype.BANK_STATEMENT.value: "Bank statement",
    ArtifactSubtype.EQUIFAX_HTML.value: "Bureau report (Equifax / CIBIL)",
    ArtifactSubtype.HOUSE_VISIT_PHOTO.value: "House-visit photo",
    ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value: "Business-premises photo",
    ArtifactSubtype.LAGR.value: "Loan agreement (LAGR)",
    ArtifactSubtype.LAPP.value: "Loan application form (LAPP)",
    ArtifactSubtype.DPN.value: "Demand promissory note (DPN)",
    ArtifactSubtype.NACH.value: "NACH mandate",
    ArtifactSubtype.RATION_CARD.value: "Ration card",
    ArtifactSubtype.ELECTRICITY_BILL.value: "Electricity bill",
}


async def compute_missing_required_artifacts(
    session: AsyncSession,
    case_id: UUID,
) -> list[MissingArtifact]:
    """Return a list of missing required artefacts for ``case_id``.

    Empty list = case is complete and the auto-run can proceed without
    a gate prompt. Order is stable so the FE renders consistently
    across reloads.
    """
    case = await session.get(Case, case_id)
    arts = (
        (
            await session.execute(
                select(CaseArtifact).where(CaseArtifact.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    present_subtypes: set[str] = {
        (a.metadata_json or {}).get("subtype")
        for a in arts
        if (a.metadata_json or {}).get("subtype")
    }

    required: list[ArtifactSubtype] = list(_REQUIRED_BASE)
    if case is not None and getattr(case, "co_applicant_name", None):
        required.extend(_REQUIRED_IF_COAPP)

    out: list[MissingArtifact] = []

    # Bulk required subtypes — one entry per missing canonical type.
    for st in required:
        if st.value not in present_subtypes:
            out.append(
                MissingArtifact(
                    subtype=st.value,
                    label=_LABELS.get(st.value, st.value),
                )
            )

    # Address-proof group (one-of). Considered satisfied if EITHER subtype
    # is present; reported as a single synthetic slot otherwise.
    if not any(st.value in present_subtypes for st in _ADDRESS_PROOF_GROUP):
        out.append(
            MissingArtifact(
                subtype="ADDRESS_PROOF",
                label="Address proof (ration card or electricity bill)",
                optional_alternatives=[st.value for st in _ADDRESS_PROOF_GROUP],
            )
        )

    return out


def required_subtypes(has_coapplicant: bool) -> list[str]:
    """Return the canonical required-subtype labels (debug / introspection)."""
    out = [s.value for s in _REQUIRED_BASE]
    if has_coapplicant:
        out.extend(s.value for s in _REQUIRED_IF_COAPP)
    return out
