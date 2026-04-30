"""CreditAnalyst — Opus-4.7 seasoned-credit-expert read of the applicant +
co-applicant Equifax reports.

PFL's policy on willful default and fraud indicators is encoded here as
hardcoded terminology guardrails (see ``CREDIT_GUARDRAILS``), which are both
injected into Opus's system prompt and used by pure-Python red-flag rules in
``level_1_5_credit``. The analyst returns a structured verdict + per-party
findings that the engine converts into LevelIssues.

Cost per case is ~$0.08–0.15 at Opus rates (cached system prompt, ~3-5k
input tokens + 1-2k output). We run it at most once per L1.5 trigger.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.enums import ExtractionStatus
from app.worker.extractors.base import ExtractionResult

_log = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


# ── PFL credit guardrails (from the ops team's infographic) ──────────────────
# These are the authoritative meanings we hardcode into the prompt so Opus
# cannot "invent" a softer interpretation. The frontend RULE_CATALOG mirrors
# these sub-step ids.

CREDIT_GUARDRAILS: dict[str, Any] = {
    "dpd_buckets": {
        # DPD = Days Past Due. Higher → higher risk.
        "000": "On Time — healthy profile, EMI paid on schedule.",
        "030": "30 days late — 1 EMI missed, early-warning.",
        "060": "60 days late — risk increasing, recovery watch.",
        "090": "90+ days late — high risk, possible default / SUB.",
    },
    "account_status_positive": {
        "STD": "Standard — account normal, EMIs paid on time. Positive signal.",
        "CLOSED": "Fully paid and closed. Positive signal.",
    },
    "account_status_early_warning": {
        # SMA = Special Mention Account — early warning signals
        "SMA-0": "1–30 days overdue — early-warning, monitor.",
        "SMA-1": "31–60 days overdue — elevated risk.",
        "SMA-2": "61–90 days overdue — pre-NPA.",
    },
    "account_status_negative": {
        "SUB": "Substandard — 90+ days overdue, account moving toward NPA.",
        "DBT": "Doubtful — recovery uncertain, high-risk.",
        "LSS": "Loss — bank considers amount uncollectible.",
        "WO": (
            "Write-Off — loan removed from lender's books but borrower is still "
            "legally liable. Strong willful-default indicator."
        ),
        "SETTLED": (
            "Settled / Compromised — closed with partial payment only. "
            "Negative signal: borrower did not honour the original contract."
        ),
    },
    "willful_default_statuses": ["WO", "LSS", "SETTLED", "DBT"],
    "fraud_indicator_statuses": ["WO", "LSS"],
    "key_checks": [
        "Payment History",
        "DPD Pattern",
        "Active Loans Count",
        "Credit Utilization",
        "Enquiry Count",
    ],
}


_SYSTEM_PROMPT = """You are a seasoned credit-risk analyst at PFL Finance, a
rural microfinance lender in Haryana / Punjab / western UP. You review the
applicant's AND co-applicant's bureau reports (Equifax / CIBIL / Highmark
format) and determine whether this loan should proceed, get an MD review, or
be rejected outright.

You are STRICT. A rural microfinance book has no room for willful-default
risk. When in doubt, escalate — do not soften findings.

=== MANDATORY TERMINOLOGY GUARDRAILS ===

DPD (Days Past Due):
- DPD 000 — On Time, healthy profile.
- DPD 030 — 30 days late, 1 EMI missed. Early warning.
- DPD 060 — 60 days late, risk increasing.
- DPD 090 — 90+ days late, HIGH RISK / possible default.

Account status codes — ALWAYS interpret them exactly as below:
- STD / Standard   — normal account, EMIs paid on time. POSITIVE.
- CLOSED           — fully paid and closed. POSITIVE.
- SMA-0            — 1–30 days overdue. Early warning.
- SMA-1            — 31–60 days overdue. Elevated risk.
- SMA-2            — 61–90 days overdue. Pre-NPA.
- SUB / Substandard — 90+ days overdue, moving toward NPA.
- DBT / Doubtful   — recovery uncertain, high risk.
- LSS / Loss       — lender considers it uncollectible. STRONG fraud flag.
- WO / Write-Off   — removed from books, borrower STILL LIABLE. STRONG
                     willful-default flag.
- SETTLED / Compromised — closed with partial payment. NEGATIVE.

Willful-default indicators (treat each instance as a serious flag):
  WO, LSS, SETTLED, DBT.

Fraud indicators (treat as likely fraud unless bureau errata explains it):
  WO, LSS on accounts with zero payment history, multiple overlapping loan
  enquiries at distinct NBFCs within the same week, PAN/name mismatch.

Key evaluation checks (the infographic's five checks):
  1. Payment history
  2. DPD pattern
  3. Active loans count
  4. Credit utilization
  5. Enquiry count

=== YOUR JOB ===

Read BOTH reports (applicant + co-applicant). For each party, surface every
red flag grounded in the guardrails above. For the pair together, give a
PFL-level verdict.

Prefer false positives over false negatives. It is better to escalate a
marginal case to the MD than to auto-approve a willful-defaulter.

=== OUTPUT FORMAT ===

Return ONLY valid JSON matching this exact schema:

{
  "overall_verdict": "clean | caution | adverse",
  "recommendation": "proceed | escalate_md | reject",
  "confidence": <0-100>,
  "applicant": {
    "credit_score": <int or null>,
    "willful_default_indicators": ["<short evidence-cited line per indicator>"],
    "fraud_red_flags": ["<short line per flag>"],
    "payment_history_summary": "<1-2 sentences>",
    "dpd_pattern_summary": "<1-2 sentences>",
    "active_loans_count": <int>,
    "active_loans_notes": "<1-2 sentences>",
    "credit_utilization_summary": "<1-2 sentences>",
    "enquiry_pattern_summary": "<1-2 sentences>",
    "per_party_verdict": "clean | caution | adverse"
  },
  "co_applicant": {
    ... same shape as applicant, or null if no co-app bureau report was provided
  },
  "overall_concerns": ["<top-level concern spanning both parties>"],
  "overall_positives": ["<top-level positive>"]
}

Rules:
- Never fabricate account numbers, EMI amounts, or dates the bureau didn't
  emit. If a field isn't in the data you were given, write "not in bureau data".
- Every ``willful_default_indicators`` / ``fraud_red_flags`` entry MUST cite
  the specific account / institution / status / date that triggered it.
- Whenever you flag a name spelling / format / identity mismatch, cite WHERE
  each conflicting value came from so the assessor can open the right file.
  Use these source labels exactly:
    * "case record" — the loan application form name supplied via case context
    * "applicant bureau report" — APPLICANT BUREAU REPORT block above
    * "co-applicant bureau report" — CO-APPLICANT BUREAU REPORT block above
  Format every mismatch sentence as e.g.:
    "Name mismatch — case record says 'X' but applicant bureau report says 'Y'."
  Never use vague phrases like "application says" or "bureau says" without
  the qualifying label.
- If credit_score < 600 → at minimum caution. Score < 500 → escalate_md.
- If ANY account has status in {WO, LSS, SETTLED, DBT} → escalate_md or
  reject, with a willful_default_indicators entry naming the account.
- If a co-applicant bureau report block was provided (i.e. NOT "NO REPORT
  PROVIDED."), you MUST populate the ``co_applicant`` object — do not return
  null. Otherwise the front-end will show an empty co-applicant verdict even
  though a bureau report is sitting on the case.
- Respond with JSON only, no prose.
"""


def _summarise_party(
    *,
    label: str,
    equifax_data: dict[str, Any] | None,
) -> str:
    """Stringify one party's bureau read into the prompt input."""
    if equifax_data is None:
        return f"=== {label} BUREAU REPORT ===\nNO REPORT PROVIDED.\n"

    parts: list[str] = [f"=== {label} BUREAU REPORT ==="]
    name = (
        (equifax_data.get("customer_info") or {}).get("name")
        if isinstance(equifax_data.get("customer_info"), dict)
        else None
    )
    parts.append(f"Name on bureau: {name or '—'}")
    score = equifax_data.get("credit_score")
    parts.append(f"Credit score: {score if score is not None else '—'}")
    summary = equifax_data.get("summary") or {}
    if summary:
        parts.append("Summary:")
        for k, v in summary.items():
            parts.append(f"  {k}: {v}")

    accounts = equifax_data.get("accounts") or []
    parts.append(f"Accounts ({len(accounts)}):")
    if not accounts:
        parts.append("  (none in bureau pull)")
    else:
        for idx, a in enumerate(accounts[:20], start=1):
            parts.append(
                f"  [{idx}] "
                f"institution={a.get('institution') or a.get('lender') or '—'} | "
                f"type={a.get('type') or '—'} | "
                f"product={a.get('product_type') or '—'} | "
                f"status={a.get('status') or '—'} | "
                f"balance={a.get('balance')} | "
                f"opened={a.get('date_opened') or a.get('opened') or '—'} | "
                f"reported={a.get('date_reported') or '—'}"
            )
        if len(accounts) > 20:
            parts.append(f"  (+ {len(accounts) - 20} more accounts, truncated)")
    enquiries = equifax_data.get("enquiries") or []
    if enquiries:
        parts.append(f"Enquiries ({len(enquiries)}): first 10 printed:")
        for e in enquiries[:10]:
            parts.append(f"  - {e}")
    return "\n".join(parts)


class CreditAnalyst:
    """Opus-4.7 credit analyst over applicant + co-applicant bureau data."""

    _TIER = "opus"

    def __init__(self, claude: Any = None) -> None:
        self._claude = claude

    async def analyse(
        self,
        *,
        applicant_equifax: dict[str, Any] | None,
        co_applicant_equifax: dict[str, Any] | None,
        applicant_name: str | None = None,
        co_applicant_name: str | None = None,
        loan_amount_inr: int | None = None,
        loan_tenure_months: int | None = None,
    ) -> ExtractionResult:
        claude = self._claude
        if claude is None:
            from app.services.claude import get_claude_service

            claude = get_claude_service()

        user_text = "\n\n".join(
            [
                f"Case context — applicant: {applicant_name or '—'} · "
                f"co-applicant: {co_applicant_name or '—'} · "
                f"loan ₹{loan_amount_inr or '—'} for "
                f"{loan_tenure_months or '—'} months.",
                _summarise_party(
                    label=f"APPLICANT ({applicant_name or 'unknown'})",
                    equifax_data=applicant_equifax,
                ),
                _summarise_party(
                    label=f"CO-APPLICANT ({co_applicant_name or 'unknown'})",
                    equifax_data=co_applicant_equifax,
                ),
                "Now produce the JSON verdict per the schema.",
            ]
        )

        messages = [{"role": "user", "content": [{"type": "text", "text": user_text}]}]
        try:
            message = await claude.invoke(
                tier=self._TIER,
                system=_SYSTEM_PROMPT,
                messages=messages,
                cache_system=True,
                max_tokens=2500,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("credit_analyst Opus call failed")
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={},
                error_message=f"opus_call_failed: {exc}",
            )

        raw = claude.extract_text(message)
        m = _JSON_RE.search(raw)
        if not m:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={"raw_text": raw[:500]},
                error_message="json_parse_failed: no JSON object in response",
            )
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={"raw_text": raw[:500]},
                error_message=f"json_parse_failed: {exc}",
            )

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        data = {
            **parsed,
            "model_used": model,
            "cost_usd": cost,
            "usage": usage,
        }
        return ExtractionResult(
            status=ExtractionStatus.SUCCESS,
            schema_version="1.0",
            data=data,
        )
