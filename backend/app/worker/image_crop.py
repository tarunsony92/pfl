"""L3 image-crop worker.

Crops per-item bounding boxes out of the business-premises photo
bundle and stores each crop as a child CaseArtifact (subtype
BUSINESS_PREMISES_CROP, parent_artifact_id stamped in metadata_json).

Inputs:
  - parent_artifacts: ordered list of CaseArtifact rows in the EXACT
    order they were sent to the BusinessPremisesScorer. The scorer's
    `source_image` per item is 1-indexed into this list.
  - items: list of dicts as returned by the scorer. Each item that has
    a non-null `bbox` AND a valid `source_image` becomes one cropped
    artefact. Items with `bbox=None` or out-of-range `source_image`
    are skipped (they keep a `crop_artifact_id=None` in the output).

Outputs:
  - The same items list, MUTATED in place to add `crop_artifact_id`
    (UUID string) and `crop_filename` for each successfully cropped
    item. Items that couldn't be cropped get `crop_artifact_id=None`.

Failure modes:
  - Pillow can't decode the parent photo -> log + skip that item
    (crop_artifact_id=None). Don't raise.
  - bbox is malformed (out-of-range, x1 <= x0, etc.) -> skip, don't raise.
  - S3 upload fails -> propagate? No — log + skip. The orchestrator
    has bigger fish to fry; a missing thumbnail is non-critical.

Cost: image bytes are downloaded once per parent artifact even if
multiple items crop from it (small in-memory cache).
"""
from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ArtifactSubtype, ArtifactType
from app.models.case_artifact import CaseArtifact

_log = logging.getLogger(__name__)

# Output JPEG quality + max dim — keep crops small (S3 + bandwidth).
_JPEG_QUALITY = 85
_MAX_CROP_DIM = 600


def _bbox_pixels(
    bbox: list[float] | tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """Convert normalised bbox [0-1] to integer pixel coords. Validates
    monotonicity + range. Returns None on malformed input."""
    if not bbox or len(bbox) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None
    px0, py0 = int(x0 * width), int(y0 * height)
    px1, py1 = int(x1 * width), int(y1 * height)
    if px1 <= px0 or py1 <= py0:
        return None
    return px0, py0, px1, py1


def crop_to_bytes(
    parent_bytes: bytes,
    bbox: list[float] | tuple[float, float, float, float],
) -> bytes | None:
    """Synchronous Pillow crop. Returns JPEG bytes or None on any failure.

    Resizes the crop so its longest edge is at most `_MAX_CROP_DIM` px —
    these are thumbnails, not archival images.
    """
    try:
        img = Image.open(io.BytesIO(parent_bytes))
        img.load()
    except Exception as exc:  # noqa: BLE001
        _log.warning("crop_to_bytes: PIL.open failed: %s", exc)
        return None

    rect = _bbox_pixels(bbox, img.width, img.height)
    if rect is None:
        return None

    try:
        crop = img.crop(rect)
        # Ensure 3-channel JPEG (some sources are RGBA / P)
        if crop.mode not in ("RGB", "L"):
            crop = crop.convert("RGB")
        # Thumbnail the crop in place if the long edge is huge
        crop.thumbnail((_MAX_CROP_DIM, _MAX_CROP_DIM))
        out = io.BytesIO()
        crop.save(out, format="JPEG", quality=_JPEG_QUALITY)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        _log.warning("crop_to_bytes: PIL.crop/save failed: %s", exc)
        return None


async def crop_business_premises_items(
    session: AsyncSession,
    *,
    case_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    parent_artifacts: list[CaseArtifact],
    items: list[dict[str, Any]],
    storage: Any,
) -> list[dict[str, Any]]:
    """Mutate `items` in place to add `crop_artifact_id` (UUID-string
    or None) and `crop_filename` (str or None). Returns the same list
    so callers can chain.

    `parent_artifacts` MUST be in the same order the BusinessPremises
    scorer received the photos so item.source_image (1-indexed) maps
    correctly.

    Storage failures, missing source_image, malformed bbox, and PIL
    decode errors all degrade to crop_artifact_id=None for the affected
    item. Non-fatal. The L3 panel falls back to the parent photo.
    """
    if not items or not parent_artifacts:
        for it in items:
            it.setdefault("crop_artifact_id", None)
            it.setdefault("crop_filename", None)
        return items

    # In-memory cache of parent bytes — multiple items may crop from
    # the same parent.
    parent_bytes_by_index: dict[int, bytes | None] = {}

    async def _get_parent(idx_zero: int) -> bytes | None:
        if idx_zero < 0 or idx_zero >= len(parent_artifacts):
            return None
        if idx_zero in parent_bytes_by_index:
            return parent_bytes_by_index[idx_zero]
        artifact = parent_artifacts[idx_zero]
        try:
            data = await storage.download_object(artifact.s3_key)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "crop worker: download_object failed s3_key=%s: %s",
                artifact.s3_key,
                exc,
            )
            data = None
        parent_bytes_by_index[idx_zero] = data
        return data

    now = datetime.now(UTC)
    for item_idx, it in enumerate(items):
        it.setdefault("crop_artifact_id", None)
        it.setdefault("crop_filename", None)

        bbox = it.get("bbox")
        if not bbox:
            continue
        src_one = it.get("source_image")
        if not isinstance(src_one, int) or src_one < 1:
            continue
        src_zero = src_one - 1
        if src_zero >= len(parent_artifacts):
            continue

        parent_bytes = await _get_parent(src_zero)
        if not parent_bytes:
            continue
        crop_bytes = crop_to_bytes(parent_bytes, bbox)
        if crop_bytes is None:
            continue

        parent = parent_artifacts[src_zero]
        crop_id = uuid.uuid4()
        crop_filename = (
            f"crop_{parent.id}_item_{item_idx:02d}.jpg"
        )
        s3_key = (
            f"cases/{case_id}/crops/{crop_filename}"
        )
        try:
            await storage.upload_object(
                s3_key, crop_bytes, content_type="image/jpeg"
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "crop worker: upload_object failed s3_key=%s: %s",
                s3_key,
                exc,
            )
            continue

        crop_artifact = CaseArtifact(
            id=crop_id,
            case_id=case_id,
            filename=crop_filename,
            artifact_type=ArtifactType.ADDITIONAL_FILE,
            s3_key=s3_key,
            uploaded_by=actor_user_id,
            uploaded_at=now,
            metadata_json={
                "subtype": ArtifactSubtype.BUSINESS_PREMISES_CROP.value,
                "parent_artifact_id": str(parent.id),
                "parent_filename": parent.filename,
                "item_index": item_idx,
                "bbox": list(bbox),
                "description": it.get("description"),
            },
            size_bytes=len(crop_bytes),
        )
        session.add(crop_artifact)
        # No flush yet — caller orchestrates; one final flush at the
        # end is fine. But populate the item dict immediately so the
        # caller doesn't need to query.
        it["crop_artifact_id"] = str(crop_id)
        it["crop_filename"] = crop_filename

    await session.flush()
    return items
