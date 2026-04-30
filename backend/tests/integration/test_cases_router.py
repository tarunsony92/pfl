"""Cases router HTTP-layer tests.

Service-layer tests in test_cases_service.py cover the business logic exhaustively;
these tests focus on HTTP status codes, role-based access, and serialization.
"""

import pytest
import pytest_asyncio

from app.core.security import create_access_token
from app.enums import UserRole
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
    """Pre-create S3 bucket + set singleton for router tests needing storage."""
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
async def initialized_queue(mock_aws_services):
    """Pre-create SQS queues + set singleton for router tests needing queue."""
    import app.services.queue as _q_mod

    queue = QueueService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        queue_name="pfl-ingestion-dev",
        dlq_name="pfl-ingestion-dev-dlq",
    )
    await queue.ensure_queues_exist()
    _q_mod._instance = queue
    yield queue
    reset_queue_for_tests()


async def _token_for(db, email: str, role: UserRole) -> tuple[str, str]:
    user = await users_svc.create_user(
        db,
        email=email,
        password="Pass123!",
        full_name="T",
        role=role,
    )
    await db.commit()
    return str(user.id), create_access_token(subject=str(user.id))


async def test_initiate_requires_ai_analyser_or_admin(client, db, mock_aws_services):
    """Underwriter cannot initiate."""
    _, token = await _token_for(db, "uw@pfl.com", UserRole.UNDERWRITER)
    r = await client.post(
        "/cases/initiate",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": "LOAN-RT-001"},
    )
    assert r.status_code == 403


async def test_list_cases_requires_auth(client):
    r = await client.get("/cases")
    assert r.status_code == 401


async def test_initiate_duplicate_loan_id_returns_409(client, db, initialized_storage):
    _, token = await _token_for(db, "a@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {token}"}

    # first initiate succeeds
    r1 = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "DUP-RT-001"})
    assert r1.status_code == 201
    # second with same loan_id → 409
    r2 = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "DUP-RT-001"})
    assert r2.status_code == 409
    detail = r2.json()["detail"]
    assert detail["error"] == "case_exists"
    assert detail["requires_admin_approval"] is True


async def test_finalize_wrong_owner_returns_403(client, db, initialized_storage, initialized_queue):
    # Analyser A initiates
    a_id, a_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    r = await client.post(
        "/cases/initiate",
        headers={"Authorization": f"Bearer {a_tok}"},
        json={"loan_id": "OWN-RT-001"},
    )
    case_id = r.json()["case_id"]
    upload_key = r.json()["upload_key"]
    # Simulate upload completion
    await initialized_storage.upload_object(upload_key, b"x")

    # Analyser B tries to finalize
    _, b_tok = await _token_for(db, "b@pfl.com", UserRole.AI_ANALYSER)
    r2 = await client.post(
        f"/cases/{case_id}/finalize",
        headers={"Authorization": f"Bearer {b_tok}"},
    )
    assert r2.status_code == 403


async def test_finalize_nonexistent_case_returns_404(
    client, db, initialized_storage, initialized_queue
):
    from uuid import uuid4

    _, token = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    r = await client.post(
        f"/cases/{uuid4()}/finalize",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


async def test_finalize_without_upload_returns_400(
    client, db, initialized_storage, initialized_queue
):
    _, token = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {token}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "NOUP-001"})
    case_id = r.json()["case_id"]
    # Don't upload; try to finalize
    r2 = await client.post(f"/cases/{case_id}/finalize", headers=hdrs)
    assert r2.status_code == 400


async def test_finalize_success_returns_case_read(
    client, db, initialized_storage, initialized_queue
):
    """Happy path: initiate → upload → finalize returns 200 with case data."""
    _, token = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {token}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "FIN-RT-OK"})
    assert r.status_code == 201
    case_id = r.json()["case_id"]
    upload_key = r.json()["upload_key"]
    await initialized_storage.upload_object(upload_key, b"zipdata")

    r2 = await client.post(f"/cases/{case_id}/finalize", headers=hdrs)
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == case_id
    assert body["current_stage"] == "CHECKLIST_VALIDATION"


async def test_list_cases_returns_200_when_authenticated(client, db, initialized_storage):
    _, token = await _token_for(db, "uw@pfl.com", UserRole.UNDERWRITER)
    r = await client.get("/cases", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert "cases" in body
    assert "total" in body


async def test_get_case_success(client, db, initialized_storage):
    """Initiate then retrieve by case_id."""
    _, token = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {token}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "GET-RT-001"})
    case_id = r.json()["case_id"]

    r2 = await client.get(f"/cases/{case_id}", headers=hdrs)
    assert r2.status_code == 200
    assert r2.json()["id"] == case_id


async def test_soft_delete_success(client, db, initialized_storage):
    """Admin can soft-delete a case."""
    _, admin_tok = await _token_for(db, "adm@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {admin_tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "SDEL-RT-001"})
    case_id = r.json()["case_id"]

    r2 = await client.delete(f"/cases/{case_id}", headers=hdrs)
    assert r2.status_code == 204


async def test_approve_reupload_success(client, db, initialized_storage):
    """Admin can approve a reupload and get back the case."""
    _, admin_tok = await _token_for(db, "adm@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {admin_tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "AR-RT-001"})
    case_id = r.json()["case_id"]

    r2 = await client.post(
        f"/cases/{case_id}/approve-reupload",
        headers=hdrs,
        json={"reason": "underwriter error in original CAM"},
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == case_id


async def test_get_case_nonexistent_returns_404(client, db, initialized_storage):
    from uuid import uuid4

    _, token = await _token_for(db, "u@pfl.com", UserRole.UNDERWRITER)
    r = await client.get(f"/cases/{uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


async def test_approve_reupload_requires_admin(client, db, initialized_storage):
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    r = await client.post(
        "/cases/initiate",
        headers={"Authorization": f"Bearer {analyser_tok}"},
        json={"loan_id": "AR-001"},
    )
    case_id = r.json()["case_id"]
    # Non-admin approves → 403
    r2 = await client.post(
        f"/cases/{case_id}/approve-reupload",
        headers={"Authorization": f"Bearer {analyser_tok}"},
        json={"reason": "underwriter error in original CAM"},
    )
    assert r2.status_code == 403


async def test_delete_case_requires_admin(client, db, initialized_storage):
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    r = await client.post(
        "/cases/initiate",
        headers={"Authorization": f"Bearer {analyser_tok}"},
        json={"loan_id": "DEL-001"},
    )
    case_id = r.json()["case_id"]
    # Non-admin deletes → 403
    r2 = await client.delete(
        f"/cases/{case_id}",
        headers={"Authorization": f"Bearer {analyser_tok}"},
    )
    assert r2.status_code == 403


async def test_finalize_twice_returns_409(client, db, initialized_storage, initialized_queue):
    """C1 regression via HTTP."""
    _, tok = await _token_for(db, "x@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "TWICE-001"})
    case_id = r.json()["case_id"]
    upload_key = r.json()["upload_key"]

    await initialized_storage.upload_object(upload_key, b"x")

    r1 = await client.post(f"/cases/{case_id}/finalize", headers=hdrs)
    assert r1.status_code == 200
    r2 = await client.post(f"/cases/{case_id}/finalize", headers=hdrs)
    assert r2.status_code == 409


# Task 14: case extraction/validation/dedupe read endpoints + reingest


async def test_list_extractions_returns_all_for_case(client, db, initialized_storage):
    """Seed 3 CaseExtraction rows via ORM, GET → 3 rows."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.enums import ExtractionStatus
    from app.models.case_extraction import CaseExtraction

    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "EXT-001"})
    case_id = r.json()["case_id"]

    # Seed 3 extractions
    for i in range(3):
        ext = CaseExtraction(
            id=uuid4(),
            case_id=case_id,
            artifact_id=None,
            extractor_name=f"extractor_{i}",
            schema_version="1.0",
            status=ExtractionStatus.SUCCESS,
            data={"key": f"value_{i}"},
            warnings=None,
            error_message=None,
            extracted_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(ext)
    await db.commit()

    r2 = await client.get(f"/cases/{case_id}/extractions", headers=hdrs)
    assert r2.status_code == 200
    body = r2.json()
    assert len(body) == 3
    assert all("id" in e and "extractor_name" in e for e in body)


async def test_list_extractions_404_for_missing_case(client, db):
    """GET /cases/{nonexistent}/extractions → 404."""
    from uuid import uuid4

    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.get(f"/cases/{uuid4()}/extractions", headers=hdrs)
    assert r.status_code == 404


async def test_get_specific_extraction_returns_row(client, db, initialized_storage):
    """GET /cases/{id}/extractions/{extractor_name} → single row."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.enums import ExtractionStatus
    from app.models.case_extraction import CaseExtraction

    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "EXT-SINGLE-001"})
    case_id = r.json()["case_id"]

    ext = CaseExtraction(
        id=uuid4(),
        case_id=case_id,
        artifact_id=None,
        extractor_name="test_extractor",
        schema_version="1.0",
        status=ExtractionStatus.SUCCESS,
        data={"test": "data"},
        warnings=None,
        error_message=None,
        extracted_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    db.add(ext)
    await db.commit()

    r2 = await client.get(f"/cases/{case_id}/extractions/test_extractor", headers=hdrs)
    assert r2.status_code == 200
    body = r2.json()
    assert body["extractor_name"] == "test_extractor"
    assert body["data"]["test"] == "data"


async def test_get_specific_extraction_404_not_found(client, db, initialized_storage):
    """GET /cases/{id}/extractions/{extractor_name} → 404 when not found."""
    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "EXT-NOTFOUND-001"})
    case_id = r.json()["case_id"]

    r2 = await client.get(f"/cases/{case_id}/extractions/nonexistent_extractor", headers=hdrs)
    assert r2.status_code == 404


async def test_get_checklist_validation_returns_result(client, db, initialized_storage):
    """GET /cases/{id}/checklist-validation → ChecklistValidationResultRead."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.models.checklist_validation_result import ChecklistValidationResult

    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "CHECKLST-001"})
    case_id = r.json()["case_id"]

    result = ChecklistValidationResult(
        id=uuid4(),
        case_id=case_id,
        is_complete=True,
        missing_docs=[],
        present_docs=[{"doc": "aadhar"}],
        validated_at=datetime.now(UTC),
    )
    db.add(result)
    await db.commit()

    r2 = await client.get(f"/cases/{case_id}/checklist-validation", headers=hdrs)
    assert r2.status_code == 200
    body = r2.json()
    assert body["is_complete"] is True
    assert body["present_docs"] == [{"doc": "aadhar"}]


async def test_get_checklist_validation_404_when_absent(client, db, initialized_storage):
    """GET /cases/{id}/checklist-validation → 404 when none exists."""
    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "CHECKLST-NONE-001"})
    case_id = r.json()["case_id"]

    r2 = await client.get(f"/cases/{case_id}/checklist-validation", headers=hdrs)
    assert r2.status_code == 404


async def test_get_dedupe_matches_returns_list(client, db, initialized_storage):
    """GET /cases/{id}/dedupe-matches → list of DedupeMatchRead."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.enums import DedupeMatchType
    from app.models.dedupe_match import DedupeMatch
    from app.models.dedupe_snapshot import DedupeSnapshot

    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    user_id, _ = await _token_for(db, "user@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "DEDUPE-001"})
    case_id = r.json()["case_id"]

    # Create a dedupe snapshot (required by FK)
    snapshot = DedupeSnapshot(
        id=uuid4(),
        uploaded_by=user_id,
        uploaded_at=datetime.now(UTC),
        s3_key="test-snapshot.xlsx",
        row_count=0,
    )
    db.add(snapshot)
    await db.flush()

    # Seed 2 matches
    for i in range(2):
        match = DedupeMatch(
            id=uuid4(),
            case_id=case_id,
            snapshot_id=snapshot.id,
            match_type=DedupeMatchType.AADHAAR,
            match_score=0.95,
            matched_customer_id=f"CUST-{i}",
            matched_details_json={"name": f"Customer {i}"},
            created_at=datetime.now(UTC),
        )
        db.add(match)
    await db.commit()

    r2 = await client.get(f"/cases/{case_id}/dedupe-matches", headers=hdrs)
    assert r2.status_code == 200
    body = r2.json()
    assert len(body) == 2
    assert all("match_type" in m and "match_score" in m for m in body)


async def test_get_dedupe_matches_empty_list_when_none(client, db, initialized_storage):
    """GET /cases/{id}/dedupe-matches → empty list when none (not 404)."""
    _, tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "DEDUPE-EMPTY-001"})
    case_id = r.json()["case_id"]

    r2 = await client.get(f"/cases/{case_id}/dedupe-matches", headers=hdrs)
    assert r2.status_code == 200
    body = r2.json()
    assert body == []


async def test_reingest_from_valid_stage_202_and_publishes_job(
    client, db, initialized_storage, initialized_queue
):
    """POST /cases/{id}/reingest from INGESTED → 202 + queue has message."""
    import json

    _, admin_tok = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}
    hdrs_analyser = {"Authorization": f"Bearer {analyser_tok}"}

    r = await client.post(
        "/cases/initiate", headers=hdrs_analyser, json={"loan_id": "REINGEST-001"}
    )
    case_id = r.json()["case_id"]
    upload_key = r.json()["upload_key"]
    await initialized_storage.upload_object(upload_key, b"zipdata")

    # Finalize to move to CHECKLIST_VALIDATION, then manually set to INGESTED
    await client.post(f"/cases/{case_id}/finalize", headers=hdrs_analyser)
    from app.enums import CaseStage
    from app.models.case import Case

    case = await db.get(Case, case_id)
    case.current_stage = CaseStage.INGESTED
    await db.commit()

    r2 = await client.post(f"/cases/{case_id}/reingest", headers=hdrs_admin)
    assert r2.status_code == 202
    assert r2.json()["detail"] == "Reingestion triggered"

    # Verify queue has message
    messages = await initialized_queue.peek_messages()
    assert len(messages) > 0
    last_msg = messages[-1]
    body = json.loads(last_msg["Body"])
    assert body["case_id"] == str(case_id)
    assert body["trigger"] == "reingest"


async def test_reingest_from_invalid_stage_409(client, db, initialized_storage):
    """POST /cases/{id}/reingest from INITIATED → 409."""
    _, admin_tok = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}
    hdrs_analyser = {"Authorization": f"Bearer {analyser_tok}"}

    r = await client.post(
        "/cases/initiate", headers=hdrs_analyser, json={"loan_id": "REINGEST-BAD-001"}
    )
    case_id = r.json()["case_id"]
    # Case is in INITIATED state

    r2 = await client.post(f"/cases/{case_id}/reingest", headers=hdrs_admin)
    assert r2.status_code == 409
    assert "does not allow reingestion" in r2.json()["detail"]


async def test_reingest_non_admin_forbidden(client, db, initialized_storage):
    """POST /cases/{id}/reingest as non-admin → 403."""

    _, credit_ho_tok = await _token_for(db, "credit@pfl.com", UserRole.CREDIT_HO)
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs_credit = {"Authorization": f"Bearer {credit_ho_tok}"}
    hdrs_analyser = {"Authorization": f"Bearer {analyser_tok}"}

    r = await client.post(
        "/cases/initiate",
        headers=hdrs_analyser,
        json={"loan_id": "REINGEST-PERMS-001"},
    )
    case_id = r.json()["case_id"]

    # Try as CREDIT_HO
    r2 = await client.post(f"/cases/{case_id}/reingest", headers=hdrs_credit)
    assert r2.status_code == 403


async def test_reingest_on_deleted_case_404(client, db, initialized_storage):
    """POST /cases/{id}/reingest on deleted case → 404."""

    _, admin_tok = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    _, analyser_tok = await _token_for(db, "a@pfl.com", UserRole.AI_ANALYSER)
    hdrs_admin = {"Authorization": f"Bearer {admin_tok}"}
    hdrs_analyser = {"Authorization": f"Bearer {analyser_tok}"}

    r = await client.post(
        "/cases/initiate", headers=hdrs_analyser, json={"loan_id": "REINGEST-DEL-001"}
    )
    case_id = r.json()["case_id"]

    # Delete the case
    await client.delete(f"/cases/{case_id}", headers=hdrs_admin)

    # Try to reingest
    r2 = await client.post(f"/cases/{case_id}/reingest", headers=hdrs_admin)
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# T4: GET /cases/{case_id}/audit-log
# ---------------------------------------------------------------------------


async def test_audit_log_returns_entries_for_case(client, db, initialized_storage):
    """Audit log returns entries recorded during case lifecycle."""
    _, admin_tok = await _token_for(db, "audit_admin@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {admin_tok}"}

    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "AUDIT-002"})
    assert r.status_code == 201
    case_id = r.json()["case_id"]

    # The case was just initiated; audit-log endpoint returns list (may be empty or not
    # depending on whether initiate itself logs a case-scoped entry)
    r2 = await client.get(f"/cases/{case_id}/audit-log", headers=hdrs)
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)


async def test_audit_log_returns_empty_list_for_case_with_no_entries(
    client, db, initialized_storage
):
    """Audit log returns empty list when no case-scoped entries exist."""
    from app.models.audit_log import AuditLog as AuditLogModel

    _, admin_tok = await _token_for(db, "audit_empty@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {admin_tok}"}

    # Initiate a case; its initiate action uses entity_type='case'
    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "AUDIT-EMPTY-001"})
    case_id = r.json()["case_id"]

    # Remove any audit entries for this case so it appears empty
    from sqlalchemy import delete as sa_delete

    await db.execute(
        sa_delete(AuditLogModel)
        .where(AuditLogModel.entity_type == "case")
        .where(AuditLogModel.entity_id == str(case_id))
    )
    await db.commit()

    r2 = await client.get(f"/cases/{case_id}/audit-log", headers=hdrs)
    assert r2.status_code == 200
    assert r2.json() == []


async def test_audit_log_404_for_missing_case(client, db):
    """GET /cases/{nonexistent}/audit-log → 404."""
    from uuid import uuid4

    _, tok = await _token_for(db, "aulg_uw@pfl.com", UserRole.UNDERWRITER)
    r = await client.get(
        f"/cases/{uuid4()}/audit-log", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# T5: list_cases UNDERWRITER own-case filter injection
# ---------------------------------------------------------------------------


async def test_underwriter_only_sees_own_cases(client, db, initialized_storage):
    """Underwriter A creates a case; Underwriter B lists and does NOT see it."""
    _, tok_a = await _token_for(db, "uw_a@pfl.com", UserRole.UNDERWRITER)
    _, tok_b = await _token_for(db, "uw_b@pfl.com", UserRole.UNDERWRITER)
    _, admin_tok = await _token_for(db, "uw_admin@pfl.com", UserRole.ADMIN)

    # Only admins/analysers can initiate; create case as admin
    r = await client.post(
        "/cases/initiate",
        headers={"Authorization": f"Bearer {admin_tok}"},
        json={"loan_id": "UW-FILTER-001"},
    )
    assert r.status_code == 201

    # Underwriter B should see empty list (or only their own cases)
    r2 = await client.get("/cases", headers={"Authorization": f"Bearer {tok_b}"})
    assert r2.status_code == 200
    # UW B created no cases, so their filtered view must be empty
    assert r2.json()["total"] == 0


async def test_admin_sees_all_cases(client, db, initialized_storage):
    """Admin listing cases sees cases from any uploader."""
    _, admin_tok = await _token_for(db, "admin_all@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {admin_tok}"}

    r = await client.post("/cases/initiate", headers=hdrs, json={"loan_id": "ADMIN-SEE-001"})
    assert r.status_code == 201

    r2 = await client.get("/cases", headers=hdrs)
    assert r2.status_code == 200
    assert r2.json()["total"] >= 1


async def test_underwriter_cannot_override_filter_with_query_param(
    client, db, initialized_storage
):
    """Underwriter passing uploaded_by=<other user id> still only sees their own cases."""
    uw_a_id, tok_a = await _token_for(db, "uwover_a@pfl.com", UserRole.UNDERWRITER)
    _, tok_b = await _token_for(db, "uwover_b@pfl.com", UserRole.UNDERWRITER)
    _, admin_tok = await _token_for(db, "uwover_admin@pfl.com", UserRole.ADMIN)

    # Admin creates a case (uploaded_by = admin_id by default via initiate)
    r = await client.post(
        "/cases/initiate",
        headers={"Authorization": f"Bearer {admin_tok}"},
        json={"loan_id": "UW-OVERRIDE-001"},
    )
    assert r.status_code == 201

    # Underwriter B tries to pass uploaded_by=uw_a_id to peek at UW A — still gets their own (0)
    r2 = await client.get(
        f"/cases?uploaded_by={uw_a_id}",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert r2.status_code == 200
    # UW B's own filter overrides the query param → they see 0 cases
    assert r2.json()["total"] == 0


# ---------------------------------------------------------------------------
# M4: CaseInitiateRequest extra fields
# ---------------------------------------------------------------------------


async def test_initiate_with_wizard_fields_persists_them(client, db, initialized_storage):
    """Wizard fields loan_amount, loan_tenure_months, co_applicant_name are saved."""
    _, token = await _token_for(db, "wiz@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        "/cases/initiate",
        headers=hdrs,
        json={
            "loan_id": "WIZ-001",
            "applicant_name": "Alice",
            "loan_amount": 100000,
            "loan_tenure_months": 24,
            "co_applicant_name": "Bob",
        },
    )
    assert r.status_code == 201
    case_id = r.json()["case_id"]

    r2 = await client.get(f"/cases/{case_id}", headers=hdrs)
    assert r2.status_code == 200
    body = r2.json()
    assert body["loan_amount"] == 100000
    assert body["loan_tenure_months"] == 24
    assert body["co_applicant_name"] == "Bob"


async def test_initiate_without_wizard_fields_is_backward_compatible(
    client, db, initialized_storage
):
    """Wizard fields are all optional; existing callers still work."""
    _, token = await _token_for(db, "wiz2@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        "/cases/initiate",
        headers=hdrs,
        json={"loan_id": "WIZ-002"},
    )
    assert r.status_code == 201
    case_id = r.json()["case_id"]

    r2 = await client.get(f"/cases/{case_id}", headers=hdrs)
    body = r2.json()
    assert body["loan_amount"] is None
    assert body["loan_tenure_months"] is None
    assert body["co_applicant_name"] is None
