"""Unit tests for Level 4 pure cross-check helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.enums import (
    ArtifactSubtype,
    ArtifactType,
    ExtractionStatus,
    LevelIssueSeverity,
    UserRole,
)
from app.verification.levels.level_4_agreement import (
    cross_check_annexure_present,
    cross_check_hypothecation_clause,
    cross_check_asset_count,
)
from app.worker.extractors.base import ExtractionResult


def test_annexure_present_passes_when_true():
    assert cross_check_annexure_present(True) is None


def test_annexure_missing_returns_critical():
    issue = cross_check_annexure_present(False)
    assert issue is not None
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    assert issue["sub_step_id"] == "loan_agreement_annexure"


def test_hypothecation_clause_passes_when_present():
    assert cross_check_hypothecation_clause(True) is None


def test_hypothecation_clause_missing_returns_critical():
    issue = cross_check_hypothecation_clause(False)
    assert issue is not None
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    assert issue["sub_step_id"] == "hypothecation_clause"


def test_asset_count_passes_when_positive():
    assert cross_check_asset_count(3) is None


def test_asset_count_zero_returns_critical():
    issue = cross_check_asset_count(0)
    assert issue is not None
    assert issue["severity"] == LevelIssueSeverity.CRITICAL.value
    assert issue["sub_step_id"] == "asset_annexure_empty"


# ---- B3 meta-emitter evidence enrichment (L4) ----
# ``loan_agreement_missing`` and ``loan_agreement_scan_failed`` are inline in
# the run_level_4_agreement orchestrator. Exercise those paths end-to-end
# against the test DB with a stubbed storage / scanner.


class _StubStorage:
    def __init__(self, *, body: bytes = b"%PDF-1.7 fake") -> None:
        self.download_object = AsyncMock(return_value=body)


async def _seed_l4_case(db, *, add_lagr: bool = False):
    from app.models.case import Case
    from app.models.case_artifact import CaseArtifact
    from app.services import users as users_svc

    user = await users_svc.create_user(
        db,
        email="l4-meta@pfl.com",
        password="Pass123!",
        full_name="L4 Meta",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()

    case = Case(
        loan_id="L4META0001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="l4meta/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()

    artifact = None
    if add_lagr:
        artifact = CaseArtifact(
            case_id=case.id,
            filename="loan_agreement.pdf",
            artifact_type=ArtifactType.ADDITIONAL_FILE,
            s3_key=f"l4meta/{case.id}/loan_agreement.pdf",
            uploaded_by=user.id,
            uploaded_at=datetime.now(UTC),
            metadata_json={"subtype": ArtifactSubtype.LAGR.value},
        )
        db.add(artifact)
        await db.flush()

    return case.id, user.id, artifact


async def test_loan_agreement_missing_evidence_carries_expected_subtypes(db):
    """When no LAGR/LOAN_AGREEMENT/LAPP/DPN artifact is uploaded, the
    emitter now records the list of subtypes that were searched for, so
    the MD panel can tell the assessor exactly what to upload."""
    from app.verification.levels import level_4_agreement as l4_mod
    from app.models.level_issue import LevelIssue
    from sqlalchemy import select

    case_id, actor_user_id, _ = await _seed_l4_case(db, add_lagr=False)
    result = await l4_mod.run_level_4_agreement(
        db,
        case_id,
        actor_user_id=actor_user_id,
        claude=object(),
        storage=_StubStorage(),
    )

    issues = (
        await db.execute(
            select(LevelIssue).where(
                LevelIssue.verification_result_id == result.id,
                LevelIssue.sub_step_id == "loan_agreement_missing",
            )
        )
    ).scalars().all()
    assert len(issues) == 1
    ev = issues[0].evidence or {}
    expected = ev.get("expected_subtypes")
    assert expected is not None
    # Real enum values — grep-verified in enums.py.
    assert set(expected) == {
        ArtifactSubtype.LAGR.value,
        ArtifactSubtype.LOAN_AGREEMENT.value,
        ArtifactSubtype.LAPP.value,
        ArtifactSubtype.DPN.value,
    }


# ---- B7: build_pass_evidence_l4 helper ----
#
# Pure helper mirroring Part A's build_pass_evidence. Populates
# sub_step_results.pass_evidence for L4 rules that DIDN'T fire by slicing
# res.data from the LoanAgreementScanner. ``source_artifacts`` cites the
# LAGR PDF on the same shape the fire path uses.


class TestBuildPassEvidenceL4:
    def _mk_artifact(self, aid: str, subtype: str, filename: str):
        class _A:
            pass
        a = _A()
        a.id = aid
        a.filename = filename
        a.metadata_json = {"subtype": subtype}
        return a

    def test_all_rules_passing_full_payload(self):
        from app.verification.levels.level_4_agreement import build_pass_evidence_l4

        lagr_art = self._mk_artifact("l1", "LAGR", "loan_agreement.pdf")
        scanner_data = {
            "annexure_present": True,
            "annexure_page_hint": 3,
            "hypothecation_clause_present": True,
            "assets": [
                {"description": "sewing machine", "value_inr": 20000},
                {"description": "2 buffaloes", "value_inr": 120000},
            ],
            "asset_count": 2,
        }
        out = build_pass_evidence_l4(
            scanner_data=scanner_data,
            agreement_artifact=lagr_art,
            fired_rules=set(),
        )

        # loan_agreement_missing — filename + artifact_id
        assert "loan_agreement_missing" in out
        e = out["loan_agreement_missing"]
        assert e["agreement_filename"] == "loan_agreement.pdf"
        assert e["artifact_id"] == "l1"
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert "l1" in ids

        # loan_agreement_annexure — present + page hint
        e = out["loan_agreement_annexure"]
        assert e["annexure_present"] is True
        assert e["annexure_page_hint"] == 3
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert "l1" in ids

        # hypothecation_clause
        e = out["hypothecation_clause"]
        assert e["hypothecation_clause_present"] is True
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert "l1" in ids

        # asset_annexure_empty — asset_count + assets list
        e = out["asset_annexure_empty"]
        assert e["asset_count"] == 2
        assert e["assets"] == [
            {"description": "sewing machine", "value_inr": 20000},
            {"description": "2 buffaloes", "value_inr": 120000},
        ]
        ids = {r["artifact_id"] for r in e["source_artifacts"]}
        assert "l1" in ids

        # loan_agreement_scan_failed — error-only rule, never populated
        assert "loan_agreement_scan_failed" not in out

    def test_fired_rules_are_excluded(self):
        from app.verification.levels.level_4_agreement import build_pass_evidence_l4

        lagr_art = self._mk_artifact("l1", "LAGR", "loan_agreement.pdf")
        out = build_pass_evidence_l4(
            scanner_data={
                "annexure_present": True,
                "hypothecation_clause_present": True,
                "assets": [{"description": "x"}],
                "asset_count": 1,
            },
            agreement_artifact=lagr_art,
            fired_rules={
                "loan_agreement_missing",
                "loan_agreement_annexure",
                "hypothecation_clause",
                "asset_annexure_empty",
            },
        )
        assert out == {}

    def test_agreement_missing_entry_skipped_when_no_artifact(self):
        """Pass-side loan_agreement_missing narrates the uploaded file.
        When no LAGR was uploaded the fire path already raised it — no
        meaningful pass entry to emit, so skip."""
        from app.verification.levels.level_4_agreement import build_pass_evidence_l4

        out = build_pass_evidence_l4(
            scanner_data={
                "annexure_present": True,
                "hypothecation_clause_present": True,
                "asset_count": 0,
                "assets": [],
            },
            agreement_artifact=None,
            fired_rules=set(),
        )
        assert "loan_agreement_missing" not in out

    def test_annexure_entry_skipped_when_not_present(self):
        """When annexure_present is False the fire path would have
        already raised loan_agreement_annexure; don't narrate a pass."""
        from app.verification.levels.level_4_agreement import build_pass_evidence_l4

        lagr_art = self._mk_artifact("l1", "LAGR", "loan_agreement.pdf")
        out = build_pass_evidence_l4(
            scanner_data={
                "annexure_present": False,
                "hypothecation_clause_present": True,
                "asset_count": 0,
                "assets": [],
            },
            agreement_artifact=lagr_art,
            fired_rules=set(),
        )
        assert "loan_agreement_annexure" not in out

    def test_hypothecation_entry_skipped_when_not_present(self):
        from app.verification.levels.level_4_agreement import build_pass_evidence_l4

        lagr_art = self._mk_artifact("l1", "LAGR", "loan_agreement.pdf")
        out = build_pass_evidence_l4(
            scanner_data={
                "annexure_present": True,
                "hypothecation_clause_present": False,
                "asset_count": 1,
                "assets": [{"description": "x"}],
            },
            agreement_artifact=lagr_art,
            fired_rules=set(),
        )
        assert "hypothecation_clause" not in out

    def test_asset_annexure_empty_skipped_when_count_zero(self):
        """Fire-path raises asset_annexure_empty when count==0; don't
        narrate a pass in that scenario."""
        from app.verification.levels.level_4_agreement import build_pass_evidence_l4

        lagr_art = self._mk_artifact("l1", "LAGR", "loan_agreement.pdf")
        out = build_pass_evidence_l4(
            scanner_data={
                "annexure_present": True,
                "hypothecation_clause_present": True,
                "asset_count": 0,
                "assets": [],
            },
            agreement_artifact=lagr_art,
            fired_rules=set(),
        )
        assert "asset_annexure_empty" not in out

    def test_schema_drift_guard_asset_annexure_keyset(self):
        """Lock the key set on asset_annexure_empty — the busiest rule
        (carries the assets list the FE card renders)."""
        from app.verification.levels.level_4_agreement import build_pass_evidence_l4

        lagr_art = self._mk_artifact("l1", "LAGR", "loan_agreement.pdf")
        out = build_pass_evidence_l4(
            scanner_data={
                "annexure_present": True,
                "hypothecation_clause_present": True,
                "asset_count": 1,
                "assets": [{"description": "x"}],
            },
            agreement_artifact=lagr_art,
            fired_rules=set(),
        )
        e = out["asset_annexure_empty"]
        assert set(e.keys()) == {
            "asset_count",
            "assets",
            "source_artifacts",
        }


async def test_loan_agreement_scan_failed_evidence_carries_error_and_artifact_id(db):
    """If the scanner raises, the emitter should reflect both the error
    message AND the artifact_id so the MD can identify which PDF broke."""
    from app.verification.levels import level_4_agreement as l4_mod
    from app.models.level_issue import LevelIssue
    from sqlalchemy import select

    case_id, actor_user_id, artifact = await _seed_l4_case(db, add_lagr=True)

    class _CrashingScanner:
        def __init__(self, claude=None) -> None:
            pass

        async def extract(self, filename, body):
            raise RuntimeError("vision call exploded: schema mismatch")

    with patch(
        "app.worker.extractors.loan_agreement_scanner.LoanAgreementScanner",
        _CrashingScanner,
    ):
        result = await l4_mod.run_level_4_agreement(
            db,
            case_id,
            actor_user_id=actor_user_id,
            claude=object(),
            storage=_StubStorage(),
        )

    issues = (
        await db.execute(
            select(LevelIssue).where(
                LevelIssue.verification_result_id == result.id,
                LevelIssue.sub_step_id == "loan_agreement_scan_failed",
            )
        )
    ).scalars().all()
    assert len(issues) == 1
    ev = issues[0].evidence or {}
    assert "vision call exploded" in (ev.get("error_message") or "")
    assert ev.get("artifact_id") == str(artifact.id)
