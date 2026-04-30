"""Tests for Level 1 Address cross-check pure helpers.

The orchestrator itself (``run_level_1_address``) is tested in an integration
test; these unit tests pin the per-sub-step rules so the orchestrator can be
small and safe.
"""

from __future__ import annotations

from app.enums import LevelIssueSeverity
from app.verification.levels.level_1_address import (
    cross_check_applicant_coapplicant_aadhaar_addresses,
    cross_check_business_gps_present,
    cross_check_commute,
    cross_check_gps_vs_applicant_aadhaar,
    cross_check_ration_owner_rule,
    cross_check_aadhaar_vs_bureau_bank,
)


# ---- applicant ↔ co-applicant Aadhaar address ----


def test_applicant_coapp_addresses_match_no_issue():
    applicant = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    coapp = "H No 123 Vill Sadipur, Hisar Haryana 125001"
    issue = cross_check_applicant_coapplicant_aadhaar_addresses(applicant, coapp)
    assert issue is None


def test_applicant_coapp_addresses_differ_returns_critical_issue():
    applicant = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    coapp = "Flat 9, MG Road, Bangalore, Karnataka 560001"
    issue = cross_check_applicant_coapplicant_aadhaar_addresses(applicant, coapp)
    assert issue is not None
    assert issue["sub_step_id"] == "applicant_coapp_address_match"
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    assert "applicant" in issue["description"].lower()


def test_applicant_coapp_no_coapp_data_no_issue():
    """If co-applicant Aadhaar wasn't supplied, skip the check without a flag."""
    applicant = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    issue = cross_check_applicant_coapplicant_aadhaar_addresses(applicant, None)
    assert issue is None


# ---- GPS vs Aadhaar ----


def test_gps_address_matches_aadhaar_no_issue():
    aadhaar = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    gps = "Sadipur Village, Hisar District, Haryana 125001, India"
    issue = cross_check_gps_vs_applicant_aadhaar(aadhaar, gps)
    assert issue is None


def test_gps_address_differs_returns_critical_issue():
    aadhaar = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    gps = "Panipat City, Haryana 132103, India"
    issue = cross_check_gps_vs_applicant_aadhaar(aadhaar, gps)
    assert issue is not None
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    assert issue["sub_step_id"] == "gps_vs_aadhaar"


def test_gps_missing_returns_warning_issue():
    """GPS EXIF missing or Google Maps failed — warning, not critical."""
    issue = cross_check_gps_vs_applicant_aadhaar("some applicant addr", None)
    assert issue is not None
    assert issue["severity"] == LevelIssueSeverity.WARNING.value
    assert issue["sub_step_id"] == "gps_vs_aadhaar"


# ---- Ration / electricity bill owner-name rule ----


def test_ration_owner_is_borrower_no_issue():
    """If the bill owner name matches the applicant, that's clean."""
    issue = cross_check_ration_owner_rule(
        bill_owner_name="AJAY SINGH",
        bill_father_or_husband_name=None,
        applicant_name="AJAY SINGH",
        co_applicant_name=None,
    )
    assert issue is None


def test_ration_owner_is_father_and_coapplicant_no_issue():
    """If the bill is in the father's name AND the father is a co-applicant."""
    issue = cross_check_ration_owner_rule(
        bill_owner_name="RAM SINGH",
        bill_father_or_husband_name=None,
        applicant_name="AJAY SINGH",
        co_applicant_name="RAM SINGH",
    )
    assert issue is None


def test_ration_owner_is_relative_not_coapplicant_critical():
    """Owner is borrower's father via S/O, but father is NOT a co-applicant."""
    issue = cross_check_ration_owner_rule(
        bill_owner_name="RAM SINGH",
        bill_father_or_husband_name="AJAY SINGH",  # borrower is the son; bill says S/O AJAY SINGH
        applicant_name="AJAY SINGH",
        co_applicant_name=None,
    )
    assert issue is not None
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    assert "co-applicant" in issue["description"].lower() or "co_applicant" in issue["description"].lower()


def test_ration_owner_completely_unrelated_critical():
    """Bill owner isn't the borrower and has no relation → CRITICAL."""
    issue = cross_check_ration_owner_rule(
        bill_owner_name="SOMEONE ELSE",
        bill_father_or_husband_name=None,
        applicant_name="AJAY SINGH",
        co_applicant_name="RAM SINGH",
    )
    assert issue is not None
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value


# ---- Aadhaar vs Equifax vs bank ----


def test_aadhaar_equifax_bank_all_match_no_issues():
    addr = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    issues = cross_check_aadhaar_vs_bureau_bank(
        aadhaar_address=addr,
        bureau_addresses=[addr],
        bank_addresses=[addr],
    )
    assert issues == []


def test_aadhaar_vs_bureau_mismatch_returns_warning():
    issues = cross_check_aadhaar_vs_bureau_bank(
        aadhaar_address="H No 123, Sadipur, Hisar, Haryana 125001",
        bureau_addresses=["Panipat, Haryana 132103"],
        bank_addresses=["H No 123 Sadipur Hisar Haryana"],
    )
    # One issue for the bureau mismatch
    sub_steps = [i["sub_step_id"] for i in issues]
    assert "aadhaar_vs_bureau_address" in sub_steps
    bureau_issue = next(i for i in issues if i["sub_step_id"] == "aadhaar_vs_bureau_address")
    assert bureau_issue["severity"] == LevelIssueSeverity.WARNING.value


def test_aadhaar_vs_bank_mismatch_returns_warning():
    issues = cross_check_aadhaar_vs_bureau_bank(
        aadhaar_address="H No 123, Sadipur, Hisar, Haryana 125001",
        bureau_addresses=["H No 123, Sadipur, Hisar, Haryana 125001"],
        bank_addresses=["MG Road, Bangalore"],
    )
    sub_steps = [i["sub_step_id"] for i in issues]
    assert "aadhaar_vs_bank_address" in sub_steps


def test_aadhaar_check_skipped_when_aadhaar_missing():
    issues = cross_check_aadhaar_vs_bureau_bank(
        aadhaar_address=None,
        bureau_addresses=["anything"],
        bank_addresses=["anything"],
    )
    # Can't cross-check without Aadhaar — return no issues (the Aadhaar
    # extraction failure is flagged separately earlier in the level).
    assert issues == []


# ---- Business-visit GPS presence (sub-step 3a') ----


def test_business_gps_present_no_issue():
    issue = cross_check_business_gps_present(business_gps_coords=(28.123, 77.456))
    assert issue is None


def test_business_gps_missing_returns_critical_mdonly():
    issue = cross_check_business_gps_present(business_gps_coords=None)
    assert issue is not None
    assert issue["sub_step_id"] == "business_visit_gps"
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    # Copy should tell the operator how to fix + that MD approval is the escape hatch.
    desc = issue["description"].lower()
    assert "business" in desc
    assert "gps" in desc
    assert "md" in desc or "md-approve" in desc or "md approval" in desc


# ---- Commute cross-check (sub-step 3b) ----
# Pure decision helper. Takes the pre-computed facts + judge verdict and
# returns either ``None`` (pass) or a LevelIssue dict. The orchestrator is
# responsible for actually invoking Distance Matrix + the Opus judge.


def test_commute_under_30_min_no_issue():
    issue = cross_check_commute(
        travel_minutes=18.0,
        distance_km=9.2,
        dm_status="ok",
        judge_verdict=None,
    )
    assert issue is None


def test_commute_over_30_min_judge_warning_emits_warning():
    issue = cross_check_commute(
        travel_minutes=42.0,
        distance_km=28.0,
        dm_status="ok",
        judge_verdict={
            "severity": "WARNING",
            "reason": "Wholesale dealer — 28 km travel is reasonable for this trade.",
            "confidence": "medium",
        },
    )
    assert issue is not None
    assert issue["sub_step_id"] == "house_business_commute"
    assert issue["severity"] == LevelIssueSeverity.WARNING.value
    assert "Wholesale dealer" in issue["description"]
    assert issue["evidence"]["travel_minutes"] == 42.0
    assert issue["evidence"]["distance_km"] == 28.0


def test_commute_over_30_min_judge_critical_emits_critical():
    issue = cross_check_commute(
        travel_minutes=95.0,
        distance_km=70.0,
        dm_status="ok",
        judge_verdict={
            "severity": "CRITICAL",
            "reason": "Small-ticket tailor with 95-min commute is implausible.",
            "confidence": "high",
        },
    )
    assert issue is not None
    assert issue["sub_step_id"] == "house_business_commute"
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    assert "95-min" in issue["description"] or "implausible" in issue["description"]


def test_commute_over_30_min_judge_unavailable_emits_warning():
    """Claude Opus call failed or returned junk — default to WARNING, not CRITICAL,
    so a flaky model call doesn't block the case."""
    issue = cross_check_commute(
        travel_minutes=55.0,
        distance_km=32.0,
        dm_status="ok",
        judge_verdict=None,  # judge was attempted but returned None
        judge_attempted=True,
    )
    assert issue is not None
    assert issue["sub_step_id"] == "house_business_commute"
    assert issue["severity"] == LevelIssueSeverity.WARNING.value
    assert "manually" in issue["description"].lower()


def test_commute_dm_zero_results_emits_critical():
    issue = cross_check_commute(
        travel_minutes=None,
        distance_km=None,
        dm_status="zero_results",
        judge_verdict=None,
    )
    assert issue is not None
    assert issue["sub_step_id"] == "house_business_commute"
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    desc = issue["description"].lower()
    assert "route" in desc or "drivable" in desc


def test_commute_dm_infra_failure_emits_warning():
    issue = cross_check_commute(
        travel_minutes=None,
        distance_km=None,
        dm_status="error",
        judge_verdict=None,
    )
    assert issue is not None
    assert issue["sub_step_id"] == "house_business_commute"
    assert issue["severity"] == LevelIssueSeverity.WARNING.value
    assert "distance matrix" in issue["description"].lower()


# ---- B2 evidence enrichment: policy thresholds / counts ----
#
# Every L1 fire-path concern now carries the constant it was judged against,
# so the "What was checked" panel can display the policy number inline with
# the observed value. These tests lock the constants so drift is caught.


def test_applicant_coapp_mismatch_evidence_carries_match_threshold():
    """The 0.85 fuzzy floor must be reflected in the evidence dict so the
    MD sees *why* the strings were judged to differ."""
    applicant = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    coapp = "Flat 9, MG Road, Bangalore, Karnataka 560001"
    issue = cross_check_applicant_coapplicant_aadhaar_addresses(applicant, coapp)
    assert issue is not None
    assert issue["evidence"]["match_threshold"] == 0.85
    # Existing keys still present.
    assert issue["evidence"]["applicant_address"] == applicant
    assert issue["evidence"]["co_applicant_address"] == coapp


def test_business_gps_missing_evidence_carries_photos_tried_count():
    """When business GPS can't be recovered we now record how many
    BUSINESS_PREMISES_PHOTO artifacts the extractor actually walked over
    before giving up."""
    issue = cross_check_business_gps_present(
        business_gps_coords=None, photos_tried_count=3
    )
    assert issue is not None
    assert issue["evidence"]["photos_tried_count"] == 3


def test_business_gps_missing_evidence_photos_tried_count_zero():
    issue = cross_check_business_gps_present(
        business_gps_coords=None, photos_tried_count=0
    )
    assert issue is not None
    assert issue["evidence"]["photos_tried_count"] == 0


def test_commute_zero_results_evidence_carries_threshold_min():
    issue = cross_check_commute(
        travel_minutes=None,
        distance_km=None,
        dm_status="zero_results",
        judge_verdict=None,
    )
    assert issue is not None
    assert issue["evidence"]["threshold_min"] == 30.0


def test_commute_dm_error_evidence_carries_threshold_min():
    issue = cross_check_commute(
        travel_minutes=None,
        distance_km=None,
        dm_status="error",
        judge_verdict=None,
    )
    assert issue is not None
    assert issue["evidence"]["threshold_min"] == 30.0


def test_commute_judge_unavailable_evidence_carries_threshold_min():
    issue = cross_check_commute(
        travel_minutes=55.0,
        distance_km=32.0,
        dm_status="ok",
        judge_verdict=None,
        judge_attempted=True,
    )
    assert issue is not None
    assert issue["evidence"]["threshold_min"] == 30.0


def test_commute_judge_warning_evidence_carries_threshold_min():
    issue = cross_check_commute(
        travel_minutes=42.0,
        distance_km=28.0,
        dm_status="ok",
        judge_verdict={
            "severity": "WARNING",
            "reason": "Wholesale dealer — 28 km travel is reasonable.",
            "confidence": "medium",
        },
    )
    assert issue is not None
    assert issue["evidence"]["threshold_min"] == 30.0


def test_commute_judge_schema_violation_evidence_carries_threshold_min():
    """Judge returned an invalid severity — WARNING branch."""
    issue = cross_check_commute(
        travel_minutes=42.0,
        distance_km=28.0,
        dm_status="ok",
        judge_verdict={"severity": "INFO", "reason": "whatever"},
    )
    assert issue is not None
    assert issue["evidence"]["threshold_min"] == 30.0


def test_aadhaar_vs_bureau_mismatch_evidence_carries_match_threshold():
    issues = cross_check_aadhaar_vs_bureau_bank(
        aadhaar_address="H No 123, Sadipur, Hisar, Haryana 125001",
        bureau_addresses=["Panipat, Haryana 132103"],
        bank_addresses=["H No 123 Sadipur Hisar Haryana"],
    )
    bureau_issue = next(
        i for i in issues if i["sub_step_id"] == "aadhaar_vs_bureau_address"
    )
    assert bureau_issue["evidence"]["match_threshold"] == 0.85


def test_aadhaar_vs_bank_mismatch_evidence_carries_match_threshold():
    issues = cross_check_aadhaar_vs_bureau_bank(
        aadhaar_address="H No 123, Sadipur, Hisar, Haryana 125001",
        bureau_addresses=["H No 123, Sadipur, Hisar, Haryana 125001"],
        bank_addresses=["MG Road, Bangalore"],
    )
    bank_issue = next(
        i for i in issues if i["sub_step_id"] == "aadhaar_vs_bank_address"
    )
    assert bank_issue["evidence"]["match_threshold"] == 0.85


# ---- B4: build_pass_evidence_l1 helper ----
#
# Pure helper mirroring ``build_pass_evidence`` in level_3_vision. Populates
# ``sub_step_results.pass_evidence`` for every L1 rule that DIDN'T fire — the
# FE's pass-detail dispatcher reads this dict to render structured cards on
# click-to-expand. Rules in ``fired_rules`` are omitted so the FE falls
# through to the LevelIssue.evidence for fails.


class TestBuildPassEvidenceL1:
    """build_pass_evidence_l1 returns a dict keyed by sub_step_id, with
    each entry populated only for rules that passed (were not in fired).
    source_artifacts is always a list when the underlying data carries
    artefact refs — the FE's LevelSourceFilesPanel aggregates them."""

    def _mk_artifact(self, aid: str, subtype: str, filename: str):
        class _A:
            pass
        a = _A()
        a.id = aid
        a.filename = filename
        a.metadata_json = {"subtype": subtype}
        return a

    def test_all_rules_passing_full_payload(self) -> None:
        from app.verification.levels.level_1_address import build_pass_evidence_l1

        applicant_aadhaar_art = self._mk_artifact(
            "a1", "KYC_AADHAAR", "applicant_aadhaar.pdf"
        )
        house_art = self._mk_artifact("h1", "HOUSE_VISIT_PHOTO", "house.jpg")
        biz_art = self._mk_artifact("b1", "BUSINESS_PREMISES_PHOTO", "biz.jpg")
        bill_art = self._mk_artifact("r1", "RATION_CARD", "ration.pdf")
        co_aadhaar_art = self._mk_artifact(
            "ca1", "CO_APPLICANT_AADHAAR", "coapp_aadhaar.pdf"
        )
        lagr_art = self._mk_artifact("l1", "LAGR", "loan_agreement.pdf")
        bureau_art = self._mk_artifact("e1", "EQUIFAX_HTML", "equifax.html")
        bank_art = self._mk_artifact("bs1", "BANK_STATEMENT", "bank.pdf")

        out = build_pass_evidence_l1(
            applicant_address="H No 123, Sadipur, Hisar, Haryana 125001",
            co_applicant_address="H No 123 Sadipur Hisar Haryana 125001",
            applicant_aadhaar_address="H No 123, Sadipur, Hisar, Haryana 125001",
            gps_derived_address="Sadipur Village, Hisar District, Haryana",
            gps_coords=(29.1, 75.7),
            gps_match=None,
            bill_owner="AJAY SINGH",
            bill_father_or_husband=None,
            applicant_name="AJAY SINGH",
            co_applicant_name="RAM SINGH",
            business_gps_coords=(29.2, 75.8),
            photos_tried_count=2,
            travel_minutes=12.0,
            distance_km=5.3,
            bureau_addresses=["H No 123, Sadipur, Hisar, Haryana 125001"],
            bank_addresses=["H No 123 Sadipur Hisar Haryana"],
            fired_rules=set(),
            applicant_aadhaar_art=applicant_aadhaar_art,
            gps_house_art=house_art,
            gps_biz_art=biz_art,
            bill_art=bill_art,
            co_aadhaar_art=co_aadhaar_art,
            lagr_art=lagr_art,
            bureau_art=bureau_art,
            bank_art=bank_art,
        )

        # Every rule populated.
        assert "applicant_coapp_address_match" in out
        assert "gps_vs_aadhaar" in out
        assert "ration_owner_rule" in out
        assert "business_visit_gps" in out
        assert "house_business_commute" in out
        assert "aadhaar_vs_bureau_address" in out
        assert "aadhaar_vs_bank_address" in out

        # applicant_coapp_address_match schema
        e = out["applicant_coapp_address_match"]
        assert e["match_threshold"] == 0.85
        assert e["verdict"] == "match"
        assert (
            e["applicant_address"] == "H No 123, Sadipur, Hisar, Haryana 125001"
        )
        assert (
            e["co_applicant_address"] == "H No 123 Sadipur Hisar Haryana 125001"
        )

        # gps_vs_aadhaar — source_artifacts cites aadhaar + house photo
        e = out["gps_vs_aadhaar"]
        assert e["applicant_aadhaar_address"].startswith("H No 123")
        assert e["gps_derived_address"].startswith("Sadipur")
        assert e["gps_coords"] == [29.1, 75.7]
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert "a1" in ids
        assert "h1" in ids

        # ration_owner_rule — bill + both aadhaars + LAGR cited
        e = out["ration_owner_rule"]
        assert e["bill_owner"] == "AJAY SINGH"
        assert e["applicant_name"] == "AJAY SINGH"
        assert e["co_applicant_name"] == "RAM SINGH"
        assert e["verdict"] == "clean"
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert {"r1", "a1", "ca1", "l1"}.issubset(ids)

        # business_visit_gps — lat/lng list + count
        e = out["business_visit_gps"]
        assert e["business_gps_coords"] == [29.2, 75.8]
        assert e["photos_tried_count"] == 2
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert "b1" in ids

        # house_business_commute — travel + threshold_min 30 + under_threshold
        e = out["house_business_commute"]
        assert e["travel_minutes"] == 12.0
        assert e["distance_km"] == 5.3
        assert e["dm_status"] == "ok"
        assert e["threshold_min"] == 30.0
        assert e["under_threshold"] is True
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert {"h1", "b1"}.issubset(ids)

        # aadhaar_vs_bureau_address
        e = out["aadhaar_vs_bureau_address"]
        assert e["match_threshold"] == 0.85
        assert e["verdict"] == "matched"
        assert e["bureau_addresses"] == [
            "H No 123, Sadipur, Hisar, Haryana 125001"
        ]
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert {"a1", "e1"}.issubset(ids)

        # aadhaar_vs_bank_address
        e = out["aadhaar_vs_bank_address"]
        assert e["match_threshold"] == 0.85
        assert e["verdict"] == "matched"
        assert e["bank_addresses"] == ["H No 123 Sadipur Hisar Haryana"]
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert {"a1", "bs1"}.issubset(ids)

    def test_fired_rules_are_excluded(self) -> None:
        """Rules present in ``fired_rules`` must not appear in the pass
        dict — the FE reads LevelIssue.evidence for those on fails."""
        from app.verification.levels.level_1_address import build_pass_evidence_l1

        out = build_pass_evidence_l1(
            applicant_address="addr",
            co_applicant_address="addr",
            applicant_aadhaar_address="addr",
            gps_derived_address="addr",
            gps_coords=(29.1, 75.7),
            gps_match=None,
            bill_owner="A",
            bill_father_or_husband=None,
            applicant_name="A",
            co_applicant_name=None,
            business_gps_coords=(29.2, 75.8),
            photos_tried_count=1,
            travel_minutes=5.0,
            distance_km=1.0,
            bureau_addresses=["addr"],
            bank_addresses=["addr"],
            fired_rules={
                "applicant_coapp_address_match",
                "gps_vs_aadhaar",
                "ration_owner_rule",
                "business_visit_gps",
                "house_business_commute",
                "aadhaar_vs_bureau_address",
                "aadhaar_vs_bank_address",
            },
            applicant_aadhaar_art=None,
            gps_house_art=None,
            gps_biz_art=None,
            bill_art=None,
            co_aadhaar_art=None,
            lagr_art=None,
            bureau_art=None,
            bank_art=None,
        )
        assert out == {}

    def test_skip_entries_when_underlying_data_missing(self) -> None:
        """When a piece of in-scope data isn't available at the orchestrator
        call-site, the helper skips that entry rather than inventing
        defaults. Keeps the FE's click-to-expand honest."""
        from app.verification.levels.level_1_address import build_pass_evidence_l1

        out = build_pass_evidence_l1(
            applicant_address=None,  # cross-check would have skipped
            co_applicant_address=None,
            applicant_aadhaar_address=None,  # gps_vs_aadhaar not meaningful
            gps_derived_address=None,
            gps_coords=None,
            gps_match=None,
            bill_owner=None,  # ration rule not meaningful
            bill_father_or_husband=None,
            applicant_name=None,
            co_applicant_name=None,
            business_gps_coords=None,  # business_visit_gps fires on missing
            photos_tried_count=0,
            travel_minutes=None,  # commute not computed
            distance_km=None,
            bureau_addresses=[],  # bureau check not run
            bank_addresses=[],  # bank check not run
            fired_rules=set(),
            applicant_aadhaar_art=None,
            gps_house_art=None,
            gps_biz_art=None,
            bill_art=None,
            co_aadhaar_art=None,
            lagr_art=None,
            bureau_art=None,
            bank_art=None,
        )
        # No entries at all — nothing meaningful can be said.
        assert "applicant_coapp_address_match" not in out
        assert "gps_vs_aadhaar" not in out
        assert "ration_owner_rule" not in out
        assert "business_visit_gps" not in out
        assert "house_business_commute" not in out
        assert "aadhaar_vs_bureau_address" not in out
        assert "aadhaar_vs_bank_address" not in out

    def test_schema_drift_guard_applicant_coapp_keyset(self) -> None:
        """Lock the exact key set on the busiest rule so a future
        rename/drop is caught by CI (same pattern as build_stock_analysis)."""
        from app.verification.levels.level_1_address import build_pass_evidence_l1

        out = build_pass_evidence_l1(
            applicant_address="addr A",
            co_applicant_address="addr A",
            applicant_aadhaar_address="addr A",
            gps_derived_address=None,
            gps_coords=None,
            gps_match=None,
            bill_owner=None,
            bill_father_or_husband=None,
            applicant_name=None,
            co_applicant_name=None,
            business_gps_coords=None,
            photos_tried_count=0,
            travel_minutes=None,
            distance_km=None,
            bureau_addresses=[],
            bank_addresses=[],
            fired_rules=set(),
            applicant_aadhaar_art=None,
            gps_house_art=None,
            gps_biz_art=None,
            bill_art=None,
            co_aadhaar_art=None,
            lagr_art=None,
            bureau_art=None,
            bank_art=None,
        )
        e = out["applicant_coapp_address_match"]
        assert set(e.keys()) == {
            "applicant_address",
            "co_applicant_address",
            "match_threshold",
            "verdict",
        }

    def test_gps_match_to_dict_flows_through(self) -> None:
        """When the structured GPSMatch is available, its full to_dict
        payload is embedded in the pass entry alongside the display fields."""
        from app.verification.levels.level_1_address import build_pass_evidence_l1
        from app.verification.services.address_normalizer import GPSMatch

        gm = GPSMatch(
            verdict="match",
            score=95,
            state_match=True,
            district_match=True,
            village_match=True,
            reason="All three components matched",
            gps_state="Haryana",
            gps_district="Hisar",
            gps_village="Sadipur",
            aadhaar_pincode="125001",
        )
        out = build_pass_evidence_l1(
            applicant_address=None,
            co_applicant_address=None,
            applicant_aadhaar_address="aadhaar addr",
            gps_derived_address="gps addr",
            gps_coords=(29.1, 75.7),
            gps_match=gm,
            bill_owner=None,
            bill_father_or_husband=None,
            applicant_name=None,
            co_applicant_name=None,
            business_gps_coords=None,
            photos_tried_count=0,
            travel_minutes=None,
            distance_km=None,
            bureau_addresses=[],
            bank_addresses=[],
            fired_rules=set(),
            applicant_aadhaar_art=None,
            gps_house_art=None,
            gps_biz_art=None,
            bill_art=None,
            co_aadhaar_art=None,
            lagr_art=None,
            bureau_art=None,
            bank_art=None,
        )
        e = out["gps_vs_aadhaar"]
        # to_dict() contents flow through — verdict + score visible.
        assert e["gps_match"]["verdict"] == "match"
        assert e["gps_match"]["score"] == 95
        assert e["applicant_aadhaar_address"] == "aadhaar addr"
        assert e["gps_derived_address"] == "gps addr"
        assert e["gps_coords"] == [29.1, 75.7]
