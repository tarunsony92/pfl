"""End-to-end: real ZIP upload through presigned POST to LocalStack S3.

Skipped automatically if the Seema ZIP isn't at the expected path.
"""

import json
from pathlib import Path

import pytest

SEEMA_ZIP = Path("/Users/sakshamgupta/Downloads/10006484 Seema Panipat.zip")

pytestmark = pytest.mark.skipif(
    not SEEMA_ZIP.exists(),
    reason="Seema ZIP not present — E2E test skipped",
)


async def test_e2e_seema_zip_upload(client, db, mock_aws_services):
    """Full flow: initiate → S3 upload → finalize → verify DB + queue state."""
    from app.core.security import create_access_token
    from app.enums import CaseStage, UserRole
    from app.services import users as users_svc
    from app.services.queue import get_queue, reset_queue_for_tests
    from app.services.storage import get_storage, reset_storage_for_tests

    reset_storage_for_tests()
    reset_queue_for_tests()

    analyser = await users_svc.create_user(
        db,
        email="an@pfl.com",
        password="Pass123!",
        full_name="Analyser",
        role=UserRole.AI_ANALYSER,
    )
    await db.commit()
    token = create_access_token(subject=str(analyser.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Under moto (in-process mock), the default-constructed get_storage()/get_queue()
    # will use the real AWS endpoint by default. Moto intercepts via patch, so any
    # client created inside mock_aws() context talks to moto. Ensure bucket+queue exist.
    storage = get_storage()
    await storage.ensure_bucket_exists()
    queue = get_queue()
    await queue.ensure_queues_exist()

    # 1. Initiate
    r = await client.post(
        "/cases/initiate",
        headers=headers,
        json={"loan_id": "10006484", "applicant_name": "SEEMA"},
    )
    assert r.status_code == 201, r.text
    init = r.json()
    case_id = init["case_id"]
    upload_key = init["upload_key"]

    # 2. Upload ZIP via storage service (bypasses presigned POST for test simplicity).
    # CAVEAT: this bypasses content-length-range conditions. Size-cap validation
    # requires a real HTTP POST round-trip — out of scope for this unit-style test.
    zip_bytes = SEEMA_ZIP.read_bytes()
    await storage.upload_object(upload_key, zip_bytes, content_type="application/zip")

    # 3. Finalize
    r = await client.post(f"/cases/{case_id}/finalize", headers=headers)
    assert r.status_code == 200, r.text
    case_body = r.json()
    assert case_body["current_stage"] == CaseStage.CHECKLIST_VALIDATION.value

    # 4. Queue should have 1 message
    msgs = await queue.peek_messages()
    assert len(msgs) == 1
    payload = json.loads(msgs[0]["Body"])
    assert payload["case_id"] == case_id
    assert payload["loan_id"] == "10006484"

    # 5. GET /cases/{id} returns artifact with size matching ZIP
    r = await client.get(f"/cases/{case_id}", headers=headers)
    assert r.status_code == 200
    detail = r.json()
    assert len(detail["artifacts"]) == 1
    assert detail["artifacts"][0]["artifact_type"] == "ORIGINAL_ZIP"
    assert detail["artifacts"][0]["size_bytes"] == len(zip_bytes)
