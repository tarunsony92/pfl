"""Worker pipeline orchestrator — spec §4.2.

Coordinates all ingestion steps:
0.  Load + soft-delete check
0a. Re-ingestion pre-flight (stage guard)
0b. Clear prior dedupe_matches
1.  Download ZIP from S3
2.  Unpack ZIP
3.  Upload + create CaseArtifact rows (with inline classification)
4.  (Classification is inline in step 3)
5.  Run per-artifact extractors → upsert CaseExtraction rows
6.  Dedupe → upsert DedupeMatch rows
7.  Checklist completeness → upsert ChecklistValidationResult
8.  Transition final stage
9.  Commit (done by caller in process_ingestion_job)
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import logging
import re
import zipfile
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.enums import ArtifactSubtype, ArtifactType, CaseStage, ExtractionStatus
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.checklist_validation_result import ChecklistValidationResult
from app.models.dedupe_match import DedupeMatch
from app.models.dedupe_snapshot import DedupeSnapshot
from app.models.user import User
from app.services import stages as stages_svc
from app.services.email import get_email_service
from app.services.storage import get_storage
from app.worker.checklist_validator import ValidationResult, validate_completeness
from app.worker.classifier import classify
from app.worker.dedupe import run_dedupe
from app.worker.extractors.auto_cam import AutoCamExtractor
from app.worker.extractors.bank_statement import BankStatementExtractor
from app.worker.extractors.checklist import ChecklistExtractor
from app.worker.extractors.dedupe_report import DedupeReportExtractor
from app.worker.extractors.equifax import EquifaxHtmlExtractor
from app.worker.extractors.pd_sheet import PDSheetExtractor
from app.worker.system_user import get_or_create_worker_user

_log = logging.getLogger(__name__)

# Cached system worker user ID — set once by __main__ before first job
SYSTEM_WORKER_USER_ID: UUID | None = None

# Stage set that allows re-ingestion pre-flight transition
_REINGEST_ALLOWED_FROM: frozenset[CaseStage] = frozenset(
    {
        CaseStage.INGESTED,
        CaseStage.CHECKLIST_VALIDATED,
        CaseStage.CHECKLIST_MISSING_DOCS,
        CaseStage.CHECKLIST_VALIDATION,
    }
)

# Subtypes that map to an extractor
_EXTRACTOR_SUBTYPES: frozenset[ArtifactSubtype] = frozenset(
    {
        ArtifactSubtype.AUTO_CAM,
        ArtifactSubtype.BANK_STATEMENT,
        ArtifactSubtype.CHECKLIST,
        ArtifactSubtype.DEDUPE_REPORT,
        ArtifactSubtype.EQUIFAX_HTML,
        ArtifactSubtype.PD_SHEET,
    }
)


def set_system_worker_user_id(uid: UUID) -> None:
    global SYSTEM_WORKER_USER_ID
    SYSTEM_WORKER_USER_ID = uid


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def process_ingestion_job(payload: dict[str, Any]) -> None:
    """Entry point called by queue.consume_jobs."""
    case_id = UUID(str(payload["case_id"]))
    trigger = payload.get("trigger", "finalize")
    _log.info("process_ingestion_job start case_id=%s trigger=%s", case_id, trigger)

    async with AsyncSessionLocal() as session:
        worker_id = SYSTEM_WORKER_USER_ID
        if worker_id is None:
            # Fallback: may not have been set in tests calling pipeline directly
            user = await get_or_create_worker_user(session)
            await session.flush()
            worker_id = user.id
            set_system_worker_user_id(worker_id)
        await _run_pipeline(session, case_id, worker_id, trigger)
        await session.commit()


# ---------------------------------------------------------------------------
# Top-level pipeline runner
# ---------------------------------------------------------------------------


async def _run_pipeline(
    session: AsyncSession,
    case_id: UUID,
    worker_id: UUID,
    trigger: str,
) -> None:
    storage = get_storage()

    # Step 0: load case (skip if missing or soft-deleted)
    case = await _load_case(session, case_id)
    if case is None:
        return

    # Step 0a: re-ingestion pre-flight
    should_continue = await _preflight_stage(session, case, worker_id, trigger)
    if not should_continue:
        return

    # Step 0b: clear prior dedupe state
    await _clear_prior_state(session, case_id)

    # Step 1 + 2: download + unpack ZIP
    files = await _download_and_unpack_zip(storage, case)

    # Step 3: upload + create artifacts (with inline classification)
    new_artifacts = await _upload_and_create_artifacts(session, storage, case, worker_id, files)

    # Fetch ALL artifacts for this case (including previously existing ones)
    all_artifacts_result = await session.execute(
        select(CaseArtifact).where(CaseArtifact.case_id == case_id)
    )
    all_artifacts: list[CaseArtifact] = list(all_artifacts_result.scalars().all())

    # On reingest, reclassify existing artifacts using the (possibly-updated)
    # classifier. This ensures a classifier-rule change is picked up without
    # requiring the user to delete and re-upload the case.
    if trigger == "reingest":
        await _reclassify_existing_artifacts(session, all_artifacts, files)

    # Step 5: run extractors. Normal ingest: only newly uploaded artifacts.
    # Admin reingest: re-run on every artifact so an extractor-code update is
    # reflected without the user having to delete and re-upload the case.
    extractor_targets = all_artifacts if trigger == "reingest" else new_artifacts
    await _run_extractors(session, case, extractor_targets, files)

    # Step 6: dedupe
    await _run_dedupe_and_persist(session, storage, case)

    # Step 7: checklist validation
    validation = await _run_checklist_validation(session, case, all_artifacts)

    # Step 8: final stage transition
    await _transition_final_stage(session, case, validation, worker_id)

    # Send missing docs email if needed
    await _send_missing_docs_email_if_needed(session, case, validation)


# ---------------------------------------------------------------------------
# Step 0: Load case
# ---------------------------------------------------------------------------


async def _load_case(session: AsyncSession, case_id: UUID) -> Case | None:
    """Load case from DB. Returns None if not found or soft-deleted."""
    result = await session.execute(select(Case).where(Case.id == case_id))
    case: Case | None = result.scalar_one_or_none()

    if case is None:
        _log.warning("_load_case: case %s not found — skipping", case_id)
        return None

    if case.is_deleted:
        _log.info("_load_case: case %s is_deleted=True — skipping", case_id)
        return None

    return case


# ---------------------------------------------------------------------------
# Step 0a: Re-ingestion pre-flight
# ---------------------------------------------------------------------------


async def _preflight_stage(
    session: AsyncSession,
    case: Case,
    worker_id: UUID,
    trigger: str,
) -> bool:
    """Guard + transition to CHECKLIST_VALIDATION if coming from a re-ingest stage.

    Returns True if pipeline should continue, False if it should be skipped.
    """
    current = case.current_stage

    if current == CaseStage.CHECKLIST_VALIDATION:
        # Already in the right stage — just continue
        return True

    if current in {
        # Re-ingest scenarios — case has already been through validation at
        # least once; bring it back to CHECKLIST_VALIDATION before reprocessing.
        CaseStage.INGESTED,
        CaseStage.CHECKLIST_VALIDATED,
        CaseStage.CHECKLIST_MISSING_DOCS,
        # First-time ingest: ordinarily the finalize() route transitions
        # UPLOADED → CHECKLIST_VALIDATION before publishing the SQS job, but if
        # the worker pulls the message ahead of the route's commit (older
        # builds, queue replay, or transient SQS visibility-timeout reuse),
        # we'd otherwise drop the job. Self-transition keeps the case alive
        # rather than wedging it at UPLOADED forever.
        CaseStage.UPLOADED,
    }:
        _log.info(
            "_preflight_stage: case %s stage=%s → CHECKLIST_VALIDATION (trigger=%s)",
            case.id,
            current,
            trigger,
        )
        await stages_svc.transition_stage(
            session,
            case=case,
            to=CaseStage.CHECKLIST_VALIDATION,
            actor_user_id=worker_id,
        )
        return True

    _log.warning(
        "_preflight_stage: case %s stage=%s is not a valid re-ingest stage — skipping",
        case.id,
        current,
    )
    return False


# ---------------------------------------------------------------------------
# Step 0b: Clear prior state
# ---------------------------------------------------------------------------


async def _clear_prior_state(session: AsyncSession, case_id: UUID) -> None:
    """Delete dedupe_matches for this case (prevents duplicates on re-ingestion)."""
    await session.execute(delete(DedupeMatch).where(DedupeMatch.case_id == case_id))
    _log.debug("_clear_prior_state: cleared dedupe_matches for case %s", case_id)


# ---------------------------------------------------------------------------
# Steps 1 + 2: Download + unpack ZIP
# ---------------------------------------------------------------------------


async def _download_and_unpack_zip(
    storage: Any,
    case: Case,
) -> list[tuple[str, bytes]]:
    """Download ZIP from S3, unpack, return list of (inner_path, bytes).

    Directory entries are skipped.
    """
    _log.info("_download_and_unpack_zip: downloading %s", case.zip_s3_key)
    zip_bytes = await storage.download_object(case.zip_s3_key)

    files: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            inner_path = info.filename
            body = zf.read(inner_path)
            files.append((inner_path, body))

    _log.info("_download_and_unpack_zip: unpacked %d files from case %s", len(files), case.id)
    return files


# ---------------------------------------------------------------------------
# Step 3: Upload + create CaseArtifact rows (inline classification)
# ---------------------------------------------------------------------------


def _safe_filename(path: str) -> str:
    last = path.rsplit("/", 1)[-1]
    return re.sub(r"[^a-zA-Z0-9._-]", "_", last) or "unnamed"


def _make_artifact_s3_key(case_id: UUID, inner_path: str) -> str:
    digest = hashlib.sha256(inner_path.encode()).hexdigest()[:12]
    return f"cases/{case_id}/artifacts/{digest}_{_safe_filename(inner_path)}"


async def _upload_and_create_artifacts(
    session: AsyncSession,
    storage: Any,
    case: Case,
    worker_id: UUID,
    files: list[tuple[str, bytes]],
) -> list[CaseArtifact]:
    """Upload new files to S3 + create CaseArtifact rows.

    Skips files where the s3_key already exists (idempotent via unique constraint).
    Returns only newly created artifacts.
    """
    new_artifacts: list[CaseArtifact] = []

    for inner_path, body_bytes in files:
        s3_key = _make_artifact_s3_key(case.id, inner_path)
        filename = _safe_filename(inner_path)

        # Check if artifact already exists (idempotency)
        existing_result = await session.execute(
            select(CaseArtifact).where(CaseArtifact.s3_key == s3_key)
        )
        existing: CaseArtifact | None = existing_result.scalar_one_or_none()
        if existing is not None:
            _log.debug("_upload_and_create_artifacts: skipping existing artifact %s", s3_key)
            continue

        # Classify (inline — step 4 per spec)
        folder_path = inner_path.rsplit("/", 1)[0] if "/" in inner_path else None
        subtype = classify(filename, folder_path=folder_path, body_bytes=body_bytes)

        # Upload to S3
        await storage.upload_object(s3_key, body_bytes)

        # Create CaseArtifact row
        artifact = CaseArtifact(
            case_id=case.id,
            filename=filename,
            artifact_type=ArtifactType.ADDITIONAL_FILE,
            s3_key=s3_key,
            size_bytes=len(body_bytes),
            content_type=None,
            uploaded_by=worker_id,
            uploaded_at=datetime.now(UTC),
            metadata_json={"subtype": subtype.value, "source_path": inner_path},
        )
        session.add(artifact)
        await session.flush()  # get artifact.id for later extraction upserts
        new_artifacts.append(artifact)

        _log.debug(
            "_upload_and_create_artifacts: created artifact %s subtype=%s",
            filename,
            subtype,
        )

    _log.info(
        "_upload_and_create_artifacts: %d new artifacts for case %s",
        len(new_artifacts),
        case.id,
    )
    return new_artifacts


# ---------------------------------------------------------------------------
# Step 5: Run extractors
# ---------------------------------------------------------------------------

_EXTRACTORS: dict[ArtifactSubtype, Any] = {
    ArtifactSubtype.AUTO_CAM: AutoCamExtractor(),
    ArtifactSubtype.BANK_STATEMENT: BankStatementExtractor(),
    ArtifactSubtype.CHECKLIST: ChecklistExtractor(),
    ArtifactSubtype.DEDUPE_REPORT: DedupeReportExtractor(),
    ArtifactSubtype.EQUIFAX_HTML: EquifaxHtmlExtractor(),
    ArtifactSubtype.PD_SHEET: PDSheetExtractor(),
}


async def _reclassify_existing_artifacts(
    session: AsyncSession,
    artifacts: list[CaseArtifact],
    files: list[tuple[str, bytes]],
) -> None:
    """On reingest, re-run the classifier for every existing artifact using
    the freshly-unpacked zip content, and update metadata_json.subtype when
    the new subtype differs. No-op when the bytes can't be matched (e.g.
    artifact is not in the zip anymore).
    """
    # Build s3_key → bytes lookup from the unpacked zip.
    bytes_by_s3_key: dict[str, bytes] = {}
    path_by_s3_key: dict[str, str] = {}
    for inner_path, body_bytes in files:
        # _make_artifact_s3_key needs a case_id — pull from the first artifact.
        pass
    if artifacts:
        case_id = artifacts[0].case_id
        for inner_path, body_bytes in files:
            s3_key = _make_artifact_s3_key(case_id, inner_path)
            bytes_by_s3_key[s3_key] = body_bytes
            path_by_s3_key[s3_key] = inner_path

    changed = 0
    for artifact in artifacts:
        body_bytes = bytes_by_s3_key.get(artifact.s3_key)
        if body_bytes is None:
            continue
        inner_path = path_by_s3_key.get(artifact.s3_key, artifact.filename)
        folder_path = inner_path.rsplit("/", 1)[0] if "/" in inner_path else None
        new_subtype = classify(
            _safe_filename(inner_path), folder_path=folder_path, body_bytes=body_bytes
        )
        meta = dict(artifact.metadata_json or {})
        current_subtype = meta.get("subtype", ArtifactSubtype.UNKNOWN.value)
        if new_subtype.value != current_subtype:
            meta["subtype"] = new_subtype.value
            artifact.metadata_json = meta
            # SQLAlchemy tracks JSON columns by identity — explicitly flag dirty.
            flag_modified(artifact, "metadata_json")
            changed += 1
            _log.info(
                "_reclassify_existing_artifacts: %s %s → %s",
                artifact.filename,
                current_subtype,
                new_subtype.value,
            )
    if changed:
        await session.flush()
    _log.info("_reclassify_existing_artifacts: %d subtype changes", changed)


async def _run_extractors(
    session: AsyncSession,
    case: Case,
    artifacts: list[CaseArtifact],
    files: list[tuple[str, bytes]],
) -> None:
    """Run extractors on newly created artifacts. Upserts CaseExtraction rows."""
    # Build a lookup from s3_key → bytes for the newly uploaded files
    # (we already have them in memory, no re-download needed)
    bytes_by_s3_key: dict[str, bytes] = {}
    for inner_path, body_bytes in files:
        s3_key = _make_artifact_s3_key(case.id, inner_path)
        bytes_by_s3_key[s3_key] = body_bytes

    for artifact in artifacts:
        meta = artifact.metadata_json or {}
        subtype_str = meta.get("subtype", ArtifactSubtype.UNKNOWN.value)
        try:
            subtype = ArtifactSubtype(subtype_str)
        except ValueError:
            subtype = ArtifactSubtype.UNKNOWN

        extractor = _EXTRACTORS.get(subtype)
        if extractor is None:
            _log.debug(
                "_run_extractors: no extractor for subtype=%s artifact=%s",
                subtype,
                artifact.filename,
            )
            continue

        artifact_bytes: bytes | None = bytes_by_s3_key.get(artifact.s3_key)
        if artifact_bytes is None:
            _log.warning(
                "_run_extractors: bytes not found in memory for %s — skipping",
                artifact.s3_key,
            )
            continue

        _log.info(
            "_run_extractors: running %s on %s (artifact=%s)",
            extractor.extractor_name,
            artifact.filename,
            artifact.id,
        )
        result = await extractor.extract(artifact.filename, artifact_bytes)

        await _upsert_artifact_extraction(
            session=session,
            case_id=case.id,
            artifact_id=artifact.id,
            extractor_name=extractor.extractor_name,
            status=result.status,
            schema_version=result.schema_version,
            data=result.data,
            warnings=result.warnings or None,
            error_message=result.error_message,
        )


async def _upsert_artifact_extraction(
    session: AsyncSession,
    case_id: UUID,
    artifact_id: UUID,
    extractor_name: str,
    status: ExtractionStatus,
    schema_version: str,
    data: dict[str, Any],
    warnings: list[str] | None,
    error_message: str | None,
) -> None:
    """Upsert a CaseExtraction row for an artifact-bound extraction.

    Uses the partial unique index: (case_id, extractor_name, artifact_id)
    WHERE artifact_id IS NOT NULL.
    """
    stmt = pg_insert(CaseExtraction).values(
        case_id=case_id,
        extractor_name=extractor_name,
        artifact_id=artifact_id,
        status=status.value,
        schema_version=schema_version,
        data=data,
        warnings=warnings,
        error_message=error_message,
        extracted_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["case_id", "extractor_name", "artifact_id"],
        index_where=CaseExtraction.artifact_id.isnot(None),
        set_={
            "status": stmt.excluded.status,
            "data": stmt.excluded.data,
            "warnings": stmt.excluded.warnings,
            "error_message": stmt.excluded.error_message,
            "extracted_at": stmt.excluded.extracted_at,
        },
    )
    await session.execute(stmt)


async def _upsert_aggregate_extraction(
    session: AsyncSession,
    case_id: UUID,
    extractor_name: str,
    status: ExtractionStatus,
    schema_version: str,
    data: dict[str, Any],
    warnings: list[str] | None,
    error_message: str | None,
) -> None:
    """Upsert a CaseExtraction row for an aggregate (case-level) extraction.

    Uses the partial unique index: (case_id, extractor_name)
    WHERE artifact_id IS NULL.
    """
    stmt = pg_insert(CaseExtraction).values(
        case_id=case_id,
        extractor_name=extractor_name,
        artifact_id=None,
        status=status.value,
        schema_version=schema_version,
        data=data,
        warnings=warnings,
        error_message=error_message,
        extracted_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["case_id", "extractor_name"],
        index_where=CaseExtraction.artifact_id.is_(None),
        set_={
            "status": stmt.excluded.status,
            "data": stmt.excluded.data,
            "warnings": stmt.excluded.warnings,
            "error_message": stmt.excluded.error_message,
            "extracted_at": stmt.excluded.extracted_at,
        },
    )
    await session.execute(stmt)


# ---------------------------------------------------------------------------
# Step 6: Dedupe
# ---------------------------------------------------------------------------


def _extract_auto_cam_applicant(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract applicant info from AutoCam extraction data."""
    system_cam = data.get("system_cam", {}) or {}
    if not system_cam:
        return None
    return {
        "name": system_cam.get("applicant_name"),
        "pan": system_cam.get("pan"),
        "dob": system_cam.get("date_of_birth"),
        "aadhaar": None,
        "mobile": None,
    }


async def _run_dedupe_and_persist(
    session: AsyncSession,
    storage: Any,
    case: Case,
) -> None:
    """Run dedupe against active snapshot + persist DedupeMatch rows."""
    # Get active dedupe snapshot
    snapshot_result = await session.execute(
        select(DedupeSnapshot)
        .where(DedupeSnapshot.is_active == True)  # noqa: E712
        .order_by(DedupeSnapshot.uploaded_at.desc())
        .limit(1)
    )
    snapshot: DedupeSnapshot | None = snapshot_result.scalar_one_or_none()

    snapshot_xlsx_bytes: bytes | None = None
    if snapshot is not None:
        try:
            snapshot_xlsx_bytes = await storage.download_object(snapshot.s3_key)
        except Exception:
            _log.exception(
                "_run_dedupe_and_persist: failed to download snapshot %s", snapshot.s3_key
            )
            snapshot_xlsx_bytes = None

    if snapshot is None:
        _log.info("_run_dedupe_and_persist: no active snapshot for case %s", case.id)

    # Get applicant info from AutoCam extraction (if any)
    auto_cam_result = await session.execute(
        select(CaseExtraction).where(
            CaseExtraction.case_id == case.id,
            CaseExtraction.extractor_name == "auto_cam",
        )
    )
    auto_cam_extractions = list(auto_cam_result.scalars().all())

    applicant: dict[str, Any] | None = None
    for extraction in auto_cam_extractions:
        if extraction.data:
            applicant = _extract_auto_cam_applicant(extraction.data)
            if applicant:
                break

    # Run dedupe.
    # AutoCamExtractor 1.0 does not currently parse co-applicant fields.
    # When it does, project them here via a co-applicant twin of
    # _extract_auto_cam_applicant so dedupe can check both subjects.
    dedupe_result = await run_dedupe(
        applicant=applicant,
        co_applicant=None,
        snapshot_xlsx_bytes=snapshot_xlsx_bytes,
    )

    # Upsert aggregate dedupe CaseExtraction row
    warnings = dedupe_result.warnings if dedupe_result.warnings else None
    status = ExtractionStatus.PARTIAL if warnings else ExtractionStatus.SUCCESS
    await _upsert_aggregate_extraction(
        session=session,
        case_id=case.id,
        extractor_name="dedupe",
        status=status,
        schema_version="1.0",
        data={"match_count": len(dedupe_result.matches)},
        warnings=warnings,
        error_message=None,
    )

    # Persist DedupeMatch rows (only if we have a snapshot to reference)
    if snapshot is not None and dedupe_result.matches:
        for match in dedupe_result.matches:
            dm = DedupeMatch(
                case_id=case.id,
                snapshot_id=snapshot.id,
                match_type=match.match_type,
                match_score=match.match_score,
                matched_customer_id=match.matched_customer_id,
                matched_details_json=match.matched_details,
            )
            session.add(dm)

        _log.info(
            "_run_dedupe_and_persist: %d dedupe matches for case %s",
            len(dedupe_result.matches),
            case.id,
        )


# ---------------------------------------------------------------------------
# Step 7: Checklist validation
# ---------------------------------------------------------------------------


async def _run_checklist_validation(
    session: AsyncSession,
    case: Case,
    all_artifacts: list[CaseArtifact],
) -> ValidationResult:
    """Validate checklist completeness from classified artifact subtypes."""
    subtypes: list[ArtifactSubtype] = []
    for artifact in all_artifacts:
        meta = artifact.metadata_json or {}
        subtype_str = meta.get("subtype")
        if subtype_str:
            with contextlib.suppress(ValueError):
                subtypes.append(ArtifactSubtype(subtype_str))

    validation = validate_completeness(subtypes)

    # Upsert ChecklistValidationResult (UNIQUE on case_id)
    stmt = pg_insert(ChecklistValidationResult).values(
        case_id=case.id,
        is_complete=validation.is_complete,
        missing_docs=validation.missing_docs,
        present_docs=validation.present_docs,
        validated_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["case_id"],
        set_={
            "is_complete": stmt.excluded.is_complete,
            "missing_docs": stmt.excluded.missing_docs,
            "present_docs": stmt.excluded.present_docs,
            "validated_at": stmt.excluded.validated_at,
        },
    )
    await session.execute(stmt)

    _log.info(
        "_run_checklist_validation: case %s is_complete=%s missing=%d",
        case.id,
        validation.is_complete,
        len(validation.missing_docs),
    )
    return validation


# ---------------------------------------------------------------------------
# Step 8: Final stage transition
# ---------------------------------------------------------------------------


async def _transition_final_stage(
    session: AsyncSession,
    case: Case,
    validation: ValidationResult,
    worker_id: UUID,
) -> None:
    """Transition case to final stage based on checklist completeness."""
    if not validation.is_complete:
        # CHECKLIST_VALIDATION → CHECKLIST_MISSING_DOCS
        await stages_svc.transition_stage(
            session,
            case=case,
            to=CaseStage.CHECKLIST_MISSING_DOCS,
            actor_user_id=worker_id,
        )
        _log.info(
            "_transition_final_stage: case %s → CHECKLIST_MISSING_DOCS",
            case.id,
        )
    else:
        # CHECKLIST_VALIDATION → CHECKLIST_VALIDATED → INGESTED (two transitions)
        await stages_svc.transition_stage(
            session,
            case=case,
            to=CaseStage.CHECKLIST_VALIDATED,
            actor_user_id=worker_id,
        )
        await stages_svc.transition_stage(
            session,
            case=case,
            to=CaseStage.INGESTED,
            actor_user_id=worker_id,
        )
        _log.info(
            "_transition_final_stage: case %s → CHECKLIST_VALIDATED → INGESTED",
            case.id,
        )


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


async def _send_missing_docs_email_if_needed(
    session: AsyncSession,
    case: Case,
    validation: ValidationResult,
) -> None:
    """Send missing-docs email to the uploader when checklist is incomplete."""
    if validation.is_complete:
        return

    # Load the uploader's email
    user_result = await session.execute(select(User).where(User.id == case.uploaded_by))
    uploader: User | None = user_result.scalar_one_or_none()

    if uploader is None or not uploader.email:
        _log.warning(
            "_send_missing_docs_email_if_needed: no uploader email for case %s",
            case.id,
        )
        return

    settings = get_settings()
    email_svc = get_email_service()

    try:
        await email_svc.send(
            to=uploader.email,
            template="missing_docs",
            context={
                "case_id": str(case.id),
                "loan_id": case.loan_id,
                "applicant_name": case.applicant_name or "Applicant",
                "missing_docs_list": validation.missing_docs,
                "link_to_case_url": f"{settings.app_base_url}/cases/{case.id}",
            },
            subject=f"Missing Documents – Loan {case.loan_id}",
        )
        _log.info(
            "_send_missing_docs_email_if_needed: sent missing-docs email to user=%s case=%s",
            uploader.id,
            case.id,
        )
    except Exception:
        _log.exception(
            "_send_missing_docs_email_if_needed: failed to send email for case %s",
            case.id,
        )
