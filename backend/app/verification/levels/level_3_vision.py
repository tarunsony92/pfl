"""Level 3 — Cloud Vision (house + business premises).

Runs two Claude Sonnet vision calls: one bundling all HOUSE_VISIT_PHOTO
artifacts for the case, one bundling all BUSINESS_PREMISES_PHOTO artifacts.
Converts the structured scoring into CRITICAL / WARNING issues per rule:

- house overall rating < ok → CRITICAL (borrower's living standard below floor)
- stock value estimate < 50% of loan amount → CRITICAL (under-collateralised)
- stock value estimate < 100% of loan amount → WARNING
- cattle health "unhealthy" → CRITICAL
- infra rating "bad" → WARNING, "worst" → CRITICAL

MVP scope: fixed parameter scale, no first-100-case calibration. The MRP
database (for stock value anchoring) is deferred — the vision scorer's
stock_value_estimate_inr is compared directly to the case's loan_amount.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    ArtifactSubtype,
    LevelIssueSeverity,
    LevelIssueStatus,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.verification.levels._common import carry_forward_prior_decisions
from app.verification.levels.level_1_address import (
    _pack,
    _ref,
    filter_suppressed_issues,
)

_log = logging.getLogger(__name__)

_ACCEPTABLE_HOUSE = frozenset({"ok", "good", "excellent"})
_REJECT_HOUSE = frozenset({"bad", "worst"})


# ───────────────────────────── Pure cross-checks ─────────────────────────────


def cross_check_house_rating(rating: str | None) -> dict[str, Any] | None:
    if rating in _ACCEPTABLE_HOUSE:
        return None
    if rating in _REJECT_HOUSE:
        return {
            "sub_step_id": "house_living_condition",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                f"House living condition rated {rating!r}. PFL microfinance "
                "ticket-floor rules require the home to be at least ``ok``. "
                "Recommend reducing ticket size or rejecting outright."
            ),
        }
    return {
        "sub_step_id": "house_living_condition",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            "House condition could not be reliably rated from the submitted "
            "photos. Request additional inside-room photos + kitchen."
        ),
    }


_SERVICE_COLLATERAL_FLOOR_PCT = 0.40  # service-biz: stock+equipment floor
_STOCK_CRITICAL_PCT = 0.50             # product-trading: <50% of loan
_LOAN_REDUCTION_TRIGGER_PCT = 0.80     # recommended < 80% of proposed → WARN


def cross_check_stock_vs_loan(
    *,
    stock_value_estimate_inr: int | None,
    loan_amount_inr: int | None,
    business_type: str | None = None,
    visible_equipment_value_inr: int | None = None,
    recommended_loan_amount_inr: int | None = None,
    recommended_loan_rationale: str | None = None,
) -> dict[str, Any] | None:
    """Collateral-vs-loan sanity check. Branches on business type:

    - ``service``: collateral = stock + visible fixed equipment; floor is 40%
      of the proposed loan (service businesses rely on equipment, not
      inventory). Falling below that is CRITICAL with a reduction
      recommendation in the description.
    - ``product_trading`` / ``mixed`` / ``manufacturing`` / ``unknown``: the
      legacy stock-only 50 / 100% thresholds apply.
    - ``cattle_dairy``: the Opus prompt already fills
      stock_value_estimate_inr with ``cattle_count × ₹60k``, so the default
      branch compares that cattle value against the loan — nothing special
      needed here.
    """
    if not loan_amount_inr:
        return None

    stock = int(stock_value_estimate_inr or 0)
    equipment = int(visible_equipment_value_inr or 0)

    analysis = build_stock_analysis(
        {
            "business_type": business_type,
            "stock_value_estimate_inr": stock_value_estimate_inr,
            "visible_equipment_value_inr": visible_equipment_value_inr,
            "recommended_loan_amount_inr": recommended_loan_amount_inr,
            "recommended_loan_rationale": recommended_loan_rationale,
        },
        loan_amount_inr=loan_amount_inr,
    )
    collateral = analysis["visible_collateral_inr"] or 0
    ratio = analysis["coverage_pct"] or 0.0
    floor_pct_critical = analysis["floor_pct_critical"]
    floor_pct_warning = analysis["floor_pct_warning"]

    if business_type == "service":
        if ratio >= floor_pct_critical:
            return None
        recommendation_line = ""
        if (
            recommended_loan_amount_inr
            and recommended_loan_amount_inr < loan_amount_inr
        ):
            recommendation_line = (
                f" The vision model recommends reducing the ticket to "
                f"₹{recommended_loan_amount_inr:,}"
                + (f" ({recommended_loan_rationale})" if recommended_loan_rationale else "")
                + "."
            )
        return {
            "sub_step_id": "stock_vs_loan",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                f"Service business — visible collateral (stock ₹{stock:,} + "
                f"equipment ₹{equipment:,} = ₹{collateral:,}) covers only "
                f"{ratio:.0%} of the ₹{loan_amount_inr:,} loan. Service "
                f"businesses rely on fixed equipment rather than inventory, "
                f"so the collateral floor is "
                f"{int(floor_pct_critical * 100)}% — this case is "
                f"below it.{recommendation_line} Reduce ticket or reject."
            ),
        }

    # Default branch: product_trading / manufacturing / mixed / unknown /
    # cattle_dairy (where stock_value_estimate is already cattle × 60k).
    if not stock:
        return None
    if ratio >= (floor_pct_warning or 1.0):
        return None
    if ratio < floor_pct_critical:
        return {
            "sub_step_id": "stock_vs_loan",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                f"Visible stock ≈ ₹{stock:,} covers only "
                f"{ratio:.0%} of the ₹{loan_amount_inr:,} loan. Severely "
                "under-collateralised — reduce the ticket or reject."
            ),
        }
    return {
        "sub_step_id": "stock_vs_loan",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"Visible stock ≈ ₹{stock:,} covers "
            f"{ratio:.0%} of the ₹{loan_amount_inr:,} loan. Recommend "
            "lowering the ticket to match stock."
        ),
    }


def cross_check_loan_amount_reduction(
    *,
    recommended_loan_amount_inr: int | None,
    loan_amount_inr: int | None,
    rationale: str | None,
    business_type: str | None = None,
    business_subtype: str | None = None,
) -> dict[str, Any] | None:
    """Flag cases where Opus's recommended loan is meaningfully below proposed.

    Fires as WARNING when the recommended ticket is less than 80% of what the
    borrower asked for. The MD can accept the reduced ticket (override with
    MD_APPROVED) or keep the original (MD_REJECTED); either way the precedent
    trains the AutoJustifier for similar cases.
    """
    if not recommended_loan_amount_inr or not loan_amount_inr:
        return None
    if recommended_loan_amount_inr >= loan_amount_inr * _LOAN_REDUCTION_TRIGGER_PCT:
        return None
    cut = 1 - recommended_loan_amount_inr / loan_amount_inr
    biz_line = (
        f" (business: {business_subtype or business_type or 'unknown'})"
        if (business_subtype or business_type)
        else ""
    )
    return {
        "sub_step_id": "loan_amount_reduction",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"Vision model recommends a reduced ticket of "
            f"₹{recommended_loan_amount_inr:,} vs the proposed "
            f"₹{loan_amount_inr:,} — a {cut:.0%} cut{biz_line}. "
            f"Rationale: {rationale or '—'}"
        ),
    }


def cross_check_cattle_health(
    health: str | None,
    *,
    business_type: str | None = None,
    cattle_count: int | None = None,
) -> dict[str, Any] | None:
    """Fire only when the business is actually a dairy operation with
    cattle on site AND the scorer flagged them as unhealthy. Guards
    against Opus wrongly emitting cattle_health on non-dairy
    businesses — a service biz (barbershop) should never trigger a
    dairy-specific concern."""
    if health != "unhealthy":
        return None
    if business_type not in ("cattle_dairy", "mixed"):
        return None
    if not cattle_count or cattle_count <= 0:
        return None
    return {
        "sub_step_id": "cattle_health",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "Cattle appear unhealthy / malnourished in the photos. "
            "Milking yield + asset value are at risk. Require a vet "
            "health certificate before disbursing a dairy loan."
        ),
    }


def cross_check_infrastructure_rating(rating: str | None) -> dict[str, Any] | None:
    if rating == "worst":
        return {
            "sub_step_id": "business_infrastructure",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                "Business premises infrastructure rated ``worst``. The setup "
                "cannot support sustained operations — reject or require a "
                "location change before disbursing."
            ),
        }
    if rating == "bad":
        return {
            "sub_step_id": "business_infrastructure",
            "severity": LevelIssueSeverity.WARNING.value,
            "description": (
                "Business premises infrastructure rated ``bad``. Recommend "
                "the borrower upgrade (better shelter, water, storage) as a "
                "loan condition."
            ),
        }
    return None


def cross_check_aggregate_drift(
    *,
    aggregate_consistency: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Fire WARNING when per-item line totals diverge from the scorer's own
    aggregate by more than the threshold (default 20%). Catches hallucinated
    item lists where Σ(items) ≠ stock_value_estimate_inr — protects against
    the model drifting between aggregate and itemised assessments."""
    if not aggregate_consistency:
        return None
    stock_warn = aggregate_consistency.get("stock_warning")
    eq_warn = aggregate_consistency.get("equipment_warning")
    if not (stock_warn or eq_warn):
        return None

    stock_drift = aggregate_consistency.get("stock_drift_pct")
    eq_drift = aggregate_consistency.get("equipment_drift_pct")
    parts: list[str] = []
    if stock_warn and stock_drift is not None:
        parts.append(
            f"stock aggregate ₹{aggregate_consistency.get('stock_aggregate', 0):,} "
            f"vs items sum ₹{aggregate_consistency.get('stock_items_sum', 0):,} "
            f"= {stock_drift:.0%} drift"
        )
    if eq_warn and eq_drift is not None:
        parts.append(
            f"equipment aggregate ₹{aggregate_consistency.get('equipment_aggregate', 0):,} "
            f"vs items sum ₹{aggregate_consistency.get('equipment_items_sum', 0):,} "
            f"= {eq_drift:.0%} drift"
        )
    threshold_pct = int(
        (aggregate_consistency.get("warning_threshold_pct") or 0.2) * 100
    )
    return {
        "sub_step_id": "stock_aggregate_drift",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"Per-item line totals diverge from the scorer's aggregates by "
            f">{threshold_pct}% — "
            + "; ".join(parts)
            + ". Confirm the photos and per-item table before relying on "
            "either number."
        ),
    }


def build_stock_analysis(
    biz_data: dict[str, Any] | None,
    *,
    loan_amount_inr: int | None,
) -> dict[str, Any] | None:
    """Package the business scorer's output + the case's loan amount into
    the sub_step_results.stock_analysis dict shape consumed by the L3
    frontend. Pure function; returns None when the scorer produced
    nothing (error path).

    Non-service businesses have two thresholds (critical 50%, warning
    100%); service businesses have one (critical 40% — stock +
    equipment together). Null loan_amount → partial dict with
    coverage_pct / cut_pct set to None.
    """
    if not biz_data:
        return None

    business_type = biz_data.get("business_type")
    stock = biz_data.get("stock_value_estimate_inr") or 0
    equipment = biz_data.get("visible_equipment_value_inr") or 0

    is_service = business_type == "service"
    visible_collateral = (stock + equipment) if is_service else stock

    coverage_pct: float | None = None
    if loan_amount_inr and loan_amount_inr > 0:
        coverage_pct = visible_collateral / loan_amount_inr

    floor_pct_critical = (
        _SERVICE_COLLATERAL_FLOOR_PCT if is_service else _STOCK_CRITICAL_PCT
    )
    floor_pct_warning = None if is_service else 1.0

    recommended = biz_data.get("recommended_loan_amount_inr")
    cut_pct: float | None = None
    if recommended is not None and loan_amount_inr and loan_amount_inr > 0:
        cut_pct = max(0.0, 1 - recommended / loan_amount_inr)

    reasoning_bits: list[str] = []
    if business_type:
        reasoning_bits.append(f"Classified as **{business_type}**.")
    if is_service:
        reasoning_bits.append(
            f"Visible collateral = stock ₹{stock:,} + equipment ₹{equipment:,} "
            f"= ₹{visible_collateral:,}. Service biz collateral floor is "
            f"{int(floor_pct_critical * 100)}% of the loan."
        )
    else:
        reasoning_bits.append(
            f"Visible stock ≈ ₹{visible_collateral:,}. Non-service biz "
            f"critical floor is {int(floor_pct_critical * 100)}% of the loan; "
            f"warning tier is {int((floor_pct_warning or 1) * 100)}%."
        )
    if coverage_pct is not None:
        reasoning_bits.append(f"Coverage ratio: {coverage_pct:.0%}.")
    if recommended is not None and loan_amount_inr:
        if recommended < loan_amount_inr:
            reasoning_bits.append(
                f"Scorer recommends reducing to ₹{recommended:,} "
                f"(cut of {cut_pct:.0%})."
            )
        else:
            reasoning_bits.append(
                f"Scorer endorses the proposed ₹{loan_amount_inr:,}."
            )

    items_list = list(biz_data.get("items") or [])

    def _line_total(it: dict[str, Any]) -> int:
        mrp = it.get("mrp_estimate_inr")
        qty = it.get("qty")
        if mrp is None or not isinstance(mrp, int | float):
            return 0
        if qty is None or not isinstance(qty, int | float):
            return 0
        return int(mrp * qty)

    stock_consumable_sum = sum(
        _line_total(it) for it in items_list
        if it.get("category") in ("stock", "consumable")
    )
    equipment_sum = sum(
        _line_total(it) for it in items_list if it.get("category") == "equipment"
    )

    def _drift_pct(claim: int | None, observed: int) -> float | None:
        """Returns abs((claim - observed) / max(claim, observed)) or None
        when both sides are zero (vacuously consistent)."""
        if (claim or 0) == 0 and observed == 0:
            return None
        denom = max(claim or 0, observed)
        if denom == 0:
            return None
        return abs((claim or 0) - observed) / denom

    stock_drift = _drift_pct(stock or 0, stock_consumable_sum)
    equipment_drift = _drift_pct(equipment or 0, equipment_sum)

    aggregate_consistency = {
        "stock_aggregate": stock or 0,
        "stock_items_sum": stock_consumable_sum,
        "stock_drift_pct": stock_drift,  # 0.0 = perfectly consistent; 0.2 = 20% drift; None = both zero
        "equipment_aggregate": equipment or 0,
        "equipment_items_sum": equipment_sum,
        "equipment_drift_pct": equipment_drift,
        "warning_threshold_pct": 0.20,
        "stock_warning": stock_drift is not None and stock_drift > 0.20,
        "equipment_warning": equipment_drift is not None and equipment_drift > 0.20,
    }

    return {
        "business_type": business_type,
        "business_subtype": biz_data.get("business_subtype"),
        "loan_amount_inr": loan_amount_inr,
        "stock_value_estimate_inr": stock or None,
        "visible_equipment_value_inr": equipment or None,
        "visible_collateral_inr": visible_collateral or None,
        "cattle_count": biz_data.get("cattle_count"),
        "cattle_health": biz_data.get("cattle_health"),
        "stock_condition": biz_data.get("stock_condition"),
        "stock_variety": biz_data.get("stock_variety"),
        "coverage_pct": coverage_pct,
        "floor_pct_critical": floor_pct_critical,
        "floor_pct_warning": floor_pct_warning,
        "recommended_loan_amount_inr": recommended,
        "recommended_loan_rationale": biz_data.get("recommended_loan_rationale"),
        "cut_pct": cut_pct,
        "reasoning": " ".join(reasoning_bits) if reasoning_bits else "",
        "items": items_list,
        "aggregate_consistency": aggregate_consistency,
    }


def build_visual_evidence(
    *,
    house_arts: list[CaseArtifact],
    biz_arts: list[CaseArtifact],
    house_imgs_count: int,
    biz_imgs_count: int,
) -> dict[str, Any]:
    """Return the sub_step_results.visual_evidence dict: per-category
    artifact-id lists + the count the scorer actually evaluated
    (distinct from uploaded, since storage fetches can fail).

    Artifact IDs alone — no download URLs. The FE resolves URLs via
    useCasePhotos(caseId) and filters to this list.
    """
    def _pack(a: CaseArtifact, subtype: str) -> dict[str, Any]:
        return {
            "artifact_id": str(a.id),
            "filename": a.filename,
            "subtype": subtype,
        }

    return {
        "house_photos": [
            _pack(a, ArtifactSubtype.HOUSE_VISIT_PHOTO.value)
            for a in house_arts
        ],
        "business_photos": [
            _pack(a, ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value)
            for a in biz_arts
        ],
        "house_photos_evaluated": house_imgs_count,
        "business_photos_evaluated": biz_imgs_count,
    }


def build_pass_evidence(
    *,
    house_data: dict[str, Any] | None,
    biz_data: dict[str, Any] | None,
    loan_amount_inr: int | None,
    house_photos_evaluated: int,
    business_photos_evaluated: int,
    fired_rules: set[str],
    house_arts: list[CaseArtifact] | None = None,
    biz_arts: list[CaseArtifact] | None = None,
) -> dict[str, Any]:
    """Return the sub_step_results.pass_evidence dict — keyed by
    sub_step_id, one entry per L3 rule that PASSED or was skipped
    (N/A). Rules in ``fired_rules`` are omitted; the FE reads their
    evidence off LevelIssue.evidence for fails.

    Each entry also carries a ``source_artifacts`` list citing the
    photos the rule ran against (same pattern the orchestrator uses
    on fire paths). The frontend's LevelSourceFilesPanel aggregates
    these across concerns + passes.

    Only L3 rules are populated here. Part B will add entries for
    other levels directly in their orchestrators.
    """
    out: dict[str, Any] = {}
    house_arts = house_arts or []
    biz_arts = biz_arts or []

    house_sources = _pack(
        *[_ref(a, relevance="House-visit photo (scored)") for a in house_arts[:8]]
    )
    biz_sources = _pack(
        *[_ref(a, relevance="Business premises photo (scored)") for a in biz_arts[:8]]
    )

    # House living condition — from house scorer data
    if house_data and "house_living_condition" not in fired_rules:
        out["house_living_condition"] = {
            "overall_rating": house_data.get("overall_rating"),
            "space_rating": house_data.get("space_rating"),
            "upkeep_rating": house_data.get("upkeep_rating"),
            "construction_type": house_data.get("construction_type"),
            "positives": house_data.get("positives") or [],
            "concerns": house_data.get("concerns") or [],
            "photos_evaluated_count": house_photos_evaluated,
            "source_artifacts": house_sources,
        }

    # Business-scorer-driven rules — all need biz_data to be non-empty
    if not biz_data:
        return out

    if "business_infrastructure" not in fired_rules:
        out["business_infrastructure"] = {
            "infrastructure_rating": biz_data.get("infrastructure_rating"),
            "infrastructure_details": biz_data.get("infrastructure_details") or [],
            "equipment_visible": bool(biz_data.get("visible_equipment_value_inr")),
            "photos_evaluated_count": business_photos_evaluated,
            "source_artifacts": biz_sources,
        }

    if "stock_vs_loan" not in fired_rules:
        analysis = build_stock_analysis(biz_data, loan_amount_inr=loan_amount_inr)
        if analysis:
            out["stock_vs_loan"] = {
                **analysis,
                "photos_evaluated_count": business_photos_evaluated,
                "source_artifacts": biz_sources,
            }

    if "loan_amount_reduction" not in fired_rules:
        recommended = biz_data.get("recommended_loan_amount_inr")
        cut_pct: float | None = None
        if recommended is not None and loan_amount_inr and loan_amount_inr > 0:
            cut_pct = max(0.0, 1 - recommended / loan_amount_inr)
        out["loan_amount_reduction"] = {
            "loan_amount_inr": loan_amount_inr,
            "recommended_loan_amount_inr": recommended,
            "cut_pct": cut_pct,
            "trigger_pct": _LOAN_REDUCTION_TRIGGER_PCT,
            "rationale": biz_data.get("recommended_loan_rationale"),
            "photos_evaluated_count": business_photos_evaluated,
            "source_artifacts": biz_sources,
        }

    if "cattle_health" not in fired_rules:
        biz_type = biz_data.get("business_type")
        if biz_type in ("cattle_dairy", "mixed") and (biz_data.get("cattle_count") or 0) > 0:
            out["cattle_health"] = {
                "business_type": biz_type,
                "cattle_count": biz_data.get("cattle_count"),
                "cattle_health": biz_data.get("cattle_health"),
                "source_artifacts": biz_sources,
            }
        else:
            out["cattle_health"] = {
                "skipped_reason": (
                    f"not a dairy business (classified: {biz_type or 'unknown'})"
                ),
            }

    return out


# ─────────────────────────────── Enrichment helper ───────────────────────────


async def _enrich_items_with_crops_and_catalogue(
    session: AsyncSession,
    *,
    case_id: UUID,
    actor_user_id: UUID,
    business_type: str | None,
    biz_data: dict[str, Any],
    parent_artifacts: list[CaseArtifact],
    storage: Any,
) -> None:
    """Mutate biz_data["items"] in place: crop each item's bbox into a
    child artefact + upsert the catalogue + stamp catalogue/source
    fields on each item dict.

    Failures are non-fatal and degrade gracefully:
      - crop worker fails / no bbox  -> crop_artifact_id=None, item still
        renders with parent photo as source
      - business_type unknown -> skip catalogue (can't key without it),
        items keep ai-estimated MRP only
      - catalogue upsert exception -> log + skip that item's catalogue
        fields, item still renders with ai-estimated MRP

    Reasons L3 must NOT raise on enrichment failures: this is display
    augmentation, not gate logic. The 3 existing rules
    (stock_vs_loan / business_infrastructure / loan_amount_reduction)
    consume the aggregate fields, not items[]; they continue to function
    even if every item ends up un-cropped + un-catalogued.
    """
    items = biz_data.get("items") or []
    if not items:
        return

    # ── Crop each item's bbox into a child artefact ──
    try:
        from app.worker.image_crop import crop_business_premises_items

        await crop_business_premises_items(
            session,
            case_id=case_id,
            actor_user_id=actor_user_id,
            parent_artifacts=parent_artifacts,
            items=items,
            storage=storage,
        )
    except Exception as exc:  # noqa: BLE001 — never let crop failures escape
        _log.warning("L3: image crop step failed (non-fatal): %s", exc)
        for it in items:
            it.setdefault("crop_artifact_id", None)
            it.setdefault("crop_filename", None)

    # ── Upsert each item into the MRP catalogue ──
    if not business_type:
        # No business type -> skip catalogue (can't key without it).
        for it in items:
            it.setdefault("catalogue_mrp_inr", None)
            it.setdefault("mrp_source", "AI_ESTIMATED")
            it.setdefault("catalogue_entry_id", None)
        return

    from app.services.mrp_catalogue import upsert_from_ai

    for it in items:
        it.setdefault("catalogue_mrp_inr", None)
        it.setdefault("mrp_source", "AI_ESTIMATED")
        it.setdefault("catalogue_entry_id", None)

        mrp = it.get("mrp_estimate_inr")
        # Only upsert items the AI was willing to commit a number to.
        # Items with mrp_estimate_inr=null don't enter the catalogue
        # (no anchor to reuse next time).
        if mrp is None or not isinstance(mrp, int | float):
            continue
        if mrp <= 0:
            continue

        description = (it.get("description") or "").strip()
        category = it.get("category") or "other"
        if not description:
            continue

        try:
            entry = await upsert_from_ai(
                session,
                business_type=business_type,
                item_description=description,
                category=category,
                mrp_inr=int(mrp),
                confidence=it.get("mrp_confidence"),
                rationale=it.get("rationale"),
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "L3: catalogue upsert failed for item '%s' (non-fatal): %s",
                description,
                exc,
            )
            continue

        it["catalogue_mrp_inr"] = entry.mrp_inr
        it["mrp_source"] = entry.source  # AI_ESTIMATED | MANUAL | OVERRIDDEN_FROM_AI
        it["catalogue_entry_id"] = str(entry.id)


# ─────────────────────────────── Orchestrator ────────────────────────────────


async def run_level_3_vision(
    session: AsyncSession,
    case_id: UUID,
    *,
    actor_user_id: UUID,
    claude: Any,
    storage: Any,
) -> VerificationResult:
    """Run Level 3 on ``case_id`` and persist the result + issues."""
    from app.verification.services.vision_scorers import (
        BusinessPremisesScorer,
        HousePremisesScorer,
    )

    started = datetime.now(UTC)
    result = VerificationResult(
        case_id=case_id,
        level_number=VerificationLevelNumber.L3_VISION,
        status=VerificationLevelStatus.RUNNING,
        started_at=started,
        triggered_by=actor_user_id,
    )
    session.add(result)
    await session.flush()

    artifacts = (
        (await session.execute(select(CaseArtifact).where(CaseArtifact.case_id == case_id)))
        .scalars()
        .all()
    )

    def _sub(a: CaseArtifact) -> str | None:
        meta = a.metadata_json or {}
        return meta.get("subtype")

    house_arts = [
        a for a in artifacts if _sub(a) == ArtifactSubtype.HOUSE_VISIT_PHOTO.value
    ]
    biz_arts = [
        a
        for a in artifacts
        if _sub(a) == ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value
    ]

    async def _load(artifact_list: list[CaseArtifact]) -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = []
        for a in artifact_list:
            try:
                body = await storage.download_object(a.s3_key)
                out.append((a.filename, body))
            except Exception as exc:  # noqa: BLE001
                _log.warning("L3: storage fetch failed for %s: %s", a.s3_key, exc)
        return out

    house_imgs = await _load(house_arts)
    biz_imgs = await _load(biz_arts)

    case = await session.get(Case, case_id)
    loan_amount = getattr(case, "loan_amount", None) if case else None

    issues: list[dict[str, Any]] = []
    total_cost = Decimal("0")
    house_data: dict[str, Any] = {}
    biz_data: dict[str, Any] = {}

    # House
    house_scorer = HousePremisesScorer(claude=claude)
    h = await house_scorer.score(house_imgs)
    house_data = h.data
    total_cost += Decimal(str(h.data.get("cost_usd") or "0"))
    if h.error_message:
        issues.append(
            {
                "sub_step_id": "house_scorer_failed",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": f"House scorer failed: {h.error_message}",
                # Attach the raw scorer error + the photos it was fed so
                # the MD panel can show what went wrong and re-render the
                # same photos for a manual judgement. Matches the fire-path
                # shape used by cross_check_house_rating (error_message +
                # photos_evaluated_count + source_artifacts).
                "evidence": {
                    "error_message": h.error_message,
                    "photos_evaluated_count": len(house_imgs),
                    "source_artifacts": _pack(
                        *[
                            _ref(p, relevance="House-visit photo (scorer attempt)")
                            for p in house_arts[:8]
                        ]
                    ),
                },
            }
        )
    else:
        iss = cross_check_house_rating(h.data.get("overall_rating"))
        if iss:
            iss["evidence"] = {k: v for k, v in h.data.items() if k != "usage"}
            iss["evidence"]["photos_evaluated_count"] = len(house_imgs)
            # Cite the HOUSE_VISIT_PHOTOs the scorer looked at (capped at 8 —
            # plenty to judge without blowing up the modal).
            iss["evidence"]["source_artifacts"] = _pack(
                *[
                    _ref(p, relevance="House-visit photo (scored)")
                    for p in house_arts[:8]
                ]
            )
            issues.append(iss)

    # Business
    biz_scorer = BusinessPremisesScorer(claude=claude)
    b = await biz_scorer.score(
        biz_imgs, loan_amount_inr=int(loan_amount) if loan_amount else None
    )
    biz_data = b.data
    total_cost += Decimal(str(b.data.get("cost_usd") or "0"))
    if b.error_message:
        issues.append(
            {
                "sub_step_id": "business_scorer_failed",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": f"Business scorer failed: {b.error_message}",
                "evidence": {
                    "error_message": b.error_message,
                    "photos_evaluated_count": len(biz_imgs),
                    "source_artifacts": _pack(
                        *[
                            _ref(p, relevance="Business-premises photo (scorer attempt)")
                            for p in biz_arts[:8]
                        ]
                    ),
                },
            }
        )
    else:
        biz_type = b.data.get("business_type")
        biz_subtype = b.data.get("business_subtype")
        recommended_loan = b.data.get("recommended_loan_amount_inr")
        rec_rationale = b.data.get("recommended_loan_rationale")
        # Aggregate-vs-items drift is computed inside build_stock_analysis;
        # extract once here so the cross-check has access. Pure / inexpensive.
        pre_stock_analysis = build_stock_analysis(
            b.data, loan_amount_inr=int(loan_amount) if loan_amount else None,
        )
        agg_consistency = (
            pre_stock_analysis.get("aggregate_consistency")
            if pre_stock_analysis else None
        )
        for rule in (
            lambda: cross_check_stock_vs_loan(
                business_type=biz_type,
                stock_value_estimate_inr=b.data.get("stock_value_estimate_inr"),
                visible_equipment_value_inr=b.data.get("visible_equipment_value_inr"),
                loan_amount_inr=int(loan_amount) if loan_amount else None,
                recommended_loan_amount_inr=recommended_loan,
                recommended_loan_rationale=rec_rationale,
            ),
            lambda: cross_check_cattle_health(
                b.data.get("cattle_health"),
                business_type=b.data.get("business_type"),
                cattle_count=b.data.get("cattle_count"),
            ),
            lambda: cross_check_infrastructure_rating(b.data.get("infrastructure_rating")),
            lambda: cross_check_loan_amount_reduction(
                recommended_loan_amount_inr=recommended_loan,
                loan_amount_inr=int(loan_amount) if loan_amount else None,
                rationale=rec_rationale,
                business_type=biz_type,
                business_subtype=biz_subtype,
            ),
            lambda: cross_check_aggregate_drift(
                aggregate_consistency=agg_consistency,
            ),
        ):
            iss = rule()
            if iss:
                iss["evidence"] = {k: v for k, v in b.data.items() if k != "usage"}
                iss["evidence"]["photos_evaluated_count"] = len(biz_imgs)
                iss["evidence"]["source_artifacts"] = _pack(
                    *[
                        _ref(p, relevance="Business premises photo (scored)")
                        for p in biz_arts[:8]
                    ]
                )
                issues.append(iss)

    # Honour /admin/learning-rules suppressions.
    issues, suppressed_rules = await filter_suppressed_issues(session, issues)

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

    has_critical = any(
        i["severity"] == LevelIssueSeverity.CRITICAL.value for i in issues
    )
    result.status = (
        VerificationLevelStatus.BLOCKED if has_critical else VerificationLevelStatus.PASSED
    )
    # Enrich biz_data["items"] with crop artifacts + catalogue MRP data.
    # Must run AFTER the scorer + cross-checks (they read aggregate fields,
    # not items[]) and BEFORE build_stock_analysis (so items[] is enriched
    # in the persisted stock_analysis dict the FE reads).
    await _enrich_items_with_crops_and_catalogue(
        session=session,
        case_id=case_id,
        actor_user_id=actor_user_id,
        business_type=biz_data.get("business_type"),
        biz_data=biz_data,
        parent_artifacts=biz_arts,
        storage=storage,
    )

    fired_sub_step_ids = {i["sub_step_id"] for i in issues}
    result.sub_step_results = {
        "house": {k: v for k, v in house_data.items() if k != "usage"},
        "business": {k: v for k, v in biz_data.items() if k != "usage"},
        "house_photo_count": len(house_imgs),
        "business_photo_count": len(biz_imgs),
        "issue_count": len(issues),
        "suppressed_rules": suppressed_rules,
        "visual_evidence": build_visual_evidence(
            house_arts=house_arts,
            biz_arts=biz_arts,
            house_imgs_count=len(house_imgs),
            biz_imgs_count=len(biz_imgs),
        ),
        "stock_analysis": build_stock_analysis(
            biz_data,
            loan_amount_inr=int(loan_amount) if loan_amount else None,
        ),
        "pass_evidence": build_pass_evidence(
            house_data=house_data,
            biz_data=biz_data,
            loan_amount_inr=int(loan_amount) if loan_amount else None,
            house_photos_evaluated=len(house_imgs),
            business_photos_evaluated=len(biz_imgs),
            fired_rules=fired_sub_step_ids,
            house_arts=house_arts,
            biz_arts=biz_arts,
        ),
    }
    result.cost_usd = total_cost
    result.completed_at = datetime.now(UTC)
    await session.flush()
    # Carry forward terminal MD / assessor decisions from any prior run on
    # the same (case, level) so re-triggers don't orphan the MD's audit
    # trail. May promote ``result.status`` to PASSED_WITH_MD_OVERRIDE.
    await carry_forward_prior_decisions(session, result=result)
    return result
