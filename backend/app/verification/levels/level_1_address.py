"""Level 1 — Address verification.

Seven sub-steps per the 4-level gate plan (§3.1):

1. Scan Aadhaar + PAN of applicant AND co-applicant → persist + extract address.
2. Match applicant Aadhaar address ↔ co-applicant Aadhaar address.
3. House-visit photo GPS EXIF → Google Maps reverse-geocode → derived address.
4. Derived address ↔ applicant Aadhaar address.
5. Electricity / ration bill owner-name rule (s/o or w/o must be co-applicant).
6. Cross-check address ↔ Equifax ↔ bank-statement address.
7. Aggregate issues → PASSED / BLOCKED.

This module contains both the orchestrator (``run_level_1_address``) and the
pure cross-check helpers, which are unit-tested in isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    ArtifactSubtype,
    DocType,
    ExtractionStatus,
    LevelIssueSeverity,
    LevelIssueStatus,
    Party,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.l1_extracted_document import L1ExtractedDocument
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.verification.levels._common import carry_forward_prior_decisions
from app.verification.services.address_normalizer import (
    addresses_match,
    first_names_match,
    has_generic_surname,
    name_is_related_via_father_husband,
    name_matches,
)

_log = logging.getLogger(__name__)


# ─────────────────────────── Source-artifact helpers ─────────────────────────
#
# Every emitted issue carries ``evidence.source_artifacts`` — an ordered list
# of the files the cross-check ran against, so the UI "View source" button
# can show the MD the actual Aadhaar card / bill / photo. Shape (stable
# contract consumed by ``IssueSourceFilesButton`` on the frontend):
#
#     {
#       "artifact_id": "<uuid>",
#       "relevance":   "Applicant Aadhaar — address field",
#       "filename":    "<original filename>",
#       "highlight_field": "address",   # optional — hints at the field inside
#       "page":        1,               # optional — PDF page, 1-indexed
#     }
#
# Helpers are pure list-builders: the orchestrator composes multiple calls
# and merges the result into each issue's ``evidence`` dict. Cross-check
# helpers stay pure (they don't see the raw artefact list) — the less
# invasive pattern called out in the design note.


def _ref(
    artifact: CaseArtifact | None,
    *,
    relevance: str,
    highlight_field: str | None = None,
    page: int | None = None,
) -> dict[str, Any] | None:
    """Build one ``source_artifacts[]`` entry, or None if ``artifact`` is None.

    Callers pass artefacts that may be absent (co-applicant missing, LAGR not
    uploaded, …). Returning None keeps the merge call-sites a one-liner —
    falsy entries are filtered out by :func:`_pack`.
    """
    if artifact is None:
        return None
    out: dict[str, Any] = {
        "artifact_id": str(artifact.id),
        "filename": artifact.filename,
        "relevance": relevance,
    }
    if highlight_field is not None:
        out["highlight_field"] = highlight_field
    if page is not None:
        out["page"] = page
    return out


def _pack(*refs: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Drop Nones and return a de-duplicated ordered list.

    Callers build refs inline; ``_pack`` removes the falsy slots and
    collapses duplicate artifact_ids (the same Aadhaar shouldn't appear
    twice just because two different checks both cite it).
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in refs:
        if r is None:
            continue
        aid = r.get("artifact_id")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append(r)
    return out


def _first(artifacts: list[CaseArtifact] | None) -> CaseArtifact | None:
    """Pick the first artefact from a (possibly None) list."""
    if not artifacts:
        return None
    return artifacts[0]


async def filter_suppressed_issues(
    session: AsyncSession,
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop issues whose rule has been suppressed via /admin/rule-overrides.

    Returns ``(kept_issues, suppressed_sub_step_ids)``. Suppressed rules
    don't get persisted as LevelIssue rows at all — they never surface on
    the MD queue or block the gate. The list of suppressed sub_step_ids
    is stamped onto ``sub_step_results.suppressed_rules`` so the audit
    trail shows which rules were skipped on this run and why.

    Shared by every L-level orchestrator.
    """
    from app.models.rule_override import RuleOverride
    from sqlalchemy import select as _select

    if not issues:
        return issues, []

    sub_ids = list({str(i.get("sub_step_id")) for i in issues})
    rows = (
        await session.execute(
            _select(RuleOverride).where(RuleOverride.sub_step_id.in_(sub_ids))
        )
    ).scalars().all()
    suppressed = {o.sub_step_id for o in rows if o.is_suppressed}
    if not suppressed:
        return issues, []
    kept = [i for i in issues if i.get("sub_step_id") not in suppressed]
    return kept, sorted(suppressed)


# ─────────── Loan-agreement parties helper (guarantors / co-applicants) ─────
#
# The signed LAGR PDF is the source of truth for who is on-the-hook for the
# loan. We run the scanner once and cache the result in ``case_extractions``
# keyed by (case_id, extractor_name='loan_agreement_scanner', artifact_id),
# so re-running L1 doesn't re-pay the ~$0.04 Haiku PDF scan each time.


_LAGR_EXTRACTOR_NAME = "loan_agreement_scanner"


async def _load_or_scan_lagr_parties(
    *,
    session: AsyncSession,
    case_id: UUID,
    artifacts: list[CaseArtifact],
    storage: Any,
    claude: Any,
) -> dict[str, Any] | None:
    """Return a dict with keys ``guarantors``, ``co_applicants``, ``borrower_name``
    (plus ``cost_usd`` if a fresh scan ran), or None if the case has no
    loan-agreement artifact uploaded.

    The function is idempotent: a cached row in ``case_extractions`` is
    preferred over a fresh scan; if a fresh scan runs, its result is persisted
    so subsequent L1 runs read the cache.
    """
    lagr_subtypes = (
        ArtifactSubtype.LAGR.value,
        ArtifactSubtype.LOAN_AGREEMENT.value,
        ArtifactSubtype.LAPP.value,
        ArtifactSubtype.DPN.value,
    )

    def _sub(a: CaseArtifact) -> str | None:
        return (a.metadata_json or {}).get("subtype")

    lagr_art: CaseArtifact | None = None
    for want in lagr_subtypes:
        matches = [
            a
            for a in artifacts
            if _sub(a) == want and a.filename.lower().endswith(".pdf")
        ]
        if matches:
            lagr_art = matches[0]
            break
    if lagr_art is None:
        return None

    # Try the cache first.
    stmt = select(CaseExtraction).where(
        CaseExtraction.case_id == case_id,
        CaseExtraction.extractor_name == _LAGR_EXTRACTOR_NAME,
        CaseExtraction.artifact_id == lagr_art.id,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing and existing.status == ExtractionStatus.SUCCESS and existing.data:
        d = existing.data
        return {
            "borrower_name": d.get("borrower_name"),
            "co_applicants": d.get("co_applicants") or [],
            "guarantors": d.get("guarantors") or [],
            "witnesses": d.get("witnesses") or [],
            "cached": True,
            "cost_usd": 0,
        }

    # Cache miss — run the scanner.
    from app.worker.extractors.loan_agreement_scanner import LoanAgreementScanner

    try:
        body = await storage.download_object(lagr_art.s3_key)
    except Exception as exc:  # noqa: BLE001
        _log.warning("L1: LAGR download failed for %s: %s", lagr_art.s3_key, exc)
        return None

    scanner = LoanAgreementScanner(claude=claude)
    res = await scanner.extract(lagr_art.filename, body)
    if res.status == ExtractionStatus.FAILED:
        _log.warning("L1: LAGR scan failed: %s", res.error_message)
        return None

    # Persist so the next L1 run is free. If a prior non-SUCCESS row exists
    # (PARTIAL from an earlier crash, stale schema) we UPDATE it in place —
    # the unique (case_id, extractor_name, artifact_id) constraint would
    # otherwise blow up on a fresh INSERT.
    if existing is not None:
        existing.schema_version = scanner.schema_version
        existing.status = res.status
        existing.data = res.data
        existing.warnings = res.warnings
        existing.error_message = res.error_message
        existing.extracted_at = datetime.now(UTC)
    else:
        session.add(
            CaseExtraction(
                case_id=case_id,
                artifact_id=lagr_art.id,
                extractor_name=_LAGR_EXTRACTOR_NAME,
                schema_version=scanner.schema_version,
                status=res.status,
                data=res.data,
                warnings=res.warnings,
                error_message=res.error_message,
                extracted_at=datetime.now(UTC),
            )
        )
    await session.flush()

    return {
        "borrower_name": res.data.get("borrower_name"),
        "co_applicants": res.data.get("co_applicants") or [],
        "guarantors": res.data.get("guarantors") or [],
        "witnesses": res.data.get("witnesses") or [],
        "cached": False,
        "cost_usd": res.data.get("cost_usd") or 0,
    }


# ───────────────────────────── Pure cross-checks ────────────────────────────
# Return an "issue dict" ``{"sub_step_id", "severity", "description"}`` when a
# rule fails, or ``None`` when it passes (or the input is missing).


def cross_check_applicant_coapplicant_aadhaar_addresses(
    applicant_address: str | None,
    co_applicant_address: str | None,
    *,
    distance_km: float | None = None,
) -> dict[str, Any] | None:
    if not applicant_address or not co_applicant_address:
        return None
    if addresses_match(applicant_address, co_applicant_address):
        return None
    evidence: dict[str, Any] = {
        "applicant_address": applicant_address,
        "co_applicant_address": co_applicant_address,
        "match_threshold": 0.85,
    }
    if distance_km is not None:
        evidence["distance_km"] = round(distance_km, 3)
    return {
        "sub_step_id": "applicant_coapp_address_match",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "Applicant and co-applicant Aadhaar addresses differ beyond the "
            "fuzzy-match threshold. Review whether both parties in fact "
            "reside at the same premises."
            + (
                f" Geocoded distance ≈ {distance_km:.2f} km."
                if distance_km is not None
                else ""
            )
        ),
        "evidence": evidence,
    }


def cross_check_gps_vs_applicant_aadhaar(
    applicant_aadhaar_address: str | None,
    gps_derived_address: str | None,
    *,
    gps_coords: tuple[float, float] | None = None,
    gps_match: GPSMatch | None = None,
    distance_km: float | None = None,
) -> dict[str, Any] | None:
    if not applicant_aadhaar_address:
        return None  # upstream issue — Aadhaar scan itself failed

    # ---- Preferred path: use the structured match when available. -----------
    # ``gps_match`` is computed only when the geocoder returned structured
    # address parts (currently Nominatim). It compares on district + village
    # rather than pincode, which is the correct check for rural India where
    # a single 6-digit pincode covers dozens of villages.
    # ``distance_km`` decoration: tucked into every issue evidence dict + the
    # description tail when present, so the assessor sees "200 m / photo
    # angle" vs "50 km / wrong village" without leaving the panel. Computed
    # one level up by the L1 engine via google_maps.forward_geocode + haversine.
    def _ev(extra: dict[str, Any]) -> dict[str, Any]:
        if distance_km is not None:
            extra = {**extra, "distance_km": round(distance_km, 3)}
        return extra

    def _dist_tail() -> str:
        return (
            f" Geocoded distance ≈ {distance_km:.2f} km."
            if distance_km is not None
            else ""
        )

    if gps_match is not None:
        if gps_match.verdict == "match":
            return None  # pass
        if gps_match.verdict == "doubtful":
            return {
                "sub_step_id": "gps_vs_aadhaar",
                "severity": LevelIssueSeverity.WARNING.value,
                "description": (
                    f"House-visit GPS partially matches the applicant's Aadhaar "
                    f"address (score {gps_match.score}/100). {gps_match.reason}"
                    + _dist_tail()
                    + f"\n\n• Aadhaar address: {applicant_aadhaar_address}\n"
                    f"• GPS-derived address: {gps_derived_address or '(none)'}"
                ),
                "evidence": _ev({
                    "applicant_aadhaar_address": applicant_aadhaar_address,
                    "gps_derived_address": gps_derived_address,
                    "gps_match": gps_match.to_dict(),
                }),
            }
        # "mismatch"
        return {
            "sub_step_id": "gps_vs_aadhaar",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                f"House-visit GPS does NOT match the applicant's Aadhaar address "
                f"(score {gps_match.score}/100). {gps_match.reason}"
                + _dist_tail()
                + f"\n\n• Aadhaar address: {applicant_aadhaar_address}\n"
                f"• GPS-derived address: {gps_derived_address or '(none)'}"
            ),
            "evidence": _ev({
                "applicant_aadhaar_address": applicant_aadhaar_address,
                "gps_derived_address": gps_derived_address,
                "gps_match": gps_match.to_dict(),
            }),
        }

    # ---- Legacy path: geocoder returned string only (Google). ---------------
    if not gps_derived_address:
        if gps_coords is None:
            # Path A — no house-visit photo yielded GPS at all.
            return {
                "sub_step_id": "gps_vs_aadhaar",
                "severity": LevelIssueSeverity.WARNING.value,
                "description": (
                    "No house-visit photo yielded GPS coordinates — EXIF metadata "
                    "was missing (typically stripped by WhatsApp) and the "
                    "GPS-Map-Camera burn-in overlay could not be read. Assessor "
                    "must provide the house-visit coordinates manually."
                ),
                "evidence": {"applicant_aadhaar_address": applicant_aadhaar_address},
            }
        # Path B — coords were extracted but both geocoders failed on them.
        return {
            "sub_step_id": "gps_vs_aadhaar",
            "severity": LevelIssueSeverity.WARNING.value,
            "description": (
                f"House-visit GPS coordinates were extracted "
                f"({gps_coords[0]:.5f}, {gps_coords[1]:.5f}) but reverse-geocoding "
                "failed on both Google Maps and OpenStreetMap Nominatim. Confirm "
                "that the Geocoding API is enabled on the Google Cloud project, "
                "or inspect the coordinates manually on a map."
            ),
            "evidence": {
                "applicant_aadhaar_address": applicant_aadhaar_address,
                "gps_coords": list(gps_coords),
            },
        }
    if addresses_match(applicant_aadhaar_address, gps_derived_address):
        return None
    return {
        "sub_step_id": "gps_vs_aadhaar",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "House-visit GPS reverse-geocoded to an address that does not match "
            "the applicant's Aadhaar address. Either the photo was taken away "
            "from the residence or the Aadhaar address is stale."
            + _dist_tail()
            + f"\n\n• Aadhaar address: {applicant_aadhaar_address}\n"
            f"• GPS-derived address: {gps_derived_address}"
        ),
        "evidence": _ev({
            "applicant_aadhaar_address": applicant_aadhaar_address,
            "gps_derived_address": gps_derived_address,
        }),
    }


def _bill_owner_loan_role(
    bill_owner_name: str | None,
    applicant_name: str | None,
    co_applicant_name: str | None,
    guarantor_names: list[str] | None,
) -> str:
    """Classify whether the bill owner is themselves a party on the loan.

    Returns one of: ``"applicant" | "co_applicant" | "guarantor" | "not_on_loan"``.
    Falls back to ``"not_on_loan"`` when ``bill_owner_name`` is missing — the
    rule itself short-circuits before reaching evidence in that case.

    Surfaced in every ``ration_owner_rule`` evidence dict so the FE card can
    show the assessor a single explicit "Role on loan" line — the screenshot
    case (bill owner shares a generic-surname first name with the applicant's
    father, but is *not* themselves on the loan) reads as ``not_on_loan``.
    """
    if not bill_owner_name:
        return "not_on_loan"
    if applicant_name and name_matches(bill_owner_name, applicant_name):
        return "applicant"
    if co_applicant_name and name_matches(bill_owner_name, co_applicant_name):
        return "co_applicant"
    if guarantor_names and any(
        name_matches(bill_owner_name, g) for g in guarantor_names
    ):
        return "guarantor"
    return "not_on_loan"


def _relation_label(gender: str | None) -> str:
    """Return the printed relationship label appropriate for the applicant.

    Aadhaar cards physically print ``C/O`` (care-of) in the address block, but
    for loan-verification output we want the semantically meaningful label:
    ``S/O`` (son of) for a male applicant, ``W/O`` (wife of) or ``D/O``
    (daughter of) for a female applicant. In rural microfinance a female
    applicant listed ``C/O`` a male name is almost always a wife — so we
    default Female to ``W/O``. Callers can pass an explicit ``relation`` if
    they have stronger evidence.
    """
    g = (gender or "").strip().lower()
    if g.startswith("m"):
        return "S/O"
    if g.startswith("f"):
        return "W/O"
    return "S/O"  # microfinance default — most applicants are male


def cross_check_ration_owner_rule(
    *,
    bill_owner_name: str | None,
    bill_father_or_husband_name: str | None,
    applicant_name: str | None,
    applicant_aadhaar_father_name: str | None = None,
    applicant_gender: str | None = None,
    co_applicant_name: str | None,
    co_applicant_aadhaar_father_name: str | None = None,
    co_applicant_gender: str | None = None,
    guarantor_names: list[str] | None = None,
) -> dict[str, Any] | None:
    """Does the ration/electricity bill legitimately establish the applicant's address?

    Decision tree (first match wins):

    1. Bill owner == applicant                           → PASS
    2. Bill owner == co-applicant                        → PASS
    3. Bill owner == applicant's father/husband          → address is attributable
       (via Aadhaar C/O or S-O / W-O). BUT loans require    via family, but the
       the house-owner to be on the hook for the loan.       owner must also be
                                                              a CO-APPLICANT or
                                                              GUARANTOR:
                                                              - if yes → PASS
                                                              - if no → CRITICAL
                                                                "add as guarantor /
                                                                 co-applicant"
    4. Bill owner == co-applicant's father/husband       → symmetric to (3) for
                                                           the co-applicant side.
    5. Legacy inverse path — bill says "owner S/O APPLICANT"
       (applicant is the owner's father, owner is a child)  → CRITICAL: bill is
                                                              in a child's name
                                                              and they must be
                                                              a co-applicant.
    6. Anything else                                     → CRITICAL (address
                                                           proof not attributable
                                                           to any loan party).
    """
    if not bill_owner_name or not applicant_name:
        return None  # can't evaluate without both

    guarantor_names = guarantor_names or []
    # Computed once and threaded into every evidence dict below so the FE
    # card always renders the bill owner's role on the loan explicitly.
    bill_owner_role = _bill_owner_loan_role(
        bill_owner_name, applicant_name, co_applicant_name, guarantor_names
    )

    # Path 1: bill owner is the applicant.
    if name_matches(bill_owner_name, applicant_name):
        return None

    # Path 2: bill owner is a declared co-applicant on the loan.
    if co_applicant_name and name_matches(bill_owner_name, co_applicant_name):
        return None

    # Path 3: bill owner is the applicant's guardian per Aadhaar
    # (C/O Sultan on Aadhaar + SULTAN on the electricity bill = same person,
    # applicant is X's son/dependent → address is attributable via family).
    # The guardian still needs to be a co-applicant or guarantor; if not, that
    # is a recoverable CRITICAL — assessor adds them on the application.
    if applicant_aadhaar_father_name and name_matches(
        bill_owner_name, applicant_aadhaar_father_name
    ):
        on_loan = (
            (co_applicant_name and name_matches(bill_owner_name, co_applicant_name))
            or any(name_matches(bill_owner_name, g) for g in guarantor_names)
        )
        if on_loan:
            return None
        rel = _relation_label(applicant_gender)
        # Build an explicit "here is what we saw" line so the assessor knows
        # this CRITICAL isn't coming from L4 (which may not have run yet) —
        # it's from an inline scan of the LAGR PDF that L1 performs on every
        # run (cached in case_extractions).
        if guarantor_names:
            scan_line = (
                "We inspected the signed loan-agreement PDF inline — the parties "
                f"listed on it are: {', '.join(guarantor_names)}. "
                f"{bill_owner_name} is not among them."
            )
        else:
            scan_line = (
                "We inspected the signed loan-agreement PDF inline — no "
                f"co-applicants or guarantors were listed, so {bill_owner_name} "
                "is definitively not on the loan."
            )
        return {
            "sub_step_id": "ration_owner_rule",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                f"Bill is in the name of {bill_owner_name}. Aadhaar lists the "
                f"applicant as {rel} {applicant_aadhaar_father_name}, so "
                f"{bill_owner_name} is the applicant's father/guardian and "
                "address attribution via the family relationship is clean. "
                f"HOWEVER, {bill_owner_name} is not listed on this loan as a "
                "co-applicant or guarantor. "
                f"{scan_line} "
                "Since the house is in their name they must be added as a "
                "co-applicant or guarantor before the loan can be disbursed."
            ),
            "evidence": {
                "bill_owner": bill_owner_name,
                "bill_owner_loan_role": bill_owner_role,
                "applicant_name": applicant_name,
                "applicant_relation_to_owner": rel,
                "applicant_aadhaar_father": applicant_aadhaar_father_name,
                "co_applicant_name": co_applicant_name,
                "guarantor_names": guarantor_names,
                "loan_agreement_parties_scanned": guarantor_names,
                "resolution": "add_guarantor_or_coapp",
            },
        }

    # Path 4: symmetric — bill owner is the co-applicant's guardian.
    if (
        co_applicant_aadhaar_father_name
        and name_matches(bill_owner_name, co_applicant_aadhaar_father_name)
    ):
        on_loan = any(
            name_matches(bill_owner_name, g) for g in guarantor_names
        ) or (co_applicant_name and name_matches(bill_owner_name, co_applicant_name))
        if on_loan:
            return None
        rel = _relation_label(co_applicant_gender)
        return {
            "sub_step_id": "ration_owner_rule",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                f"Bill is in the name of {bill_owner_name}. Aadhaar lists the "
                f"co-applicant as {rel} {co_applicant_aadhaar_father_name}, so "
                "address attribution via family is clean, BUT they must be "
                "added as co-applicant or guarantor on the loan agreement "
                "before disbursal."
            ),
            "evidence": {
                "bill_owner": bill_owner_name,
                "bill_owner_loan_role": bill_owner_role,
                "applicant_name": applicant_name,
                "co_applicant_name": co_applicant_name,
                "co_applicant_relation_to_owner": rel,
                "co_applicant_aadhaar_father": co_applicant_aadhaar_father_name,
                "guarantor_names": guarantor_names,
                "resolution": "add_guarantor_or_coapp",
            },
        }

    # Path 5 (legacy inverse): bill says "OWNER S/O APPLICANT" — owner is the
    # applicant's child. They must be a co-applicant (already rejected by Path 2
    # if the name matches co_applicant).
    related = name_is_related_via_father_husband(
        owner_name=bill_owner_name,
        father_or_husband_name=bill_father_or_husband_name,
        candidate=applicant_name,
    )
    if related:
        return {
            "sub_step_id": "ration_owner_rule",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                "Ration/electricity bill is in the name of a family member "
                f"({bill_owner_name}) who is NOT on the loan as a co-applicant. "
                "The bill owner must either be the borrower or a co-applicant."
            ),
            "evidence": {
                "bill_owner": bill_owner_name,
                "bill_owner_loan_role": bill_owner_role,
                "bill_father_or_husband": bill_father_or_husband_name,
                "applicant_name": applicant_name,
                "co_applicant_name": co_applicant_name,
                "guarantor_names": guarantor_names,
            },
        }

    # Path 5b: generic-surname tolerance. Indian utility bills frequently
    # carry the customer's first name plus a placeholder surname ("KUMAR",
    # "DEVI", "SINGH", "LAL"…) used to mask caste at sign-up time. When the
    # bill owner's first name matches the applicant / co-applicant / either
    # parent's first name AND the bill owner's surname is a known generic
    # placeholder, the strict surname mismatch is a data-entry artefact, not
    # a real identity gap — the bill IS in a relative's name.
    #
    # Soft-flag this as WARNING (not CRITICAL), with explicit
    # ``generic_surname_tolerance`` metadata so the FE can render a green
    # "tolerance applied" hint and the assessor can flip it back to a real
    # concern via the standard solution → MD adjudication flow when they
    # have ground truth that this is a stranger.
    generic_sur = has_generic_surname(bill_owner_name)
    if generic_sur is not None:
        candidates = {
            "applicant_name": applicant_name,
            "co_applicant_name": co_applicant_name,
            "applicant_aadhaar_father_name": applicant_aadhaar_father_name,
            "co_applicant_aadhaar_father_name": co_applicant_aadhaar_father_name,
        }
        first_name_match_label: str | None = None
        first_name_match_value: str | None = None
        for label, val in candidates.items():
            if first_names_match(bill_owner_name, val):
                first_name_match_label = label
                first_name_match_value = val
                break
        if first_name_match_label is not None:
            relation_friendly = {
                "applicant_name": "the applicant",
                "co_applicant_name": "the co-applicant",
                "applicant_aadhaar_father_name": "the applicant's father / guardian",
                "co_applicant_aadhaar_father_name": "the co-applicant's father / guardian",
            }[first_name_match_label]

            # When the first-name match is against a parent/guardian (not the
            # borrower or the co-applicant themselves), the relative must also
            # appear on the signed loan agreement — otherwise the tolerance
            # silently waves through a bill in a non-loan-party's name. Match
            # the parent's full name (not the bill-owner placeholder, which is
            # just first-name + generic surname) against the LAGR parties.
            matched_party_must_be_on_lagr = first_name_match_label in (
                "applicant_aadhaar_father_name",
                "co_applicant_aadhaar_father_name",
            )
            on_loan_agreement = (
                first_name_match_value is not None
                and any(
                    name_matches(first_name_match_value, g) for g in guarantor_names
                )
            )

            if matched_party_must_be_on_lagr and not on_loan_agreement:
                if guarantor_names:
                    scan_line = (
                        "We inspected the signed loan-agreement PDF inline — the "
                        f"parties listed on it are: {', '.join(guarantor_names)}. "
                        f"{first_name_match_value} is not among them, so the "
                        "first-name + generic-surname tolerance cannot be "
                        "applied: the relative giving the address authority "
                        "must be on the loan as a co-applicant or guarantor."
                    )
                else:
                    scan_line = (
                        "We inspected the signed loan-agreement PDF inline — no "
                        "co-applicants or guarantors were listed, so "
                        f"{first_name_match_value} is definitively not on the "
                        "loan and the address authority chain is broken."
                    )
                return {
                    "sub_step_id": "ration_owner_rule",
                    "severity": LevelIssueSeverity.CRITICAL.value,
                    "description": (
                        f"Ration/electricity bill owner ({bill_owner_name}) "
                        f"shares a first name with {relation_friendly} "
                        f"({first_name_match_value}) and the bill surname "
                        f"\"{generic_sur.upper()}\" is a generic Indian "
                        "data-entry placeholder. The bill might still be in a "
                        "relative's name, BUT the relative is not on the loan "
                        "agreement, so address attribution cannot be cleared "
                        f"on first-name tolerance alone. {scan_line} Add "
                        f"{first_name_match_value} as a co-applicant or "
                        "guarantor on the loan, or supply a replacement "
                        "address proof in the borrower's own name."
                    ),
                    "evidence": {
                        "bill_owner": bill_owner_name,
                        "bill_owner_loan_role": bill_owner_role,
                        "applicant_name": applicant_name,
                        "co_applicant_name": co_applicant_name,
                        "applicant_aadhaar_father": applicant_aadhaar_father_name,
                        "co_applicant_aadhaar_father": co_applicant_aadhaar_father_name,
                        "guarantor_names": guarantor_names,
                        "loan_agreement_parties_scanned": guarantor_names,
                        "generic_surname_tolerance": {
                            "generic_surname": generic_sur,
                            "first_name_matched_against": first_name_match_label,
                            "matched_value": first_name_match_value,
                            "on_loan_agreement": False,
                        },
                        "resolution": "add_guarantor_or_coapp",
                    },
                }

            return {
                "sub_step_id": "ration_owner_rule",
                "severity": LevelIssueSeverity.WARNING.value,
                "description": (
                    f"Ration/electricity bill owner ({bill_owner_name}) shares "
                    f"a first name with {relation_friendly} "
                    f"({first_name_match_value}); the bill surname "
                    f"\"{generic_sur.upper()}\" is a placeholder commonly used in "
                    "Indian utility-bill data-entry to mask caste. Address "
                    "attribution is treated as clean under this tolerance — "
                    "flag as a real concern only if you have ground truth that "
                    "this is a stranger, not a relative."
                ),
                "evidence": {
                    "bill_owner": bill_owner_name,
                    "bill_owner_loan_role": bill_owner_role,
                    "applicant_name": applicant_name,
                    "co_applicant_name": co_applicant_name,
                    "applicant_aadhaar_father": applicant_aadhaar_father_name,
                    "co_applicant_aadhaar_father": co_applicant_aadhaar_father_name,
                    "guarantor_names": guarantor_names,
                    "loan_agreement_parties_scanned": guarantor_names,
                    "generic_surname_tolerance": {
                        "generic_surname": generic_sur,
                        "first_name_matched_against": first_name_match_label,
                        "matched_value": first_name_match_value,
                        "on_loan_agreement": on_loan_agreement,
                    },
                },
            }

    # Path 6: owner is neither applicant nor co-applicant nor a declared family
    # relation → address proof is not attributable to the loan.
    return {
        "sub_step_id": "ration_owner_rule",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"Ration/electricity bill owner ({bill_owner_name}) is not the "
            "borrower, not a co-applicant, and has no declared relationship "
            "to the borrower. The address proof is not attributable to the loan."
        ),
        "evidence": {
            "bill_owner": bill_owner_name,
            "bill_owner_loan_role": bill_owner_role,
            "applicant_name": applicant_name,
            "co_applicant_name": co_applicant_name,
            "guarantor_names": guarantor_names,
        },
    }


def cross_check_business_gps_present(
    *,
    business_gps_coords: tuple[float, float] | None,
    photos_tried_count: int = 0,
) -> dict[str, Any] | None:
    """Sub-step 3a': every case needs coordinates from at least one
    BUSINESS_PREMISES_PHOTO. Without them we cannot run the commute check, so
    we block the level with an MD-only CRITICAL rather than letting the file
    pass on partial geography.

    ``photos_tried_count`` is reported back in the evidence so the MD can see
    how many BUSINESS_PREMISES_PHOTO artifacts the extractor walked over
    before giving up (separates "no photo at all" from "several photos, none
    with usable EXIF / overlay").
    """
    if business_gps_coords is not None:
        return None
    return {
        "sub_step_id": "business_visit_gps",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "Business-visit photo GPS could not be recovered — no "
            "BUSINESS_PREMISES_PHOTO artifact yielded coordinates via EXIF "
            "or via the GPS-Map-Camera burn-in overlay. Upload a "
            "business-premises photo with intact EXIF or a legible overlay, "
            "or MD-approve this case on the specific context."
        ),
        "evidence": {
            "photos_tried_count": photos_tried_count,
        },
    }


def cross_check_commute(
    *,
    travel_minutes: float | None,
    distance_km: float | None,
    dm_status: str,
    judge_verdict: dict[str, Any] | None,
    judge_attempted: bool = False,
) -> dict[str, Any] | None:
    """Sub-step 3b: travel-time sanity check between house GPS and business GPS.

    ``dm_status`` values:
      - "ok"            → Distance Matrix returned a concrete duration.
      - "zero_results"  → coordinates are valid but no drivable route exists
                          between them (CRITICAL: almost always garbage coords).
      - "error"         → Distance Matrix itself failed (network, key denied,
                          non-OK top-level status) — WARNING, not CRITICAL.

    When ``travel_minutes > 30`` the orchestrator invokes the Opus judge and
    passes its verdict in ``judge_verdict``. If the judge was attempted but
    failed (``judge_attempted=True`` and ``judge_verdict is None``), we
    downgrade to a WARNING so a flaky model call never blocks a case.
    """
    # Infra / data failures — decided before the 30-min threshold matters.
    if dm_status == "zero_results":
        return {
            "sub_step_id": "house_business_commute",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                "No drivable route was found between the house-visit and "
                "business-visit coordinates. The coordinates may be invalid "
                "or separated by water / a restricted area — investigate "
                "before releasing the file."
            ),
            "evidence": {
                "dm_status": dm_status,
                "threshold_min": 30.0,
            },
        }
    if dm_status == "error":
        return {
            "sub_step_id": "house_business_commute",
            "severity": LevelIssueSeverity.WARNING.value,
            "description": (
                "Google Distance Matrix was unavailable while checking the "
                "house-to-business commute. Re-run Level 1 or verify the "
                "commute manually on a map."
            ),
            "evidence": {
                "dm_status": dm_status,
                "threshold_min": 30.0,
            },
        }

    # Happy path — under the 30-min cap.
    if travel_minutes is None or travel_minutes <= 30.0:
        return None

    # Over 30 min — either the judge ran and returned a verdict, or it was
    # attempted and failed. Either way the floor is WARNING.
    if judge_verdict is None:
        return {
            "sub_step_id": "house_business_commute",
            "severity": LevelIssueSeverity.WARNING.value,
            "description": (
                f"House-to-business commute is {travel_minutes:.0f} min "
                f"({(distance_km or 0):.1f} km by road), which exceeds the "
                "30-minute cap. The AI commute judge was "
                + ("unavailable" if judge_attempted else "not invoked")
                + " — please review the profile manually and close with a "
                "written justification."
            ),
            "evidence": {
                "travel_minutes": travel_minutes,
                "distance_km": distance_km,
                "judge_attempted": judge_attempted,
                "threshold_min": 30.0,
            },
        }

    sev = str(judge_verdict.get("severity") or "").upper()
    reason = str(judge_verdict.get("reason") or "").strip()
    if sev not in ("WARNING", "CRITICAL"):
        # Schema violation from the judge — treat as unavailable.
        return {
            "sub_step_id": "house_business_commute",
            "severity": LevelIssueSeverity.WARNING.value,
            "description": (
                f"House-to-business commute is {travel_minutes:.0f} min "
                f"({(distance_km or 0):.1f} km by road). The AI commute "
                "judge returned an invalid verdict — please review manually."
            ),
            "evidence": {
                "travel_minutes": travel_minutes,
                "distance_km": distance_km,
                "judge_verdict_raw": judge_verdict,
                "threshold_min": 30.0,
            },
        }

    severity = (
        LevelIssueSeverity.CRITICAL.value
        if sev == "CRITICAL"
        else LevelIssueSeverity.WARNING.value
    )
    verdict_label = "BLOCK" if sev == "CRITICAL" else "FLAG"
    return {
        "sub_step_id": "house_business_commute",
        "severity": severity,
        "description": (
            f"House-to-business commute is {travel_minutes:.0f} min "
            f"({(distance_km or 0):.1f} km by road) — exceeds the 30-minute "
            f"cap. Opus {verdict_label}: {reason}"
        ),
        "evidence": {
            "travel_minutes": travel_minutes,
            "distance_km": distance_km,
            "judge_verdict": judge_verdict,
            "threshold_min": 30.0,
        },
    }


def cross_check_aadhaar_vs_bureau_bank(
    *,
    aadhaar_address: str | None,
    bureau_addresses: list[str],
    bank_addresses: list[str],
) -> list[dict[str, Any]]:
    """Return an issue per mismatch (bureau or bank). Skips the check entirely
    when Aadhaar address is missing (that's an upstream issue).
    """
    if not aadhaar_address:
        return []

    issues: list[dict[str, Any]] = []

    if bureau_addresses and not any(
        addresses_match(aadhaar_address, b) for b in bureau_addresses
    ):
        # Show all bureau addresses we checked against — lets the MD see
        # whether it's one stale address (bureau not updated) vs. all three
        # differing (likely stale Aadhaar).
        bureau_lines = "\n".join(f"  – {b}" for b in bureau_addresses[:4])
        issues.append(
            {
                "sub_step_id": "aadhaar_vs_bureau_address",
                "severity": LevelIssueSeverity.WARNING.value,
                "description": (
                    "Applicant Aadhaar address does not match any address on "
                    "the Equifax/bureau report. May indicate stale bureau record "
                    "or applicant recently moved.\n\n"
                    f"• Aadhaar address: {aadhaar_address}\n"
                    f"• Bureau addresses on file ({len(bureau_addresses)}):\n"
                    f"{bureau_lines}"
                ),
                "evidence": {
                    "aadhaar_address": aadhaar_address,
                    "bureau_addresses": bureau_addresses,
                    "match_threshold": 0.85,
                },
            }
        )

    if bank_addresses and not any(
        addresses_match(aadhaar_address, b) for b in bank_addresses
    ):
        bank_lines = "\n".join(f"  – {b}" for b in bank_addresses[:4])
        issues.append(
            {
                "sub_step_id": "aadhaar_vs_bank_address",
                "severity": LevelIssueSeverity.WARNING.value,
                "description": (
                    "Applicant Aadhaar address does not match the bank-statement "
                    "registered address. Bank KYC may be out of date.\n\n"
                    f"• Aadhaar address: {aadhaar_address}\n"
                    f"• Bank-statement address{'es' if len(bank_addresses) != 1 else ''}:\n"
                    f"{bank_lines}"
                ),
                "evidence": {
                    "aadhaar_address": aadhaar_address,
                    "bank_addresses": bank_addresses,
                    "match_threshold": 0.85,
                },
            }
        )

    return issues


# ───────────────────── Sub-step 3b orchestration helper ─────────────────────
#
# Extracted for testability: the big orchestrator below delegates the commute
# decision to this async helper, which is pure apart from its two injected
# dependencies (Distance Matrix fn, judge fn). Unit-tested in
# ``tests/unit/test_verification_commute_sub_step.py``.


def _rebuild_issue_from_cached_status(
    *,
    travel_minutes: float | None,
    distance_km: float | None,
    judge_verdict: dict[str, Any] | None,
    status: str,
) -> dict[str, Any] | None:
    """Replay a cached commute verdict as the equivalent LevelIssue.

    Used when the coord pair is unchanged from a prior L1 run: instead of
    paying for Distance Matrix + Opus again, we look up the prior
    ``commute_sub_step_status`` and reconstruct the same issue that the
    original run would have emitted. Status values that don't emit an
    issue (``pass``, ``skipped_*``) return None.
    """
    if status == "warn_dm_unavailable":
        return cross_check_commute(
            travel_minutes=None,
            distance_km=None,
            dm_status="error",
            judge_verdict=None,
        )
    if status == "block_no_route":
        return cross_check_commute(
            travel_minutes=None,
            distance_km=None,
            dm_status="zero_results",
            judge_verdict=None,
        )
    if status == "warn_judge_unavailable":
        return cross_check_commute(
            travel_minutes=travel_minutes,
            distance_km=distance_km,
            dm_status="ok",
            judge_verdict=None,
            judge_attempted=True,
        )
    if status in ("flag_reviewable", "block_absurd"):
        return cross_check_commute(
            travel_minutes=travel_minutes,
            distance_km=distance_km,
            dm_status="ok",
            judge_verdict=judge_verdict,
            judge_attempted=True,
        )
    return None


def _coords_equal_rounded(
    a: tuple[float, float] | None,
    b: tuple[float, float] | None,
    *,
    places: int = 5,
) -> bool:
    """GPS noise is ~1-5 m even on clean EXIF. Compare at 5 decimal places
    (~1.1 m resolution at the equator) — tight enough to detect "this is a
    different photo" and loose enough to cover jitter within the same spot.
    """
    if a is None or b is None:
        return False
    return (
        round(a[0], places) == round(b[0], places)
        and round(a[1], places) == round(b[1], places)
    )


async def _compute_commute_sub_step(
    *,
    house_coords: tuple[float, float] | None,
    business_coords: tuple[float, float] | None,
    prior_house_coords: tuple[float, float] | None,
    prior_business_coords: tuple[float, float] | None,
    prior_commute_fields: dict[str, Any] | None,
    profile_inputs: dict[str, Any],
    claude: Any,
    api_key: str | None,
    distance_matrix_fn: Callable[..., Any] | None = None,
    judge_fn: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], Decimal]:
    """Returns ``(fields_to_merge, issues_to_emit, extra_cost_usd)``.

    Orchestration:
      1. If prior run saw the same coord pair, copy its commute fields and
         re-emit the same issue (if any). No DM / judge calls.
      2. Otherwise call Distance Matrix. Handle ZERO_RESULTS (CRITICAL) /
         infra-error (WARNING) exits.
      3. If travel_minutes ≤ 30 → pass. No judge call.
      4. If travel_minutes > 30 → call Opus judge, then delegate issue
         construction to ``cross_check_commute``.
    """
    # Lazy defaults so tests can inject mocks without pulling the real
    # network-backed functions into module import.
    if distance_matrix_fn is None:
        from app.verification.services.google_maps import distance_matrix_driving

        distance_matrix_fn = distance_matrix_driving
    if judge_fn is None:
        from app.verification.services.commute_judge import (
            judge_commute_reasonableness,
        )

        judge_fn = judge_commute_reasonableness

    fields: dict[str, Any] = {
        "commute_distance_km": None,
        "commute_travel_minutes": None,
        "commute_judge_verdict": None,
        "commute_sub_step_status": "pass",
    }
    issues: list[dict[str, Any]] = []
    cost = Decimal("0")

    # Cache hit: both coord pairs unchanged → reuse the prior verdict.
    cache_hit = (
        prior_commute_fields is not None
        and _coords_equal_rounded(house_coords, prior_house_coords)
        and _coords_equal_rounded(business_coords, prior_business_coords)
    )
    if cache_hit:
        for k in (
            "commute_distance_km",
            "commute_travel_minutes",
            "commute_judge_verdict",
            "commute_sub_step_status",
        ):
            if k in prior_commute_fields:
                fields[k] = prior_commute_fields[k]
        # Rebuild the issue from the cached status. We CANNOT just hardcode
        # dm_status="ok" here — prior runs legitimately include infra
        # failures (warn_dm_unavailable, block_no_route), and replaying them
        # as "ok" with travel_minutes=None would silently drop the warning.
        rebuilt = _rebuild_issue_from_cached_status(
            travel_minutes=fields["commute_travel_minutes"],
            distance_km=fields["commute_distance_km"],
            judge_verdict=fields["commute_judge_verdict"],
            status=str(fields.get("commute_sub_step_status") or ""),
        )
        if rebuilt is not None:
            issues.append(rebuilt)
        return fields, issues, cost

    # No cache — call Distance Matrix.
    if house_coords is None or business_coords is None:
        # Caller is supposed to skip us when either side is missing, but be
        # defensive — status stays "pass" with no issue emitted here (the
        # missing-GPS issues are raised elsewhere by the caller).
        return fields, issues, cost

    dm = await distance_matrix_fn(
        origin_lat=house_coords[0],
        origin_lon=house_coords[1],
        dest_lat=business_coords[0],
        dest_lon=business_coords[1],
        api_key=api_key,
    )

    if dm is None:
        # Infra failure — WARNING.
        fields["commute_sub_step_status"] = "warn_dm_unavailable"
        iss = cross_check_commute(
            travel_minutes=None,
            distance_km=None,
            dm_status="error",
            judge_verdict=None,
        )
        if iss is not None:
            issues.append(iss)
        return fields, issues, cost

    fields["commute_distance_km"] = dm.distance_km
    fields["commute_travel_minutes"] = dm.travel_minutes

    if dm.raw_status in ("zero_results", "not_found"):
        fields["commute_sub_step_status"] = "block_no_route"
        iss = cross_check_commute(
            travel_minutes=None,
            distance_km=None,
            dm_status="zero_results",
            judge_verdict=None,
        )
        if iss is not None:
            issues.append(iss)
        return fields, issues, cost

    # DM succeeded. Apply the 30-min rule.
    if dm.travel_minutes <= 30.0:
        fields["commute_sub_step_status"] = "pass"
        return fields, issues, cost

    # Over 30 min — invoke the Opus judge.
    verdict = await judge_fn(
        travel_minutes=dm.travel_minutes,
        distance_km=dm.distance_km,
        claude=claude,
        **profile_inputs,
    )

    if verdict is None:
        fields["commute_sub_step_status"] = "warn_judge_unavailable"
        iss = cross_check_commute(
            travel_minutes=dm.travel_minutes,
            distance_km=dm.distance_km,
            dm_status="ok",
            judge_verdict=None,
            judge_attempted=True,
        )
        if iss is not None:
            issues.append(iss)
        return fields, issues, cost

    verdict_dict = {
        "severity": verdict.severity,
        "reason": verdict.reason,
        "confidence": verdict.confidence,
        "model_used": verdict.model_used,
        "cost_usd": str(verdict.cost_usd),
    }
    fields["commute_judge_verdict"] = verdict_dict
    fields["commute_sub_step_status"] = (
        "block_absurd" if verdict.severity == "CRITICAL" else "flag_reviewable"
    )
    cost += verdict.cost_usd

    iss = cross_check_commute(
        travel_minutes=dm.travel_minutes,
        distance_km=dm.distance_km,
        dm_status="ok",
        judge_verdict=verdict_dict,
        judge_attempted=True,
    )
    if iss is not None:
        issues.append(iss)
    return fields, issues, cost


# ───────────────────────────── Pass-evidence helper ─────────────────────────
#
# Mirrors Part A's ``build_pass_evidence`` in level_3_vision. Populates
# ``sub_step_results.pass_evidence`` for every L1 rule that DIDN'T fire so the
# FE's pass-detail dispatcher can render structured cards on click-to-expand.
#
# Keys MUST match the rule's ``sub_step_id`` exactly — the FE lookup is keyed
# on that and silently falls through to the "no pass-detail" placeholder on
# any mismatch. Each entry also carries ``source_artifacts`` on the same
# fire-path shape so ``LevelSourceFilesPanel`` aggregates passes + concerns.
#
# If the orchestrator call-site doesn't have a piece of in-scope data (e.g.
# the structured GPSMatch is only built on the Nominatim path), that entry
# is simply skipped rather than invented. The cross-check itself already
# returned None in that scenario, so the rule isn't "passing" in a
# meaningful sense — just un-evaluated.


def build_pass_evidence_l1(
    *,
    applicant_address: str | None,
    co_applicant_address: str | None,
    applicant_aadhaar_address: str | None,
    gps_derived_address: str | None,
    gps_coords: tuple[float, float] | None,
    gps_match: Any | None,  # services.address_normalizer.GPSMatch
    bill_owner: str | None,
    bill_father_or_husband: str | None,
    applicant_name: str | None,
    co_applicant_name: str | None,
    guarantor_names: list[str] | None = None,
    business_gps_coords: tuple[float, float] | None,
    photos_tried_count: int,
    travel_minutes: float | None,
    distance_km: float | None,
    bureau_addresses: list[str],
    bank_addresses: list[str],
    fired_rules: set[str],
    applicant_aadhaar_art: CaseArtifact | None,
    gps_house_art: CaseArtifact | None,
    gps_biz_art: CaseArtifact | None,
    bill_art: CaseArtifact | None,
    co_aadhaar_art: CaseArtifact | None,
    lagr_art: CaseArtifact | None,
    bureau_art: CaseArtifact | None,
    bank_art: CaseArtifact | None,
) -> dict[str, Any]:
    """Return the ``sub_step_results.pass_evidence`` dict for L1.

    One entry per L1 ``sub_step_id`` in ``RULE_CATALOG.L1_ADDRESS`` that
    PASSED (or where there is meaningful data to show). Rules in
    ``fired_rules`` are omitted — their evidence lives on ``LevelIssue``.

    If a piece of in-scope data isn't available at the call-site (e.g. no
    ration bill uploaded → no bill_owner), the corresponding entry is
    skipped rather than invented. The cross-check itself returned None in
    that scenario, so the rule isn't truly "passing" either.
    """
    out: dict[str, Any] = {}

    # applicant_coapp_address_match — only meaningful when both addresses
    # exist (otherwise cross-check returned None for "can't evaluate").
    if (
        "applicant_coapp_address_match" not in fired_rules
        and applicant_address
        and co_applicant_address
    ):
        out["applicant_coapp_address_match"] = {
            "applicant_address": applicant_address,
            "co_applicant_address": co_applicant_address,
            "match_threshold": 0.85,
            "verdict": "match",
        }

    # gps_vs_aadhaar — need Aadhaar address + EITHER coords or gps_match.
    # When gps_match is available (Nominatim path) embed its full to_dict()
    # payload alongside the display fields so the FE can render the structured
    # district/village breakdown. Fallback shows coords only.
    if (
        "gps_vs_aadhaar" not in fired_rules
        and applicant_aadhaar_address
        and (gps_coords is not None or gps_match is not None)
    ):
        entry: dict[str, Any] = {
            "applicant_aadhaar_address": applicant_aadhaar_address,
            "gps_derived_address": gps_derived_address,
        }
        if gps_coords is not None:
            entry["gps_coords"] = [gps_coords[0], gps_coords[1]]
        if gps_match is not None and hasattr(gps_match, "to_dict"):
            entry["gps_match"] = gps_match.to_dict()
        sources = _pack(
            _ref(
                applicant_aadhaar_art,
                relevance="Applicant Aadhaar — address field",
                highlight_field="address",
            ),
            _ref(
                gps_house_art,
                relevance="House-visit photo (GPS source)",
                highlight_field="gps_watermark",
            ),
        )
        if sources:
            entry["source_artifacts"] = sources
        out["gps_vs_aadhaar"] = entry

    # ration_owner_rule — meaningful when bill_owner + applicant_name both
    # exist (cross-check skips otherwise). "clean" verdict covers every
    # pass path the ration owner decision tree produces.
    if (
        "ration_owner_rule" not in fired_rules
        and bill_owner
        and applicant_name
    ):
        sources = _pack(
            _ref(
                bill_art,
                relevance="Ration / electricity bill — owner name line",
                highlight_field="owner_name",
            ),
            _ref(
                applicant_aadhaar_art,
                relevance="Applicant Aadhaar — name & S/O field",
                highlight_field="name",
            ),
            _ref(
                co_aadhaar_art,
                relevance="Co-applicant Aadhaar — name & S/O field",
                highlight_field="name",
            ),
            _ref(
                lagr_art,
                relevance="Loan agreement — parties section",
                highlight_field="parties",
            ),
        )
        _guarantor_names_list = guarantor_names or []
        entry = {
            "bill_owner": bill_owner,
            "bill_owner_loan_role": _bill_owner_loan_role(
                bill_owner, applicant_name, co_applicant_name, _guarantor_names_list
            ),
            "bill_father_or_husband": bill_father_or_husband,
            "applicant_name": applicant_name,
            "co_applicant_name": co_applicant_name,
            "guarantor_names": _guarantor_names_list,
            "verdict": "clean",
        }
        if sources:
            entry["source_artifacts"] = sources
        out["ration_owner_rule"] = entry

    # business_visit_gps — only populate when coords were recovered (the
    # rule fires the moment they're missing, so a "pass" means we had them).
    if (
        "business_visit_gps" not in fired_rules
        and business_gps_coords is not None
    ):
        sources = _pack(
            _ref(
                gps_biz_art,
                relevance="Business premises photo (GPS source)",
                highlight_field="gps_watermark",
            ),
        )
        entry = {
            "business_gps_coords": [business_gps_coords[0], business_gps_coords[1]],
            "photos_tried_count": photos_tried_count,
        }
        if sources:
            entry["source_artifacts"] = sources
        out["business_visit_gps"] = entry

    # house_business_commute — need a concrete travel_minutes under the cap.
    # When DM failed or the judge ran, the fire-path already captured it on
    # LevelIssue.evidence; we only narrate the happy path here.
    if (
        "house_business_commute" not in fired_rules
        and travel_minutes is not None
        and travel_minutes <= 30.0
    ):
        sources = _pack(
            _ref(
                gps_house_art,
                relevance="House-visit photo (house GPS)",
                highlight_field="gps_watermark",
            ),
            _ref(
                gps_biz_art,
                relevance="Business premises photo (business GPS)",
                highlight_field="gps_watermark",
            ),
        )
        entry = {
            "travel_minutes": travel_minutes,
            "distance_km": distance_km,
            "dm_status": "ok",
            "threshold_min": 30.0,
            "under_threshold": True,
        }
        if sources:
            entry["source_artifacts"] = sources
        out["house_business_commute"] = entry

    # aadhaar_vs_bureau_address — emit an entry whenever the rule didn't fire
    # AND we know a bureau report is on the case (so the assessor can verify
    # the source). When the bureau extractor produced no addresses for us to
    # cross-check, the entry still carries the source files + a
    # ``no_bureau_addresses_extracted`` verdict — better than rendering "No
    # additional pass-detail available" with no link to the bureau HTML at all.
    if "aadhaar_vs_bureau_address" not in fired_rules and (
        applicant_aadhaar_art is not None or bureau_art is not None
    ):
        sources = _pack(
            _ref(
                applicant_aadhaar_art,
                relevance="Applicant Aadhaar — address field",
                highlight_field="address",
            ),
            _ref(
                bureau_art,
                relevance="Bureau report — address block",
                highlight_field="address",
            ),
        )
        entry = {
            "aadhaar_address": applicant_aadhaar_address,
            "bureau_addresses": list(bureau_addresses),
            "match_threshold": 0.85,
            "verdict": (
                "matched"
                if applicant_aadhaar_address and bureau_addresses
                else "no_bureau_addresses_extracted"
            ),
        }
        if sources:
            entry["source_artifacts"] = sources
        out["aadhaar_vs_bureau_address"] = entry

    # aadhaar_vs_bank_address — symmetric to bureau.
    if "aadhaar_vs_bank_address" not in fired_rules and (
        applicant_aadhaar_art is not None or bank_art is not None
    ):
        sources = _pack(
            _ref(
                applicant_aadhaar_art,
                relevance="Applicant Aadhaar — address field",
                highlight_field="address",
            ),
            _ref(
                bank_art,
                relevance="Bank statement — registered address",
                highlight_field="address",
            ),
        )
        entry = {
            "aadhaar_address": applicant_aadhaar_address,
            "bank_addresses": list(bank_addresses),
            "match_threshold": 0.85,
            "verdict": (
                "matched"
                if applicant_aadhaar_address and bank_addresses
                else "no_bank_addresses_extracted"
            ),
        }
        if sources:
            entry["source_artifacts"] = sources
        out["aadhaar_vs_bank_address"] = entry

    return out


# ───────────────────────────── Orchestrator ─────────────────────────────────


async def run_level_1_address(
    session: AsyncSession,
    case_id: UUID,
    *,
    actor_user_id: UUID,
    claude: Any,
    storage: Any,
    api_key: str | None,
) -> VerificationResult:
    """Run Level 1 on ``case_id`` and persist the result + any issues.

    Returns the created ``VerificationResult`` (status PASSED / BLOCKED / FAILED).

    Requires (via DI):
    - ``claude`` — async ``ClaudeService`` for vision scanners.
    - ``storage`` — an object with ``await get_bytes(key)`` returning ``bytes``
      for a case artifact (the project's ``StorageService``).
    - ``api_key`` — Google Maps key.
    """
    from app.enums import ArtifactSubtype
    from app.verification.services.exif import extract_gps_from_exif
    from app.verification.services.google_maps import (
        forward_geocode,
        haversine_km,
        reverse_geocode,
    )
    from app.worker.extractors.aadhaar_scanner import AadhaarScanner
    from app.worker.extractors.pan_scanner import PanScanner
    from app.worker.extractors.ration_bill_scanner import RationBillScanner

    # 1. Create in-flight result row
    started = datetime.now(UTC)
    result = VerificationResult(
        case_id=case_id,
        level_number=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.RUNNING,
        started_at=started,
        triggered_by=actor_user_id,
    )
    session.add(result)
    await session.flush()

    # 2. Gather artifacts grouped by subtype
    artifacts = (
        (await session.execute(select(CaseArtifact).where(CaseArtifact.case_id == case_id)))
        .scalars()
        .all()
    )

    def _sub(a: CaseArtifact) -> str | None:
        meta = a.metadata_json or {}
        return meta.get("subtype")

    by_subtype: dict[str, list[CaseArtifact]] = {}
    for a in artifacts:
        s = _sub(a)
        if s:
            by_subtype.setdefault(s, []).append(a)

    total_cost: Decimal = Decimal("0")
    sub_step_results: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []

    aadhaar_scanner = AadhaarScanner(claude=claude)
    pan_scanner = PanScanner(claude=claude)
    ration_scanner = RationBillScanner(claude=claude)

    # Single-doc snapshot used by the cross-checks. ``raw_scans`` holds every
    # persisted scan for audit; ``merged`` pulls the first non-null value per
    # field across the snapshots (handles front + back of an Aadhaar card).
    class _Merged:  # tiny struct, lighter than a Pydantic model for in-loop use
        __slots__ = (
            "extracted_name",
            "extracted_father_name",
            "extracted_address",
            "extracted_number",
            "extracted_dob",
            "extracted_gender",
            "id",
        )

        def __init__(self) -> None:
            self.extracted_name = None
            self.extracted_father_name = None
            self.extracted_address = None
            self.extracted_number = None
            self.extracted_dob = None
            self.extracted_gender = None
            self.id = None

    async def _scan_and_persist(
        artifact: CaseArtifact, doc_type: DocType, party: Party, scanner: Any
    ) -> L1ExtractedDocument | None:
        try:
            body = await storage.download_object(artifact.s3_key)
        except Exception as exc:  # noqa: BLE001
            _log.warning("L1: storage fetch failed for %s: %s", artifact.s3_key, exc)
            return None

        res = await scanner.extract(artifact.filename, body)
        extracted = L1ExtractedDocument(
            case_id=case_id,
            artifact_id=artifact.id,
            doc_type=doc_type,
            party=party,
            extracted_name=res.data.get("name"),
            extracted_father_name=res.data.get("father_name"),
            extracted_address=res.data.get("address"),
            extracted_number=res.data.get("aadhaar_number")
            or res.data.get("pan_number")
            or res.data.get("document_number"),
            extracted_dob=None,  # string DOB is stored in raw_vision_json; date parse is a polish follow-up
            extracted_gender=res.data.get("gender"),
            raw_vision_json={**(res.data.get("usage") or {}), "dob_raw": res.data.get("dob")},
            model_used=res.data.get("model_used"),
            cost_usd=Decimal(str(res.data.get("cost_usd") or "0")),
            error_message=res.error_message,
        )
        session.add(extracted)
        await session.flush()
        return extracted

    async def _scan_all_and_merge(
        artifacts: list[CaseArtifact], doc_type: DocType, party: Party, scanner: Any
    ) -> tuple[_Merged | None, Decimal]:
        scans: list[L1ExtractedDocument] = []
        cost = Decimal("0")
        for art in artifacts:
            doc = await _scan_and_persist(art, doc_type, party, scanner)
            if doc:
                scans.append(doc)
                cost += doc.cost_usd or Decimal("0")
        if not scans:
            return None, cost

        merged = _Merged()
        # Prefer the first non-null value across scans (order = artifact upload order).
        for field in (
            "extracted_name",
            "extracted_father_name",
            "extracted_address",
            "extracted_number",
            "extracted_dob",
            "extracted_gender",
        ):
            for d in scans:
                val = getattr(d, field)
                if val:
                    setattr(merged, field, val)
                    break
        # ``id`` tracks the most-complete scan for UI "evidence popover" links.
        most_complete = max(
            scans,
            key=lambda d: sum(
                1
                for f in ("extracted_name", "extracted_address", "extracted_number")
                if getattr(d, f)
            ),
        )
        merged.id = most_complete.id
        return merged, cost

    # --- Sub-step 1: scan IDs (front + back of each Aadhaar, etc.) ---
    applicant_aadhaar, c = await _scan_all_and_merge(
        by_subtype.get(ArtifactSubtype.KYC_AADHAAR.value, []),
        DocType.AADHAAR,
        Party.APPLICANT,
        aadhaar_scanner,
    )
    total_cost += c
    co_applicant_aadhaar, c = await _scan_all_and_merge(
        by_subtype.get(ArtifactSubtype.CO_APPLICANT_AADHAAR.value, []),
        DocType.AADHAAR,
        Party.CO_APPLICANT,
        aadhaar_scanner,
    )
    total_cost += c
    applicant_pan, c = await _scan_all_and_merge(
        by_subtype.get(ArtifactSubtype.KYC_PAN.value, []),
        DocType.PAN,
        Party.APPLICANT,
        pan_scanner,
    )
    total_cost += c
    co_applicant_pan, c = await _scan_all_and_merge(
        by_subtype.get(ArtifactSubtype.CO_APPLICANT_PAN.value, []),
        DocType.PAN,
        Party.CO_APPLICANT,
        pan_scanner,
    )
    total_cost += c

    ration_bill: _Merged | None = None
    for sub_t, dt in (
        (ArtifactSubtype.RATION_CARD.value, DocType.RATION),
        (ArtifactSubtype.ELECTRICITY_BILL.value, DocType.ELECTRICITY_BILL),
    ):
        merged, c = await _scan_all_and_merge(
            by_subtype.get(sub_t, []), dt, Party.APPLICANT, ration_scanner
        )
        total_cost += c
        if merged is not None:
            ration_bill = ration_bill or merged

    # --- Sub-step 2: applicant ↔ co-applicant Aadhaar address ---
    # Forward-geocode both to compute the great-circle distance — surfaced in
    # the issue evidence so the assessor / MD can distinguish "200 m apart"
    # (joint family compound, photo angle) from "50 km apart" (different
    # address altogether). Skipped silently if the geocoder fails.
    coapp_distance_km: float | None = None
    if (
        applicant_aadhaar
        and co_applicant_aadhaar
        and applicant_aadhaar.extracted_address
        and co_applicant_aadhaar.extracted_address
    ):
        try:
            a_pt = await forward_geocode(
                address=applicant_aadhaar.extracted_address, api_key=api_key
            )
            b_pt = await forward_geocode(
                address=co_applicant_aadhaar.extracted_address, api_key=api_key
            )
            if a_pt and b_pt:
                coapp_distance_km = haversine_km(a_pt[0], a_pt[1], b_pt[0], b_pt[1])
        except Exception:  # noqa: BLE001 — geocoder must never crash the level
            coapp_distance_km = None

    iss = cross_check_applicant_coapplicant_aadhaar_addresses(
        applicant_aadhaar.extracted_address if applicant_aadhaar else None,
        co_applicant_aadhaar.extracted_address if co_applicant_aadhaar else None,
        distance_km=coapp_distance_km,
    )
    if iss:
        # Cite the two Aadhaar PDFs the addresses were extracted from so the
        # MD can open them side-by-side instead of being told the addresses
        # mismatch with no way to verify. Both are pulled from ``by_subtype``
        # (already populated above) and either may be None for partial
        # uploads — _ref / _pack tolerate None and skip silently.
        applicant_aadhaar_art = _first(
            by_subtype.get(ArtifactSubtype.KYC_AADHAAR.value, [])
        )
        co_applicant_aadhaar_art = _first(
            by_subtype.get(ArtifactSubtype.CO_APPLICANT_AADHAAR.value, [])
        )
        iss.setdefault("evidence", {})["source_artifacts"] = _pack(
            _ref(
                applicant_aadhaar_art,
                relevance="Applicant Aadhaar — address field",
                highlight_field="address",
            ),
            _ref(
                co_applicant_aadhaar_art,
                relevance="Co-applicant Aadhaar — address field",
                highlight_field="address",
            ),
        )
        issues.append(iss)

    # --- Sub-step 3: GPS reverse-geocode ---
    # Try EXIF first; if the photo was taken by an Indian field-ops app (GPS
    # Map Camera, etc.) that burns the coordinates into the pixels as a
    # visual overlay, fall back to Claude Haiku vision OCR on the watermark.
    # WhatsApp strips EXIF but the overlay survives.
    from app.verification.services.address_normalizer import (
        GPSMatch,
        compare_aadhaar_to_gps,
    )
    from app.verification.services.gps_watermark import (
        extract_gps_from_visual_watermark,
    )
    from app.verification.services.nominatim import (
        GPSAddress,
        reverse_geocode_nominatim,
    )

    gps_addr: str | None = None
    gps_addr_source: str | None = None  # "google" | "nominatim" | None
    gps_nominatim: GPSAddress | None = None  # structured, only when nominatim succeeds
    gps_coords: tuple[float, float] | None = None
    gps_source: str | None = None
    gps_watermark_meta: dict[str, Any] | None = None
    # Track the HOUSE_VISIT_PHOTO that actually yielded GPS so the UI
    # "View source" button points to the exact photo, not all of them.
    gps_house_artifact: CaseArtifact | None = None

    for art in by_subtype.get(ArtifactSubtype.HOUSE_VISIT_PHOTO.value, []):
        try:
            body = await storage.download_object(art.s3_key)
        except Exception:
            continue

        # Path A — EXIF GPS (desktop camera / original capture)
        candidate = extract_gps_from_exif(body)
        source_this_photo: str | None = None
        watermark_meta: dict[str, Any] | None = None
        if candidate:
            source_this_photo = "exif"
        else:
            # Path B — visual watermark OCR (field-ops app)
            wm = await extract_gps_from_visual_watermark(
                image_bytes=body, filename=art.filename, claude=claude
            )
            if wm is not None:
                candidate = (wm.lat, wm.lon)
                source_this_photo = "watermark"
                total_cost += wm.cost_usd
                watermark_meta = {
                    "place": wm.place,
                    "pincode": wm.pincode,
                    "timestamp_text": wm.timestamp_text,
                    "employee_name": wm.employee_name,
                    "employee_id": wm.employee_id,
                    "artifact_id": str(art.id),
                    "filename": art.filename,
                }

        if candidate:
            gps_coords = candidate
            gps_source = source_this_photo
            gps_watermark_meta = watermark_meta
            gps_house_artifact = art
            # Try Google first (fast, high-quality). On any non-OK response
            # (REQUEST_DENIED, OVER_QUERY_LIMIT, network error, etc.) fall back
            # to the free OSM Nominatim endpoint so a GCP misconfig doesn't
            # silently black-hole the whole sub-step.
            gps_addr = await reverse_geocode(
                lat=candidate[0], lon=candidate[1], api_key=api_key
            )
            gps_addr_source = "google" if gps_addr else None
            if not gps_addr:
                nomi = await reverse_geocode_nominatim(
                    lat=candidate[0], lon=candidate[1]
                )
                if nomi is not None:
                    gps_nominatim = nomi
                    gps_addr = nomi.display_name
                    gps_addr_source = "nominatim"
            if gps_addr:
                break

    # Structured Aadhaar ↔ GPS match (district + village aware). Only meaningful
    # when Nominatim gave us structured address parts; Google's plain string
    # falls through to the legacy fuzzy-string check inside the cross-check.
    #
    # Pincode precedence for the match: watermark-embedded pincode BEATS
    # Nominatim's reverse-geocoded pincode whenever available. The burn-in
    # overlay is written by the GPS-Map-Camera app at photo capture time using
    # the phone's own geofence data, while Nominatim just guesses a pincode
    # from the (lat, lon) against an OSM polygon — and OSM polygons for rural
    # Haryana are frequently off by a village or two, which then routes to a
    # neighbouring postal district and triggers false "mismatch" verdicts.
    gps_match: GPSMatch | None = None
    if (
        gps_nominatim is not None
        and applicant_aadhaar is not None
        and applicant_aadhaar.extracted_address
    ):
        watermark_pincode = (gps_watermark_meta or {}).get("pincode")
        effective_pincode = watermark_pincode or gps_nominatim.postcode
        # When the watermark provides a clean place string we also prefer it
        # as the "village" hint — it's the GPS app's own geocode, typically
        # more specific than OSM's "Hisar II Block" type admin labels.
        watermark_place = (gps_watermark_meta or {}).get("place")
        effective_village = (
            watermark_place if watermark_place else gps_nominatim.village
        )
        gps_match = compare_aadhaar_to_gps(
            aadhaar_address=applicant_aadhaar.extracted_address,
            gps_state=gps_nominatim.state,
            gps_district=gps_nominatim.district,
            gps_village=effective_village,
            gps_pincode=effective_pincode,
        )

    # --- Sub-step 4: GPS vs applicant Aadhaar ---
    # Forward-geocode the Aadhaar address to (lat, lon) — we already have the
    # photo's GPS coords — and compute haversine. The distance is the most
    # actionable signal an MD has when the village/text mismatch is borderline.
    aadhaar_gps_distance_km: float | None = None
    if (
        applicant_aadhaar
        and applicant_aadhaar.extracted_address
        and gps_coords is not None
    ):
        try:
            a_pt = await forward_geocode(
                address=applicant_aadhaar.extracted_address, api_key=api_key
            )
            if a_pt:
                aadhaar_gps_distance_km = haversine_km(
                    a_pt[0], a_pt[1], gps_coords[0], gps_coords[1]
                )
        except Exception:  # noqa: BLE001
            aadhaar_gps_distance_km = None

    iss = cross_check_gps_vs_applicant_aadhaar(
        applicant_aadhaar.extracted_address if applicant_aadhaar else None,
        gps_addr,
        gps_coords=gps_coords,
        gps_match=gps_match,
        distance_km=aadhaar_gps_distance_km,
    )
    if iss:
        # Attach source files so the MD can open the Aadhaar + the exact
        # house-visit photo that yielded (or failed to yield) GPS.
        applicant_aadhaar_art = _first(
            by_subtype.get(ArtifactSubtype.KYC_AADHAAR.value, [])
        )
        house_photos = by_subtype.get(ArtifactSubtype.HOUSE_VISIT_PHOTO.value, [])
        if gps_house_artifact is not None:
            photo_refs = [
                _ref(
                    gps_house_artifact,
                    relevance="House-visit photo (GPS source)",
                    highlight_field="gps_watermark",
                )
            ]
        else:
            photo_refs = [
                _ref(p, relevance="House-visit photo") for p in house_photos[:3]
            ]
        iss.setdefault("evidence", {})["source_artifacts"] = _pack(
            _ref(
                applicant_aadhaar_art,
                relevance="Applicant Aadhaar — address field",
                highlight_field="address",
            ),
            *photo_refs,
        )
        issues.append(iss)

    # --- Sub-step 3a': Business-visit photo GPS ---------------------------
    # Identical path to the house loop — EXIF first, then Haiku watermark OCR
    # on the GPS-Map-Camera burn-in overlay. Stops at the first photo that
    # yields coordinates.
    business_gps_coords: tuple[float, float] | None = None
    business_gps_source: str | None = None
    business_gps_watermark_meta: dict[str, Any] | None = None
    # Same convention as gps_house_artifact — which biz photo actually
    # yielded the GPS.
    gps_biz_artifact: CaseArtifact | None = None

    for art in by_subtype.get(ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value, []):
        try:
            body = await storage.download_object(art.s3_key)
        except Exception:
            continue

        candidate = extract_gps_from_exif(body)
        src: str | None = None
        wm_meta: dict[str, Any] | None = None
        if candidate:
            src = "exif"
        else:
            wm = await extract_gps_from_visual_watermark(
                image_bytes=body, filename=art.filename, claude=claude
            )
            if wm is not None:
                candidate = (wm.lat, wm.lon)
                src = "watermark"
                total_cost += wm.cost_usd
                wm_meta = {
                    "place": wm.place,
                    "pincode": wm.pincode,
                    "timestamp_text": wm.timestamp_text,
                    "employee_name": wm.employee_name,
                    "employee_id": wm.employee_id,
                    "artifact_id": str(art.id),
                    "filename": art.filename,
                }

        if candidate:
            business_gps_coords = candidate
            business_gps_source = src
            business_gps_watermark_meta = wm_meta
            gps_biz_artifact = art
            break

    # Emit the CRITICAL "missing business GPS" issue if the loop found nothing.
    # Only when at least one BUSINESS_PREMISES_PHOTO was uploaded — otherwise
    # the checklist validator already blocks the case for missing premises
    # photos, and we shouldn't double-flag.
    biz_photo_count = len(
        by_subtype.get(ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value, [])
    )
    if biz_photo_count > 0 and business_gps_coords is None:
        iss = cross_check_business_gps_present(
            business_gps_coords=None,
            photos_tried_count=biz_photo_count,
        )
        if iss is not None:
            # Cite every BUSINESS_PREMISES_PHOTO we tried (capped at 5) so the
            # MD can see which photos the extractor walked over.
            biz_photos = by_subtype.get(
                ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value, []
            )
            iss.setdefault("evidence", {})["source_artifacts"] = _pack(
                *[
                    _ref(
                        p,
                        relevance="Business premises photo (tried for GPS)",
                        highlight_field="gps_watermark",
                    )
                    for p in biz_photos[:5]
                ]
            )
            issues.append(iss)

    # --- Sub-step 3b: House ↔ Business commute check ----------------------
    commute_fields: dict[str, Any] = {
        "commute_distance_km": None,
        "commute_travel_minutes": None,
        "commute_judge_verdict": None,
        "commute_sub_step_status": (
            "skipped_missing_house_gps"
            if gps_coords is None
            else (
                "skipped_missing_business_gps"
                if business_gps_coords is None
                else "pending"
            )
        ),
    }
    business_derived_address: str | None = None

    if gps_coords is not None and business_gps_coords is not None:
        # Reverse-geocode the business coords for audit evidence + the judge
        # prompt. Silent failure → stays None; the judge tolerates nulls.
        try:
            business_derived_address = await reverse_geocode(
                lat=business_gps_coords[0],
                lon=business_gps_coords[1],
                api_key=api_key,
            )
        except Exception:  # noqa: BLE001
            business_derived_address = None

        # Load the case + any prior L3 result + bureau / bank extractions to
        # assemble the Opus judge's profile inputs (spec §7). All reads are
        # resilient — missing inputs just become None in the prompt.
        from app.models.case import Case as _Case
        from app.verification.services.commute_inputs import (
            classify_area,
            classify_bank_income_pattern,
        )

        case_row = await session.get(_Case, case_id)

        # Prior L3 business-type hint (best-effort; no fresh L3 call).
        prior_l3 = (
            await session.execute(
                select(VerificationResult)
                .where(
                    VerificationResult.case_id == case_id,
                    VerificationResult.level_number
                    == VerificationLevelNumber.L3_VISION,
                    VerificationResult.status.in_(
                        [
                            VerificationLevelStatus.PASSED,
                            VerificationLevelStatus.BLOCKED,
                        ]
                    ),
                )
                # ``id.desc()`` is a deterministic tiebreaker when two rows
                # share a ``completed_at`` (common in fixtures and in
                # fast-turnaround re-runs that round to the same second).
                .order_by(
                    VerificationResult.completed_at.desc(),
                    VerificationResult.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        biz_type_hint: str | None = None
        if prior_l3 is not None:
            biz_sub = (prior_l3.sub_step_results or {}).get("business") or {}
            biz_type_hint = biz_sub.get("business_type") if isinstance(biz_sub, dict) else None

        # Bureau + bank from case_extractions (already loaded by sub-step 6
        # downstream, but we read them again here because extractions is
        # materialised later in the function — cheap, a few rows).
        # NB: we READ the extractions before sub-step 5 runs — if sub-step 5
        # (``_load_or_scan_lagr_parties``) ever starts writing a new row to
        # ``case_extractions``, our snapshot here will pre-date that write.
        # Safe today (LAGR only upserts its own row which we never read), but
        # keep this invariant in mind when extending the orchestrator.
        extractions_for_profile = (
            (
                await session.execute(
                    select(CaseExtraction).where(
                        CaseExtraction.case_id == case_id
                    )
                )
            )
            .scalars()
            .all()
        )
        bureau_occ: str | None = None
        bank_tx_list: list[dict[str, Any]] | None = None
        for e in extractions_for_profile:
            d = e.data or {}
            if e.extractor_name == "equifax":
                occ = (d.get("customer_info") or {}).get("occupation")
                if isinstance(occ, str) and occ:
                    bureau_occ = occ
            elif e.extractor_name == "bank_statement":
                txs = d.get("transactions")
                if isinstance(txs, list):
                    bank_tx_list = txs

        # Rural/urban hint: prefer Nominatim's ``addresstype`` (most
        # authoritative — village / hamlet / town / city tags). When Google
        # was the winning geocoder, addresstype isn't available and we fall
        # back to keyword-matching the formatted address ("Village …",
        # "Municipal Corporation", etc.) so the signal isn't lost on the
        # Google path. ``classify_area`` returns None for ambiguous strings
        # and the judge reasons without the field.
        area_place_type: str | None = None
        if gps_nominatim is not None and isinstance(gps_nominatim.raw, dict):
            at = gps_nominatim.raw.get("addresstype")
            if isinstance(at, str) and at.strip():
                area_place_type = at.strip()
        area_class = classify_area(
            place_type=area_place_type, address=gps_addr
        )
        bank_pattern = classify_bank_income_pattern(bank_tx_list)

        profile_inputs = {
            "applicant_occupation_from_form": (
                getattr(case_row, "occupation", None) if case_row else None
            ),
            "applicant_business_type_hint": biz_type_hint,
            "loan_amount_inr": (
                int(getattr(case_row, "loan_amount", None) or 0) or None
                if case_row
                else None
            ),
            "area_class": area_class,
            "bureau_occupation_history": bureau_occ,
            "bank_income_pattern": bank_pattern,
            "house_derived_address": gps_addr,
            "business_derived_address": business_derived_address,
        }

        # Cache-reuse: did a prior L1 run score the same coord pair?
        prior_l1 = (
            await session.execute(
                select(VerificationResult)
                .where(
                    VerificationResult.case_id == case_id,
                    VerificationResult.level_number
                    == VerificationLevelNumber.L1_ADDRESS,
                    VerificationResult.id != result.id,
                    VerificationResult.status.in_(
                        [
                            VerificationLevelStatus.PASSED,
                            VerificationLevelStatus.BLOCKED,
                        ]
                    ),
                )
                .order_by(
                    VerificationResult.completed_at.desc(),
                    VerificationResult.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        prior_sub = (prior_l1.sub_step_results or {}) if prior_l1 else {}
        prior_house = prior_sub.get("gps_coords")
        prior_biz = prior_sub.get("business_gps_coords")
        prior_house_tuple: tuple[float, float] | None = (
            (prior_house[0], prior_house[1])
            if isinstance(prior_house, list) and len(prior_house) == 2
            else None
        )
        prior_biz_tuple: tuple[float, float] | None = (
            (prior_biz[0], prior_biz[1])
            if isinstance(prior_biz, list) and len(prior_biz) == 2
            else None
        )

        fields, commute_issues, commute_cost = await _compute_commute_sub_step(
            house_coords=gps_coords,
            business_coords=business_gps_coords,
            prior_house_coords=prior_house_tuple,
            prior_business_coords=prior_biz_tuple,
            prior_commute_fields={
                k: prior_sub.get(k)
                for k in (
                    "commute_distance_km",
                    "commute_travel_minutes",
                    "commute_judge_verdict",
                    "commute_sub_step_status",
                )
            }
            if prior_l1 is not None
            else None,
            profile_inputs=profile_inputs,
            claude=claude,
            api_key=api_key,
        )
        commute_fields.update(fields)
        for ci in commute_issues:
            # Commute issues span both locations — cite the exact pair of
            # photos that produced the coordinates. Falls back to nothing
            # if we don't know which photo (shouldn't happen here — we
            # only enter this branch when both GPS coords are present).
            ci.setdefault("evidence", {})["source_artifacts"] = _pack(
                _ref(
                    gps_house_artifact,
                    relevance="House-visit photo (house GPS)",
                    highlight_field="gps_watermark",
                ),
                _ref(
                    gps_biz_artifact,
                    relevance="Business premises photo (business GPS)",
                    highlight_field="gps_watermark",
                ),
            )
            issues.append(ci)
        total_cost += commute_cost

    # --- Sub-step 5: ration owner-name rule ---
    lagr_parties: dict[str, Any] | None = None
    if ration_bill:
        # Assume the first applicant-PAN name is authoritative (falls back to aadhaar).
        applicant_name = (
            (applicant_pan.extracted_name if applicant_pan else None)
            or (applicant_aadhaar.extracted_name if applicant_aadhaar else None)
        )
        co_applicant_name = (
            (co_applicant_pan.extracted_name if co_applicant_pan else None)
            or (co_applicant_aadhaar.extracted_name if co_applicant_aadhaar else None)
        )
        # Resolve guarantor + co-applicant names from the signed loan-agreement
        # kit (LAGR). We cache the vision call via ``case_extractions`` so the
        # ~$0.04 Haiku scan runs at most once per case even when L1 is re-run
        # many times during assessor iteration.
        lagr_parties = await _load_or_scan_lagr_parties(
            session=session,
            case_id=case_id,
            artifacts=artifacts,
            storage=storage,
            claude=claude,
        )
        if lagr_parties and lagr_parties.get("cost_usd"):
            total_cost += Decimal(str(lagr_parties["cost_usd"]))
        guarantor_names_from_lagr = (
            (lagr_parties or {}).get("guarantors") or []
        )
        agreement_coapps = (lagr_parties or {}).get("co_applicants") or []

        iss = cross_check_ration_owner_rule(
            bill_owner_name=ration_bill.extracted_name,
            bill_father_or_husband_name=ration_bill.extracted_father_name,
            applicant_name=applicant_name,
            applicant_aadhaar_father_name=(
                applicant_aadhaar.extracted_father_name if applicant_aadhaar else None
            ),
            applicant_gender=(
                applicant_aadhaar.extracted_gender if applicant_aadhaar else None
            ),
            co_applicant_name=co_applicant_name,
            co_applicant_aadhaar_father_name=(
                co_applicant_aadhaar.extracted_father_name
                if co_applicant_aadhaar
                else None
            ),
            co_applicant_gender=(
                co_applicant_aadhaar.extracted_gender
                if co_applicant_aadhaar
                else None
            ),
            guarantor_names=[
                *guarantor_names_from_lagr,
                *agreement_coapps,  # LAGR co-applicants also count as on-loan parties
            ],
        )
        if iss:
            # Attach the bill, both Aadhaars, and the signed loan-agreement
            # PDF — the four artefacts that together back this rule.
            bill_art = _first(
                by_subtype.get(ArtifactSubtype.RATION_CARD.value, [])
            ) or _first(
                by_subtype.get(ArtifactSubtype.ELECTRICITY_BILL.value, [])
            )
            applicant_aadhaar_art = _first(
                by_subtype.get(ArtifactSubtype.KYC_AADHAAR.value, [])
            )
            co_applicant_aadhaar_art = _first(
                by_subtype.get(ArtifactSubtype.CO_APPLICANT_AADHAAR.value, [])
            )
            lagr_art = (
                _first(by_subtype.get(ArtifactSubtype.LAGR.value, []))
                or _first(by_subtype.get(ArtifactSubtype.LOAN_AGREEMENT.value, []))
            )
            iss.setdefault("evidence", {})["source_artifacts"] = _pack(
                _ref(
                    bill_art,
                    relevance="Ration / electricity bill — owner name line",
                    highlight_field="owner_name",
                ),
                _ref(
                    applicant_aadhaar_art,
                    relevance="Applicant Aadhaar — name & S/O field",
                    highlight_field="name",
                ),
                _ref(
                    co_applicant_aadhaar_art,
                    relevance="Co-applicant Aadhaar — name & S/O field",
                    highlight_field="name",
                ),
                _ref(
                    lagr_art,
                    relevance="Loan agreement — parties section",
                    highlight_field="parties",
                ),
            )
            issues.append(iss)

    # --- Sub-step 6: Aadhaar vs Equifax vs bank ---
    bureau_addrs: list[str] = []
    bank_addrs: list[str] = []
    extractions = (
        (
            await session.execute(
                select(CaseExtraction).where(CaseExtraction.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    for e in extractions:
        data = e.data or {}
        if e.extractor_name == "equifax":
            # Equifax addresses nested in customer_info.addresses[] OR flat
            addrs = (data.get("customer_info") or {}).get("addresses") or []
            if isinstance(addrs, list):
                for a in addrs:
                    if isinstance(a, str):
                        bureau_addrs.append(a)
                    elif isinstance(a, dict) and a.get("line"):
                        bureau_addrs.append(a["line"])
            # Fallback — some extractions have a single ``address`` string
            flat_addr = data.get("address") or (
                (data.get("customer_info") or {}).get("address")
            )
            if isinstance(flat_addr, str):
                bureau_addrs.append(flat_addr)
        elif e.extractor_name == "bank_statement":
            flat_addr = data.get("account_holder_address") or data.get("address")
            if isinstance(flat_addr, str):
                bank_addrs.append(flat_addr)

    applicant_aadhaar_art = _first(
        by_subtype.get(ArtifactSubtype.KYC_AADHAAR.value, [])
    )
    for iss in cross_check_aadhaar_vs_bureau_bank(
        aadhaar_address=applicant_aadhaar.extracted_address if applicant_aadhaar else None,
        bureau_addresses=bureau_addrs,
        bank_addresses=bank_addrs,
    ):
        # Attach Aadhaar + the specific external source (bureau or bank)
        # the mismatch was flagged against.
        if iss["sub_step_id"] == "aadhaar_vs_bureau_address":
            bureau_art = (
                _first(by_subtype.get(ArtifactSubtype.EQUIFAX_HTML.value, []))
                or _first(by_subtype.get(ArtifactSubtype.CIBIL_HTML.value, []))
                or _first(by_subtype.get(ArtifactSubtype.HIGHMARK_HTML.value, []))
                or _first(by_subtype.get(ArtifactSubtype.EXPERIAN_HTML.value, []))
            )
            iss.setdefault("evidence", {})["source_artifacts"] = _pack(
                _ref(
                    applicant_aadhaar_art,
                    relevance="Applicant Aadhaar — address field",
                    highlight_field="address",
                ),
                _ref(
                    bureau_art,
                    relevance="Bureau report — address block",
                    highlight_field="address",
                ),
            )
        elif iss["sub_step_id"] == "aadhaar_vs_bank_address":
            bank_art = _first(
                by_subtype.get(ArtifactSubtype.BANK_STATEMENT.value, [])
            )
            iss.setdefault("evidence", {})["source_artifacts"] = _pack(
                _ref(
                    applicant_aadhaar_art,
                    relevance="Applicant Aadhaar — address field",
                    highlight_field="address",
                ),
                _ref(
                    bank_art,
                    relevance="Bank statement — registered address",
                    highlight_field="address",
                ),
            )
        issues.append(iss)

    # Honour admin /admin/learning-rules suppressions — rules flagged as
    # "skipped by the AI" don't persist as LevelIssue rows, don't block
    # the gate, and don't show up in the MD queue.
    issues, suppressed_rules = await filter_suppressed_issues(session, issues)

    # --- Persist issues as LevelIssue rows ---
    for iss in issues:
        session.add(
            LevelIssue(
                verification_result_id=result.id,
                sub_step_id=iss["sub_step_id"],
                severity=LevelIssueSeverity(iss["severity"]),
                description=iss["description"],
                evidence=iss.get("evidence"),
                status=LevelIssueStatus.OPEN,
            )
        )

    # --- Sub-step 7: aggregate status ---
    has_critical = any(
        i["severity"] == LevelIssueSeverity.CRITICAL.value for i in issues
    )
    final_status = (
        VerificationLevelStatus.BLOCKED if has_critical else VerificationLevelStatus.PASSED
    )

    # --- Pass-evidence: mirror of fire-path evidence for rules that passed --
    # Resolve artefact refs that might only have been scoped inside upstream
    # branches (ration owner, bureau, bank). Falling back to the first match
    # of each subtype keeps the helper honest — we only cite what was
    # uploaded; absent artefacts stay absent.
    fired_sub_step_ids = {i["sub_step_id"] for i in issues}
    _applicant_aadhaar_art = _first(
        by_subtype.get(ArtifactSubtype.KYC_AADHAAR.value, [])
    )
    _co_applicant_aadhaar_art = _first(
        by_subtype.get(ArtifactSubtype.CO_APPLICANT_AADHAAR.value, [])
    )
    _bill_art = _first(
        by_subtype.get(ArtifactSubtype.RATION_CARD.value, [])
    ) or _first(by_subtype.get(ArtifactSubtype.ELECTRICITY_BILL.value, []))
    _lagr_art = (
        _first(by_subtype.get(ArtifactSubtype.LAGR.value, []))
        or _first(by_subtype.get(ArtifactSubtype.LOAN_AGREEMENT.value, []))
    )
    _bureau_art = (
        _first(by_subtype.get(ArtifactSubtype.EQUIFAX_HTML.value, []))
        or _first(by_subtype.get(ArtifactSubtype.CIBIL_HTML.value, []))
        or _first(by_subtype.get(ArtifactSubtype.HIGHMARK_HTML.value, []))
        or _first(by_subtype.get(ArtifactSubtype.EXPERIAN_HTML.value, []))
    )
    _bank_art = _first(by_subtype.get(ArtifactSubtype.BANK_STATEMENT.value, []))
    _applicant_name = (
        (applicant_pan.extracted_name if applicant_pan else None)
        or (applicant_aadhaar.extracted_name if applicant_aadhaar else None)
    )
    _co_applicant_name = (
        (co_applicant_pan.extracted_name if co_applicant_pan else None)
        or (co_applicant_aadhaar.extracted_name if co_applicant_aadhaar else None)
    )
    pass_evidence = build_pass_evidence_l1(
        applicant_address=(
            applicant_aadhaar.extracted_address if applicant_aadhaar else None
        ),
        co_applicant_address=(
            co_applicant_aadhaar.extracted_address if co_applicant_aadhaar else None
        ),
        applicant_aadhaar_address=(
            applicant_aadhaar.extracted_address if applicant_aadhaar else None
        ),
        gps_derived_address=gps_addr,
        gps_coords=gps_coords,
        gps_match=gps_match,
        bill_owner=ration_bill.extracted_name if ration_bill else None,
        bill_father_or_husband=(
            ration_bill.extracted_father_name if ration_bill else None
        ),
        applicant_name=_applicant_name,
        co_applicant_name=_co_applicant_name,
        guarantor_names=list(guarantor_names_from_lagr),
        business_gps_coords=business_gps_coords,
        photos_tried_count=biz_photo_count,
        travel_minutes=commute_fields.get("commute_travel_minutes"),
        distance_km=commute_fields.get("commute_distance_km"),
        bureau_addresses=bureau_addrs,
        bank_addresses=bank_addrs,
        fired_rules=fired_sub_step_ids,
        applicant_aadhaar_art=_applicant_aadhaar_art,
        gps_house_art=gps_house_artifact,
        gps_biz_art=gps_biz_artifact,
        bill_art=_bill_art,
        co_aadhaar_art=_co_applicant_aadhaar_art,
        lagr_art=_lagr_art,
        bureau_art=_bureau_art,
        bank_art=_bank_art,
    )

    sub_step_results = {
        "applicant_aadhaar_id": str(applicant_aadhaar.id) if applicant_aadhaar else None,
        "co_applicant_aadhaar_id": str(co_applicant_aadhaar.id)
        if co_applicant_aadhaar
        else None,
        "applicant_pan_id": str(applicant_pan.id) if applicant_pan else None,
        "co_applicant_pan_id": str(co_applicant_pan.id) if co_applicant_pan else None,
        "ration_bill_id": str(ration_bill.id) if ration_bill else None,
        "gps_coords": list(gps_coords) if gps_coords else None,
        "gps_source": gps_source,  # "exif" | "watermark" | None
        "gps_watermark_meta": gps_watermark_meta,
        "gps_derived_address": gps_addr,
        "gps_derived_address_source": gps_addr_source,  # "google" | "nominatim" | None
        "gps_derived_address_structured": (
            gps_nominatim.to_dict() if gps_nominatim else None
        ),
        "gps_match": gps_match.to_dict() if gps_match else None,
        "loan_agreement_parties": (
            {
                "borrower_name": lagr_parties.get("borrower_name"),
                "co_applicants": lagr_parties.get("co_applicants") or [],
                "guarantors": lagr_parties.get("guarantors") or [],
                "witnesses": lagr_parties.get("witnesses") or [],
                "cached": lagr_parties.get("cached", False),
            }
            if lagr_parties
            else None
        ),
        "applicant_aadhaar_father_name": (
            applicant_aadhaar.extracted_father_name if applicant_aadhaar else None
        ),
        "applicant_gender": (
            applicant_aadhaar.extracted_gender if applicant_aadhaar else None
        ),
        "co_applicant_aadhaar_father_name": (
            co_applicant_aadhaar.extracted_father_name if co_applicant_aadhaar else None
        ),
        "ration_bill_owner": ration_bill.extracted_name if ration_bill else None,
        "ration_bill_address": ration_bill.extracted_address if ration_bill else None,
        "bureau_addresses_considered": bureau_addrs,
        "bank_addresses_considered": bank_addrs,
        # Sub-step 3a' + 3b: business-visit photo GPS + commute check.
        "business_gps_coords": (
            list(business_gps_coords) if business_gps_coords else None
        ),
        "business_gps_source": business_gps_source,
        "business_gps_watermark_meta": business_gps_watermark_meta,
        "business_derived_address": business_derived_address,
        "commute_distance_km": commute_fields.get("commute_distance_km"),
        "commute_travel_minutes": commute_fields.get("commute_travel_minutes"),
        "commute_judge_verdict": commute_fields.get("commute_judge_verdict"),
        "commute_sub_step_status": commute_fields.get("commute_sub_step_status"),
        "issue_count": len(issues),
        "suppressed_rules": suppressed_rules,
        "pass_evidence": pass_evidence,
    }

    result.status = final_status
    result.sub_step_results = sub_step_results
    result.cost_usd = total_cost
    result.completed_at = datetime.now(UTC)
    await session.flush()
    # Carry forward terminal MD / assessor decisions from any prior run on
    # the same (case, level) so re-triggers don't orphan the MD's audit
    # trail. May promote ``result.status`` to PASSED_WITH_MD_OVERRIDE.
    await carry_forward_prior_decisions(session, result=result)
    return result
