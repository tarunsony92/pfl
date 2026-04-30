"""L3 orchestrator enrichment: crops + catalogue."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.enums import ArtifactSubtype, ArtifactType, UserRole
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.mrp_catalogue_entry import MrpCatalogueEntry
from app.services import users as users_svc
from app.verification.levels.level_3_vision import (
    _enrich_items_with_crops_and_catalogue,
)


def _png_bytes(w: int = 200, h: int = 200) -> bytes:
    import io
    from PIL import Image
    img = Image.new("RGB", (w, h), (255, 0, 0))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


async def _seed(db):
    user = await users_svc.create_user(
        db,
        email=f"l3enrich-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!",
        full_name="L3 Enrich Tester",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    case = Case(
        loan_id=f"L3E{int(datetime.now(UTC).timestamp() * 1000) % 10_000_000}",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key=f"l3e/{user.id}/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()

    parent = CaseArtifact(
        case_id=case.id,
        filename="biz1.jpg",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
        s3_key=f"l3e/{case.id}/biz1.jpg",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        metadata_json={"subtype": "BUSINESS_PREMISES_PHOTO"},
    )
    db.add(parent)
    await db.flush()
    return case, user, parent


@pytest.mark.asyncio
async def test_enrichment_crops_and_catalogues_each_priced_item(db):
    case, user, parent = await _seed(db)
    storage = AsyncMock()
    storage.download_object = AsyncMock(return_value=_png_bytes())
    storage.upload_object = AsyncMock()

    biz_data = {
        "business_type": "service",
        "items": [
            {"description": "Barber Chair", "qty": 2, "category": "equipment",
             "mrp_estimate_inr": 8500, "mrp_confidence": "medium",
             "rationale": "x", "source_image": 1,
             "bbox": [0.1, 0.1, 0.4, 0.4]},
            {"description": "Hair Clipper", "qty": 1, "category": "equipment",
             "mrp_estimate_inr": 2500, "mrp_confidence": "high",
             "rationale": "y", "source_image": 1,
             "bbox": [0.5, 0.5, 0.7, 0.7]},
        ],
    }

    await _enrich_items_with_crops_and_catalogue(
        db, case_id=case.id, actor_user_id=user.id,
        business_type="service", biz_data=biz_data,
        parent_artifacts=[parent], storage=storage,
    )

    items = biz_data["items"]
    assert all(it["crop_artifact_id"] is not None for it in items)
    assert all(it["catalogue_entry_id"] is not None for it in items)
    assert all(it["mrp_source"] == "AI_ESTIMATED" for it in items)
    assert items[0]["catalogue_mrp_inr"] == 8500
    assert items[1]["catalogue_mrp_inr"] == 2500

    # Verify catalogue rows were actually written
    rows = (await db.execute(select(MrpCatalogueEntry))).scalars().all()
    canonicals = {r.item_canonical for r in rows}
    assert "barber_chair" in canonicals
    assert "hair_clipper" in canonicals


@pytest.mark.asyncio
async def test_enrichment_skips_null_mrp_for_catalogue_but_still_crops(db):
    case, user, parent = await _seed(db)
    storage = AsyncMock()
    storage.download_object = AsyncMock(return_value=_png_bytes())
    storage.upload_object = AsyncMock()

    biz_data = {
        "business_type": "service",
        "items": [
            {"description": "Mystery Jar", "qty": 1, "category": "other",
             "mrp_estimate_inr": None, "mrp_confidence": "low",
             "rationale": "couldn't price", "source_image": 1,
             "bbox": [0.0, 0.0, 0.5, 0.5]},
        ],
    }
    await _enrich_items_with_crops_and_catalogue(
        db, case_id=case.id, actor_user_id=user.id,
        business_type="service", biz_data=biz_data,
        parent_artifacts=[parent], storage=storage,
    )
    it = biz_data["items"][0]
    # Cropped (because bbox was valid) but NOT catalogued (null MRP).
    assert it["crop_artifact_id"] is not None
    assert it["catalogue_entry_id"] is None
    assert it["mrp_source"] == "AI_ESTIMATED"

    # Verify no catalogue row was written
    rows = (await db.execute(select(MrpCatalogueEntry))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_enrichment_uses_existing_admin_curated_mrp(db):
    """When the catalogue already has a MANUAL or OVERRIDDEN_FROM_AI
    entry, the orchestrator surfaces THAT mrp_inr (not the AI's fresh
    estimate) — admin edits propagate to every future case view."""
    case, user, parent = await _seed(db)
    storage = AsyncMock()
    storage.download_object = AsyncMock(return_value=_png_bytes())
    storage.upload_object = AsyncMock()

    # Pre-seed the catalogue with an admin-curated row
    from app.services.mrp_catalogue import create_manual

    admin = await users_svc.create_user(
        db, email=f"l3-admin-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="MRP Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    await create_manual(
        db, business_type="service", item_description="Barber Chair",
        category="equipment", mrp_inr=12345, rationale="admin truth",
        actor_user_id=admin.id,
    )
    await db.flush()

    biz_data = {
        "business_type": "service",
        "items": [
            {"description": "Barber Chair", "qty": 2, "category": "equipment",
             "mrp_estimate_inr": 8500,  # AI says 8500 ...
             "mrp_confidence": "medium", "rationale": "x",
             "source_image": 1, "bbox": [0.0, 0.0, 0.4, 0.4]},
        ],
    }
    await _enrich_items_with_crops_and_catalogue(
        db, case_id=case.id, actor_user_id=user.id,
        business_type="service", biz_data=biz_data,
        parent_artifacts=[parent], storage=storage,
    )
    it = biz_data["items"][0]
    # ... but the catalogue says 12345 (admin-curated). That wins.
    assert it["catalogue_mrp_inr"] == 12345
    assert it["mrp_source"] == "MANUAL"


@pytest.mark.asyncio
async def test_enrichment_handles_missing_business_type_gracefully(db):
    case, user, parent = await _seed(db)
    storage = AsyncMock()
    storage.download_object = AsyncMock(return_value=_png_bytes())
    storage.upload_object = AsyncMock()

    biz_data = {
        "business_type": None,
        "items": [
            {"description": "Mystery Item", "qty": 1, "category": "other",
             "mrp_estimate_inr": 100, "mrp_confidence": "low",
             "source_image": 1, "bbox": [0.0, 0.0, 0.5, 0.5]},
        ],
    }
    await _enrich_items_with_crops_and_catalogue(
        db, case_id=case.id, actor_user_id=user.id,
        business_type=None, biz_data=biz_data,
        parent_artifacts=[parent], storage=storage,
    )
    it = biz_data["items"][0]
    # Cropped (bbox valid) but NOT catalogued (no business_type to key on)
    assert it["crop_artifact_id"] is not None
    assert it["catalogue_entry_id"] is None
    assert it["catalogue_mrp_inr"] is None
    assert it["mrp_source"] == "AI_ESTIMATED"
