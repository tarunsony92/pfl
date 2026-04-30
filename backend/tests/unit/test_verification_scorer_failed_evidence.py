"""Tests for scorer-failed evidence payloads.

Covers:
- L3 ``house_scorer_failed`` / ``business_scorer_failed`` attach
  ``error_message`` + ``photos_evaluated_count`` + ``source_artifacts``.
- L2 ``ca_analyzer_failed`` attaches ``source_artifacts`` pointing at the
  bank statement PDF.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

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
from app.worker.extractors.base import ExtractionResult


class _StubStorage:
    def __init__(self):
        self.download_object = AsyncMock(
            return_value=b"\xff\xd8\xff\xe0fake_jpeg_bytes"
        )


async def _seed_l3_case(db, house_count=2, biz_count=2):
    user = await users_svc.create_user(
        db,
        email="m6-l3@pfl.com",
        password="Pass123!",
        full_name="M6 L3",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    case = Case(
        loan_id="M6-L3-001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="m6l3/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()
    for i in range(house_count):
        db.add(
            CaseArtifact(
                case_id=case.id,
                filename=f"house_{i}.jpg",
                artifact_type=ArtifactType.ADDITIONAL_FILE,
                s3_key=f"m6l3/{case.id}/house_{i}.jpg",
                uploaded_by=user.id,
                uploaded_at=datetime.now(UTC),
                metadata_json={"subtype": ArtifactSubtype.HOUSE_VISIT_PHOTO.value},
            )
        )
    for i in range(biz_count):
        db.add(
            CaseArtifact(
                case_id=case.id,
                filename=f"biz_{i}.jpg",
                artifact_type=ArtifactType.ADDITIONAL_FILE,
                s3_key=f"m6l3/{case.id}/biz_{i}.jpg",
                uploaded_by=user.id,
                uploaded_at=datetime.now(UTC),
                metadata_json={
                    "subtype": ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value
                },
            )
        )
    await db.flush()
    return case.id, user.id


async def test_house_scorer_failed_carries_evidence(db):
    from app.verification.levels import level_3_vision as l3_mod

    case_id, actor_user_id = await _seed_l3_case(db)

    failing_house = ExtractionResult(
        status=ExtractionStatus.FAILED,
        schema_version="1.0",
        data={"cost_usd": "0.01"},
        error_message="Anthropic API timed out after 60s",
    )
    passing_biz = ExtractionResult(
        status=ExtractionStatus.SUCCESS,
        schema_version="1.0",
        data={
            "business_type": "service",
            "business_subtype": "barbershop",
            "stock_value_estimate_inr": 60_000,
            "visible_equipment_value_inr": 50_000,
            "cattle_count": 0,
            "cattle_health": None,
            "infrastructure_rating": "ok",
            "recommended_loan_amount_inr": 100_000,
            "recommended_loan_rationale": "ok",
            "cost_usd": 0.0,
        },
    )

    class _StubHouse:
        def __init__(self, claude=None): pass
        async def score(self, imgs):
            return failing_house

    class _StubBiz:
        def __init__(self, claude=None): pass
        async def score(self, imgs, *, loan_amount_inr=None):
            return passing_biz

    with (
        patch(
            "app.verification.services.vision_scorers.HousePremisesScorer",
            _StubHouse,
        ),
        patch(
            "app.verification.services.vision_scorers.BusinessPremisesScorer",
            _StubBiz,
        ),
    ):
        result = await l3_mod.run_level_3_vision(
            db,
            case_id,
            actor_user_id=actor_user_id,
            claude=object(),
            storage=_StubStorage(),
        )

    issues = (
        (
            await db.execute(
                select(LevelIssue).where(
                    LevelIssue.verification_result_id == result.id,
                    LevelIssue.sub_step_id == "house_scorer_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 1
    ev = issues[0].evidence or {}
    assert ev.get("error_message") == "Anthropic API timed out after 60s"
    assert ev.get("photos_evaluated_count") == 2
    srcs = ev.get("source_artifacts") or []
    assert len(srcs) == 2
    filenames = {s.get("filename") for s in srcs}
    assert filenames == {"house_0.jpg", "house_1.jpg"}


async def test_business_scorer_failed_carries_evidence(db):
    from app.verification.levels import level_3_vision as l3_mod

    case_id, actor_user_id = await _seed_l3_case(db, house_count=1, biz_count=3)

    passing_house = ExtractionResult(
        status=ExtractionStatus.SUCCESS,
        schema_version="1.0",
        data={"overall_rating": "ok", "cost_usd": 0},
    )
    failing_biz = ExtractionResult(
        status=ExtractionStatus.FAILED,
        schema_version="1.0",
        data={"cost_usd": 0},
        error_message="Claude returned invalid JSON",
    )

    class _StubHouse:
        def __init__(self, claude=None): pass
        async def score(self, imgs):
            return passing_house

    class _StubBiz:
        def __init__(self, claude=None): pass
        async def score(self, imgs, *, loan_amount_inr=None):
            return failing_biz

    with (
        patch(
            "app.verification.services.vision_scorers.HousePremisesScorer",
            _StubHouse,
        ),
        patch(
            "app.verification.services.vision_scorers.BusinessPremisesScorer",
            _StubBiz,
        ),
    ):
        result = await l3_mod.run_level_3_vision(
            db,
            case_id,
            actor_user_id=actor_user_id,
            claude=object(),
            storage=_StubStorage(),
        )

    issues = (
        (
            await db.execute(
                select(LevelIssue).where(
                    LevelIssue.verification_result_id == result.id,
                    LevelIssue.sub_step_id == "business_scorer_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 1
    ev = issues[0].evidence or {}
    assert ev.get("error_message") == "Claude returned invalid JSON"
    assert ev.get("photos_evaluated_count") == 3
    srcs = ev.get("source_artifacts") or []
    assert len(srcs) == 3
    filenames = {s.get("filename") for s in srcs}
    assert filenames == {"biz_0.jpg", "biz_1.jpg", "biz_2.jpg"}


# ─────────── L2 ca_analyzer_failed carries source_artifacts ────────────


async def _seed_l2_case(db):
    user = await users_svc.create_user(
        db,
        email="m6-l2@pfl.com",
        password="Pass123!",
        full_name="M6 L2",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    case = Case(
        loan_id="M6-L2-001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="m6l2/case.zip",
        loan_amount=100_000,
        loan_tenure_months=24,
    )
    db.add(case)
    await db.flush()
    bank_art = CaseArtifact(
        case_id=case.id,
        filename="bank_statement.pdf",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
        s3_key=f"m6l2/{case.id}/bank.pdf",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        metadata_json={"subtype": ArtifactSubtype.BANK_STATEMENT.value},
    )
    db.add(bank_art)
    await db.flush()
    # Seed a bank_statement extraction with tx_lines so the analyzer path
    # runs; the stubbed analyzer will return error_message to force the
    # failure branch.
    ext = CaseExtraction(
        case_id=case.id,
        artifact_id=bank_art.id,
        extractor_name="bank_statement",
        schema_version="1.0",
        status=ExtractionStatus.SUCCESS,
        data={"transaction_lines": ["2024-01-01 CREDIT 10000", "2024-01-02 DEBIT 500"]},
        extracted_at=datetime.now(UTC),
    )
    db.add(ext)
    await db.flush()
    return case.id, user.id, bank_art


async def test_ca_analyzer_failed_cites_bank_statement_source(db):
    from app.verification.levels import level_2_banking as l2_mod

    case_id, actor_user_id, bank_art = await _seed_l2_case(db)

    failing_result = ExtractionResult(
        status=ExtractionStatus.FAILED,
        schema_version="1.0",
        data={"cost_usd": "0"},
        error_message="Anthropic rate limited — retry later",
    )

    class _StubAnalyzer:
        def __init__(self, claude=None): pass
        async def analyze(self, **_kwargs):
            return failing_result

    with patch("app.verification.services.bank_ca_analyzer.BankCaAnalyzer", _StubAnalyzer):
        result = await l2_mod.run_level_2_banking(
            db,
            case_id,
            actor_user_id=actor_user_id,
            claude=object(),
        )

    issues = (
        (
            await db.execute(
                select(LevelIssue).where(
                    LevelIssue.verification_result_id == result.id,
                    LevelIssue.sub_step_id == "ca_analyzer_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 1
    ev = issues[0].evidence or {}
    assert ev.get("error_message") == "Anthropic rate limited — retry later"
    srcs = ev.get("source_artifacts") or []
    assert len(srcs) == 1
    assert srcs[0].get("filename") == "bank_statement.pdf"
    assert srcs[0].get("artifact_id") == str(bank_art.id)
