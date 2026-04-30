"""Unit tests for L3 image_crop worker module."""
from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select

from app.enums import ArtifactSubtype, ArtifactType, UserRole
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.services import users as users_svc
from app.worker.image_crop import (
    _bbox_pixels,
    crop_business_premises_items,
    crop_to_bytes,
)


def _png_bytes(w: int = 200, h: int = 200, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def test_bbox_pixels_validates_range():
    assert _bbox_pixels([0.0, 0.0, 1.0, 1.0], 100, 100) == (0, 0, 100, 100)
    assert _bbox_pixels([0.1, 0.2, 0.5, 0.6], 100, 100) == (10, 20, 50, 60)
    # Out of range
    assert _bbox_pixels([-0.1, 0.0, 0.5, 0.5], 100, 100) is None
    # x1 <= x0
    assert _bbox_pixels([0.5, 0.5, 0.4, 0.6], 100, 100) is None
    # Wrong arity
    assert _bbox_pixels([0.0, 0.0, 1.0], 100, 100) is None
    # Garbage
    assert _bbox_pixels([None, None, None, None], 100, 100) is None


def test_crop_to_bytes_valid_returns_jpeg():
    parent = _png_bytes(400, 300)
    out = crop_to_bytes(parent, [0.25, 0.25, 0.75, 0.75])
    assert out is not None
    # Decoded result should be a valid JPEG
    decoded = Image.open(io.BytesIO(out))
    assert decoded.format == "JPEG"
    assert decoded.size == (200, 150)


def test_crop_to_bytes_returns_none_on_corrupt_image():
    out = crop_to_bytes(b"this is not an image", [0.0, 0.0, 1.0, 1.0])
    assert out is None


def test_crop_to_bytes_returns_none_on_bad_bbox():
    parent = _png_bytes()
    out = crop_to_bytes(parent, [0.5, 0.5, 0.4, 0.6])
    assert out is None


@pytest.mark.asyncio
async def test_crop_business_premises_items_skips_no_bbox(db):
    actor = await users_svc.create_user(
        db, email=f"crop-skip-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Tester", role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    case = Case(
        loan_id=f"CROP{int(datetime.now(UTC).timestamp() * 1000) % 10_000_000}",
        uploaded_by=actor.id, uploaded_at=datetime.now(UTC),
        zip_s3_key=f"crop/{actor.id}/case.zip", loan_amount=100_000,
    )
    db.add(case)
    await db.flush()

    storage = AsyncMock()
    storage.download_object = AsyncMock(return_value=_png_bytes())
    storage.upload_object = AsyncMock()

    parent = CaseArtifact(
        case_id=case.id, filename="biz1.jpg",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
        s3_key=f"crop/{case.id}/biz1.jpg",
        uploaded_by=actor.id, uploaded_at=datetime.now(UTC),
        metadata_json={"subtype": "BUSINESS_PREMISES_PHOTO"},
    )
    db.add(parent)
    await db.flush()

    items = [
        {"description": "chair", "qty": 2, "category": "equipment",
         "mrp_estimate_inr": 5000, "mrp_confidence": "high",
         "source_image": 1, "bbox": [0.1, 0.1, 0.4, 0.4]},
        {"description": "mirror", "qty": 1, "category": "equipment",
         "mrp_estimate_inr": 1500, "mrp_confidence": "high",
         "source_image": 1, "bbox": None},  # SKIPPED — no bbox
    ]
    out = await crop_business_premises_items(
        db, case_id=case.id, actor_user_id=actor.id,
        parent_artifacts=[parent], items=items, storage=storage,
    )
    assert out is items  # mutated in place
    assert items[0]["crop_artifact_id"] is not None
    assert items[1]["crop_artifact_id"] is None
    # Storage was hit exactly once (one crop produced)
    assert storage.upload_object.await_count == 1


@pytest.mark.asyncio
async def test_crop_business_premises_items_creates_child_artifact(db):
    actor = await users_svc.create_user(
        db, email=f"crop-child-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Tester", role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    case = Case(
        loan_id=f"CROPCH{int(datetime.now(UTC).timestamp() * 1000) % 10_000_000}",
        uploaded_by=actor.id, uploaded_at=datetime.now(UTC),
        zip_s3_key=f"crop/{actor.id}/case.zip", loan_amount=100_000,
    )
    db.add(case)
    await db.flush()

    storage = AsyncMock()
    storage.download_object = AsyncMock(return_value=_png_bytes())
    storage.upload_object = AsyncMock()

    parent = CaseArtifact(
        case_id=case.id, filename="biz1.jpg",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
        s3_key=f"crop/{case.id}/biz1.jpg",
        uploaded_by=actor.id, uploaded_at=datetime.now(UTC),
        metadata_json={"subtype": "BUSINESS_PREMISES_PHOTO"},
    )
    db.add(parent)
    await db.flush()

    items = [
        {"description": "chair", "qty": 1, "category": "equipment",
         "mrp_estimate_inr": 5000, "mrp_confidence": "high",
         "source_image": 1, "bbox": [0.0, 0.0, 0.5, 0.5]},
    ]
    await crop_business_premises_items(
        db, case_id=case.id, actor_user_id=actor.id,
        parent_artifacts=[parent], items=items, storage=storage,
    )
    crop_id = uuid.UUID(items[0]["crop_artifact_id"])
    crop_artifact = (await db.execute(
        select(CaseArtifact).where(CaseArtifact.id == crop_id)
    )).scalars().first()
    assert crop_artifact is not None
    meta = crop_artifact.metadata_json
    assert meta["subtype"] == ArtifactSubtype.BUSINESS_PREMISES_CROP.value
    assert meta["parent_artifact_id"] == str(parent.id)
    assert meta["item_index"] == 0
    assert meta["description"] == "chair"


@pytest.mark.asyncio
async def test_crop_handles_storage_download_failure_gracefully(db):
    actor = await users_svc.create_user(
        db, email=f"crop-fail-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Tester", role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    case = Case(
        loan_id=f"CROPF{int(datetime.now(UTC).timestamp() * 1000) % 10_000_000}",
        uploaded_by=actor.id, uploaded_at=datetime.now(UTC),
        zip_s3_key=f"crop/{actor.id}/case.zip", loan_amount=100_000,
    )
    db.add(case)
    await db.flush()

    storage = AsyncMock()
    storage.download_object = AsyncMock(side_effect=RuntimeError("boom"))
    storage.upload_object = AsyncMock()

    parent = CaseArtifact(
        case_id=case.id, filename="biz1.jpg",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
        s3_key=f"crop/{case.id}/biz1.jpg",
        uploaded_by=actor.id, uploaded_at=datetime.now(UTC),
        metadata_json={"subtype": "BUSINESS_PREMISES_PHOTO"},
    )
    db.add(parent)
    await db.flush()

    items = [{"description": "chair", "qty": 1, "category": "equipment",
              "mrp_estimate_inr": 5000, "mrp_confidence": "high",
              "source_image": 1, "bbox": [0.1, 0.1, 0.4, 0.4]}]
    out = await crop_business_premises_items(
        db, case_id=case.id, actor_user_id=actor.id,
        parent_artifacts=[parent], items=items, storage=storage,
    )
    # Storage download failed -> no crop, no upload, no exception
    assert out[0]["crop_artifact_id"] is None
    assert storage.upload_object.await_count == 0
