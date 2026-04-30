"""Unit tests for the 32-point scoring model (pure resolvers)."""

from __future__ import annotations

from app.verification.services.scoring_model import (
    CATALOG,
    ScoringContext,
    SECTIONS,
    build_score,
)


def _empty_ctx() -> ScoringContext:
    return ScoringContext()


# ── Catalog shape ────────────────────────────────────────────────────────────


def test_catalog_has_32_rows():
    assert len(CATALOG) == 32


def test_catalog_section_weights_match_spec():
    by_section: dict[str, int] = {}
    for p in CATALOG:
        by_section[p.section_id] = by_section.get(p.section_id, 0) + p.weight
    assert by_section == {"A": 45, "B": 35, "C": 13, "D": 7}
    assert sum(max_s for _, _, max_s in SECTIONS) == 100


def test_catalog_snos_are_1_to_32():
    assert sorted(p.sno for p in CATALOG) == list(range(1, 33))


# ── Empty context behaviour ─────────────────────────────────────────────────


def test_empty_context_produces_all_pending_or_fail():
    res = build_score(_empty_ctx())
    # earned should be 0 for applicant-heavy sections on empty context
    assert res.earned_score <= 5  # a couple of paths may NA-pass
    assert res.max_score == 100
    assert res.grade == "D"


# ── Section A specific ──────────────────────────────────────────────────────


def test_high_cibil_passes_row_3():
    ctx = ScoringContext(primary_equifax={"credit_score": 834})
    res = build_score(ctx)
    row3 = next(r for r in res.sections[0].rows if r.sno == 3)
    assert row3.status == "PASS"
    assert row3.score == 4


def test_low_cibil_fails_row_3():
    ctx = ScoringContext(primary_equifax={"credit_score": 620})
    res = build_score(ctx)
    row3 = next(r for r in res.sections[0].rows if r.sno == 3)
    assert row3.status == "FAIL"
    assert row3.score == 0


def test_dscr_graded_scoring():
    for dscr, expected_score in (
        (1.3, 4),
        (1.1, 3),
        (0.95, 2),
        (0.80, 1),
        (0.60, 0),
    ):
        ctx = ScoringContext(auto_cam={"system_cam": {"dscr": dscr}})
        res = build_score(ctx)
        row = next(r for r in res.sections[0].rows if r.sno == 12)
        assert row.score == expected_score, f"DSCR {dscr} expected {expected_score}, got {row.score}"


def test_foir_bands():
    cases = [
        (0.15, "PASS"),
        (0.35, "PASS"),
        (0.45, "PASS"),  # partial credit — weight-1
        (0.60, "FAIL"),
    ]
    for foir, expected in cases:
        ctx = ScoringContext(auto_cam={"cm_cam_il": {"foir": foir}})
        res = build_score(ctx)
        row = next(r for r in res.sections[0].rows if r.sno == 10)
        assert row.status == expected, f"FOIR {foir} expected {expected}, got {row.status}"


def test_writeoff_row_fails_when_account_has_wo_status():
    ctx = ScoringContext(
        primary_equifax={
            "accounts": [
                {"status": "Standard"},
                {"status": "Write-Off", "institution": "XYZ", "date_opened": "2020-01-01"},
            ]
        }
    )
    res = build_score(ctx)
    row = next(r for r in res.sections[0].rows if r.sno == 7)
    assert row.status == "FAIL"
    assert "XYZ" in row.evidence


def test_abb_ratio_graded():
    ctx = ScoringContext(
        bank_ca={"avg_monthly_balance_inr": 15000},
        proposed_emi_inr=10000,
    )
    res = build_score(ctx)
    row22 = next(r for r in res.sections[1].rows if r.sno == 22)
    # ratio = 1.5 → full weight 4
    assert row22.score == 4


def test_manual_override_wins():
    ctx = ScoringContext(
        manual_overrides={
            31: {"status": "PASS", "score": 3, "evidence": "TVR done by HO", "remarks": "phoned"}
        }
    )
    res = build_score(ctx)
    row = next(r for r in res.sections[3].rows if r.sno == 31)
    assert row.status == "PASS"
    assert row.score == 3


def test_overall_pct_and_grade():
    # Perfect score with manual overrides on every row
    overrides = {p.sno: {"status": "PASS", "score": p.weight} for p in CATALOG}
    ctx = ScoringContext(manual_overrides=overrides)
    res = build_score(ctx)
    assert res.earned_score == 100
    assert res.overall_pct == 100.0
    assert res.grade == "A+"


# ── r_a09 (CIBIL Address Match) — distinguishes L1-never-ran from L1-passed ─


def test_r_a09_pending_when_l1_never_ran():
    """If L1 hasn't been triggered at all, r_a09 cannot PASS by silence —
    it must return PENDING so the assessor runs L1 first. Before the fix
    an empty ``l1_issues_by_step`` and a bureau extraction was enough to
    count as a PASS, which is unsafe."""
    from app.enums import VerificationLevelNumber

    # L1 never ran (empty latest_vr_by_level) — even with a bureau
    # extraction on file, r_a09 must wait for L1.
    ctx = ScoringContext(
        primary_equifax={"credit_score": 750, "accounts": []},
        latest_vr_by_level={},
        l1_issues_by_step={},
    )
    res = build_score(ctx)
    row = next(r for r in res.sections[0].rows if r.sno == 9)
    assert row.status == "PENDING", (
        "r_a09 must be PENDING when L1 hasn't run — silence is not PASS"
    )


def test_r_a09_pass_when_l1_ran_and_did_not_flag():
    """L1 ran (entry present in latest_vr_by_level) and didn't flag
    aadhaar_vs_bureau_address → PASS."""
    from uuid import uuid4

    from app.enums import VerificationLevelNumber

    ctx = ScoringContext(
        primary_equifax={"credit_score": 750, "accounts": []},
        latest_vr_by_level={VerificationLevelNumber.L1_ADDRESS: uuid4()},
        l1_issues_by_step={},  # L1 ran and emitted nothing on this rule
    )
    res = build_score(ctx)
    row = next(r for r in res.sections[0].rows if r.sno == 9)
    assert row.status == "PASS"


def test_r_a09_fail_when_l1_flagged_open():
    from uuid import uuid4

    from app.enums import VerificationLevelNumber

    ctx = ScoringContext(
        primary_equifax={"credit_score": 750, "accounts": []},
        latest_vr_by_level={VerificationLevelNumber.L1_ADDRESS: uuid4()},
        l1_issues_by_step={
            "aadhaar_vs_bureau_address": {
                "severity": "CRITICAL",
                "status": "OPEN",
                "verification_result_id": str(uuid4()),
            }
        },
    )
    res = build_score(ctx)
    row = next(r for r in res.sections[0].rows if r.sno == 9)
    assert row.status == "FAIL"
