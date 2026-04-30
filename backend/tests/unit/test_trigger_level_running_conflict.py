"""Tests for ``trigger_level`` short-circuit behaviour.

If a ``VerificationResult`` for the same ``(case_id, level_number)`` is
already ``RUNNING`` (within a ~5 minute freshness window), re-posting the
endpoint must return 409 with the existing VR id — not spawn a second
Claude call + second VR row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.routers.verification import trigger_level
from app.enums import (
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.verification_result import VerificationResult
from app.services import users as users_svc


class _FakeSettings:
    """Mimics the fields ``trigger_level`` reads from ``Settings``."""

    verification_enabled = True
    google_maps_api_key = None


class _FakeStorage:
    pass


@pytest_asyncio.fixture
async def _seeded_case(db):
    actor = await users_svc.create_user(
        db,
        email="m3-actor@pfl.com",
        password="Pass123!",
        full_name="M3 Actor",
        role=UserRole.ADMIN,
    )
    await db.flush()
    case = Case(
        loan_id="M3-RUN-001",
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="m3/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()
    return case, actor


async def test_trigger_level_409_when_running_vr_exists(db, _seeded_case):
    case, actor = _seeded_case
    # Seed an in-flight RUNNING VR — simulates another worker already
    # mid-run.
    inflight = VerificationResult(
        case_id=case.id,
        level_number=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.RUNNING,
        started_at=datetime.now(UTC),
        triggered_by=actor.id,
    )
    db.add(inflight)
    await db.flush()

    with pytest.raises(HTTPException) as exc_info:
        await trigger_level(
            case_id=case.id,
            level_number=VerificationLevelNumber.L1_ADDRESS,
            actor=actor,
            session=db,
            storage=_FakeStorage(),
            settings=_FakeSettings(),
        )
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    # Detail should carry the existing VR id for the UI.
    assert isinstance(detail, dict)
    assert detail.get("verification_result_id") == str(inflight.id)


async def test_trigger_level_ignores_stale_running_vr(db, _seeded_case):
    """A RUNNING VR older than the freshness window must not block a new
    trigger — that row is a zombie from a crashed worker."""
    case, actor = _seeded_case
    stale = VerificationResult(
        case_id=case.id,
        level_number=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.RUNNING,
        started_at=datetime.now(UTC) - timedelta(minutes=30),
        triggered_by=actor.id,
    )
    db.add(stale)
    await db.flush()
    # Force the created_at to be old so the freshness window doesn't
    # include it.
    stale.created_at = datetime.now(UTC) - timedelta(minutes=30)
    await db.flush()

    # The endpoint will try to dispatch to ``run_level_1_address`` (which
    # requires real infra) — we only care that it does NOT short-circuit
    # with 409. Any other failure downstream is fine.
    try:
        await trigger_level(
            case_id=case.id,
            level_number=VerificationLevelNumber.L1_ADDRESS,
            actor=actor,
            session=db,
            storage=_FakeStorage(),
            settings=_FakeSettings(),
        )
    except HTTPException as exc:
        # Must not be the 409 short-circuit.
        assert exc.status_code != 409, (
            f"stale RUNNING VR should not trigger 409 short-circuit; got {exc.detail}"
        )
    except Exception:
        # Downstream orchestrator failures are expected in this narrow
        # test — it only asserts that we got past the short-circuit.
        pass


async def test_trigger_level_409_only_for_matching_level(db, _seeded_case):
    """A RUNNING VR for L2 must not block a fresh L1 trigger."""
    case, actor = _seeded_case
    inflight_l2 = VerificationResult(
        case_id=case.id,
        level_number=VerificationLevelNumber.L2_BANKING,
        status=VerificationLevelStatus.RUNNING,
        started_at=datetime.now(UTC),
        triggered_by=actor.id,
    )
    db.add(inflight_l2)
    await db.flush()

    try:
        await trigger_level(
            case_id=case.id,
            level_number=VerificationLevelNumber.L1_ADDRESS,
            actor=actor,
            session=db,
            storage=_FakeStorage(),
            settings=_FakeSettings(),
        )
    except HTTPException as exc:
        assert exc.status_code != 409 or (
            isinstance(exc.detail, dict)
            and exc.detail.get("verification_result_id") != str(inflight_l2.id)
        )
    except Exception:
        pass  # downstream infra — fine
