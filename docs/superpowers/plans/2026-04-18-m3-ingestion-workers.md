# Milestone 3: Ingestion Workers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the ingestion pipeline that consumes M2's SQS jobs, unpacks case ZIPs, classifies and extracts content from 5 source types (Auto CAM xlsx, Checklist xlsx, PD Sheet docx, Equifax HTML, bank statement PDF), runs dedupe + checklist completeness, transitions stages, and emails uploaders on missing docs.

**Architecture:** Separate worker container running a deterministic pipeline. Five deterministic extractors (no LLM calls in M3). JSONB-based extraction storage for schema flexibility. LocalStack SES for dev emails. Idempotent pipeline via stable-hash artifact keys + upserts.

**Tech Stack:** Python 3.12 + existing M1/M2 stack + new deps: `pdfplumber`, `beautifulsoup4`, `lxml`, `rapidfuzz`, `jinja2`. LocalStack services extended to include SES.

**Builds on:** M2 (tagged `m2-case-upload-storage`, merged at `ca0e57a`).

**Spec reference:** `docs/superpowers/specs/2026-04-18-m3-ingestion-workers-design.md` — implementers should read the relevant section when prompted.

**Definition of done:** Spec §15. 126 existing tests still pass; new tests bring total to ~200+, coverage ≥ 85% on new code, ruff + mypy clean, E2E ZIP upload flows all the way to `INGESTED` state.

---

## File structure for M3

```
backend/
├── app/
│   ├── enums.py                         # MODIFY — add ArtifactSubtype, ExtractionStatus, DedupeMatchType
│   ├── config.py                        # MODIFY — add SES + worker + flag settings
│   ├── models/
│   │   ├── case_extraction.py           # NEW
│   │   ├── checklist_validation_result.py  # NEW
│   │   ├── dedupe_snapshot.py           # NEW
│   │   └── dedupe_match.py              # NEW
│   ├── services/
│   │   ├── stages.py                    # MODIFY — add reverse transitions
│   │   ├── email.py                     # NEW — SES wrapper
│   │   └── cases.py                     # MODIFY — add_artifact re-triggers pipeline
│   ├── schemas/
│   │   ├── extraction.py                # NEW — CaseExtractionRead, ChecklistValidationResultRead, DedupeMatchRead
│   │   └── dedupe_snapshot.py           # NEW
│   ├── api/routers/
│   │   ├── cases.py                     # MODIFY — add read endpoints for extractions/validation/dedupe; add reingest
│   │   └── dedupe_snapshots.py          # NEW — upload + list + view-active
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── __main__.py                  # NEW — `python -m app.worker` entrypoint
│   │   ├── system_user.py               # NEW — get_or_create worker@system user
│   │   ├── classifier.py                # NEW — filename + content → ArtifactSubtype
│   │   ├── pipeline.py                  # NEW — process_ingestion_job orchestrator
│   │   ├── checklist_validator.py       # NEW
│   │   ├── dedupe.py                    # NEW — exact + fuzzy match
│   │   └── extractors/
│   │       ├── __init__.py
│   │       ├── base.py                  # NEW — ExtractionResult dataclass, BaseExtractor abstract
│   │       ├── auto_cam.py              # NEW
│   │       ├── checklist.py             # NEW
│   │       ├── pd_sheet.py              # NEW
│   │       ├── equifax.py               # NEW
│   │       └── bank_statement.py        # NEW
│   ├── templates/
│   │   ├── missing_docs.html            # NEW — Jinja2
│   │   └── missing_docs.txt             # NEW
│   └── startup.py                       # MODIFY — ensure SES identity in dev
├── alembic/versions/
│   └── <hash>_m3_ingestion_tables.py    # NEW
└── tests/
    ├── fixtures/
    │   ├── __init__.py
    │   ├── builders/                     # NEW — programmatic fixture generators
    │   │   ├── auto_cam_builder.py
    │   │   ├── checklist_builder.py
    │   │   ├── pd_sheet_builder.py
    │   │   ├── equifax_builder.py
    │   │   ├── bank_statement_builder.py
    │   │   ├── dedupe_builder.py
    │   │   └── case_zip_builder.py
    │   └── README.md                    # documents how fixtures are regenerated
    ├── unit/
    │   ├── test_classifier.py           # NEW
    │   ├── test_checklist_validator.py  # NEW
    │   └── test_extractors_*.py         # NEW — one per extractor
    └── integration/
        ├── test_pipeline.py             # NEW — end-to-end on fixture ZIP
        ├── test_email_service.py        # NEW
        ├── test_dedupe.py               # NEW
        ├── test_dedupe_snapshots_router.py  # NEW
        └── test_e2e_seema_ingestion.py  # NEW — skipped if Seema ZIP absent

docker-compose.yml                       # MODIFY — add worker service, enable SES in LocalStack
```

Each module has one clear responsibility. Extractors share `BaseExtractor` interface so the pipeline dispatches polymorphically.

---

## Task 1: Deps, config, LocalStack SES, worker container

**Files:** `backend/pyproject.toml`, `backend/app/config.py`, `.env.example`, `docker-compose.yml`

- [ ] Add deps: `poetry add pdfplumber beautifulsoup4 lxml rapidfuzz jinja2` (non-dev group)
- [ ] Append to `Settings`:

```python
    # SES
    ses_sender: str = "no-reply@pflfinance.com"
    ses_verify_on_startup: bool = True
    # Worker
    worker_poll_interval_seconds: int = 20
    worker_concurrency: int = 1
    # Ingestion feature flags (M5 flips these)
    enable_bank_statement_deep_parse: bool = False
    enable_photo_classification: bool = False
    enable_kyc_video_analysis: bool = False
    # Web app base URL (for email links)
    app_base_url: str = "http://localhost:8000"
```

- [ ] `.env.example`: add `SES_SENDER`, `SES_VERIFY_ON_STARTUP=true`, `APP_BASE_URL=http://localhost:8000`, `WORKER_POLL_INTERVAL_SECONDS=20`
- [ ] `docker-compose.yml`:
  - LocalStack env: change `SERVICES=s3,sqs` → `SERVICES=s3,sqs,ses`
  - New service `worker`: same build as backend, different `command: python -m app.worker`, same env + depends_on as backend
- [ ] Verify: `docker compose config >/dev/null && echo OK`; `docker compose up -d localstack`; check `curl -s http://localhost:4566/_localstack/health | grep ses`
- [ ] Run all existing tests: `poetry run pytest -q` → 126 passing
- [ ] Commit: `feat(m3): deps (pdfplumber, bs4, rapidfuzz, jinja2), SES config, worker container`

---

## Task 2: Enums + stage machine reverse transitions

**Files:** `backend/app/enums.py`, `backend/app/services/stages.py`, `backend/tests/unit/test_stages.py`, `backend/tests/unit/test_enums.py`

- [ ] Append to `enums.py`:

```python
class ArtifactSubtype(StrEnum):
    """Fine-grained classification of case artifacts. M3 classifier output."""
    KYC_AADHAAR = "KYC_AADHAAR"
    KYC_PAN = "KYC_PAN"
    KYC_VOTER = "KYC_VOTER"
    KYC_DL = "KYC_DL"
    KYC_PASSPORT = "KYC_PASSPORT"
    RATION_CARD = "RATION_CARD"
    ELECTRICITY_BILL = "ELECTRICITY_BILL"
    BANK_ACCOUNT_PROOF = "BANK_ACCOUNT_PROOF"
    INCOME_PROOF = "INCOME_PROOF"
    CO_APPLICANT_AADHAAR = "CO_APPLICANT_AADHAAR"
    CO_APPLICANT_PAN = "CO_APPLICANT_PAN"
    AUTO_CAM = "AUTO_CAM"
    CHECKLIST = "CHECKLIST"
    PD_SHEET = "PD_SHEET"
    EQUIFAX_HTML = "EQUIFAX_HTML"
    CIBIL_HTML = "CIBIL_HTML"
    HIGHMARK_HTML = "HIGHMARK_HTML"
    EXPERIAN_HTML = "EXPERIAN_HTML"
    BANK_STATEMENT = "BANK_STATEMENT"
    HOUSE_VISIT_PHOTO = "HOUSE_VISIT_PHOTO"
    BUSINESS_PREMISES_PHOTO = "BUSINESS_PREMISES_PHOTO"
    KYC_VIDEO = "KYC_VIDEO"
    LOAN_AGREEMENT = "LOAN_AGREEMENT"
    DPN = "DPN"
    LAPP = "LAPP"
    LAGR = "LAGR"
    NACH = "NACH"
    KFS = "KFS"
    UDYAM_REG = "UDYAM_REG"
    UNKNOWN = "UNKNOWN"


class ExtractionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DedupeMatchType(StrEnum):
    AADHAAR = "AADHAAR"
    PAN = "PAN"
    MOBILE = "MOBILE"
    DOB_NAME = "DOB_NAME"
```

- [ ] In `stages.py` `ALLOWED_TRANSITIONS` dict, add these entries (extend existing sets):

```python
    CaseStage.INGESTED: {CaseStage.PHASE_1_DECISIONING, CaseStage.CHECKLIST_VALIDATION},  # re-ingest path
    CaseStage.CHECKLIST_VALIDATED: {CaseStage.INGESTED, CaseStage.CHECKLIST_VALIDATION},   # re-ingest path
```

- [ ] Append tests to `test_stages.py`:

```python
def test_reingest_from_ingested_to_checklist_validation():
    validate_transition(CaseStage.INGESTED, CaseStage.CHECKLIST_VALIDATION)

def test_reingest_from_validated_back_to_validation():
    validate_transition(CaseStage.CHECKLIST_VALIDATED, CaseStage.CHECKLIST_VALIDATION)

def test_ingested_still_allows_phase_1_decisioning():
    validate_transition(CaseStage.INGESTED, CaseStage.PHASE_1_DECISIONING)
```

- [ ] Append to `test_enums.py`:

```python
def test_artifact_subtype_has_29_values():
    assert len(list(ArtifactSubtype)) == 29

def test_extraction_status_three_values():
    assert len(list(ExtractionStatus)) == 3

def test_dedupe_match_type_four_values():
    assert len(list(DedupeMatchType)) == 4
```

- [ ] Run tests: expect full suite passing + new tests green
- [ ] Commit: `feat(m3): ArtifactSubtype + ExtractionStatus + DedupeMatchType enums; stage machine re-ingest transitions`

---

## Task 3: Models + migration for extraction/validation/dedupe tables

**Files:** `backend/app/models/{case_extraction,checklist_validation_result,dedupe_snapshot,dedupe_match}.py`, `backend/app/models/__init__.py`, new Alembic migration

**Reference:** Spec §3.1, §3.2, §3.3, §3.4.

- [ ] Create each model file. Apply the partial-unique-index pattern for `case_extractions` (§3.1 has the SQL). Use `PgEnum(create_type=True)` on each enum column with `values_callable=lambda e: [v.value for v in e]` (follow M2 pattern exactly).
- [ ] Update `models/__init__.py` to re-export all four new models.
- [ ] Generate migration: `poetry run alembic revision --autogenerate -m "m3 ingestion tables"`
- [ ] Review generated migration. Then manually add the two partial indexes for `case_extractions` — autogenerate does not produce `postgresql_where` conditions without explicit hints. Use `op.create_index(..., postgresql_where=sa.text("artifact_id IS NOT NULL"))` and `op.create_index(..., postgresql_where=sa.text("artifact_id IS NULL"))`. Remove the full unique constraint autogenerate may create on `(case_id, extractor_name, artifact_id)` if it appears.
- [ ] Also add partial unique index on `dedupe_snapshots(is_active) WHERE is_active = true` (§3.3) — will be autogenerated as full unique, modify to partial.
- [ ] Apply: `poetry run alembic upgrade head`. Verify with `\d case_extractions` — should show two partial indexes.
- [ ] Verify tests pass
- [ ] Commit: `feat(m3): extraction, checklist_validation, dedupe models + migration with partial indexes`

---

## Task 4: System worker user + pydantic schemas

**Files:** `backend/app/worker/__init__.py` (empty), `backend/app/worker/system_user.py`, `backend/app/schemas/extraction.py`, `backend/app/schemas/dedupe_snapshot.py`

- [ ] `system_user.py`:

```python
"""Get-or-create the well-known worker system user.

Called once per worker process boot. Uses a stable email so lookups are idempotent.
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.enums import UserRole
from app.models.user import User
from app.services import users as users_svc
import secrets

WORKER_EMAIL = "worker@system.pflfinance.internal"


async def get_or_create_worker_user(session: AsyncSession) -> User:
    existing = await users_svc.get_user_by_email(session, WORKER_EMAIL)
    if existing is not None:
        return existing
    user = User(
        email=WORKER_EMAIL,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        full_name="System Worker",
        role=UserRole.AI_ANALYSER,
        mfa_enabled=False,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user
```

- [ ] `schemas/extraction.py`: Pydantic schemas with `from_attributes=True` for `CaseExtractionRead`, `ChecklistValidationResultRead`, `DedupeMatchRead`. Include fields from §3.1/§3.2/§3.4.
- [ ] `schemas/dedupe_snapshot.py`: `DedupeSnapshotRead` (id, uploaded_by, uploaded_at, row_count, is_active, download_url|None).
- [ ] Unit test for `get_or_create_worker_user` — verifies idempotency (two calls return same ID)
- [ ] Commit: `feat(m3): worker system user + extraction/dedupe-snapshot Pydantic schemas`

---

## Task 5: Fixture builders

**Files:** `backend/tests/fixtures/builders/*.py`, `backend/tests/fixtures/README.md`

**Reference:** Spec §10.

Create programmatic builders that produce minimal valid fixture files. No customer data — all synthetic.

- [ ] `auto_cam_builder.py::build_auto_cam_xlsx(path: Path, **overrides)` — uses openpyxl to create xlsx with the 4 expected sheets (SystemCam, Elegibilty, CM CAM IL, Health Sheet). Populate key cells (applicant name, DOB, PAN, loan amount, CIBIL score, FOIR, Health Sheet totals). Default values resemble the Seema case; overrides via kwargs.
- [ ] `checklist_builder.py::build_checklist_xlsx(path: Path, yes_keys, no_keys, na_keys)` — one-sheet checklist with section headers + item rows with "Yes"/"No"/"NA" values.
- [ ] `pd_sheet_builder.py::build_pd_sheet_docx(path: Path, fields)` — uses python-docx to create a minimal PD Sheet with a table of Q/A pairs.
- [ ] `equifax_builder.py::build_equifax_html(path: Path, score, accounts, inquiries, addresses)` — generates a minimal HTML document with Equifax-style structure.
- [ ] `bank_statement_builder.py::build_bank_statement_pdf(path: Path, account_holder, transactions)` — uses reportlab (new dev dep) to produce a PDF with account header + transaction table.
- [ ] `dedupe_builder.py::build_dedupe_xlsx(path: Path, customers: list[dict])` — produces xlsx matching the Customer_Dedupe format (§3.3).
- [ ] `case_zip_builder.py::build_case_zip(path: Path, **kwargs)` — assembles all builders into a zip matching the Seema folder structure (e.g., `20007897_OTH/`, `20007897_BUSINESS_PREMISES/`, `20007897_HOUSE_VISIT/`).
- [ ] Add `reportlab` to dev deps: `poetry add --group dev reportlab`
- [ ] `fixtures/README.md`: document builder usage; state that no real customer data is committed.
- [ ] Tiny verification test per builder: build to tmp_path, assert file exists and has expected size/structure.
- [ ] Commit: `test(m3): fixture builders for all extractor source formats`

---

## Task 6: File classifier + tests

**Files:** `backend/app/worker/classifier.py`, `backend/tests/unit/test_classifier.py`

**Reference:** Spec §4.3.

- [ ] Write failing tests first. Cover:
  - Seema-style filenames: `10006484_AADHAR_1.jpeg` → `KYC_AADHAAR`, `AUTO_CAM-SEEMA.xlsx` → `AUTO_CAM`, `Checklist_-Seema.xlsx` → `CHECKLIST`, `PD_Sheet.docx` → `PD_SHEET`, `EQUIFAX_CREDIT_REPORT.html` → `EQUIFAX_HTML`, `BANK_STATEMENT_(1).pdf` → `BANK_STATEMENT`, `KYCVideo.mp4` → `KYC_VIDEO`
  - Folder-based: `20007897_BUSINESS_PREMISES/photo.jpeg` → `BUSINESS_PREMISES_PHOTO`, `20007897_HOUSE_VISIT/photo.jpeg` → `HOUSE_VISIT_PHOTO`
  - Loan docs: `10006484_LAPP_1.pdf` → `LAPP`, `10006484_LAGR_1.pdf` → `LAGR`, `10006484_DPN_1.pdf` → `DPN`, `10006484_NACH_1.jpeg` → `NACH`
  - Unknown: `random.txt` → `UNKNOWN`
  - Content-based fallback: xlsx without obvious name but containing "CREDIT ASSESSMENT" cell → likely `AUTO_CAM`
- [ ] Implement classifier as a decision tree: filename regex → folder hints → content inspection (only for xlsx/html) → `UNKNOWN` default
- [ ] Signature: `classify(filename: str, folder_path: str | None = None, body_bytes: bytes | None = None) -> ArtifactSubtype`
- [ ] Tests must pass, 100% coverage on classifier
- [ ] Commit: `feat(m3): file classifier with filename + folder + content heuristics`

---

## Task 7: Base extractor interface + all 5 extractors

**Files:** `backend/app/worker/extractors/*.py`, `backend/tests/unit/test_extractors_*.py`

**Reference:** Spec §4.4.1–§4.4.5.

Batch because extractors share the base interface and tests run similarly.

- [ ] `extractors/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.enums import ExtractionStatus


@dataclass
class ExtractionResult:
    status: ExtractionStatus
    schema_version: str
    data: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None


class BaseExtractor(ABC):
    extractor_name: str = ""
    schema_version: str = "1.0"

    @abstractmethod
    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult: ...
```

**Signature rationale:** `(filename, body_bytes)` is used here (deviates from spec §4.4's `(artifact, body_bytes)` suggestion) so extractor unit tests don't have to construct `CaseArtifact` ORM objects. The pipeline in Task 11 passes only the filename + bytes it already has in memory from unpacking. This is consistent — all extractors and the pipeline use this signature.

- [ ] `auto_cam.py` (openpyxl-based). Define a dict of cell coordinates per sheet → extracted field name. Parse in bulk. Cite the spec §4.4.1 field list for completeness. Return PARTIAL if a sheet is missing, SUCCESS if all 4 present.
- [ ] `checklist.py` (openpyxl-based). Iterate rows; collect `(section, item, value, remarks)` tuples. Aggregate counts.
- [ ] `pd_sheet.py` (python-docx). Extract paragraphs + table data; look for specific headings.
- [ ] `equifax.py` (beautifulsoup4 + lxml). Target specific DOM structures that Equifax uses: score in `.CreditScore`, accounts in table rows, etc. Use resilient selectors with fallbacks.
- [ ] `bank_statement.py` (pdfplumber). Extract text per page; regex for account number, period, opening/closing balance, transaction-like lines. Don't try to be smart — M5 will re-process.

Tests per extractor: use the fixtures from Task 5. One happy path + one degraded (missing field) path per extractor. 10+ tests total.

- [ ] Commit: `feat(m3): five extractors (auto_cam, checklist, pd_sheet, equifax, bank_statement) with unit tests`

---

## Task 8: Checklist validator + tests

**Files:** `backend/app/worker/checklist_validator.py`, `backend/tests/unit/test_checklist_validator.py`

**Reference:** Spec §4.6.

- [ ] Function `validate_completeness(artifacts: list[CaseArtifact]) -> ValidationResult`
- [ ] Required doc list constant (spec §4.6) — separate hard vs soft
- [ ] Returns `{is_complete, missing_docs: [{doc_type, reason}], present_docs: [...]}`
- [ ] Tests: all required present → complete; missing Aadhaar → incomplete with reason; minimum photos count enforced (≥3 house, ≥3 business)
- [ ] Commit: `feat(m3): checklist completeness validator`

---

## Task 9: Dedupe service + tests

**Files:** `backend/app/worker/dedupe.py`, `backend/tests/integration/test_dedupe.py`

**Reference:** Spec §4.5.

- [ ] Load active dedupe snapshot from DB; if none → return empty matches with warning. If present → read xlsx via openpyxl.
- [ ] Exact match on Aadhaar/PAN/Mobile; fuzzy on (name+DOB) using `rapidfuzz.fuzz.token_sort_ratio`
- [ ] Normalization: uppercase, strip whitespace, remove spl chars
- [ ] Returns list of `DedupeMatch` rows (not yet persisted)
- [ ] Tests: exact Aadhaar hit; fuzzy name hit at score 90; no match; no snapshot → empty list + warning
- [ ] Commit: `feat(m3): dedupe service with exact + fuzzy matching`

---

## Task 10: Email service + template + tests

**Files:** `backend/app/services/email.py`, `backend/app/templates/missing_docs.{html,txt}`, `backend/tests/integration/test_email_service.py`

**Reference:** Spec §4.7.

- [ ] `EmailService` class with `send(to: str, template: str, context: dict)` method. Uses aioboto3 `ses.send_email`. Loads templates from `app/templates/`.
- [ ] Module-level singleton `get_email_service()` following storage/queue pattern.
- [ ] Reset fn for tests.
- [ ] Templates: minimal HTML + text version, Jinja2 variables per spec
- [ ] Tests using moto SES: send an email, verify stats via `ses.get_send_statistics`
- [ ] Startup.py extension: `await ses.verify_email_identity(EmailAddress=settings.ses_sender)` when `ses_verify_on_startup=True`
- [ ] Commit: `feat(m3): email service with SES + missing-docs templates`

---

## Task 11: Worker pipeline orchestrator + main entrypoint

**Files:** `backend/app/worker/pipeline.py`, `backend/app/worker/__main__.py`, `backend/tests/integration/test_pipeline.py`

**Reference:** Spec §4.2.

- [ ] `pipeline.py::process_ingestion_job(payload: dict)`:
  - Open a DB session via AsyncSessionLocal
  - Lookup case
  - Pre-flight stage reset (§3.5)
  - Download ZIP, unpack, create artifacts (idempotent via stable-hash s3_key)
  - Dispatch to extractors, upsert CaseExtraction
  - Run dedupe, clear previous matches, insert new
  - Run checklist validator, upsert result
  - Transition stage + send email if missing
  - Commit
- [ ] `__main__.py`:

```python
import asyncio
import logging
from app.config import get_settings
from app.db import AsyncSessionLocal
from app.services.queue import get_queue
from app.worker.pipeline import process_ingestion_job
from app.worker.system_user import get_or_create_worker_user

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)


async def main():
    _log.info("PFL ingestion worker starting")
    # Ensure system user exists once
    async with AsyncSessionLocal() as session:
        user = await get_or_create_worker_user(session)
        await session.commit()
    _log.info("System worker user: %s", user.id)

    queue = get_queue()
    settings = get_settings()

    while True:
        try:
            await queue.consume_jobs(
                handler=process_ingestion_job,
                wait_seconds=settings.worker_poll_interval_seconds,
            )
        except Exception:
            _log.exception("Worker loop iteration failed")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] Integration test: build fixture ZIP, upload to moto S3 with moto SQS message, call `process_ingestion_job` directly, verify DB state (artifacts, extractions, checklist, dedupe, stage, audit entries).
- [ ] Commit: `feat(m3): worker pipeline orchestrator + main entrypoint`

---

## Task 12: Modify cases service — add_artifact triggers re-validation

**Files:** `backend/app/services/cases.py`, `backend/tests/integration/test_cases_service.py`

**Reference:** Spec §3.5.

- [ ] Modify `add_artifact` signature to accept `queue: QueueService` as a new keyword-only argument. Update the caller in `backend/app/api/routers/cases.py::add_artifact` to inject the queue via the existing `get_queue_dep` dependency. All existing test call sites need the `queue=` kwarg too (use `queue_svc` fixture).
- [ ] In `add_artifact` service function:
  - After successful artifact creation (post-audit-log), check `case.current_stage == CHECKLIST_MISSING_DOCS`
  - If yes: transition back to `CHECKLIST_VALIDATION` via `stages_svc.transition_stage(... actor_user_id=actor.id)`; publish a new ingestion SQS job with `{"case_id": str(case.id), "loan_id": case.loan_id, "zip_s3_key": case.zip_s3_key, "trigger": "artifact_added"}`; log `case.reingestion_triggered` audit entry with `after_json={"reason": "artifact_added"}`
- [ ] Append test: add artifact to case in CHECKLIST_MISSING_DOCS → case stage back to CHECKLIST_VALIDATION, queue has a new message
- [ ] Commit: `feat(m3): add_artifact re-triggers ingestion when case is in CHECKLIST_MISSING_DOCS`

---

## Task 13: Dedupe snapshots router + tests

**Files:** `backend/app/api/routers/dedupe_snapshots.py`, `backend/tests/integration/test_dedupe_snapshots_router.py`, `backend/app/main.py` (wire)

**Reference:** Spec §5.1.

- [ ] Endpoints:
  - `POST /dedupe-snapshots` admin-only, multipart upload, 50 MB max (reuse `max_artifact_size_bytes`), deactivates all previous + marks new as active
  - `GET /dedupe-snapshots` admin+ceo+credit_ho — list
  - `GET /dedupe-snapshots/active` — return active or 404
- [ ] Wire router into main.py
- [ ] Tests cover: only admin can POST, active swap is atomic (prior snapshot deactivated), empty list returns empty array, 404 if no active
- [ ] Commit: `feat(m3): dedupe snapshots router with upload + list + active endpoints`

---

## Task 14: Case read endpoints for extractions/validation/dedupe + reingest

**Files:** `backend/app/api/routers/cases.py` (extend), `backend/tests/integration/test_cases_router.py`

**Reference:** Spec §5.2, §5.3.

- [ ] Add endpoints on existing cases router:
  - `GET /cases/{id}/extractions` — all extractions rows for case
  - `GET /cases/{id}/extractions/{extractor_name}` — specific extractor
  - `GET /cases/{id}/checklist-validation` — current validation result
  - `GET /cases/{id}/dedupe-matches` — all matches
  - `POST /cases/{id}/reingest` admin-only — pre-condition check, publish SQS job with `trigger="reingest"`, log audit
- [ ] Tests cover: reingest from valid stage (200) + invalid stage (409), non-admin rejected (403), extraction list returns rows, missing extraction returns 404
- [ ] Commit: `feat(m3): case extraction/validation/dedupe read endpoints + reingest endpoint`

---

## Task 15: E2E test with real Seema ZIP

**Files:** `backend/tests/integration/test_e2e_seema_ingestion.py`

Pattern from M2. Skipped if ZIP absent. Asserts on specific values:
- Applicant name SEEMA
- CIBIL score matches Equifax report number (~769)
- Loan amount 150000
- Stage ends at `INGESTED` if all docs present (or `CHECKLIST_MISSING_DOCS` with expected missing list)
- Queue has the original message marked deleted after successful processing

- [ ] Commit: `test(m3): E2E Seema ZIP ingestion test (skipped if ZIP absent)`

---

## Task 16: Coverage polish + lint/type + README + M3 tag

**Files:** various tests, README

- [ ] Run `poetry run pytest --cov=app --cov-report=term-missing`
- [ ] Fill coverage gaps to ≥ 85% on new modules
- [ ] `poetry run ruff format app tests && poetry run ruff check app tests`
- [ ] `poetry run mypy app`
- [ ] Fix any issues
- [ ] Update README: add "M3 ✅" section with brief summary + updated roadmap
- [ ] Commit: `test(m3): fill coverage gaps, fix lint and type`
- [ ] Commit: `docs(m3): README update`
- [ ] Tag: `git tag -a m3-ingestion-workers -m "M3 complete: Ingestion workers, extractors, dedupe, validation, email"`

---

## M3 Exit Criteria

- [ ] docker compose up -d boots Postgres + backend + worker + LocalStack (all services)
- [ ] Worker logs show "PFL ingestion worker starting" + "System worker user: <uuid>"
- [ ] Upload a fixture ZIP via POST /cases/initiate + finalize → worker picks up SQS message → case transitions to INGESTED within seconds (or CHECKLIST_MISSING_DOCS with email sent)
- [ ] All 5 extractors work on fixture files
- [ ] Dedupe matches work when snapshot is present; skip gracefully when absent
- [ ] Re-ingestion endpoint works + is idempotent
- [ ] add_artifact re-triggers pipeline when case is in MISSING_DOCS
- [ ] ≥ 85% coverage on new code
- [ ] Ruff + mypy clean
- [ ] Tag created, merge to main with --no-ff

---

## Cross-reference to spec

| Task | Spec section |
|---|---|
| T1 | §2.1, §11, §12, §13 |
| T2 | §3.5, spec enums |
| T3 | §3.1–§3.4 |
| T4 | §4.2a, §5 schemas |
| T5 | §10 |
| T6 | §4.3 |
| T7 | §4.4.1–§4.4.5 |
| T8 | §4.6 |
| T9 | §4.5 |
| T10 | §4.7, §8 |
| T11 | §4.2 |
| T12 | §3.5 |
| T13 | §5.1 |
| T14 | §5.2, §5.3 |
| T15 | §9.3 |
| T16 | §9.4, §15 |

---

*End of M3 plan.*
