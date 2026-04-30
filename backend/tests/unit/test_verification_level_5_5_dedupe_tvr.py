"""Unit tests for Level 5.5 (Dedupe + TVR presence-check) orchestrator.

Four scenarios covering the matrix of (dedupe present blank / dedupe
present non-blank / dedupe missing) x (TVR present / TVR missing).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.enums import (
    ArtifactSubtype,
    ArtifactType,
    ExtractionStatus,
    LevelIssueSeverity,
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.level_issue import LevelIssue
from app.services import users as users_svc
from app.verification.levels.level_5_5_dedupe_tvr import run_level_5_5_dedupe_tvr


async def _seed_l55_case(
    db,
    *,
    add_dedupe: bool = False,
    dedupe_row_count: int = 0,
    add_tvr: bool = False,
    tvr_size_bytes: int = 400_000,
):
    """Seed a case + optional artefacts/extractions for L5.5 testing.

    Returns (case_id, actor_user_id, dedupe_artifact, tvr_artifact).
    """
    user = await users_svc.create_user(
        db,
        email=f"l55-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!",
        full_name="L5.5 Tester",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()

    case = Case(
        loan_id=f"L55{int(datetime.now(UTC).timestamp() * 1000) % 10_000_000}",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key=f"l55/{user.id}/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()

    dedupe_artifact = None
    if add_dedupe:
        dedupe_artifact = CaseArtifact(
            case_id=case.id,
            filename="Customer_Dedupe.xlsx",
            artifact_type=ArtifactType.ADDITIONAL_FILE,
            s3_key=f"l55/{case.id}/Customer_Dedupe.xlsx",
            uploaded_by=user.id,
            uploaded_at=datetime.now(UTC),
            metadata_json={"subtype": ArtifactSubtype.DEDUPE_REPORT.value},
        )
        db.add(dedupe_artifact)
        await db.flush()
        # Synthetic CaseExtraction matching what DedupeReportExtractor would emit
        matched_rows = [
            {"customer_id": f"C{i:03d}", "full_name": f"Match {i}",
             "aadhaar_id": f"XXXX-XXXX-{1000 + i}"}
            for i in range(dedupe_row_count)
        ]
        extraction = CaseExtraction(
            case_id=case.id,
            artifact_id=dedupe_artifact.id,
            extractor_name="dedupe_report",
            schema_version="1.0",
            status=ExtractionStatus.SUCCESS,
            data={
                "row_count": dedupe_row_count,
                "matched_rows": matched_rows,
                "matched_fields": (
                    ["aadhaar_id", "customer_id", "full_name"]
                    if dedupe_row_count > 0 else []
                ),
            },
            extracted_at=datetime.now(UTC),
        )
        db.add(extraction)
        await db.flush()

    tvr_artifact = None
    if add_tvr:
        tvr_artifact = CaseArtifact(
            case_id=case.id,
            filename="tvr_sample.mp3",
            artifact_type=ArtifactType.ADDITIONAL_FILE,
            s3_key=f"l55/{case.id}/tvr_sample.mp3",
            uploaded_by=user.id,
            uploaded_at=datetime.now(UTC),
            metadata_json={"subtype": ArtifactSubtype.TVR_AUDIO.value},
            size_bytes=tvr_size_bytes,
        )
        db.add(tvr_artifact)
        await db.flush()

    return case.id, user.id, dedupe_artifact, tvr_artifact


async def _fetch_issues(db, result_id):
    return (
        await db.execute(
            select(LevelIssue).where(LevelIssue.verification_result_id == result_id)
        )
    ).scalars().all()


# ── Scenario 1 — happy path ──
async def test_blank_dedupe_and_tvr_present_passes(db):
    case_id, actor_user_id, _, _ = await _seed_l55_case(
        db, add_dedupe=True, dedupe_row_count=0, add_tvr=True
    )
    result = await run_level_5_5_dedupe_tvr(
        db, case_id, actor_user_id=actor_user_id,
    )
    assert result.status == VerificationLevelStatus.PASSED
    assert result.level_number == VerificationLevelNumber.L5_5_DEDUPE_TVR
    assert result.cost_usd == Decimal("0")
    issues = await _fetch_issues(db, result.id)
    assert issues == []
    # pass_evidence should cite both artefacts
    pe = result.sub_step_results["pass_evidence"]
    assert "dedupe_clear" in pe
    assert "tvr_present" in pe


# ── Scenario 2 — TVR missing ──
async def test_blank_dedupe_and_missing_tvr_blocks_with_critical(db):
    case_id, actor_user_id, _, _ = await _seed_l55_case(
        db, add_dedupe=True, dedupe_row_count=0, add_tvr=False
    )
    result = await run_level_5_5_dedupe_tvr(
        db, case_id, actor_user_id=actor_user_id,
    )
    assert result.status == VerificationLevelStatus.BLOCKED
    issues = await _fetch_issues(db, result.id)
    assert len(issues) == 1
    assert issues[0].sub_step_id == "tvr_present"
    assert issues[0].severity == LevelIssueSeverity.CRITICAL


# ── Scenario 3 — dedupe non-blank ──
async def test_non_blank_dedupe_blocks_with_critical_and_evidence(db):
    case_id, actor_user_id, dedupe_art, _ = await _seed_l55_case(
        db, add_dedupe=True, dedupe_row_count=2, add_tvr=True
    )
    result = await run_level_5_5_dedupe_tvr(
        db, case_id, actor_user_id=actor_user_id,
    )
    assert result.status == VerificationLevelStatus.BLOCKED
    issues = await _fetch_issues(db, result.id)
    assert len(issues) == 1
    iss = issues[0]
    assert iss.sub_step_id == "dedupe_clear"
    assert iss.severity == LevelIssueSeverity.CRITICAL
    assert iss.evidence["row_count"] == 2
    assert len(iss.evidence["matched_rows"]) == 2
    assert iss.evidence["source_artifacts"][0]["artifact_id"] == str(dedupe_art.id)
    # artifact_id on the LevelIssue itself ties to the dedupe artefact
    assert iss.artifact_id == dedupe_art.id


# ── Scenario 4 — both missing ──
async def test_missing_dedupe_and_missing_tvr_blocks_with_two_criticals(db):
    case_id, actor_user_id, _, _ = await _seed_l55_case(
        db, add_dedupe=False, add_tvr=False
    )
    result = await run_level_5_5_dedupe_tvr(
        db, case_id, actor_user_id=actor_user_id,
    )
    assert result.status == VerificationLevelStatus.BLOCKED
    issues = await _fetch_issues(db, result.id)
    sub_step_ids = {i.sub_step_id for i in issues}
    assert sub_step_ids == {"dedupe_clear", "tvr_present"}
    assert all(i.severity == LevelIssueSeverity.CRITICAL for i in issues)
    # Dedupe-missing issue should NOT have an artifact_id
    dedupe_issue = next(i for i in issues if i.sub_step_id == "dedupe_clear")
    assert dedupe_issue.artifact_id is None
    assert dedupe_issue.evidence["expected_subtype"] == ArtifactSubtype.DEDUPE_REPORT.value


# ── Scenario 5 — multiple TVR files ──
async def test_multiple_tvr_files_picks_largest(db):
    """Per the brief: when multiple TVR audio files are present, the
    orchestrator should select the largest one."""
    case_id, actor_user_id, _, _ = await _seed_l55_case(
        db, add_dedupe=True, dedupe_row_count=0, add_tvr=True, tvr_size_bytes=200_000
    )
    # Add a second, larger TVR
    user_id = actor_user_id
    larger_tvr = CaseArtifact(
        case_id=case_id,
        filename="tvr_call2.mp3",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
        s3_key=f"l55/{case_id}/tvr_call2.mp3",
        uploaded_by=user_id,
        uploaded_at=datetime.now(UTC),
        metadata_json={"subtype": ArtifactSubtype.TVR_AUDIO.value},
        size_bytes=900_000,
    )
    db.add(larger_tvr)
    await db.flush()

    result = await run_level_5_5_dedupe_tvr(
        db, case_id, actor_user_id=actor_user_id,
    )
    assert result.status == VerificationLevelStatus.PASSED
    # sub_step_results.tvr.filename should be the larger file
    assert result.sub_step_results["tvr"]["filename"] == "tvr_call2.mp3"
    assert result.sub_step_results["tvr"]["size_bytes"] == 900_000


# ── Scenario 6 — artefact uploaded but extraction not yet run ──
async def test_dedupe_artifact_without_extraction_blocks_with_critical(db):
    """Artefact uploaded but extraction not yet run -> CRITICAL
    (don't silently pass as if row_count == 0)."""
    case_id, actor_user_id, dedupe_art, _ = await _seed_l55_case(
        db, add_dedupe=True, dedupe_row_count=0, add_tvr=True,
    )
    # Manually delete the extraction the seed helper created
    extractions = (await db.execute(
        select(CaseExtraction).where(CaseExtraction.artifact_id == dedupe_art.id)
    )).scalars().all()
    for e in extractions:
        await db.delete(e)
    await db.flush()

    result = await run_level_5_5_dedupe_tvr(
        db, case_id, actor_user_id=actor_user_id,
    )
    assert result.status == VerificationLevelStatus.BLOCKED
    issues = await _fetch_issues(db, result.id)
    assert len(issues) == 1
    iss = issues[0]
    assert iss.sub_step_id == "dedupe_clear"
    assert iss.severity == LevelIssueSeverity.CRITICAL
    assert "not yet parsed" in iss.description.lower() or "pending" in iss.description.lower()


# ── Scenario 7 — extraction ran but FAILED ──
async def test_dedupe_extraction_failed_blocks_with_critical(db):
    """Extraction ran but FAILED status -> CRITICAL (extraction error
    surfaced; not silently passed)."""
    case_id, actor_user_id, dedupe_art, _ = await _seed_l55_case(
        db, add_dedupe=True, dedupe_row_count=0, add_tvr=True,
    )
    # Flip the extraction's status to FAILED with an error message
    extraction = (await db.execute(
        select(CaseExtraction).where(CaseExtraction.artifact_id == dedupe_art.id)
    )).scalars().first()
    extraction.status = ExtractionStatus.FAILED
    extraction.error_message = "openpyxl load failed: BadZipFile"
    extraction.data = {}
    await db.flush()

    result = await run_level_5_5_dedupe_tvr(
        db, case_id, actor_user_id=actor_user_id,
    )
    assert result.status == VerificationLevelStatus.BLOCKED
    issues = await _fetch_issues(db, result.id)
    assert len(issues) == 1
    iss = issues[0]
    assert iss.sub_step_id == "dedupe_clear"
    assert iss.severity == LevelIssueSeverity.CRITICAL
    assert iss.evidence.get("extraction_status") == "FAILED"
