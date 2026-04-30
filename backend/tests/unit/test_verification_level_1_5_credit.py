"""Unit tests for Level 1.5 pure cross-checks (willful-default rules)."""

from __future__ import annotations

from app.enums import LevelIssueSeverity
from app.verification.levels.level_1_5_credit import (
    cross_check_credit_score,
    cross_check_doubtful,
    cross_check_loss,
    cross_check_settled,
    cross_check_sma,
    cross_check_substandard,
    cross_check_write_off,
)


# ── Write-off / Loss / Settled / SUB / DBT / SMA ─────────────────────────────


def test_no_write_off_passes():
    assert cross_check_write_off([{"status": "Standard"}, {"status": "Closed"}]) is None


def test_write_off_detected_as_critical():
    iss = cross_check_write_off(
        [
            {"status": "Standard"},
            {"status": "Write-Off", "institution": "ABC NBFC", "date_opened": "01-01-2022"},
        ]
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value
    assert "WRITE-OFF" in iss["description"]
    assert "ABC NBFC" in iss["description"]


def test_wo_abbreviation_also_detected():
    iss = cross_check_write_off([{"status": "WO", "institution": "XYZ"}])
    assert iss is not None


def test_loss_accounts_are_critical():
    iss = cross_check_loss([{"status": "LSS", "institution": "L1"}])
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value


def test_loss_word_variant_also_detected():
    iss = cross_check_loss([{"status": "Loss", "institution": "L1"}])
    assert iss is not None


def test_settled_accounts_are_critical():
    iss = cross_check_settled([{"status": "Settled", "institution": "SBI"}])
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value
    assert "SETTLED" in iss["description"]


def test_substandard_accounts_are_warning():
    iss = cross_check_substandard([{"status": "Substandard", "institution": "X"}])
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_doubtful_accounts_are_warning():
    iss = cross_check_doubtful([{"status": "DBT", "institution": "Y"}])
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_sma_accounts_are_warning():
    iss = cross_check_sma([{"status": "SMA-1", "institution": "Z"}])
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_sma_sma0_variant_detected():
    iss = cross_check_sma([{"status": "sma-0", "institution": "Z"}])
    assert iss is not None


def test_clean_applicant_no_issues():
    accounts = [
        {"status": "Standard", "institution": "A"},
        {"status": "Closed", "institution": "B"},
    ]
    for rule in (
        cross_check_write_off,
        cross_check_loss,
        cross_check_settled,
        cross_check_substandard,
        cross_check_doubtful,
        cross_check_sma,
    ):
        assert rule(accounts) is None


# ── Credit score floor ───────────────────────────────────────────────────────


def test_credit_score_above_700_passes():
    assert cross_check_credit_score(800) is None
    assert cross_check_credit_score(700) is None


def test_credit_score_680_to_699_is_warning():
    iss = cross_check_credit_score(690)
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_credit_score_below_680_is_critical():
    iss = cross_check_credit_score(650)
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value


def test_credit_score_ntc_or_none_is_skipped():
    # -1 is Equifax "Bureau hit but no score" / NTC sentinel; None is missing.
    assert cross_check_credit_score(None) is None
    assert cross_check_credit_score(-1) is None


# ── Evidence enrichment — status scanners ────────────────────────────────────


class TestStatusScannerEvidence:
    """Every status scanner must emit evidence.statuses_seen + evidence.worst_account
    on fire, normalised to the real Equifax schema regardless of whether the input
    account dict uses the real extractor keys or the fixture keys."""

    def test_write_off_emits_statuses_seen_and_worst_account_real_schema(self):
        iss = cross_check_write_off(
            [
                {"status": "Standard"},
                {
                    "status": "Write-Off",
                    "institution": "ABC NBFC",
                    "date_opened": "01-01-2022",
                    "balance": 50000,
                    "type": "Personal Loan",
                    "product_type": "Unsecured",
                },
            ]
        )
        assert iss is not None
        ev = iss["evidence"]
        assert ev["statuses_seen"] == ["Write-Off"]
        assert ev["worst_account"] == {
            "institution": "ABC NBFC",
            "status": "Write-Off",
            "date_opened": "01-01-2022",
            "balance": 50000,
            "type": "Personal Loan",
            "product_type": "Unsecured",
        }

    def test_write_off_emits_worst_account_fixture_schema_normalised(self):
        # Fixture variant: lender + opened instead of institution + date_opened.
        iss = cross_check_write_off(
            [
                {
                    "status": "WO",
                    "lender": "XYZ Bank",
                    "opened": "15-06-2021",
                    "balance": 12345,
                    "type": "Credit Card",
                }
            ]
        )
        assert iss is not None
        ev = iss["evidence"]
        assert ev["statuses_seen"] == ["WO"]
        wa = ev["worst_account"]
        # Normalised: fixture 'lender' -> 'institution', 'opened' -> 'date_opened'.
        assert wa["institution"] == "XYZ Bank"
        assert wa["date_opened"] == "15-06-2021"
        assert wa["status"] == "WO"
        assert wa["balance"] == 12345
        assert wa["type"] == "Credit Card"
        # product_type not present in fixture -> None
        assert wa["product_type"] is None

    def test_loss_emits_evidence(self):
        iss = cross_check_loss(
            [{"status": "LSS", "institution": "L1", "date_opened": "2020"}]
        )
        assert iss is not None
        ev = iss["evidence"]
        assert ev["statuses_seen"] == ["LSS"]
        assert ev["worst_account"]["institution"] == "L1"
        assert ev["worst_account"]["status"] == "LSS"

    def test_settled_emits_evidence(self):
        iss = cross_check_settled(
            [{"status": "Settled", "institution": "SBI", "balance": 1000}]
        )
        assert iss is not None
        ev = iss["evidence"]
        assert ev["statuses_seen"] == ["Settled"]
        assert ev["worst_account"]["institution"] == "SBI"
        assert ev["worst_account"]["balance"] == 1000

    def test_substandard_emits_evidence(self):
        iss = cross_check_substandard(
            [{"status": "Substandard", "institution": "X", "type": "PL"}]
        )
        assert iss is not None
        ev = iss["evidence"]
        assert ev["statuses_seen"] == ["Substandard"]
        assert ev["worst_account"]["institution"] == "X"
        assert ev["worst_account"]["type"] == "PL"

    def test_doubtful_emits_evidence(self):
        iss = cross_check_doubtful([{"status": "DBT", "institution": "Y"}])
        assert iss is not None
        ev = iss["evidence"]
        assert ev["statuses_seen"] == ["DBT"]
        assert ev["worst_account"]["institution"] == "Y"
        assert ev["worst_account"]["status"] == "DBT"

    def test_sma_emits_evidence(self):
        iss = cross_check_sma([{"status": "SMA-1", "institution": "Z"}])
        assert iss is not None
        ev = iss["evidence"]
        assert ev["statuses_seen"] == ["SMA-1"]
        assert ev["worst_account"]["institution"] == "Z"
        assert ev["worst_account"]["status"] == "SMA-1"

    def test_statuses_seen_includes_every_matching_account(self):
        iss = cross_check_write_off(
            [
                {"status": "Standard"},
                {"status": "Write-Off", "institution": "A"},
                {"status": "WO", "institution": "B"},
                {"status": "write off", "institution": "C"},
            ]
        )
        assert iss is not None
        # All three matches appear in statuses_seen in order.
        assert iss["evidence"]["statuses_seen"] == ["Write-Off", "WO", "write off"]
        # Worst account is the first hit.
        assert iss["evidence"]["worst_account"]["institution"] == "A"

    def test_no_fire_still_returns_none_not_empty_evidence(self):
        # Clean account list — scanner returns None (unchanged behaviour).
        assert cross_check_write_off([{"status": "Standard"}]) is None


# ── Evidence enrichment — credit score floor ─────────────────────────────────


class TestCreditScoreEvidence:
    def test_critical_band_at_650(self):
        iss = cross_check_credit_score(650)
        assert iss is not None
        assert iss["severity"] == LevelIssueSeverity.CRITICAL.value
        ev = iss["evidence"]
        assert ev["credit_score"] == 650
        assert ev["threshold_critical"] == 680
        assert ev["threshold_warning"] == 700
        assert ev["band"] == "crit"

    def test_warning_band_at_690(self):
        iss = cross_check_credit_score(690)
        assert iss is not None
        assert iss["severity"] == LevelIssueSeverity.WARNING.value
        ev = iss["evidence"]
        assert ev["credit_score"] == 690
        assert ev["threshold_critical"] == 680
        assert ev["threshold_warning"] == 700
        assert ev["band"] == "warn"


# ---- B5: build_pass_evidence_l1_5 helper ----
#
# Pure helper mirroring Part A's build_pass_evidence in level_3_vision.
# Populates sub_step_results.pass_evidence for every L1.5 rule that DIDN'T
# fire: the 6 status scanners × 2 parties + credit_score_floor × 2 parties
# + bureau_report_missing + opus_credit_verdict. source_artifacts cites
# the applicant or co-applicant bureau HTML depending on the rule.


class TestBuildPassEvidenceL1_5:
    def _mk_artifact(self, aid: str, subtype: str, filename: str):
        class _A:
            pass
        a = _A()
        a.id = aid
        a.filename = filename
        a.metadata_json = {"subtype": subtype}
        return a

    def _all_status_scanner_sub_step_ids(self) -> list[str]:
        base = [
            "credit_write_off",
            "credit_loss",
            "credit_settled",
            "credit_substandard",
            "credit_doubtful",
            "credit_sma",
        ]
        return base + [f"coapp_{x}" for x in base]

    def test_clean_applicant_and_coapp_all_scanners_populated(self):
        from app.verification.levels.level_1_5_credit import (
            build_pass_evidence_l1_5,
        )

        app_art = self._mk_artifact("e1", "EQUIFAX_HTML", "applicant_equifax.html")
        co_art = self._mk_artifact("e2", "EQUIFAX_HTML", "coapp_equifax.html")

        out = build_pass_evidence_l1_5(
            applicant_accounts=[
                {"status": "Standard", "institution": "A"},
                {"status": "Closed", "institution": "B"},
            ],
            applicant_credit_score=780,
            co_applicant_accounts=[
                {"status": "Standard", "institution": "C"},
            ],
            co_applicant_credit_score=740,
            equifax_rows_found=2,
            opus_evidence={
                "applicant_verdict": "clean",
                "applicant_credit_score": 780,
                "analyst_overall_verdict": "clean",
                "analyst_recommendation": "approve",
            },
            fired_rules=set(),
            applicant_bureau_art=app_art,
            coapp_bureau_art=co_art,
        )

        # Every status scanner × 2 parties is populated.
        for sub in self._all_status_scanner_sub_step_ids():
            assert sub in out, f"expected {sub} in pass_evidence"
            e = out[sub]
            assert e["statuses_clean"] is True
            assert "party" in e
            assert "accounts_examined" in e
            # source_artifacts cites the right bureau HTML per party.
            ids = {r["artifact_id"] for r in e["source_artifacts"]}
            if sub.startswith("coapp_"):
                assert "e2" in ids
                assert e["party"] == "co_applicant"
                assert e["accounts_examined"] == 1
            else:
                assert "e1" in ids
                assert e["party"] == "applicant"
                assert e["accounts_examined"] == 2

        # credit_score_floor populated for both parties.
        assert out["credit_score_floor"]["party"] == "applicant"
        assert out["credit_score_floor"]["credit_score"] == 780
        assert out["credit_score_floor"]["threshold_critical"] == 680
        assert out["credit_score_floor"]["threshold_warning"] == 700
        assert out["coapp_credit_score_floor"]["party"] == "co_applicant"
        assert out["coapp_credit_score_floor"]["credit_score"] == 740

        # bureau_report_missing populated when bureau was found.
        assert "bureau_report_missing" in out
        assert out["bureau_report_missing"]["expected_subtype"] == "EQUIFAX_HTML"
        assert out["bureau_report_missing"]["equifax_rows_found"] == 2
        ids = {r["artifact_id"] for r in out["bureau_report_missing"]["source_artifacts"]}
        assert "e1" in ids

        # opus_credit_verdict flows opus_evidence through directly.
        ev = out["opus_credit_verdict"]
        assert ev["applicant_verdict"] == "clean"
        assert ev["analyst_recommendation"] == "approve"
        ids = {r["artifact_id"] for r in ev["source_artifacts"]}
        assert {"e1", "e2"}.issubset(ids)

    def test_fired_rules_are_excluded(self):
        from app.verification.levels.level_1_5_credit import (
            build_pass_evidence_l1_5,
        )

        out = build_pass_evidence_l1_5(
            applicant_accounts=[{"status": "Standard"}],
            applicant_credit_score=750,
            co_applicant_accounts=[],
            co_applicant_credit_score=None,
            equifax_rows_found=1,
            opus_evidence={},
            fired_rules={
                "credit_write_off",
                "credit_score_floor",
                "bureau_report_missing",
                "opus_credit_verdict",
            },
            applicant_bureau_art=None,
            coapp_bureau_art=None,
        )
        # Fired rules are absent.
        assert "credit_write_off" not in out
        assert "credit_score_floor" not in out
        assert "bureau_report_missing" not in out
        assert "opus_credit_verdict" not in out
        # Sibling rules that weren't in fired still populate.
        assert "credit_loss" in out
        assert "credit_settled" in out

    def test_coapp_score_absent_when_score_none(self):
        """If the co-applicant has no bureau hit / NTC, don't emit a
        coapp_credit_score_floor pass entry (avoid asserting a fake
        "score above threshold" for an invisible co-app)."""
        from app.verification.levels.level_1_5_credit import (
            build_pass_evidence_l1_5,
        )

        out = build_pass_evidence_l1_5(
            applicant_accounts=[{"status": "Standard"}],
            applicant_credit_score=780,
            co_applicant_accounts=[],
            co_applicant_credit_score=None,
            equifax_rows_found=1,
            opus_evidence={},
            fired_rules=set(),
            applicant_bureau_art=None,
            coapp_bureau_art=None,
        )
        # Applicant side populated.
        assert "credit_score_floor" in out
        assert out["credit_score_floor"]["credit_score"] == 780
        # Co-app side absent — we wouldn't fake a pass from None.
        assert "coapp_credit_score_floor" not in out

    def test_bureau_missing_absent_when_zero_rows(self):
        """bureau_report_missing is a meta-rule that FIRES when no bureau
        row is found. On the pass side we only narrate it when ≥1 bureau
        row exists (fixing the spec's 'equifax_rows_found ≥1' invariant)."""
        from app.verification.levels.level_1_5_credit import (
            build_pass_evidence_l1_5,
        )

        out = build_pass_evidence_l1_5(
            applicant_accounts=[],
            applicant_credit_score=None,
            co_applicant_accounts=[],
            co_applicant_credit_score=None,
            equifax_rows_found=0,  # would have fired bureau_report_missing
            opus_evidence={},
            fired_rules={"bureau_report_missing"},
            applicant_bureau_art=None,
            coapp_bureau_art=None,
        )
        assert "bureau_report_missing" not in out

    def test_opus_verdict_absent_when_opus_evidence_empty(self):
        """When Opus wasn't invoked or returned nothing, don't narrate a
        clean opus_credit_verdict entry — there's literally nothing to say."""
        from app.verification.levels.level_1_5_credit import (
            build_pass_evidence_l1_5,
        )

        out = build_pass_evidence_l1_5(
            applicant_accounts=[{"status": "Standard"}],
            applicant_credit_score=780,
            co_applicant_accounts=[],
            co_applicant_credit_score=None,
            equifax_rows_found=1,
            opus_evidence={},
            fired_rules=set(),
            applicant_bureau_art=None,
            coapp_bureau_art=None,
        )
        assert "opus_credit_verdict" not in out

    def test_schema_drift_guard_status_scanner_keyset(self):
        """Lock the key set on status-scanner pass entries — any future
        rename/drop is caught by CI (same pattern as Part A tests)."""
        from app.verification.levels.level_1_5_credit import (
            build_pass_evidence_l1_5,
        )

        out = build_pass_evidence_l1_5(
            applicant_accounts=[{"status": "Standard"}],
            applicant_credit_score=780,
            co_applicant_accounts=[],
            co_applicant_credit_score=None,
            equifax_rows_found=1,
            opus_evidence={},
            fired_rules=set(),
            applicant_bureau_art=None,
            coapp_bureau_art=None,
        )
        e = out["credit_write_off"]
        assert set(e.keys()) == {
            "party",
            "accounts_examined",
            "statuses_clean",
            "source_artifacts",
        }

    def test_source_artifacts_always_a_list(self):
        """Even when no bureau artefact is on hand, source_artifacts is
        an empty list (not missing / None) so the FE's aggregator can
        iterate without null checks."""
        from app.verification.levels.level_1_5_credit import (
            build_pass_evidence_l1_5,
        )

        out = build_pass_evidence_l1_5(
            applicant_accounts=[{"status": "Standard"}],
            applicant_credit_score=780,
            co_applicant_accounts=[],
            co_applicant_credit_score=None,
            equifax_rows_found=1,
            opus_evidence={},
            fired_rules=set(),
            applicant_bureau_art=None,
            coapp_bureau_art=None,
        )
        assert isinstance(out["credit_write_off"]["source_artifacts"], list)
