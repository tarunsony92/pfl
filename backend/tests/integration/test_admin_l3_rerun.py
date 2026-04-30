"""Integration tests for the /admin/l3 bulk-rerun endpoints.

Covers the auth gate, the stale-extractions preview query, and that the
POST endpoint schedules one background task per stale case (without
actually running L3 — the per-case task is patched to a no-op so we
don't pull in Claude or storage stubs)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.security import create_access_token
from app.enums import (
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.verification_result import VerificationResult
from app.services import users as users_svc


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_case_with_l3(
    db: Any,
    *,
    uploader_id: Any,
    loan_id: str,
    items_present: bool,
) -> Case:
    """Insert a Case + a single L3 VerificationResult.

    items_present=True  → COMPLETED L3 with stock_analysis.items=[...]
    items_present=False → COMPLETED L3 without items key (legacy schema)
    """
    case = Case(
        loan_id=loan_id,
        uploaded_by=uploader_id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key=f"s3://test/{loan_id}",
    )
    db.add(case)
    await db.flush()

    sub_step_results: dict[str, Any] = {
        "stock_analysis": {
            "business_type": "service",
            "stock_value_estimate_inr": 10_000,
        },
    }
    if items_present:
        sub_step_results["stock_analysis"]["items"] = [
            {"description": "barber chair", "qty": 2, "category": "equipment",
             "mrp_estimate_inr": 5000, "mrp_confidence": "high"},
        ]

    vr = VerificationResult(
        case_id=case.id,
        level_number=VerificationLevelNumber.L3_VISION,
        status=VerificationLevelStatus.PASSED,
        sub_step_results=sub_step_results,
    )
    db.add(vr)
    await db.flush()
    return case


async def test_preview_requires_admin(client, db):
    """Non-admin role gets 403."""
    user = await users_svc.create_user(
        db, email=f"l3rerun-nonadmin-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Analyst", role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    token = create_access_token(subject=str(user.id))

    res = await client.get("/admin/l3/stale-extractions", headers=_auth(token))
    assert res.status_code == 403


async def test_preview_lists_stale_cases_only(client, db):
    """Cases whose latest L3 row has items[] are filtered out; legacy ones surface."""
    admin = await users_svc.create_user(
        db, email=f"l3rerun-admin-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))

    fresh = await _seed_case_with_l3(
        db, uploader_id=admin.id, loan_id="L3RR-FRESH", items_present=True,
    )
    stale = await _seed_case_with_l3(
        db, uploader_id=admin.id, loan_id="L3RR-STALE", items_present=False,
    )

    res = await client.get("/admin/l3/stale-extractions", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    case_ids = set(body["case_ids"])
    assert str(stale.id) in case_ids
    assert str(fresh.id) not in case_ids
    assert body["stale_count"] >= 1
    # Cost guardrail surfaces in the preview
    assert body["estimated_cost_usd"] == round(body["stale_count"] * 0.05, 2)


async def test_rerun_schedules_one_task_per_stale_case(client, db, monkeypatch):
    """POST → returns count + scheduled tasks; per-case task is mocked."""
    from app.api.routers import admin_l3_rerun as router_module

    admin = await users_svc.create_user(
        db, email=f"l3rerun-post-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))

    stale_a = await _seed_case_with_l3(
        db, uploader_id=admin.id, loan_id="L3RR-A", items_present=False,
    )
    stale_b = await _seed_case_with_l3(
        db, uploader_id=admin.id, loan_id="L3RR-B", items_present=False,
    )
    await _seed_case_with_l3(
        db, uploader_id=admin.id, loan_id="L3RR-C", items_present=True,
    )

    called_with: list[Any] = []

    async def _mock_rerun(case_id, *, actor_id, settings):
        called_with.append(case_id)

    monkeypatch.setattr(router_module, "_rerun_one_case", _mock_rerun)

    res = await client.post("/admin/l3/rerun-stale", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["queued_count"] >= 2
    assert body["estimated_cost_usd"] == round(body["queued_count"] * 0.05, 2)

    # FastAPI runs BackgroundTasks after the response within the same client
    # call, so by now both stale cases must have been scheduled.
    scheduled = set(called_with)
    assert stale_a.id in scheduled
    assert stale_b.id in scheduled
