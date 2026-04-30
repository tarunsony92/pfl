"""Part B finish: pass_evidence helpers emit skipped_reason for missing input."""
from __future__ import annotations

from app.verification.levels.level_2_banking import build_pass_evidence_l2


def _ca_min(**overrides):
    base = {
        "avg_monthly_balance_inr": None,
        "three_month_credit_sum_inr": None,
        "distinct_credit_payers": None,
        "impulsive_debit_total_inr": None,
        "nach_bounce_count": 0,
        "nach_bounces": [],
        "ca_concerns": [],
        "ca_positives": [],
    }
    base.update(overrides)
    return base


def test_l2_avg_balance_vs_emi_skipped_when_no_avg_balance():
    out = build_pass_evidence_l2(
        ca_data=_ca_min(),
        declared_income=20000,
        proposed_emi=5000,
        tx_line_count=200,
        bank_art=None,
        fired_rules=set(),
    )
    assert "avg_balance_vs_emi" in out
    assert out["avg_balance_vs_emi"]["skipped_reason"]


def test_l2_avg_balance_vs_emi_skipped_when_no_emi():
    out = build_pass_evidence_l2(
        ca_data=_ca_min(avg_monthly_balance_inr=5000),
        declared_income=20000,
        proposed_emi=0,
        tx_line_count=200,
        bank_art=None,
        fired_rules=set(),
    )
    assert "avg_balance_vs_emi" in out
    assert "no proposed emi" in out["avg_balance_vs_emi"]["skipped_reason"].lower()


def test_l2_credits_skipped_when_no_declared_income():
    out = build_pass_evidence_l2(
        ca_data=_ca_min(three_month_credit_sum_inr=18000),
        declared_income=0,
        proposed_emi=5000,
        tx_line_count=200,
        bank_art=None,
        fired_rules=set(),
    )
    assert "credits_vs_declared_income" in out
    assert "declared monthly income" in out["credits_vs_declared_income"]["skipped_reason"].lower()


def test_l2_single_payer_skipped_below_income_floor():
    out = build_pass_evidence_l2(
        ca_data=_ca_min(distinct_credit_payers=5),
        declared_income=10000,  # below _L2_SINGLE_PAYER_MIN_INCOME (15000)
        proposed_emi=5000,
        tx_line_count=200,
        bank_art=None,
        fired_rules=set(),
    )
    assert "single_payer_concentration" in out
    assert "skipped_reason" in out["single_payer_concentration"]


def test_l2_populated_entries_when_inputs_present():
    """Smoke: when all inputs are present and rule passes, entry has the
    rich payload (not skipped_reason)."""
    out = build_pass_evidence_l2(
        ca_data=_ca_min(
            avg_monthly_balance_inr=10000,
            three_month_credit_sum_inr=60000,
            distinct_credit_payers=5,
        ),
        declared_income=20000,
        proposed_emi=5000,
        tx_line_count=200,
        bank_art=None,
        fired_rules=set(),
    )
    avg = out["avg_balance_vs_emi"]
    assert "skipped_reason" not in avg
    assert avg["avg_monthly_balance_inr"] == 10000
    assert avg["multiplier"] > 0
