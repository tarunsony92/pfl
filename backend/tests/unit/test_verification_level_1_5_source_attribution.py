"""Test L1.5 attributes bureau source_artifacts by party, not by
artifact-list position.

If the co-applicant's Equifax HTML is uploaded *first* (lower
``created_at``), the old ``bureau_arts[0]`` / ``bureau_arts[1]``
positional pick would have cited the co-app's file for an applicant-side
issue. Now we pick by ``CaseExtraction.artifact_id`` so the attribution
tracks the party the extraction was picked for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select

from app.enums import (
    ArtifactSubtype,
    ArtifactType,
    ExtractionStatus,
    LevelIssueStatus,
    UserRole,
    VerificationLevelNumber,
)
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.level_issue import LevelIssue
from app.services import users as users_svc
from app.verification.levels.level_1_5_credit import run_level_1_5_credit


class _StubAnalyst:
    """Stand-in for ``CreditAnalyst`` — avoids hitting Claude."""

    def __init__(self, *, claude=None):
        self.claude = claude

    async def analyse(self, **_kwargs):
        class _R:
            data = {"applicant": {}, "co_applicant": {}, "cost_usd": "0"}
            error_message = None
        return _R()


class _StubClaude:
    pass


async def _mk_bureau_art(db, case_id, uploader_id, *, filename, created_at):
    art = CaseArtifact(
        case_id=case_id,
        filename=filename,
        artifact_type=ArtifactType.ADDITIONAL_FILE,
        s3_key=f"bureau/{case_id}/{filename}",
        uploaded_by=uploader_id,
        uploaded_at=created_at,
        metadata_json={"subtype": ArtifactSubtype.EQUIFAX_HTML.value},
    )
    db.add(art)
    await db.flush()
    # Force created_at so ordering is deterministic regardless of
    # microsecond resolution.
    art.created_at = created_at
    await db.flush()
    return art


async def _mk_equifax_extraction(db, case_id, artifact_id, *, name, score, write_off=False):
    accounts = []
    if write_off:
        accounts.append(
            {"status": "Write-Off", "institution": "TestBank", "date_opened": "01-01-2020"}
        )
    data = {
        "bureau_hit": True,
        "credit_score": score,
        "customer_info": {"name": name},
        "accounts": accounts,
        "summary": {},
    }
    row = CaseExtraction(
        case_id=case_id,
        artifact_id=artifact_id,
        extractor_name="equifax",
        schema_version="1.0",
        status=ExtractionStatus.SUCCESS,
        data=data,
        extracted_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    return row


@pytest_asyncio.fixture
async def _seeded_case_swapped_order(db, monkeypatch):
    """Co-applicant bureau uploaded FIRST, applicant bureau uploaded SECOND.

    A positional pick would cite the co-app's artifact for applicant-side
    issues; the by-party pick must cite the correct one.
    """
    # Stub the CreditAnalyst import inside the orchestrator so the test
    # never touches Claude.
    import app.verification.levels.level_1_5_credit as l15_mod
    import app.verification.services.credit_analyst as analyst_mod

    monkeypatch.setattr(analyst_mod, "CreditAnalyst", _StubAnalyst)

    actor = await users_svc.create_user(
        db,
        email="m5-actor@pfl.com",
        password="Pass123!",
        full_name="M5 Actor",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    case = Case(
        loan_id="M5-BUREAU-001",
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="m5/case.zip",
        loan_amount=100_000,
        applicant_name="Ramesh Kumar",
        co_applicant_name="Savita Kumari",
    )
    db.add(case)
    await db.flush()

    earlier = datetime.now(UTC) - timedelta(minutes=10)
    later = datetime.now(UTC)

    # Uploaded first
    coapp_art = await _mk_bureau_art(
        db, case.id, actor.id, filename="coapp_equifax.html", created_at=earlier
    )
    # Uploaded second
    applicant_art = await _mk_bureau_art(
        db, case.id, actor.id, filename="applicant_equifax.html", created_at=later
    )

    # Extractions — applicant extraction cites applicant_art, etc.
    # Write-off on applicant so a CRITICAL issue is emitted and we can
    # inspect source_artifacts.
    await _mk_equifax_extraction(
        db, case.id, applicant_art.id,
        name="Ramesh Kumar", score=750, write_off=True,
    )
    await _mk_equifax_extraction(
        db, case.id, coapp_art.id,
        name="Savita Kumari", score=730, write_off=False,
    )

    return case, actor, applicant_art, coapp_art


async def test_bureau_source_artifacts_picked_by_party_not_position(
    db, _seeded_case_swapped_order
):
    case, actor, applicant_art, coapp_art = _seeded_case_swapped_order
    vr = await run_level_1_5_credit(
        db,
        case.id,
        actor_user_id=actor.id,
        claude=_StubClaude(),
    )
    # Fetch the applicant's write-off issue
    issues = (
        (
            await db.execute(
                select(LevelIssue).where(
                    LevelIssue.verification_result_id == vr.id,
                    LevelIssue.sub_step_id == "credit_write_off",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 1, (
        f"Expected one applicant write-off issue; got {len(issues)}"
    )
    iss = issues[0]
    sources = (iss.evidence or {}).get("source_artifacts") or []
    cited_ids = {s.get("artifact_id") for s in sources}
    assert str(applicant_art.id) in cited_ids, (
        "Applicant-side issue must cite applicant's Equifax artifact, "
        f"got {cited_ids}"
    )
    assert str(coapp_art.id) not in cited_ids, (
        "Applicant-side issue must NOT cite co-applicant's Equifax "
        f"(position-0 mis-attribution), got {cited_ids}"
    )
