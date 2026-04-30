"""Step 1: Policy Gates — pure Python, no LLM.

Applies hard rules from policy.yaml against extraction data.
Short-circuits the pipeline (hard_fail=True) when any gate fails.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus

_log = logging.getLogger(__name__)

STEP_NUMBER = 1
STEP_NAME = "policy_gates"


def _get_autocam(extractions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Extract AutoCam data from extractions dict."""
    return extractions.get("auto_cam", extractions.get("autocam", {})) or {}


def _get_checklist(extractions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Extract checklist validator output."""
    return extractions.get("checklist_validator", extractions.get("checklist", {})) or {}


async def run(ctx: StepContext, claude: Any) -> StepOutput:  # noqa: ARG001
    """Apply hard policy gates. No LLM call."""
    policy = ctx.policy
    hard_rules: dict[str, Any] = policy.get("hard_rules", {})
    autocam = _get_autocam(ctx.extractions)
    checklist = _get_checklist(ctx.extractions)

    per_rule_results: dict[str, dict[str, Any]] = {}
    hard_fail = False
    fail_reason: str | None = None
    warnings: list[str] = []

    # ── CIBIL applicant ──────────────────────────────────────────────────────
    cibil_min = hard_rules.get("cibil_min", 700)
    _cibil_raw = autocam.get("cibil_score")
    if _cibil_raw is None:
        _cibil_raw = autocam.get("applicant_cibil_score")
    applicant_cibil = _cibil_raw
    if applicant_cibil is not None:
        applicant_cibil = int(applicant_cibil)
        # Treat 0 as 650 per heuristics
        if applicant_cibil == 0:
            applicant_cibil = 650
        cibil_passed = applicant_cibil >= cibil_min
        per_rule_results["applicant_cibil"] = {
            "passed": cibil_passed,
            "actual_value": applicant_cibil,
            "policy_value": cibil_min,
        }
        if not cibil_passed:
            hard_fail = True
            fail_reason = "cibil_below_700"
    else:
        warnings.append("applicant_cibil_score missing from AutoCAM")

    # ── CIBIL co-applicant ──────────────────────────────────────────────────
    coapplicant_cibil_min = hard_rules.get("coapplicant_cibil_min", 700)
    co_cibil = autocam.get("coapplicant_cibil_score") or autocam.get("co_applicant_cibil_score")
    if co_cibil is not None:
        co_cibil = int(co_cibil)
        if co_cibil == 0:
            co_cibil = 650
        co_passed = co_cibil >= coapplicant_cibil_min
        per_rule_results["coapplicant_cibil"] = {
            "passed": co_passed,
            "actual_value": co_cibil,
            "policy_value": coapplicant_cibil_min,
        }
        if not co_passed and not hard_fail:
            hard_fail = True
            fail_reason = "cibil_below_700"

    # ── Applicant age ────────────────────────────────────────────────────────
    age_min = hard_rules.get("applicant_age_min", 21)
    age_max = hard_rules.get("applicant_age_max", 60)
    applicant_age = autocam.get("applicant_age") or autocam.get("age")
    if applicant_age is not None:
        applicant_age = int(applicant_age)
        age_passed = age_min <= applicant_age <= age_max
        per_rule_results["applicant_age"] = {
            "passed": age_passed,
            "actual_value": applicant_age,
            "policy_value": f"{age_min}-{age_max}",
        }
        if not age_passed and not hard_fail:
            hard_fail = True
            fail_reason = "age_out_of_bounds"
    else:
        warnings.append("applicant_age missing from AutoCAM")

    # ── Indebtedness ─────────────────────────────────────────────────────────
    max_indebtedness = hard_rules.get("max_total_indebtedness_inr", 500_000)
    total_indebtedness = autocam.get("total_existing_indebtedness_inr") or autocam.get(
        "total_indebtedness"
    )
    if total_indebtedness is not None:
        total_indebtedness = float(total_indebtedness)
        indebt_passed = total_indebtedness < max_indebtedness
        per_rule_results["indebtedness"] = {
            "passed": indebt_passed,
            "actual_value": total_indebtedness,
            "policy_value": max_indebtedness,
        }
        if not indebt_passed and not hard_fail:
            hard_fail = True
            fail_reason = "indebtedness_exceeds_cap"
    else:
        warnings.append("total_indebtedness missing from AutoCAM")

    # ── Negative CIBIL statuses ───────────────────────────────────────────────
    negative_statuses = hard_rules.get("negative_statuses", ["WRITTEN_OFF", "SUIT_FILED", "LSS"])
    cibil_statuses = autocam.get("cibil_account_statuses", []) or []
    if isinstance(cibil_statuses, list):
        found_negatives = [s for s in cibil_statuses if s in negative_statuses]
        neg_passed = len(found_negatives) == 0
        per_rule_results["cibil_negative_status"] = {
            "passed": neg_passed,
            "actual_value": found_negatives,
            "policy_value": negative_statuses,
        }
        if not neg_passed and not hard_fail:
            hard_fail = True
            fail_reason = "negative_cibil_status"

    # ── Geo / distance ────────────────────────────────────────────────────────
    max_distance_km = hard_rules.get("max_business_distance_km", 25)
    geo_distance = autocam.get("business_distance_km")
    if geo_distance is not None:
        geo_distance = float(geo_distance)
        geo_passed = geo_distance <= max_distance_km
        per_rule_results["geo_distance"] = {
            "passed": geo_passed,
            "actual_value": geo_distance,
            "policy_value": max_distance_km,
        }
        if not geo_passed and not hard_fail:
            hard_fail = True
            fail_reason = "business_outside_serviceable_area"
    else:
        warnings.append("geo_distance not available, skipping distance gate")
        per_rule_results["geo_distance"] = {
            "passed": True,
            "actual_value": None,
            "policy_value": max_distance_km,
            "note": "skipped: data unavailable",
        }

    # ── Document checklist ────────────────────────────────────────────────────
    checklist_complete = checklist.get("all_required_present", checklist.get("passed", True))
    missing_docs = checklist.get("missing_docs", checklist.get("missing", []))
    pause_for_upload = False
    if not checklist_complete:
        pause_for_upload = True
        warnings.append(f"Missing required documents: {missing_docs}")
    per_rule_results["doc_checklist"] = {
        "passed": checklist_complete,
        "actual_value": {"missing": missing_docs},
        "policy_value": "all required docs present",
    }

    passed_all = not hard_fail and not pause_for_upload

    status = StepStatus.SUCCEEDED
    if hard_fail:
        status = StepStatus.FAILED

    output_data: dict[str, Any] = {
        "passed_all": passed_all,
        "per_rule_results": per_rule_results,
        "pause_for_upload": pause_for_upload,
    }

    return StepOutput(
        status=status,
        step_name=STEP_NAME,
        step_number=STEP_NUMBER,
        model_used=None,
        output_data=output_data,
        citations=[],
        hard_fail=hard_fail,
        warnings=warnings,
        error_message=fail_reason,
    )
