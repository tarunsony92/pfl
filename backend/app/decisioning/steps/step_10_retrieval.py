"""Step 10: Case Library Retrieval — No LLM, embeddings-based.

Uses compute_feature_vector + similarity_search from the foundation.
Gracefully degrades when fewer than 10 cases exist or pgvector unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.case_library import compute_feature_vector, similarity_search
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus

_log = logging.getLogger(__name__)

STEP_NUMBER = 10
STEP_NAME = "case_library_retrieval"


async def run(ctx: StepContext, claude: Any) -> StepOutput:  # noqa: ARG001
    """Retrieve similar past cases using feature vector similarity."""
    autocam = (
        ctx.extractions.get("auto_cam")
        or ctx.extractions.get("autocam")
        or {}
    )
    step2 = ctx.prior_steps.get(2)
    step3 = ctx.prior_steps.get(3)
    step8 = ctx.prior_steps.get(8)

    # Build feature vector from available data
    loan_amount = 0.0
    if hasattr(ctx, "case") and ctx.case is not None:
        loan_amount = float(getattr(ctx.case, "loan_amount", 0) or 0)
    if loan_amount == 0:
        _la_fallback = autocam.get("loan_amount_requested", autocam.get("loan_amount", 0))
        loan_amount = float(_la_fallback or 0)

    cibil_score = float(autocam.get("cibil_score") or autocam.get("applicant_cibil_score") or 700)
    if cibil_score == 0:
        cibil_score = 650.0

    foir_pct = 0.0
    if step8 and step8.output_data:
        foir_raw = step8.output_data.get("foir", 0.0)
        # Normalize: if given as percentage (e.g. 35.0), convert to fraction
        foir_pct = foir_raw / 100.0 if foir_raw > 1.0 else float(foir_raw)

    business_type = str(
        autocam.get("business_type") or autocam.get("business_category") or "OTHER"
    )
    district = str(autocam.get("district") or autocam.get("location") or "")

    monthly_income = 0.0
    if step3 and step3.output_data:
        monthly_income = float(step3.output_data.get("total_monthly_inflow_inr") or 0)
    if monthly_income == 0:
        _inc_fallback = autocam.get("monthly_income", autocam.get("net_monthly_income", 0))
        monthly_income = float(_inc_fallback or 0)

    abb = 0.0
    if step2 and step2.output_data:
        abb = float(step2.output_data.get("abb_inr") or 0)

    tenure_months = 24.0
    if hasattr(ctx, "case") and ctx.case is not None:
        tenure_months = float(getattr(ctx.case, "loan_tenure_months", 24) or 24)

    feature_vector = compute_feature_vector(
        loan_amount=loan_amount,
        cibil_score=cibil_score,
        foir_pct=foir_pct,
        business_type=business_type,
        district=district,
        monthly_income_inr=monthly_income,
        abb_inr=abb,
        tenure_months=tenure_months,
    )

    similar_cases: list[dict[str, Any]] = []
    note: str | None = None

    # Try DB retrieval if session is available
    db_session = getattr(ctx, "db_session", None)
    if db_session is not None:
        try:
            raw_results = await similarity_search(
                session=db_session,
                vector=feature_vector,
                k=10,
            )
            if len(raw_results) < 10:
                note = "case_library_empty" if not raw_results else "insufficient_cases_in_library"
            similar_cases = [
                {
                    "case_id": r.get("case_id"),
                    "loan_id": r.get("id"),
                    "decision": r.get("final_decision"),
                    "outcome": r.get("final_decision"),
                    "similarity_score": r.get("similarity"),
                    "feedback_notes": r.get("reasoning_markdown", ""),
                }
                for r in raw_results
            ]
        except Exception as exc:  # noqa: BLE001
            _log.warning("Case library retrieval failed: %s", exc)
            note = "case_library_empty"
    else:
        note = "case_library_empty"

    output_data: dict[str, Any] = {
        "similar_cases": similar_cases,
        "feature_vector": feature_vector,
        "note": note,
    }

    return StepOutput(
        status=StepStatus.SUCCEEDED,
        step_name=STEP_NAME,
        step_number=STEP_NUMBER,
        model_used=None,
        output_data=output_data,
        citations=[],
    )
