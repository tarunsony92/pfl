"""Tests for BankCaAnalyzer — Claude-Haiku-based CA-style bank statement analysis.

Given a list of raw SBI/BOB transaction strings + declared income/FOIR/EMI,
Claude returns a structured CA read: NACH bounce lines, distinct credit
payers, 3-month credit sum, avg monthly balance, impulsive-debit summary,
narrative concerns/positives.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.enums import ExtractionStatus
from app.verification.services.bank_ca_analyzer import BankCaAnalyzer


def _mock(payload: dict) -> MagicMock:
    mock_msg = MagicMock()
    c = MagicMock()
    c.invoke = AsyncMock(return_value=mock_msg)
    c.extract_text = MagicMock(return_value=json.dumps(payload))
    c.usage_dict = MagicMock(return_value={"input_tokens": 30_000, "output_tokens": 800})
    c.cost_usd = MagicMock(return_value=0.027)
    return c


async def test_analyzer_returns_structured_findings_on_clean_bank():
    payload = {
        "nach_bounces": [],
        "nach_bounce_count": 0,
        "distinct_credit_payers": 5,
        "three_month_credit_sum_inr": 72000,
        "avg_monthly_balance_inr": 14500,
        "impulsive_debit_count": 2,
        "impulsive_debit_total_inr": 3500,
        "ca_concerns": [],
        "ca_positives": [
            "Regular credits from 5 distinct payers totalling ₹72,000 over 3 months",
            "Avg monthly balance ₹14,500 comfortably supports a ₹8,000 EMI NACH",
        ],
    }
    claude = _mock(payload)
    analyzer = BankCaAnalyzer(claude=claude)

    result = await analyzer.analyze(
        tx_lines=["line1", "line2", "line3"],
        declared_monthly_income_inr=20000,
        declared_foir_pct=38,
        proposed_emi_inr=8000,
    )

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["nach_bounce_count"] == 0
    assert result.data["distinct_credit_payers"] == 5
    assert result.data["avg_monthly_balance_inr"] == 14500
    assert "72,000" in " ".join(result.data["ca_positives"])


async def test_analyzer_flags_nach_bounces_and_low_balance():
    payload = {
        "nach_bounces": [
            {"date": "15/03/2026", "description": "NACH RETURN - INSUFFICIENT FUNDS", "amount_inr": 8000}
        ],
        "nach_bounce_count": 1,
        "distinct_credit_payers": 1,
        "three_month_credit_sum_inr": 18000,
        "avg_monthly_balance_inr": 1200,
        "impulsive_debit_count": 30,
        "impulsive_debit_total_inr": 18000,
        "ca_concerns": [
            "NACH bounce 15/03/2026 ₹8,000 — prior EMI default",
            "Avg balance ₹1,200 cannot sustain proposed EMI ₹8,000 NACH debit",
            "Impulsive retail debits dominate (30 txns, ₹18,000) — no business spend pattern",
        ],
        "ca_positives": [],
    }
    claude = _mock(payload)
    analyzer = BankCaAnalyzer(claude=claude)

    result = await analyzer.analyze(
        tx_lines=["any"],
        declared_monthly_income_inr=20000,
        declared_foir_pct=38,
        proposed_emi_inr=8000,
    )

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["nach_bounce_count"] == 1
    assert result.data["avg_monthly_balance_inr"] == 1200
    assert len(result.data["ca_concerns"]) >= 3


async def test_analyzer_sends_structured_prompt_with_declared_values():
    claude = _mock(
        {
            "nach_bounces": [],
            "nach_bounce_count": 0,
            "distinct_credit_payers": 3,
            "three_month_credit_sum_inr": 60000,
            "avg_monthly_balance_inr": 10000,
            "impulsive_debit_count": 0,
            "impulsive_debit_total_inr": 0,
            "ca_concerns": [],
            "ca_positives": [],
        }
    )
    analyzer = BankCaAnalyzer(claude=claude)

    await analyzer.analyze(
        tx_lines=["tx_a", "tx_b"],
        declared_monthly_income_inr=25000,
        declared_foir_pct=40,
        proposed_emi_inr=10000,
    )

    kwargs = claude.invoke.call_args.kwargs
    assert kwargs["tier"] == "opus"
    user_text = kwargs["messages"][0]["content"][0]["text"]
    assert "25000" in user_text or "25,000" in user_text
    assert "40" in user_text
    assert "10000" in user_text or "10,000" in user_text
    assert "tx_a" in user_text


async def test_analyzer_failed_on_non_json_response():
    mock_msg = MagicMock()
    c = MagicMock()
    c.invoke = AsyncMock(return_value=mock_msg)
    c.extract_text = MagicMock(return_value="Cannot parse bank statement.")
    c.usage_dict = MagicMock(return_value={"input_tokens": 1000, "output_tokens": 10})
    c.cost_usd = MagicMock(return_value=0.001)
    analyzer = BankCaAnalyzer(claude=c)

    result = await analyzer.analyze(
        tx_lines=["tx"],
        declared_monthly_income_inr=20000,
        declared_foir_pct=38,
        proposed_emi_inr=8000,
    )
    assert result.status == ExtractionStatus.FAILED


async def test_analyzer_truncates_huge_transaction_lists_to_keep_cost_bounded():
    """Analyzer must cap the tx-line payload to avoid blowing the token budget."""
    claude = _mock(
        {
            "nach_bounces": [],
            "nach_bounce_count": 0,
            "distinct_credit_payers": 2,
            "three_month_credit_sum_inr": 50000,
            "avg_monthly_balance_inr": 5000,
            "impulsive_debit_count": 0,
            "impulsive_debit_total_inr": 0,
            "ca_concerns": [],
            "ca_positives": [],
        }
    )
    analyzer = BankCaAnalyzer(claude=claude)
    huge_tx = [f"2026-04-{i % 30:02d} line-{i}" for i in range(2000)]

    await analyzer.analyze(
        tx_lines=huge_tx,
        declared_monthly_income_inr=20000,
        declared_foir_pct=38,
        proposed_emi_inr=8000,
    )

    kwargs = claude.invoke.call_args.kwargs
    user_text = kwargs["messages"][0]["content"][0]["text"]
    # The prompt should be capped — specifically, it shouldn't include all
    # 2000 lines. We check the max-tx-included bound.
    assert user_text.count("line-") <= BankCaAnalyzer.MAX_TX_LINES
