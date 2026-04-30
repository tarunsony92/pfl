"""Step 11: Final Synthesis — Opus.

THE BIG ONE. Ingests all 10 prior steps + policy + heuristics + retrieved similar cases,
and produces the final credit decision.

System block is cached (full policy + heuristics + role description + output format).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 11
STEP_NAME = "final_synthesis"
_TIER = "opus"
_MODEL_ID = MODELS[_TIER]

_SYSTEM_TEMPLATE = """\
You are Saksham's AI credit-head at PFL Finance, applying his codified judgment
for Phase 1 microfinance credit decisions in rural India.

=== POLICY ===
{policy}

=== CREDIT HEURISTICS ===
{heuristics}

=== 4-LEVEL VERIFICATION WEIGHT (HIGHEST) ===
The case has been run through a strict 4-level pre-Phase-1 verification gate
(L1 Address, L2 Banking, L3 Vision, L4 Loan-Agreement assets). Those outputs
are supplied to you under "=== 4-LEVEL VERIFICATION OUTPUTS ===" below and
carry the HIGHEST weight in your confidence score:

- If all 4 levels are PASSED or PASSED_WITH_MD_OVERRIDE unambiguously, start
  your confidence at 85+. The 11 sub-step outputs are supporting evidence
  only — do not let them pull confidence below 85 on an otherwise-clean gate.
- If ANY level is BLOCKED, FAILED, or has unresolved OPEN issues, cap
  confidence at 70 and set decision = ESCALATE_TO_CEO regardless of the
  11 sub-step evidence. An unresolved gate is non-negotiable.
- PASSED_WITH_MD_OVERRIDE means the MD has already waived a flag — treat it
  like PASSED but lower confidence by ~5 points per overridden level as a
  mild uncertainty penalty.
- A level shown as PENDING (not yet run) is neither a pass nor a fail; treat
  it as unknown and cap confidence at 70 until it runs.

=== DECISION RULES ===
1. Any 4-level BLOCKED / FAILED / PENDING → decision = ESCALATE_TO_CEO.
2. If ANY policy deviation is present → decision = ESCALATE_TO_CEO.
3. If confidence_score < {confidence_auto_threshold} → decision = ESCALATE_TO_CEO.
4. If Step 1 had hard_fail → decision = REJECT (pipeline should have stopped, handle defensively).
5. APPROVE: all 4 gates PASSED, all steps clean, FOIR < 40%, strong income proof, consistent addresses.
6. APPROVE_WITH_CONDITIONS: gates PASSED (with or without MD override), minor step-level issues resolvable with conditions (e.g., lower amount).
7. REJECT: hard policy violation or multiple serious red flags despite gates green.
8. ESCALATE_TO_CEO: any unresolved gate, deviations, borderline, or insufficient confidence.

=== OUTPUT FORMAT ===
Respond ONLY with valid JSON matching this exact schema:
{{
  "decision": "APPROVE"|"APPROVE_WITH_CONDITIONS"|"REJECT"|"ESCALATE_TO_CEO",
  "recommended_amount": <integer or null>,
  "recommended_tenure": <integer or null>,
  "conditions": [<string>],
  "reasoning_markdown": <string — detailed markdown reasoning>,
  "pros_cons": {{
    "pros": [{{"text": <string>, "citations": [<string>]}}],
    "cons": [{{"text": <string>, "citations": [<string>]}}]
  }},
  "deviations": [
    {{"name": <string>, "policy_rule": <string>,
      "severity": "low"|"medium"|"high", "justification": <string>}}
  ],
  "risk_summary": [<string>],
  "confidence_score": <integer 0-100>
}}
"""

_USER_TEMPLATE = """\
=== 4-LEVEL VERIFICATION OUTPUTS (highest weight) ===
{verification_outputs}

=== PRIOR STEP OUTPUTS ===

Step 1 (Policy Gates):
{step1}

Step 2 (Banking Check):
{step2}

Step 3 (Income Analysis):
{step3}

Step 4 (KYC Verification):
{step4}

Step 5 (Address Verification):
{step5}

Step 6 (Business Premises):
{step6}

Step 7 (Stock Quantification):
{step7}

Step 8 (Reconciliation):
{step8}

Step 9 (PD Sheet Analysis):
{step9}

Step 10 (Case Library Retrieval):
{step10}

=== SIMILAR HISTORICAL CASES ===
{similar_cases}

Please provide your final credit decision with full reasoning.
"""


def _summarize_step(step: Any) -> str:
    """Create a concise summary of a step output for the synthesis prompt."""
    if step is None:
        return "Not executed"
    try:
        return json.dumps(
            {
                "status": str(step.status),
                "output": step.output_data,
                "hard_fail": step.hard_fail,
                "warnings": step.warnings,
                "error": step.error_message,
            },
            ensure_ascii=False,
            default=str,
        )[:2000]  # Cap at 2000 chars per step to manage context
    except Exception:  # noqa: BLE001
        return str(step.output_data)[:1000]


def _format_verification_outputs(ctx: StepContext) -> tuple[str, dict[str, Any]]:
    """Serialise ``ctx.verification_results`` into the JSON block Opus receives.

    Returns (json_string, summary_dict). ``summary_dict`` is used by
    post-processing to decide whether to force ESCALATE on BLOCKED.
    """
    results = getattr(ctx, "verification_results", None) or {}
    summary: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    for level_name, row in results.items():
        if row is None:
            summary[level_name] = "PENDING"
            payload[level_name] = {"status": "PENDING", "note": "level not yet run"}
            continue
        status = getattr(row.status, "value", str(row.status))
        summary[level_name] = status
        payload[level_name] = {
            "status": status,
            "cost_usd": str(row.cost_usd) if row.cost_usd is not None else None,
            "sub_step_results": row.sub_step_results,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
    # Include a header summary so Opus sees the verdict at a glance.
    payload["_summary"] = summary
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:6000],
        summary,
    )


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run final synthesis using Opus."""
    # Build cached system block
    policy_str = json.dumps(ctx.policy, ensure_ascii=False, indent=2)
    try:
        from app.config import get_settings

        _auto_threshold = get_settings().decisioning_confidence_auto_threshold
    except Exception:  # pragma: no cover
        _auto_threshold = 60
    system_prompt = _SYSTEM_TEMPLATE.format(
        policy=policy_str,
        heuristics=ctx.heuristics,
        confidence_auto_threshold=_auto_threshold,
    )

    # Gather similar cases from step 10
    step10 = ctx.prior_steps.get(10)
    similar_cases_raw = []
    if step10 and step10.output_data:
        similar_cases_raw = step10.output_data.get("similar_cases", [])
    similar_cases_str = (
        json.dumps(similar_cases_raw[:5], ensure_ascii=False, indent=2)
        if similar_cases_raw
        else "No similar cases found in library"
    )

    # Check for step 1 hard fail — defensive handling
    step1 = ctx.prior_steps.get(1)
    if step1 and step1.hard_fail:
        # Pipeline should have stopped but handle defensively
        output_data: dict[str, Any] = {
            "decision": "REJECT",
            "recommended_amount": None,
            "recommended_tenure": None,
            "conditions": [],
            "reasoning_markdown": (
                f"Hard policy failure at Step 1: {step1.error_message}. "
                "Application does not meet minimum eligibility criteria."
            ),
            "pros_cons": {"pros": [], "cons": [{"text": step1.error_message, "citations": []}]},
            "deviations": [],
            "risk_summary": [f"Hard fail: {step1.error_message}"],
            "confidence_score": 99,
        }
        return StepOutput(
            status=StepStatus.SUCCEEDED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data=output_data,
            citations=[],
        )

    verif_json, verif_summary = _format_verification_outputs(ctx)
    user_message = _USER_TEMPLATE.format(
        verification_outputs=verif_json,
        step1=_summarize_step(ctx.prior_steps.get(1)),
        step2=_summarize_step(ctx.prior_steps.get(2)),
        step3=_summarize_step(ctx.prior_steps.get(3)),
        step4=_summarize_step(ctx.prior_steps.get(4)),
        step5=_summarize_step(ctx.prior_steps.get(5)),
        step6=_summarize_step(ctx.prior_steps.get(6)),
        step7=_summarize_step(ctx.prior_steps.get(7)),
        step8=_summarize_step(ctx.prior_steps.get(8)),
        step9=_summarize_step(ctx.prior_steps.get(9)),
        step10=_summarize_step(ctx.prior_steps.get(10)),
        similar_cases=similar_cases_str,
    )

    try:
        message = await claude.invoke(
            tier=_TIER,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            cache_system=True,
            max_tokens=4096,
        )
        response_text = claude.extract_text(message)
        output_data = _extract_json_from_text(response_text)

        # Enforce decision rules
        decision = output_data.get("decision", "ESCALATE_TO_CEO")
        confidence = int(output_data.get("confidence_score", 0))
        deviations = output_data.get("deviations", [])

        # 4-level override: any unresolved gate forces ESCALATE regardless of
        # what Opus returned. PASSED / PASSED_WITH_MD_OVERRIDE flow through.
        _BLOCKING_STATES = {"BLOCKED", "FAILED", "RUNNING", "PENDING"}
        unresolved_levels = [
            lvl for lvl, st in verif_summary.items() if st in _BLOCKING_STATES
        ]
        if unresolved_levels:
            decision = "ESCALATE_TO_CEO"
            output_data.setdefault("risk_summary", []).append(
                f"unresolved 4-level gates: {unresolved_levels}"
            )

        if deviations:
            decision = "ESCALATE_TO_CEO"
        if confidence < _auto_threshold:
            decision = "ESCALATE_TO_CEO"
        output_data["decision"] = decision
        output_data["verification_summary"] = verif_summary

        # Defaults
        output_data.setdefault("recommended_amount", None)
        output_data.setdefault("recommended_tenure", None)
        output_data.setdefault("conditions", [])
        output_data.setdefault("reasoning_markdown", "")
        output_data.setdefault("pros_cons", {"pros": [], "cons": []})
        output_data.setdefault("deviations", [])
        output_data.setdefault("risk_summary", [])
        output_data.setdefault("confidence_score", confidence)

        usage = build_usage(message, _MODEL_ID)
        return StepOutput(
            status=StepStatus.SUCCEEDED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data=output_data,
            citations=[],
            **usage,
        )
    except Exception as exc:  # noqa: BLE001
        _log.exception("Step 11 synthesis failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
