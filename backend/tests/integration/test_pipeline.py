"""Integration tests for the worker pipeline orchestrator.

Exercises the full ingestion pipeline (T11) against moto S3 + Postgres.
Each test creates a case, uploads the appropriate ZIP, and directly invokes
`process_ingestion_job` to avoid queue setup overhead.

Fixture ZIP is assembled by `build_case_zip` from T5 fixture builders.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import pytest
import pytest_asyncio
from moto.backends import get_backend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ArtifactSubtype, CaseStage, ExtractionStatus
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.checklist_validation_result import ChecklistValidationResult
from app.models.dedupe_match import DedupeMatch
from app.models.dedupe_snapshot import DedupeSnapshot
from app.models.user import User
from app.services import users as users_svc
from app.services.email import EmailService, reset_email_service
from app.worker.pipeline import (
    process_ingestion_job,
    set_system_worker_user_id,
)
from app.worker.system_user import get_or_create_worker_user
from tests.fixtures.builders.case_zip_builder import build_case_zip

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENDER = "no-reply@pflfinance.com"
_REGION = "ap-south-1"


def _ses_backend():
    """Return the moto SES backend for the test region."""
    ses_b = get_backend("ses")
    for _account, region, backend in ses_b.iter_backends():
        if region == _REGION:
            return backend
    raise RuntimeError(f"No moto SES backend for region {_REGION}")


async def _make_user(
    db: AsyncSession,
    email: str = "uploader@pfl.com",
) -> User:
    user = await users_svc.create_user(
        db,
        email=email,
        password="Pass123!",
        full_name="Test User",
        role="ai_analyser",
    )
    await db.flush()
    return user


def _build_zip_bytes(**kwargs: object) -> bytes:
    """Build a full case ZIP using the fixture builder. Returns raw bytes."""
    with TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "case.zip"
        build_case_zip(zip_path, **kwargs)
        return zip_path.read_bytes()


def _build_minimal_zip(filename: str = "random.txt", content: bytes = b"hello world") -> bytes:
    """Build a minimal ZIP with a single file for subtype=UNKNOWN tests."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return buf.getvalue()


def _build_missing_docs_zip() -> bytes:
    """Build a ZIP that has only a PD sheet (so checklist is incomplete)."""
    from tests.fixtures.builders.pd_sheet_builder import build_pd_sheet_docx

    with TemporaryDirectory() as tmpdir:
        pd_path = Path(tmpdir) / "PD_Sheet.docx"
        build_pd_sheet_docx(pd_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.write(pd_path, "OTH/PD_Sheet.docx")
        return buf.getvalue()


async def _create_case(
    db: AsyncSession,
    storage_svc: object,
    user: User,
    loan_id: str,
    zip_bytes: bytes,
    *,
    stage: CaseStage = CaseStage.CHECKLIST_VALIDATION,
) -> Case:
    """Create a case + upload ZIP to storage, skip queue."""
    zip_s3_key = f"cases/test/{loan_id}.zip"
    await storage_svc.upload_object(zip_s3_key, zip_bytes)

    case = Case(
        loan_id=loan_id,
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key=zip_s3_key,
        zip_size_bytes=len(zip_bytes),
        current_stage=stage,
    )
    db.add(case)
    await db.flush()
    return case


async def _setup_worker_user(db: AsyncSession) -> UUID:
    """Ensure system worker user exists, set pipeline global, return ID."""
    worker = await get_or_create_worker_user(db)
    await db.flush()
    set_system_worker_user_id(worker.id)
    return worker.id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def storage_svc(mock_aws_services):
    from app.services.storage import StorageService, reset_storage_for_tests

    reset_storage_for_tests()
    svc = StorageService(
        region=_REGION,
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        bucket="pfl-cases-test",
    )
    await svc.ensure_bucket_exists()
    # Patch the global storage singleton so pipeline.py uses this instance
    with patch("app.worker.pipeline.get_storage", return_value=svc):
        yield svc
    reset_storage_for_tests()


@pytest_asyncio.fixture
async def email_svc(mock_aws_services):
    """SES-backed email service using moto; resets singleton on teardown."""
    reset_email_service()
    svc = EmailService(
        region=_REGION,
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        sender=_SENDER,
    )
    await svc.verify_sender_identity()
    with patch("app.worker.pipeline.get_email_service", return_value=svc):
        yield svc
    reset_email_service()


@pytest_asyncio.fixture
async def pipeline_session(db: AsyncSession, storage_svc):
    """Patch AsyncSessionLocal in pipeline to use the test db session.

    The pipeline opens its own AsyncSessionLocal() inside process_ingestion_job.
    We need to route that to our test transaction so assertions see the rows.
    """

    # Create a context manager that yields our test `db` session
    class _FakeCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            # Don't commit or close the test session
            pass

    with patch("app.worker.pipeline.AsyncSessionLocal", return_value=_FakeCtx()):
        yield db


# ---------------------------------------------------------------------------
# Test 1: Happy path — zip with most docs; pipeline completes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_happy_path_artifacts_and_extractions(
    pipeline_session: AsyncSession, storage_svc, email_svc
):
    """Full ZIP through pipeline — CaseArtifact rows + CaseExtraction rows created."""
    db = pipeline_session
    user = await _make_user(db, "happy@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = _build_zip_bytes(loan_id="HAPPY001")
    case = await _create_case(db, storage_svc, user, "HAPPY001", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Re-query artifacts
    arts_result = await db.execute(select(CaseArtifact).where(CaseArtifact.case_id == case.id))
    artifacts = list(arts_result.scalars().all())
    # build_case_zip creates: auto_cam, checklist, pd_sheet, equifax, bank_stmt,
    # 2 aadhaar, 3 bp, 3 hv = 13 files
    assert len(artifacts) >= 10, f"Expected >=10 artifacts, got {len(artifacts)}"

    # Verify extractors ran
    extractions_result = await db.execute(
        select(CaseExtraction).where(CaseExtraction.case_id == case.id)
    )
    extractions = list(extractions_result.scalars().all())
    extractor_names = {e.extractor_name for e in extractions}
    # auto_cam, checklist, pd_sheet, equifax, bank_statement, dedupe
    assert "auto_cam" in extractor_names
    assert "checklist" in extractor_names
    assert "pd_sheet" in extractor_names
    assert "equifax" in extractor_names
    assert "bank_statement" in extractor_names
    assert "dedupe" in extractor_names

    # ChecklistValidationResult should exist
    cvr_result = await db.execute(
        select(ChecklistValidationResult).where(ChecklistValidationResult.case_id == case.id)
    )
    cvr = cvr_result.scalar_one_or_none()
    assert cvr is not None

    # Verify the pipeline actually transitioned the case's stage at the end.
    # The fixture ZIP is intentionally incomplete (missing KYC_PAN / KYC_VIDEO /
    # CO_APPLICANT docs), so the expected terminal stage is tied to cvr.is_complete:
    #   complete  → INGESTED (two-step: VALIDATION → VALIDATED → INGESTED)
    #   incomplete → CHECKLIST_MISSING_DOCS
    await db.refresh(case)
    if cvr.is_complete:
        assert case.current_stage == CaseStage.INGESTED
    else:
        assert case.current_stage == CaseStage.CHECKLIST_MISSING_DOCS


# ---------------------------------------------------------------------------
# Test 2: Missing docs → CHECKLIST_MISSING_DOCS + email sent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_missing_docs_sends_email_and_transitions(
    pipeline_session: AsyncSession, storage_svc, email_svc
):
    """Incomplete ZIP → stage=CHECKLIST_MISSING_DOCS; email sent to uploader."""
    db = pipeline_session
    user = await _make_user(db, "missing@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = _build_missing_docs_zip()
    case = await _create_case(db, storage_svc, user, "MISS001", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Refresh case state
    await db.refresh(case)
    assert case.current_stage == CaseStage.CHECKLIST_MISSING_DOCS

    # ChecklistValidationResult should exist with is_complete=False
    cvr_result = await db.execute(
        select(ChecklistValidationResult).where(ChecklistValidationResult.case_id == case.id)
    )
    cvr = cvr_result.scalar_one_or_none()
    assert cvr is not None
    assert cvr.is_complete is False
    assert len(cvr.missing_docs) > 0

    # Email should have been sent
    backend = _ses_backend()
    assert backend.sent_message_count >= 1


# ---------------------------------------------------------------------------
# Test 3: Idempotent on retry — no duplicate artifacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_is_idempotent_on_retry(
    pipeline_session: AsyncSession, storage_svc, email_svc
):
    """Running pipeline twice on same case produces no duplicate CaseArtifact rows."""
    db = pipeline_session
    user = await _make_user(db, "idempotent@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = _build_zip_bytes(loan_id="IDEM001")
    case = await _create_case(db, storage_svc, user, "IDEM001", zip_bytes)

    payload = {"case_id": str(case.id), "trigger": "finalize"}
    await process_ingestion_job(payload)

    # Count artifacts after first run
    arts_result = await db.execute(select(CaseArtifact).where(CaseArtifact.case_id == case.id))
    count_first = len(list(arts_result.scalars().all()))
    assert count_first > 0

    # Second run: case stage must be re-set to a re-ingest-allowed stage
    await db.refresh(case)
    # If case moved to CHECKLIST_MISSING_DOCS, the pre-flight will re-transition it
    # Just re-run with trigger=reingest
    await process_ingestion_job({"case_id": str(case.id), "trigger": "reingest"})

    arts_result2 = await db.execute(select(CaseArtifact).where(CaseArtifact.case_id == case.id))
    count_second = len(list(arts_result2.scalars().all()))
    assert (
        count_second == count_first
    ), f"Expected same count after retry: first={count_first} second={count_second}"


# ---------------------------------------------------------------------------
# Test 4: Re-ingestion clears dedupe matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_reingestion_clears_dedupe_matches(
    pipeline_session: AsyncSession, storage_svc, email_svc
):
    """Stale DedupeMatch rows are cleared before re-ingestion."""
    db = pipeline_session
    user = await _make_user(db, "reingest@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = _build_zip_bytes(loan_id="REIN001")

    # Create case at INGESTED stage (simulates re-ingestion)
    case = await _create_case(db, storage_svc, user, "REIN001", zip_bytes, stage=CaseStage.INGESTED)

    # Insert a stale DedupeSnapshot + DedupeMatch
    snap = DedupeSnapshot(
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        s3_key="dedupe/old_snapshot.xlsx",
        row_count=0,
        is_active=False,  # inactive, so pipeline finds no active snapshot
    )
    db.add(snap)
    await db.flush()

    stale_match = DedupeMatch(
        case_id=case.id,
        snapshot_id=snap.id,
        match_type="AADHAAR",
        match_score=1.0,
        matched_customer_id="CUST001",
        matched_details_json={"source": "applicant"},
    )
    db.add(stale_match)
    await db.flush()

    # Verify stale match exists
    dm_result = await db.execute(select(DedupeMatch).where(DedupeMatch.case_id == case.id))
    assert len(list(dm_result.scalars().all())) == 1

    # Run pipeline
    await process_ingestion_job({"case_id": str(case.id), "trigger": "reingest"})

    # Stale match should be gone (no active snapshot → no new matches)
    dm_result2 = await db.execute(select(DedupeMatch).where(DedupeMatch.case_id == case.id))
    assert len(list(dm_result2.scalars().all())) == 0

    # Stage should have transitioned from INGESTED through pipeline
    await db.refresh(case)
    assert case.current_stage in {
        CaseStage.CHECKLIST_VALIDATED,
        CaseStage.INGESTED,
        CaseStage.CHECKLIST_MISSING_DOCS,
    }


# ---------------------------------------------------------------------------
# Test 5: Skips soft-deleted case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_skips_deleted_case(pipeline_session: AsyncSession, storage_svc, email_svc):
    """Soft-deleted case is skipped — no artifacts created."""
    db = pipeline_session
    user = await _make_user(db, "deleted@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = _build_zip_bytes(loan_id="DEL001")
    case = await _create_case(db, storage_svc, user, "DEL001", zip_bytes)

    # Soft-delete the case
    case.is_deleted = True
    await db.flush()

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # No artifacts should have been created
    arts_result = await db.execute(select(CaseArtifact).where(CaseArtifact.case_id == case.id))
    assert len(list(arts_result.scalars().all())) == 0

    # Stage should not have changed
    await db.refresh(case)
    assert case.current_stage == CaseStage.CHECKLIST_VALIDATION
    assert case.is_deleted is True


# ---------------------------------------------------------------------------
# Test 6: Unknown artifact stored but not extracted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_unknown_artifact_stored_not_extracted(
    pipeline_session: AsyncSession, storage_svc, email_svc
):
    """ZIP with random.txt → artifact created with subtype=UNKNOWN; no extraction."""
    db = pipeline_session
    user = await _make_user(db, "unknown@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = _build_minimal_zip("random.txt", b"some random content")
    case = await _create_case(db, storage_svc, user, "UNK001", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Artifact should exist with subtype=UNKNOWN
    arts_result = await db.execute(select(CaseArtifact).where(CaseArtifact.case_id == case.id))
    artifacts = list(arts_result.scalars().all())
    assert len(artifacts) == 1
    assert artifacts[0].metadata_json is not None
    assert artifacts[0].metadata_json["subtype"] == ArtifactSubtype.UNKNOWN.value

    # No artifact-bound CaseExtraction should exist (no extractor for UNKNOWN)
    extr_result = await db.execute(
        select(CaseExtraction).where(
            CaseExtraction.case_id == case.id,
            CaseExtraction.artifact_id == artifacts[0].id,
        )
    )
    artifact_extractions = list(extr_result.scalars().all())
    assert len(artifact_extractions) == 0


# ---------------------------------------------------------------------------
# Test 7: No active dedupe snapshot → dedupe CaseExtraction has warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_no_active_snapshot_sets_dedupe_warning(
    pipeline_session: AsyncSession, storage_svc, email_svc
):
    """When no active dedupe snapshot exists, dedupe extraction has warnings."""
    db = pipeline_session
    user = await _make_user(db, "nodedupe@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = _build_minimal_zip("random.txt")
    case = await _create_case(db, storage_svc, user, "NOSNAP001", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Dedupe extraction should exist and have warnings
    extr_result = await db.execute(
        select(CaseExtraction).where(
            CaseExtraction.case_id == case.id,
            CaseExtraction.extractor_name == "dedupe",
        )
    )
    dedupe_extraction = extr_result.scalar_one_or_none()
    assert dedupe_extraction is not None
    assert dedupe_extraction.warnings is not None
    assert "no_active_snapshot" in dedupe_extraction.warnings
    assert dedupe_extraction.status == ExtractionStatus.PARTIAL


# ---------------------------------------------------------------------------
# Test 8: Non-existent case_id is safely skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_nonexistent_case_is_skipped(
    pipeline_session: AsyncSession, storage_svc, email_svc
):
    """Passing a non-existent case_id logs warning and returns without error."""
    db = pipeline_session
    await _setup_worker_user(db)

    fake_case_id = "00000000-0000-0000-0000-000000000001"

    # Should not raise
    await process_ingestion_job({"case_id": fake_case_id, "trigger": "finalize"})

    # No artifacts created
    arts_result = await db.execute(
        select(CaseArtifact).where(CaseArtifact.case_id == UUID(fake_case_id))
    )
    assert len(list(arts_result.scalars().all())) == 0
