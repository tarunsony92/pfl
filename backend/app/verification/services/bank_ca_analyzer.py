"""BankCaAnalyzer — Claude-Opus CA-style read of bank-statement transactions.

Given raw transaction lines (as extracted by the M3 ``bank_statement`` extractor)
plus the borrower's declared monthly income / FOIR% / proposed EMI, Claude
returns a structured CA view used by Level 2 (Banking):

- NACH / ECS bounce detection
- Distinct credit-payer count (proxy for income diversity)
- Three-month credit total
- Avg monthly balance estimate
- Impulsive-debit summary (consumables / retail, not business)
- Narrative concerns + positives

Uses Opus rather than Haiku because L2 is a credit-critical PASS/FAIL gate —
mis-classifying a recurring NACH bounce as a one-off, or missing a
single-payer-concentration pattern, directly drives wrong loan decisions.
The bank-statement *parsing* (PDF → transaction lines) stays cheap (pure
regex + pdfplumber); only the CA-grade *analysis* runs on Opus.

All output fields are structured so Level 2's pure rules can raise
CRITICAL / WARNING issues without re-reading the bank statement.
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


_SYSTEM_PROMPT = """You are a chartered accountant (CA) auditing a rural microfinance
borrower's bank statement for loan-repayment capacity.

Read the transaction lines and return ONLY valid JSON matching this schema:

{
  "nach_bounces": [
    {"date": "<as printed>", "description": "<raw txn text>", "amount_inr": <int or null>}
  ],
  "nach_bounce_count": <int>,
  "distinct_credit_payers": <int — count of distinct payer-names on credit lines>,
  "three_month_credit_sum_inr": <int — sum of all credits across the most recent 3 months>,
  "avg_monthly_balance_inr": <int — estimated average closing balance across months>,
  "impulsive_debit_count": <int>,
  "impulsive_debit_total_inr": <int>,
  "ca_concerns": [<string — each a short, evidence-citing concern>],
  "ca_positives": [<string — each a short, evidence-citing positive>]
}

Definitions:
- A NACH / ECS bounce has "NACH RETURN", "ECS RETURN", "INSUFFICIENT FUNDS",
  "INSUFF FUNDS", "CHEQUE RETURN", or similar in the description.
- "Impulsive debits" = retail / consumable / non-business spends: ATM withdrawals
  over ₹5,000 with no corresponding credit nearby, Amazon/Flipkart/Swiggy/Zomato
  debits, recharges, gaming. Ignore NACH/EMI/utility bills.
- "Distinct credit payers" = unique payer names on credit txns (strip common
  prefixes like UPI/IMPS/NEFT/RTGS/BY).

Rules:
- Cite specific transaction rows in concerns/positives when possible.
- Respond ONLY with the JSON. No prose before or after.
"""

_USER_TEMPLATE = """\
Declared monthly income (CAM): ₹{declared_monthly_income_inr}
Declared FOIR (CAM): {declared_foir_pct}%
Proposed EMI: ₹{proposed_emi_inr}
Transaction lines ({tx_count} shown, newest first):

{tx_block}

Please produce the JSON CA read per the schema."""


class BankCaAnalyzer:
    """Opus-based CA analysis over bank-statement transaction lines.

    Cost is ~12× Haiku per call but L2 is a credit-critical gate — Haiku has
    been observed to miss recurring NACH-bounce patterns and single-payer
    concentration on rural-borrower statements where the salary signal is
    noisy. The PDF parsing layer (BankStatementExtractor) is regex-only, so
    no LLM cost is duplicated."""

    _TIER = "opus"
    MAX_TX_LINES = 400  # caps prompt size so a 2000-txn statement stays under budget

    def __init__(self, claude: Any = None) -> None:
        self._claude = claude

    async def analyze(
        self,
        *,
        tx_lines: list[str],
        declared_monthly_income_inr: int,
        declared_foir_pct: float,
        proposed_emi_inr: int,
    ) -> ExtractionResult:
        claude = self._claude
        if claude is None:
            from app.services.claude import get_claude_service

            claude = get_claude_service()

        # Keep the most-recent MAX_TX_LINES (assume list is chronological; take tail)
        kept = tx_lines[-self.MAX_TX_LINES :] if len(tx_lines) > self.MAX_TX_LINES else list(tx_lines)
        tx_block = "\n".join(kept)

        user_text = _USER_TEMPLATE.format(
            declared_monthly_income_inr=declared_monthly_income_inr,
            declared_foir_pct=declared_foir_pct,
            proposed_emi_inr=proposed_emi_inr,
            tx_count=len(kept),
            tx_block=tx_block[:60_000],  # hard cap on prompt chars
        )
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": user_text}],
            }
        ]

        try:
            message = await claude.invoke(
                tier=self._TIER,
                system=_SYSTEM_PROMPT,
                messages=messages,
                cache_system=True,
                max_tokens=2048,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("bank CA analyser vision call failed")
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={},
                error_message=f"ca_call_failed: {exc}",
            )

        raw_text = claude.extract_text(message)
        match = _JSON_RE.search(raw_text)
        if not match:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={"raw_text": raw_text[:500]},
                error_message="json_parse_failed: no JSON object in CA response",
            )
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={"raw_text": raw_text[:500]},
                error_message=f"json_parse_failed: {exc}",
            )

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        data = {
            "nach_bounces": parsed.get("nach_bounces") or [],
            "nach_bounce_count": int(parsed.get("nach_bounce_count") or 0),
            "distinct_credit_payers": int(parsed.get("distinct_credit_payers") or 0),
            "three_month_credit_sum_inr": int(parsed.get("three_month_credit_sum_inr") or 0),
            "avg_monthly_balance_inr": int(parsed.get("avg_monthly_balance_inr") or 0),
            "impulsive_debit_count": int(parsed.get("impulsive_debit_count") or 0),
            "impulsive_debit_total_inr": int(parsed.get("impulsive_debit_total_inr") or 0),
            "ca_concerns": parsed.get("ca_concerns") or [],
            "ca_positives": parsed.get("ca_positives") or [],
            "model_used": model,
            "cost_usd": cost,
            "usage": usage,
        }

        return ExtractionResult(
            status=ExtractionStatus.SUCCESS,
            schema_version="1.0",
            data=data,
        )
