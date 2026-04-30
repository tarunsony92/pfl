"""Unit tests for Level 2 pure cross-check helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from app.enums import (
    ArtifactSubtype,
    ArtifactType,
    ExtractionStatus,
    LevelIssueSeverity,
    UserRole,
)
from app.verification.levels.level_2_banking import (
    cross_check_nach_bounces,
    cross_check_avg_balance_vs_emi,
    cross_check_credits_vs_declared_income,
    cross_check_distinct_payer_concentration,
    cross_check_impulsive_debits,
    cross_check_chronic_low_balance,
    cross_check_ca_narrative,
    estimate_proposed_emi_inr,
)
from app.worker.extractors.base import ExtractionResult


# ------- NACH bounces ----------


def test_nach_bounces_none_no_issue():
    assert cross_check_nach_bounces(0) is None


def test_nach_bounces_one_is_critical():
    iss = cross_check_nach_bounces(1)
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value
    assert iss["sub_step_id"] == "nach_bounces"


def test_nach_bounces_many_is_critical():
    iss = cross_check_nach_bounces(5)
    assert iss is not None
    assert "5" in iss["description"] or "five" in iss["description"].lower()


# ------- avg balance vs EMI ----------


def test_avg_balance_sufficient_no_issue():
    assert cross_check_avg_balance_vs_emi(
        avg_monthly_balance_inr=20000, proposed_emi_inr=8000
    ) is None


def test_avg_balance_just_at_1p5x_is_ok():
    assert cross_check_avg_balance_vs_emi(
        avg_monthly_balance_inr=12000, proposed_emi_inr=8000
    ) is None


def test_avg_balance_below_1p5x_is_critical():
    iss = cross_check_avg_balance_vs_emi(
        avg_monthly_balance_inr=8000, proposed_emi_inr=8000
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value


def test_avg_balance_missing_emi_skips_check():
    # If proposed EMI is unknown, we can't run the rule.
    assert cross_check_avg_balance_vs_emi(
        avg_monthly_balance_inr=10000, proposed_emi_inr=0
    ) is None


# ------- credits vs declared income ----------


def test_credits_match_declared_income_no_issue():
    # 3 months × ₹20k = ₹60k declared; credits of ₹72k is fine
    assert cross_check_credits_vs_declared_income(
        three_month_credit_sum_inr=72000,
        declared_monthly_income_inr=20000,
    ) is None


def test_credits_far_below_declared_income_is_warning():
    # 3 months × ₹20k = ₹60k declared; only ₹20k credits is a mismatch
    iss = cross_check_credits_vs_declared_income(
        three_month_credit_sum_inr=20000,
        declared_monthly_income_inr=20000,
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


# ------- distinct payer concentration ----------


def test_multiple_payers_no_issue():
    assert cross_check_distinct_payer_concentration(
        distinct_credit_payers=3, declared_monthly_income_inr=20000
    ) is None


def test_single_payer_with_high_income_is_warning():
    iss = cross_check_distinct_payer_concentration(
        distinct_credit_payers=1, declared_monthly_income_inr=20000
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_single_payer_with_low_income_no_issue():
    # A borrower declaring ₹8k/mo could legitimately have one employer — skip.
    assert cross_check_distinct_payer_concentration(
        distinct_credit_payers=1, declared_monthly_income_inr=8000
    ) is None


# ------- impulsive debits ----------


def test_low_impulsive_debits_no_issue():
    assert cross_check_impulsive_debits(
        impulsive_debit_total_inr=2000, declared_monthly_income_inr=20000
    ) is None


def test_impulsive_debits_exceeding_income_is_warning():
    iss = cross_check_impulsive_debits(
        impulsive_debit_total_inr=30000, declared_monthly_income_inr=20000
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


# ------- EMI estimator ----------


def test_estimate_emi_flat_rate_roughly_correct():
    # ₹1,20,000 over 24 months at flat 24% APR.
    # Interest = 120000 * 0.24 * 2 = ₹57,600. EMI = 177,600 / 24 = ₹7,400.
    emi = estimate_proposed_emi_inr(loan_amount_inr=120000, tenure_months=24)
    assert 7500 >= emi >= 7300


def test_estimate_emi_returns_zero_when_missing_data():
    assert estimate_proposed_emi_inr(loan_amount_inr=None, tenure_months=None) == 0
    assert estimate_proposed_emi_inr(loan_amount_inr=50000, tenure_months=None) == 0
    assert estimate_proposed_emi_inr(loan_amount_inr=None, tenure_months=24) == 0


# ------- chronic low balance ----------


def test_chronic_low_balance_passes_when_healthy():
    assert cross_check_chronic_low_balance(10_000) is None


def test_chronic_low_balance_below_1k_is_critical():
    iss = cross_check_chronic_low_balance(487)
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value
    assert "487" in iss["description"]


# ------- CA narrative fallback ----------


def test_ca_narrative_empty_no_issue():
    assert cross_check_ca_narrative([]) is None


def test_ca_narrative_with_concerns_returns_warning():
    iss = cross_check_ca_narrative(
        ["avg balance below EMI", "impulsive debits high", "no salary credits"]
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value
    assert "3 qualitative concern" in iss["description"]
    assert "avg balance" in iss["description"]


# ---- B3 meta-emitter evidence enrichment (L2) ----
# ``bank_statement_missing`` and ``ca_analyzer_failed`` are inline in the
# run_level_2_banking orchestrator (not broken out as pure helpers). We
# exercise the orchestrator end-to-end with a stubbed BankCaAnalyzer to
# verify the evidence dict now carries the new keys.


async def _seed_l2_fixture(db, *, bank_artifact: bool = False):
    """Seed a minimal case + optional bank statement artifact."""
    from app.models.case import Case
    from app.models.case_artifact import CaseArtifact
    from app.services import users as users_svc

    user = await users_svc.create_user(
        db,
        email="l2-meta@pfl.com",
        password="Pass123!",
        full_name="L2 Meta",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()

    case = Case(
        loan_id="L2META0001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="l2meta/case.zip",
        loan_amount=100_000,
        loan_tenure_months=24,
    )
    db.add(case)
    await db.flush()

    if bank_artifact:
        db.add(
            CaseArtifact(
                case_id=case.id,
                filename="bank_statement.pdf",
                artifact_type=ArtifactType.ADDITIONAL_FILE,
                s3_key=f"l2meta/{case.id}/bank_statement.pdf",
                uploaded_by=user.id,
                uploaded_at=datetime.now(UTC),
                metadata_json={"subtype": ArtifactSubtype.BANK_STATEMENT.value},
            )
        )
        await db.flush()

    return case.id, user.id


async def test_bank_statement_missing_evidence_carries_expected_subtype_and_tx_count(db):
    """When no bank_statement extraction exists, the emitter records the
    expected ArtifactSubtype (so the MD panel can say 'we looked for X')
    and tx_line_count: 0 (so the zero-lines case is explicit)."""
    from app.verification.levels import level_2_banking as l2_mod
    from app.models.level_issue import LevelIssue
    from sqlalchemy import select

    case_id, actor_user_id = await _seed_l2_fixture(db, bank_artifact=False)
    result = await l2_mod.run_level_2_banking(
        db, case_id, actor_user_id=actor_user_id, claude=object(),
    )

    issues = (
        await db.execute(
            select(LevelIssue).where(
                LevelIssue.verification_result_id == result.id,
                LevelIssue.sub_step_id == "bank_statement_missing",
            )
        )
    ).scalars().all()
    assert len(issues) == 1
    ev = issues[0].evidence or {}
    assert ev.get("expected_subtype") == ArtifactSubtype.BANK_STATEMENT.value
    assert ev.get("tx_line_count") == 0


# ---- B6: build_pass_evidence_l2 helper ----
#
# Pure helper mirroring Part A's build_pass_evidence. Populates
# sub_step_results.pass_evidence for every L2 rule that DIDN'T fire by
# slicing ca_data per rule. source_artifacts always cites the bank
# statement PDF — every L2 rule is backed by the same upload.


class TestBuildPassEvidenceL2:
    def _mk_artifact(self, aid: str, subtype: str, filename: str):
        class _A:
            pass
        a = _A()
        a.id = aid
        a.filename = filename
        a.metadata_json = {"subtype": subtype}
        return a

    def test_all_rules_passing_full_payload(self):
        from app.verification.levels.level_2_banking import build_pass_evidence_l2

        bank_art = self._mk_artifact("b1", "BANK_STATEMENT", "bank.pdf")
        ca_data = {
            "nach_bounce_count": 0,
            "nach_bounces": [],
            "avg_monthly_balance_inr": 30000,
            "three_month_credit_sum_inr": 90000,
            "distinct_credit_payers": 3,
            "impulsive_debit_total_inr": 5000,
            "ca_concerns": [],
            "ca_positives": ["regular salary credits", "low discretionary spend"],
            "tx_line_count": 120,
            "extraction_status": "ok",
        }
        out = build_pass_evidence_l2(
            ca_data=ca_data,
            declared_income=20000,
            proposed_emi=7400,
            tx_line_count=120,
            bank_art=bank_art,
            fired_rules=set(),
        )

        # bank_statement_missing narrated on the pass side
        assert "bank_statement_missing" in out
        e = out["bank_statement_missing"]
        assert e["extraction_status"] == "ok"
        assert e["tx_line_count"] == 120
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert "b1" in ids

        # nach_bounces
        e = out["nach_bounces"]
        assert e["nach_bounce_count"] == 0
        assert e["nach_bounces"] == []

        # avg_balance_vs_emi — ratio + multiplier
        e = out["avg_balance_vs_emi"]
        assert e["avg_monthly_balance_inr"] == 30000
        assert e["proposed_emi_inr"] == 7400
        assert e["multiplier"] == 1.5
        # ratio = avg_bal / proposed_emi = 30000/7400 ~= 4.054
        assert abs(e["ratio"] - (30000 / 7400)) < 1e-6

        # credits_vs_declared_income — floor_ratio + ratio
        e = out["credits_vs_declared_income"]
        assert e["three_month_credit_sum_inr"] == 90000
        assert e["declared_monthly_income_inr"] == 20000
        assert e["floor_ratio"] == 0.50
        # ratio = 90000 / (20000*3) = 1.5
        assert abs(e["ratio"] - 1.5) < 1e-6

        # single_payer_concentration
        e = out["single_payer_concentration"]
        assert e["distinct_credit_payers"] == 3
        assert e["declared_monthly_income_inr"] == 20000
        assert e["min_income_for_rule_inr"] == 15000

        # impulsive_debit_overspend
        e = out["impulsive_debit_overspend"]
        assert e["impulsive_debit_total_inr"] == 5000
        assert e["declared_monthly_income_inr"] == 20000

        # chronic_low_balance
        e = out["chronic_low_balance"]
        assert e["avg_monthly_balance_inr"] == 30000
        assert e["min_floor_inr"] == 1000

        # ca_narrative_concerns
        e = out["ca_narrative_concerns"]
        assert e["ca_concerns"] == []
        assert e["ca_positives"] == [
            "regular salary credits",
            "low discretionary spend",
        ]
        assert e["overall_verdict"] == "clean"

        # Every entry has source_artifacts
        for sub, entry in out.items():
            assert isinstance(entry.get("source_artifacts"), list), (
                f"{sub} missing source_artifacts list"
            )

    def test_fired_rules_are_excluded(self):
        from app.verification.levels.level_2_banking import build_pass_evidence_l2

        out = build_pass_evidence_l2(
            ca_data={"nach_bounce_count": 0},
            declared_income=20000,
            proposed_emi=7400,
            tx_line_count=10,
            bank_art=None,
            fired_rules={
                "bank_statement_missing",
                "nach_bounces",
                "avg_balance_vs_emi",
                "credits_vs_declared_income",
                "single_payer_concentration",
                "impulsive_debit_overspend",
                "chronic_low_balance",
                "ca_narrative_concerns",
            },
        )
        assert out == {}

    def test_skip_entries_when_ca_data_missing_field(self):
        """When ca_data doesn't carry a required field (e.g., declared_income
        is 0 or EMI is 0), the helper now emits a skipped_reason entry instead
        of silently omitting the rule. This ensures the FE renders the reason
        inline rather than the stale 'Part B placeholder' text."""
        from app.verification.levels.level_2_banking import build_pass_evidence_l2

        out = build_pass_evidence_l2(
            ca_data={
                "nach_bounce_count": 0,
                "nach_bounces": [],
                "avg_monthly_balance_inr": 30000,
                "ca_concerns": [],
            },
            declared_income=0,  # income-based rules emit skipped_reason
            proposed_emi=0,  # EMI-based rule emits skipped_reason
            tx_line_count=50,
            bank_art=None,
            fired_rules=set(),
        )
        # bank_statement_missing, chronic_low_balance, nach_bounces and
        # ca_narrative_concerns still carry full payloads.
        assert "bank_statement_missing" in out
        assert "chronic_low_balance" in out
        assert "nach_bounces" in out
        assert "ca_narrative_concerns" in out
        # income / EMI-dependent rules are now present but with skipped_reason.
        assert "avg_balance_vs_emi" in out
        assert "skipped_reason" in out["avg_balance_vs_emi"]
        assert "credits_vs_declared_income" in out
        assert "skipped_reason" in out["credits_vs_declared_income"]
        assert "single_payer_concentration" in out
        assert "skipped_reason" in out["single_payer_concentration"]
        assert "impulsive_debit_overspend" in out
        assert "skipped_reason" in out["impulsive_debit_overspend"]

    def test_source_artifacts_empty_list_when_bank_art_missing(self):
        """When bank_art is None, source_artifacts is an empty list so
        the FE can still iterate. (This shouldn't happen in practice —
        the orchestrator only hits the pass path when extraction
        succeeded — but be defensive.)"""
        from app.verification.levels.level_2_banking import build_pass_evidence_l2

        out = build_pass_evidence_l2(
            ca_data={"nach_bounce_count": 0, "avg_monthly_balance_inr": 10_000},
            declared_income=0,
            proposed_emi=0,
            tx_line_count=50,
            bank_art=None,
            fired_rules=set(),
        )
        assert out["bank_statement_missing"]["source_artifacts"] == []

    def test_schema_drift_guard_avg_balance_vs_emi_keyset(self):
        """Lock the key set on avg_balance_vs_emi — the busiest pass
        entry (feeds the AvgBalanceVsEmiCard smart layout)."""
        from app.verification.levels.level_2_banking import build_pass_evidence_l2

        out = build_pass_evidence_l2(
            ca_data={"avg_monthly_balance_inr": 30000},
            declared_income=20000,
            proposed_emi=7400,
            tx_line_count=10,
            bank_art=None,
            fired_rules=set(),
        )
        e = out["avg_balance_vs_emi"]
        assert set(e.keys()) == {
            "avg_monthly_balance_inr",
            "proposed_emi_inr",
            "multiplier",
            "ratio",
            "source_artifacts",
        }


async def test_ca_analyzer_failed_evidence_carries_error_message(db):
    """When the BankCaAnalyzer returns an error_message, the meta-emitter
    should reflect it in evidence.error_message so the MD sees the cause
    without having to dig into logs."""
    from app.verification.levels import level_2_banking as l2_mod
    from app.models.case_extraction import CaseExtraction
    from app.models.level_issue import LevelIssue
    from sqlalchemy import select

    case_id, actor_user_id = await _seed_l2_fixture(db, bank_artifact=True)
    # Seed a bank_statement extraction with tx lines — otherwise the
    # "missing" branch fires instead of the analyzer branch.
    db.add(
        CaseExtraction(
            case_id=case_id,
            extractor_name="bank_statement",
            schema_version="1.0",
            status=ExtractionStatus.SUCCESS,
            data={"transaction_lines": ["01-Jan ABC 100 Cr", "02-Jan XYZ 200 Dr"]},
            extracted_at=datetime.now(UTC),
        )
    )
    await db.flush()

    # Stub BankCaAnalyzer to return a failure with a specific error_message.
    FAKE_ERR = "ca_call_failed: anthropic rate limit — retry in 60s"

    class _FailingAnalyzer:
        def __init__(self, claude=None) -> None:
            pass

        async def analyze(self, **kwargs):
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={},
                error_message=FAKE_ERR,
            )

    with patch(
        "app.verification.services.bank_ca_analyzer.BankCaAnalyzer",
        _FailingAnalyzer,
    ):
        result = await l2_mod.run_level_2_banking(
            db, case_id, actor_user_id=actor_user_id, claude=object(),
        )

    issues = (
        await db.execute(
            select(LevelIssue).where(
                LevelIssue.verification_result_id == result.id,
                LevelIssue.sub_step_id == "ca_analyzer_failed",
            )
        )
    ).scalars().all()
    assert len(issues) == 1
    ev = issues[0].evidence or {}
    assert ev.get("error_message") == FAKE_ERR
