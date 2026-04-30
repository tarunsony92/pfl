"""End-to-end integration tests for Seema ZIP ingestion.

Uses a real Seema ZIP file to test the complete pipeline. Skipped if ZIP absent.
Tests verify: pipeline completion, extractions, and queue handling.
"""

from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import CaseStage
from app.models.case import Case
from app.models.case_extraction import CaseExtraction
from app.models.checklist_validation_result import ChecklistValidationResult
from app.services import users as users_svc
from app.services.email import EmailService, reset_email_service
from app.services.queue import QueueService, reset_queue_for_tests
from app.services.storage import StorageService, reset_storage_for_tests
from app.worker.pipeline import process_ingestion_job, set_system_worker_user_id
from app.worker.system_user import get_or_create_worker_user

# Skip marker - will skip all tests in this file if ZIP absent
SEEMA_ZIP = Path("/Users/sakshamgupta/Downloads/10006484 Seema Panipat.zip")

pytestmark = pytest.mark.skipif(
    not SEEMA_ZIP.exists(),
    reason="Seema ZIP not present",
)

# Test constants
_SENDER = "no-reply@pflfinance.com"
_REGION = "ap-south-1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession,
    email: str = "seema_uploader@pfl.com",
) -> object:
    """Create a test user for case uploads."""
    user = await users_svc.create_user(
        db,
        email=email,
        password="Pass123!",
        full_name="Seema Uploader",
        role="ai_analyser",
    )
    await db.flush()
    return user


async def _create_case(
    db: AsyncSession,
    storage_svc: StorageService,
    user: object,
    loan_id: str,
    zip_bytes: bytes,
    stage: CaseStage = CaseStage.CHECKLIST_VALIDATION,
) -> Case:
    """Create a case and upload ZIP to storage."""
    from datetime import UTC, datetime

    zip_s3_key = f"cases/seema_test/{loan_id}.zip"
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
    """Ensure system worker user exists and set pipeline global."""
    worker = await get_or_create_worker_user(db)
    await db.flush()
    set_system_worker_user_id(worker.id)
    return worker.id


# ---------------------------------------------------------------------------
# Fixtures (copied from test_pipeline.py pattern)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def storage_svc(mock_aws_services):
    """Storage service with moto S3 backend."""
    reset_storage_for_tests()
    svc = StorageService(
        region=_REGION,
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        bucket="pfl-cases-test",
    )
    await svc.ensure_bucket_exists()
    with patch("app.worker.pipeline.get_storage", return_value=svc):
        yield svc
    reset_storage_for_tests()


@pytest_asyncio.fixture
async def queue_svc(mock_aws_services):
    """Queue service with moto SQS backend."""
    reset_queue_for_tests()
    svc = QueueService(
        region=_REGION,
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        queue_name="pfl-ingestion-test",
        dlq_name="pfl-ingestion-dlq-test",
    )
    await svc.ensure_queues_exist()
    with patch("app.worker.pipeline.get_queue", return_value=svc):
        yield svc
    reset_queue_for_tests()


@pytest_asyncio.fixture
async def email_svc(mock_aws_services):
    """Email service with moto SES backend."""
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
    """Patch AsyncSessionLocal to use test db session for pipeline."""

    class _FakeCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    with patch("app.worker.pipeline.AsyncSessionLocal", return_value=_FakeCtx()):
        yield db


# ---------------------------------------------------------------------------
# Test 1: Full pipeline to terminal stage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seema_ingestion_end_to_end_runs_pipeline_to_terminal_stage(
    pipeline_session: AsyncSession, storage_svc, email_svc, queue_svc
):
    """ZIP through full pipeline; stage is INGESTED or CHECKLIST_MISSING_DOCS."""
    db = pipeline_session
    user = await _make_user(db, "seema_e2e@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = SEEMA_ZIP.read_bytes()
    case = await _create_case(db, storage_svc, user, "10006484", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Refresh and verify stage
    await db.refresh(case)
    assert case.current_stage in (CaseStage.INGESTED, CaseStage.CHECKLIST_MISSING_DOCS)


# ---------------------------------------------------------------------------
# Test 2: Auto_CAM extraction has known values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seema_auto_cam_extraction_has_known_values(
    pipeline_session: AsyncSession, storage_svc, email_svc, queue_svc
):
    """Auto_CAM extraction for Seema contains expected values."""
    db = pipeline_session
    user = await _make_user(db, "seema_autocam@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = SEEMA_ZIP.read_bytes()
    case = await _create_case(db, storage_svc, user, "10006484", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Query auto_cam extraction
    extr_result = await db.execute(
        select(CaseExtraction).where(
            CaseExtraction.case_id == case.id,
            CaseExtraction.extractor_name == "auto_cam",
        )
    )
    extraction = extr_result.scalar_one_or_none()
    assert extraction is not None, "auto_cam extraction not found"

    # Extract values from read_model (Pydantic model)
    data = extraction.read_model
    assert data is not None

    # applicant_name contains "SEEMA" (case-insensitive)
    applicant_name = data.applicant_name or ""
    assert "seema" in applicant_name.lower(), f"Expected 'seema' in {applicant_name}"

    # CIBIL score is an integer in expected range
    cibil_score = data.cibil_score
    assert isinstance(cibil_score, int), f"Expected int, got {type(cibil_score)}"
    assert 700 <= cibil_score <= 850, f"CIBIL score {cibil_score} outside range"

    # Loan amount is 150000 or close
    loan_amount = data.loan_amount
    assert isinstance(loan_amount, int | float), f"Expected numeric, got {type(loan_amount)}"
    # Allow ±10% tolerance
    assert 135000 <= loan_amount <= 165000, f"Loan amount {loan_amount} outside range"


# ---------------------------------------------------------------------------
# Test 3: Equifax extraction has credit score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seema_equifax_extraction_has_credit_score(
    pipeline_session: AsyncSession, storage_svc, email_svc, queue_svc
):
    """Equifax extraction present with positive credit_score."""
    db = pipeline_session
    user = await _make_user(db, "seema_equifax@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = SEEMA_ZIP.read_bytes()
    case = await _create_case(db, storage_svc, user, "10006484", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Query equifax extraction
    extr_result = await db.execute(
        select(CaseExtraction).where(
            CaseExtraction.case_id == case.id,
            CaseExtraction.extractor_name == "equifax",
        )
    )
    extraction = extr_result.scalar_one_or_none()
    assert extraction is not None, "equifax extraction not found"

    # Extract credit_score from read_model
    data = extraction.read_model
    assert data is not None
    credit_score = data.credit_score
    assert isinstance(credit_score, int), f"Expected int, got {type(credit_score)}"
    assert credit_score > 0, f"Expected positive credit_score, got {credit_score}"


# ---------------------------------------------------------------------------
# Test 4: PD Sheet extraction has applicant fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seema_pd_sheet_extraction_has_applicant_fields(
    pipeline_session: AsyncSession, storage_svc, email_svc, queue_svc
):
    """PD Sheet extraction present with non-empty fields dict."""
    db = pipeline_session
    user = await _make_user(db, "seema_pdsheet@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = SEEMA_ZIP.read_bytes()
    case = await _create_case(db, storage_svc, user, "10006484", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Query pd_sheet extraction
    extr_result = await db.execute(
        select(CaseExtraction).where(
            CaseExtraction.case_id == case.id,
            CaseExtraction.extractor_name == "pd_sheet",
        )
    )
    extraction = extr_result.scalar_one_or_none()
    assert extraction is not None, "pd_sheet extraction not found"

    # Extract fields from read_model
    data = extraction.read_model
    assert data is not None
    fields = data.fields or {}
    assert isinstance(fields, dict), f"Expected dict, got {type(fields)}"
    assert len(fields) > 0, "Expected non-empty fields dict"


# ---------------------------------------------------------------------------
# Test 5: Checklist validation produces result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seema_checklist_validation_produces_result(
    pipeline_session: AsyncSession, storage_svc, email_svc, queue_svc
):
    """ChecklistValidationResult row exists with doc lists."""
    db = pipeline_session
    user = await _make_user(db, "seema_checklist@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = SEEMA_ZIP.read_bytes()
    case = await _create_case(db, storage_svc, user, "10006484", zip_bytes)

    await process_ingestion_job({"case_id": str(case.id), "trigger": "finalize"})

    # Query ChecklistValidationResult
    cvr_result = await db.execute(
        select(ChecklistValidationResult).where(ChecklistValidationResult.case_id == case.id)
    )
    result = cvr_result.scalar_one_or_none()
    assert result is not None, "ChecklistValidationResult not found"

    # Verify doc lists exist
    assert result.present_docs is not None
    assert result.missing_docs is not None
    assert isinstance(result.present_docs, list)
    assert isinstance(result.missing_docs, list)


# ---------------------------------------------------------------------------
# Test 6: Queue message deleted after successful processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seema_queue_message_deleted_after_successful_processing(
    pipeline_session: AsyncSession, storage_svc, queue_svc, email_svc
):
    """SQS message consumed is deleted after handler succeeds."""
    db = pipeline_session
    user = await _make_user(db, "seema_queue@pfl.com")
    await _setup_worker_user(db)
    zip_bytes = SEEMA_ZIP.read_bytes()
    case = await _create_case(db, storage_svc, user, "10006484", zip_bytes)

    # Publish a job to the queue
    await queue_svc.publish_job({"case_id": str(case.id), "trigger": "finalize"})

    # Verify message is enqueued
    msgs_before = await queue_svc.peek_messages()
    assert len(msgs_before) == 1, "Expected 1 message before processing"

    # Consume and process using the queue's handler
    async def handler(payload: dict) -> None:
        await process_ingestion_job(payload)

    await queue_svc.consume_jobs(handler, max_messages=1, wait_seconds=1)

    # Verify message was deleted (queue is now empty)
    msgs_after = await queue_svc.peek_messages()
    assert len(msgs_after) == 0, "Expected queue to be empty after successful processing"
