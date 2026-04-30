"""AutoJustifier — Claude self-resolve pass on verification-gate issues.

Runs after each level engine has created its ``LevelIssue`` rows. For every
issue the justifier:

1. Reads past MD rulings on the same ``sub_step_id`` from the DB (precedents).
2. Gathers the case context (extractions, CAM fields, loan amount).
3. Calls Claude Sonnet with: the issue description + evidence + precedents +
   case context + strict output format.
4. Parses a verdict ``{can_justify, confidence, assessor_note, md_rationale}``.

When the verdict is ``can_justify=true`` AND ``confidence >= AUTO_THRESHOLD``,
the caller marks the issue ``MD_APPROVED`` with the AI's rationale prefixed
with a clear ``[AI auto-justified @ confidence X%]`` tag so the UI and audit
log can distinguish AI-resolved issues from human-MD decisions.

The MD can always override an AI auto-justification after the fact.

Cost: ~$0.01-0.02 per issue on Sonnet with the current prompt.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import LevelIssueStatus
from app.models.case import Case
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult

_log = logging.getLogger(__name__)

AUTO_THRESHOLD = 75  # require >=75% AI confidence to auto-resolve
AI_MARKER_ASSESSOR = "[AI] "
AI_MARKER_MD_PREFIX = "[AI auto-justified @ confidence "
# [CASE_SPECIFIC] approvals are MD one-offs the MD explicitly did NOT want to
# generalise into precedent. The justifier must never surface them as past
# rulings, or it would learn patterns the MD rejected learning.
CASE_SPECIFIC_MARKER = "[CASE_SPECIFIC]"

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class AIJustification:
    can_justify: bool
    confidence: int  # 0-100
    assessor_note: str
    md_rationale: str
    cost_usd: Decimal
    model_used: str


_SYSTEM_PROMPT = """You are an AI credit-risk analyst at PFL Finance. You are
reading a single concern raised by the pre-Phase-1 verification gate on a
microfinance loan case, and deciding whether the concern can be auto-resolved
with high confidence OR whether it must be escalated to the Managing Director.

Your default is to ESCALATE. Only claim you can justify dismissing the concern
when the evidence in the case + past MD rulings PROVABLY resolves it. Prefer
false negatives over false positives: a missed MD review is recoverable; an
auto-dismissed CRITICAL concern on a real risk is not.

Output format — respond ONLY with valid JSON exactly matching:
{
  "can_justify": true | false,
  "confidence": <int 0-100>,
  "assessor_note": "<1-3 sentences — what the assessor would write if resolving>",
  "md_rationale": "<1-3 sentences — what the MD would write when approving>"
}

Rules:
- Set ``can_justify=true`` only when confidence >= 75.
- WARNING severity may auto-justify at confidence >= 70.
- CRITICAL severity requires strict evidence + clear precedent alignment.
- If past MD rulings on the same sub_step_id are mixed or absent, set
  ``can_justify=false`` — let the human MD decide.
- Cite concrete evidence in ``assessor_note`` (bank figures, photos analysed,
  matching addresses, etc.). Never fabricate values.
"""


def _extract_json(text: str) -> dict[str, Any]:
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"no JSON found in: {text[:200]!r}")
    return json.loads(m.group(0))


def _build_user_prompt(
    *,
    issue: LevelIssue,
    precedents: list[dict[str, Any]],
    case_context: dict[str, Any],
) -> str:
    precedent_block = ""
    if precedents:
        lines = []
        for p in precedents[:6]:
            lines.append(
                f"  - {p['decision']} on loan {p['loan_id']}"
                f" ({p['applicant_name'] or 'unknown'}):"
                f" {p.get('md_rationale') or '—'}"
            )
        precedent_block = (
            "\n=== PAST MD RULINGS ON THIS RULE ===\n"
            + f"approved: {sum(1 for p in precedents if p['decision'] == 'MD_APPROVED')}"
            + f" · rejected: {sum(1 for p in precedents if p['decision'] == 'MD_REJECTED')}\n"
            + "\n".join(lines)
        )
    else:
        precedent_block = "\n=== PAST MD RULINGS ===\nNone recorded for this rule."

    evidence_block = ""
    if issue.evidence:
        try:
            evidence_block = json.dumps(issue.evidence, indent=2)[:2000]
        except Exception:
            evidence_block = str(issue.evidence)[:2000]

    ctx = case_context
    ctx_block = (
        f"applicant: {ctx.get('applicant_name')}\n"
        f"co_applicant: {ctx.get('co_applicant_name')}\n"
        f"loan_amount_inr: {ctx.get('loan_amount')}\n"
        f"tenure_months: {ctx.get('loan_tenure_months')}\n"
    )

    return f"""Concern to justify (or escalate):

sub_step_id: {issue.sub_step_id}
severity:    {issue.severity.value}
description: {issue.description}

=== EVIDENCE ===
{evidence_block}

=== CASE CONTEXT ===
{ctx_block}
{precedent_block}

Decide whether this concern can be auto-justified. Respond with JSON only.
"""


async def _fetch_precedents(
    session: AsyncSession, sub_step_id: str
) -> list[dict[str, Any]]:
    """Fetch every past MD_APPROVED / MD_REJECTED issue on the same sub_step_id."""
    stmt = (
        select(LevelIssue, VerificationResult, Case)
        .join(
            VerificationResult,
            LevelIssue.verification_result_id == VerificationResult.id,
        )
        .join(Case, VerificationResult.case_id == Case.id)
        .where(LevelIssue.sub_step_id == sub_step_id)
        .where(
            LevelIssue.status.in_(
                [LevelIssueStatus.MD_APPROVED, LevelIssueStatus.MD_REJECTED]
            )
        )
        .order_by(LevelIssue.md_reviewed_at.desc().nulls_last())
        .limit(12)
    )
    rows = (await session.execute(stmt)).all()
    out: list[dict[str, Any]] = []
    for issue, _lr, case in rows:
        # Skip AI-marker precedents — we want human MD rulings as ground truth.
        if issue.md_rationale and issue.md_rationale.startswith(AI_MARKER_MD_PREFIX):
            continue
        # Skip case-specific approvals — MD explicitly flagged these as one-offs
        # that should NOT teach the model to auto-resolve similar issues.
        if issue.md_rationale and issue.md_rationale.startswith(CASE_SPECIFIC_MARKER):
            continue
        out.append(
            {
                "decision": issue.status.value,
                "loan_id": case.loan_id,
                "applicant_name": case.applicant_name,
                "md_rationale": issue.md_rationale,
            }
        )
    return out


async def try_auto_justify(
    *,
    issue: LevelIssue,
    precedents: list[dict[str, Any]],
    case_context: dict[str, Any],
    claude: Any,
) -> AIJustification | None:
    """Ask Claude Sonnet whether this issue can be auto-resolved. Return None
    on API / parse error (caller should leave the issue OPEN).
    """
    user_prompt = _build_user_prompt(
        issue=issue, precedents=precedents, case_context=case_context
    )

    try:
        message = await claude.invoke(
            tier="sonnet",
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            cache_system=True,
            max_tokens=512,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("auto_justify: Claude call failed: %s", exc)
        return None

    raw = claude.extract_text(message)
    try:
        parsed = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        _log.warning("auto_justify: parse failed — %s — raw: %r", exc, raw[:200])
        return None

    can_justify = bool(parsed.get("can_justify", False))
    try:
        confidence = int(parsed.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))

    from app.services.claude import MODELS

    model = MODELS.get("sonnet", "sonnet")
    usage = claude.usage_dict(message)
    cost = Decimal(str(claude.cost_usd(model, usage)))

    return AIJustification(
        can_justify=can_justify,
        confidence=confidence,
        assessor_note=str(parsed.get("assessor_note") or "")[:2000],
        md_rationale=str(parsed.get("md_rationale") or "")[:2000],
        cost_usd=cost,
        model_used=model,
    )


async def auto_justify_level_issues(
    *,
    session: AsyncSession,
    case_id: Any,
    issue_rows: list[LevelIssue],
    claude: Any,
) -> tuple[int, Decimal]:
    """Apply AutoJustifier to every OPEN issue in ``issue_rows``.

    Marks issues ``MD_APPROVED`` in-place when Claude clears the threshold.
    Returns ``(count_auto_justified, total_cost_usd)``.
    """
    if not issue_rows:
        return 0, Decimal("0")

    # Load case context once
    case = await session.get(Case, case_id)
    if case is None:
        return 0, Decimal("0")
    case_context = {
        "applicant_name": case.applicant_name,
        "co_applicant_name": case.co_applicant_name,
        "loan_amount": case.loan_amount,
        "loan_tenure_months": case.loan_tenure_months,
    }

    # Cache precedents per sub_step_id to avoid repeat queries
    precedents_cache: dict[str, list[dict[str, Any]]] = {}

    from datetime import UTC, datetime

    resolved = 0
    total_cost = Decimal("0")
    for issue in issue_rows:
        if issue.status != LevelIssueStatus.OPEN:
            continue

        subkey = issue.sub_step_id
        if subkey not in precedents_cache:
            precedents_cache[subkey] = await _fetch_precedents(session, subkey)
        precedents = precedents_cache[subkey]

        verdict = await try_auto_justify(
            issue=issue,
            precedents=precedents,
            case_context=case_context,
            claude=claude,
        )
        if verdict is None:
            continue
        total_cost += verdict.cost_usd

        # Apply threshold. WARNING gets a slightly lower bar (70).
        from app.enums import LevelIssueSeverity

        threshold = AUTO_THRESHOLD
        if issue.severity == LevelIssueSeverity.WARNING:
            threshold = 70
        elif issue.severity == LevelIssueSeverity.CRITICAL:
            threshold = 80  # harder bar for CRITICAL auto-dismiss

        if not verdict.can_justify or verdict.confidence < threshold:
            _log.info(
                "auto_justify: leaving %s OPEN (justify=%s, confidence=%s/%s)",
                issue.sub_step_id,
                verdict.can_justify,
                verdict.confidence,
                threshold,
            )
            continue

        now = datetime.now(UTC)
        issue.assessor_user_id = None
        issue.assessor_note = AI_MARKER_ASSESSOR + (verdict.assessor_note or "—")
        issue.assessor_resolved_at = now
        issue.md_user_id = None
        issue.md_rationale = (
            f"{AI_MARKER_MD_PREFIX}{verdict.confidence}%] "
            f"{verdict.md_rationale or '—'}"
        )
        issue.md_reviewed_at = now
        issue.status = LevelIssueStatus.MD_APPROVED
        resolved += 1
        _log.info(
            "auto_justify: resolved %s at confidence %s%%",
            issue.sub_step_id,
            verdict.confidence,
        )

    if resolved:
        await session.flush()
    return resolved, total_cost
