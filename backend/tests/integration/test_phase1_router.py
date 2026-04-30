"""Integration tests for Phase 1 decisioning endpoints (T18).

Tests cover:
- POST /cases/{id}/phase1  (happy path, permission, precondition)
- GET  /cases/{id}/phase1
- GET  /cases/{id}/phase1/steps
- GET  /cases/{id}/phase1/steps/{step_number}
- POST /cases/{id}/phase1/cancel
"""

import json
import uuid

import pytest
import pytest_asyncio

from app.core.security import create_access_token
from app.enums import CaseStage, DecisionStatus, UserRole
from app.models.case import Case
from app.models.decision_result import DecisionResult
from app.models.decision_step import DecisionStep
from app.services import users as users_svc
from app.services.queue import QueueService, reset_queue_for_tests
from app.services.storage import StorageService, reset_storage_for_tests


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_storage_for_tests()
    reset_queue_for_tests()
    yield
    reset_storage_for_tests()
    reset_queue_for_tests()


@pytest_asyncio.fixture
async def initialized_storage(mock_aws_services):
    import app.services.storage as _st_mod

    storage = StorageService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        bucket="pfl-cases-dev",
    )
    await storage.ensure_bucket_exists()
    _st_mod._instance = storage
    yield storage
    reset_storage_for_tests()


@pytest_asyncio.fixture
async def initialized_queues(mock_aws_services):
    """Set up both ingestion + decisioning queue singletons."""
    import app.services.queue as _q_mod

    ingestion_q = QueueService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        queue_name="pfl-ingestion-dev",
        dlq_name="pfl-ingestion-dev-dlq",
    )
    await ingestion_q.ensure_queues_exist()
    _q_mod._instance = ingestion_q

    decisioning_q = QueueService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        queue_name="pfl-decisioning-jobs",
        dlq_name="pfl-decisioning-dlq",
    )
    await decisioning_q.ensure_queues_exist()
    _q_mod._decisioning_instance = decisioning_q

    yield ingestion_q, decisioning_q
    reset_queue_for_tests()


async def _token_for(db, email: str, role: UserRole) -> tuple[str, str]:
    user = await users_svc.create_user(
        db, email=email, password="Pass123!", full_name="T", role=role
    )
    await db.commit()
    return str(user.id), create_access_token(subject=str(user.id))


async def _create_ingested_case(client, db, storage, analyser_tok: str, loan_id: str) -> str:
    """Helper: initiate + finalize + force INGESTED stage."""
    hdrs = {"Authorization": f"Bearer {analyser_tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": loan_id})
    assert r.status_code == 201
    case_id = r.json()["case_id"]
    upload_key = r.json()["upload_key"]
    await storage.upload_object(upload_key, b"zipdata")

    # Finalize moves to CHECKLIST_VALIDATION; we force INGESTED
    await client.post(f"/cases/{case_id}/finalize", headers=hdrs)
    case = await db.get(Case, case_id)
    case.current_stage = CaseStage.INGESTED
    await db.commit()
    return case_id


# ---------------------------------------------------------------------------
# POST /cases/{id}/phase1 — happy path
# ---------------------------------------------------------------------------

async def test_start_phase1_happy_path_202(client, db, initialized_storage, initialized_queues):
    """Admin can start Phase 1 on an INGESTED case → 202 + decision_result_id."""
    _, admin_tok = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)

    _, decisioning_q = initialized_queues
    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-HAPPY-001"
    )

    r = await client.post(
        f"/cases/{case_id}/phase1",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 202
    body = r.json()
    assert "decision_result_id" in body

    # Verify a DecisionResult row was created
    dr_id = body["decision_result_id"]
    dr = await db.get(DecisionResult, dr_id)
    assert dr is not None
    assert dr.status == DecisionStatus.PENDING
    assert dr.phase == "phase1"
    assert str(dr.case_id) == case_id

    # Verify case transitioned to PHASE_1_DECISIONING
    case = await db.get(Case, case_id)
    await db.refresh(case)
    assert case.current_stage == CaseStage.PHASE_1_DECISIONING

    # Verify SQS message was published
    messages = await decisioning_q.peek_messages()
    assert len(messages) >= 1
    msg_body = json.loads(messages[-1]["Body"])
    assert msg_body["decision_result_id"] == dr_id


# ---------------------------------------------------------------------------
# POST /cases/{id}/phase1 — permission checks
# ---------------------------------------------------------------------------

async def test_start_phase1_underwriter_forbidden(client, db, initialized_storage, initialized_queues):
    """Underwriter cannot start Phase 1."""
    _, uw_tok = await _token_for(db, "uw@pfl.com", UserRole.UNDERWRITER)
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)

    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-PERM-001"
    )
    r = await client.post(
        f"/cases/{case_id}/phase1",
        headers={"Authorization": f"Bearer {uw_tok}"},
    )
    assert r.status_code == 403


async def test_start_phase1_ai_analyser_allowed(client, db, initialized_storage, initialized_queues):
    """AI Analyser can also trigger Phase 1."""
    _, analyser_tok = await _token_for(db, "a2@pfl.com", UserRole.AI_ANALYSER)

    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-AI-001"
    )
    r = await client.post(
        f"/cases/{case_id}/phase1",
        headers={"Authorization": f"Bearer {analyser_tok}"},
    )
    assert r.status_code == 202


# ---------------------------------------------------------------------------
# POST /cases/{id}/phase1 — precondition: must be INGESTED
# ---------------------------------------------------------------------------

async def test_start_phase1_wrong_stage_409(client, db, initialized_storage, initialized_queues):
    """Starting Phase 1 on a non-INGESTED case returns 409."""
    _, admin_tok = await _token_for(db, "admin2@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a3@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}
    hdrs_analyser = {"Authorization": f"Bearer {analyser_tok}"}

    # Case starts in UPLOADED stage after initiate
    r = await client.post(
        "/cases/initiate", headers=hdrs_analyser, json={"loan_id": "PH1-STAGE-001"}
    )
    case_id = r.json()["case_id"]

    r2 = await client.post(f"/cases/{case_id}/phase1", headers=hdrs_admin)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# POST /cases/{id}/phase1 — 404 for non-existent case
# ---------------------------------------------------------------------------

async def test_start_phase1_404_for_missing_case(client, db, initialized_queues):
    """Non-existent case returns 404."""
    _, admin_tok = await _token_for(db, "admin3@pfl.com", UserRole.ADMIN)
    missing_id = str(uuid.uuid4())
    r = await client.post(
        f"/cases/{missing_id}/phase1",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /cases/{id}/phase1 — fetch latest result
# ---------------------------------------------------------------------------

async def test_get_phase1_returns_decision_result(client, db, initialized_storage, initialized_queues):
    """GET /phase1 returns the latest DecisionResult."""
    _, admin_tok = await _token_for(db, "admin4@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a4@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}

    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-GET-001"
    )
    r = await client.post(f"/cases/{case_id}/phase1", headers=hdrs_admin)
    dr_id = r.json()["decision_result_id"]

    r2 = await client.get(f"/cases/{case_id}/phase1", headers=hdrs_admin)
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == dr_id
    assert body["case_id"] == case_id
    assert body["status"] == "PENDING"
    assert body["phase"] == "phase1"


async def test_get_phase1_404_when_none(client, db, initialized_storage, initialized_queues):
    """GET /phase1 returns 404 when no decisioning has been started."""
    _, admin_tok = await _token_for(db, "admin5@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a5@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}

    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-NODR-001"
    )
    r = await client.get(f"/cases/{case_id}/phase1", headers=hdrs_admin)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /cases/{id}/phase1/steps + specific step
# ---------------------------------------------------------------------------

async def test_list_phase1_steps_empty_when_no_steps(client, db, initialized_storage, initialized_queues):
    """GET /phase1/steps returns empty list when no steps have run yet."""
    _, admin_tok = await _token_for(db, "admin6@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a6@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}

    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-STEPS-001"
    )
    await client.post(f"/cases/{case_id}/phase1", headers=hdrs_admin)

    r = await client.get(f"/cases/{case_id}/phase1/steps", headers=hdrs_admin)
    assert r.status_code == 200
    assert r.json() == []


async def test_get_specific_step_404_when_missing(client, db, initialized_storage, initialized_queues):
    """GET /phase1/steps/5 returns 404 when step hasn't run."""
    _, admin_tok = await _token_for(db, "admin7@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a7@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}

    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-STEP5-001"
    )
    await client.post(f"/cases/{case_id}/phase1", headers=hdrs_admin)

    r = await client.get(f"/cases/{case_id}/phase1/steps/5", headers=hdrs_admin)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /cases/{id}/phase1/cancel
# ---------------------------------------------------------------------------

async def test_cancel_phase1_happy_path(client, db, initialized_storage, initialized_queues):
    """Admin can cancel a PENDING decisioning run → case rolls back to INGESTED."""
    _, admin_tok = await _token_for(db, "admin8@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a8@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}

    case_id = await _create_ingested_case(
        client, db, initialized_storage, analyser_tok, "PH1-CANCEL-001"
    )
    r = await client.post(f"/cases/{case_id}/phase1", headers=hdrs_admin)
    assert r.status_code == 202

    r2 = await client.post(f"/cases/{case_id}/phase1/cancel", headers=hdrs_admin)
    assert r2.status_code == 200
    assert r2.json()["detail"] == "Phase 1 decisioning canceled"

    # Verify DR status
    dr_id = r.json()["decision_result_id"]
    dr = await db.get(DecisionResult, dr_id)
    await db.refresh(dr)
    assert dr.status == DecisionStatus.CANCELLED

    # Verify case rolled back
    case = await db.get(Case, case_id)
    await db.refresh(case)
    assert case.current_stage == CaseStage.INGESTED
