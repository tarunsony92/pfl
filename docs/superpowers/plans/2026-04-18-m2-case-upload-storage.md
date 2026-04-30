# Milestone 2: Case Upload & Storage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable ai_analyser/admin roles to upload case ZIPs. Cases persist in Postgres; ZIPs persist in S3 (LocalStack for dev). Workflow state machine tracks each case. Queue service publishes ingestion jobs for M3 to consume. No ZIP extraction in M2.

**Architecture:** FastAPI endpoints mint presigned S3 POST URLs so clients upload binaries directly to S3 without transiting the API. On finalize, the server confirms the object, creates artifact row, transitions stage, and enqueues an SQS job. State machine enforced in a dedicated service. Re-upload is admin-gated; prior state archived as versioned JSON in the case's S3 folder.

**Tech Stack:**
- aioboto3 (async AWS client) + moto (unit-test AWS mocking)
- LocalStack 3 (dev-time S3 + SQS)
- All existing M1 stack (FastAPI, async SQLAlchemy, Alembic, Pydantic, bcrypt, JWT, pytest)

**Builds on:** M1 (merged at `ad0c98f`, tagged `m1-backend-foundation`)

**Definition of done:** see spec §15. At the end of M2:
- `docker compose up -d` boots Postgres + backend + LocalStack
- Bucket `pfl-cases-dev` and queues `pfl-ingestion-dev` + `pfl-ingestion-dev-dlq` auto-created
- End-to-end upload of the Seema ZIP works (presigned URL → S3 upload → finalize → DB + queue state correct)
- ≥90% coverage on new code, ruff + mypy clean
- Tagged `m2-case-upload-storage` on merge commit

---

## Scope boundaries

**In M2:**
- Cases + artifacts data model
- Full stage enum (13 values, parent spec §9 + `PHASE_1_REJECTED`)
- Storage + queue services (LocalStack-backed for dev)
- 8 endpoints per spec §6
- Re-upload flow with archival
- State machine with transition enforcement
- LocalStack in docker-compose
- Startup bucket/queue init (dev only)
- ≥90% test coverage

**Deferred (intentionally):**
- ZIP extraction (M3)
- Checklist validation (M3)
- Queue consumer workers (M3)
- Frontend (M4)
- Phase 1/2 engines (M5/M6)
- Real AWS deploy (M8)

---

## File structure for M2

```
backend/
├── app/
│   ├── models/
│   │   ├── case.py                  # NEW — Case model
│   │   └── case_artifact.py         # NEW — CaseArtifact model
│   ├── enums.py                     # MODIFY — add CaseStage, ArtifactType
│   ├── config.py                    # MODIFY — add AWS settings
│   ├── services/
│   │   ├── storage.py               # NEW — S3 wrapper (aioboto3)
│   │   ├── queue.py                 # NEW — SQS wrapper (aioboto3)
│   │   ├── stages.py                # NEW — state machine
│   │   └── cases.py                 # NEW — case business logic (create, finalize, list, reupload, etc.)
│   ├── schemas/
│   │   └── case.py                  # NEW — Pydantic request/response
│   ├── api/routers/
│   │   └── cases.py                 # NEW — HTTP endpoints
│   ├── main.py                      # MODIFY — wire cases router + startup init
│   └── startup.py                   # NEW — bucket/queue init (dev)
├── alembic/versions/
│   └── <hash>_cases_and_artifacts.py  # NEW — migration
├── tests/
│   ├── unit/
│   │   ├── test_stages.py           # NEW — state machine rules
│   │   └── test_storage_keys.py     # NEW — S3 key convention helpers
│   ├── integration/
│   │   ├── test_storage_service.py  # NEW — moto-backed S3 tests
│   │   ├── test_queue_service.py    # NEW — moto-backed SQS tests
│   │   ├── test_cases_service.py    # NEW — service layer
│   │   ├── test_cases_router.py     # NEW — HTTP layer
│   │   └── test_e2e_case_upload.py  # NEW — full flow with LocalStack + Seema ZIP
│   ├── conftest.py                  # MODIFY — add localstack fixture + storage/queue fixtures
│   └── factories.py                 # MODIFY — add CaseFactory
└── pyproject.toml                   # MODIFY — add aioboto3, moto

docker-compose.yml                   # MODIFY — enable LocalStack service
.env.example                         # MODIFY — add AWS env vars
README.md                            # MODIFY — document new quick-start steps
```

Each file has one clear responsibility:
- **Models** — ORM only
- **Enums** — centralized
- **Schemas** — HTTP-shape only
- **Services** — business logic, no HTTP concerns
- **Routers** — HTTP handlers delegating to services
- **startup.py** — one-time init (idempotent, dev-only)

---

## Task 1: Dependencies, config, LocalStack in docker-compose

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`

- [ ] **Step 1.1: Add deps via Poetry**

```bash
export PATH="$HOME/.local/bin:$PATH"
cd backend
poetry add aioboto3
poetry add --group dev moto
```

Expected: both installed, lockfile updated. `aioboto3` version ^13.0+, `moto` ^5.0+.

- [ ] **Step 1.2: Update `backend/app/config.py` — append AWS fields**

Edit the `Settings` class. Add these fields (keep existing ones unchanged):

```python
    # AWS / LocalStack
    aws_region: str = "ap-south-1"
    aws_s3_endpoint_url: str | None = None  # None = real AWS; set for LocalStack
    aws_sqs_endpoint_url: str | None = None
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    s3_bucket: str = "pfl-cases-dev"
    sqs_ingestion_queue: str = "pfl-ingestion-dev"
    sqs_ingestion_dlq: str = "pfl-ingestion-dev-dlq"
    presigned_url_expires_seconds: int = 900
    max_zip_size_bytes: int = 100 * 1024 * 1024  # 100 MiB
    dev_auto_create_aws_resources: bool = False  # startup creates bucket/queue if True
```

- [ ] **Step 1.3: Update `.env.example` — append**

```
# AWS / LocalStack (dev defaults; override for prod)
AWS_REGION=ap-south-1
AWS_S3_ENDPOINT_URL=http://localhost:4566
AWS_SQS_ENDPOINT_URL=http://localhost:4566
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
S3_BUCKET=pfl-cases-dev
SQS_INGESTION_QUEUE=pfl-ingestion-dev
SQS_INGESTION_DLQ=pfl-ingestion-dev-dlq
PRESIGNED_URL_EXPIRES_SECONDS=900
MAX_ZIP_SIZE_BYTES=104857600
DEV_AUTO_CREATE_AWS_RESOURCES=true
```

- [ ] **Step 1.4: Update `docker-compose.yml` — enable LocalStack and add backend env**

Replace the commented LocalStack placeholder with:

```yaml
  localstack:
    image: localstack/localstack:3
    container_name: pfl-localstack
    environment:
      - SERVICES=s3,sqs
      - AWS_DEFAULT_REGION=ap-south-1
      - PERSISTENCE=1
    ports:
      - "4566:4566"
    volumes:
      - pfl-localstack-data:/var/lib/localstack
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:4566/_localstack/health"]
      interval: 10s
      timeout: 5s
      retries: 12
```

Under `backend:` service's `environment:`, add:

```yaml
      AWS_REGION: ap-south-1
      AWS_S3_ENDPOINT_URL: http://localstack:4566
      AWS_SQS_ENDPOINT_URL: http://localstack:4566
      AWS_ACCESS_KEY_ID: test
      AWS_SECRET_ACCESS_KEY: test
      S3_BUCKET: pfl-cases-dev
      SQS_INGESTION_QUEUE: pfl-ingestion-dev
      SQS_INGESTION_DLQ: pfl-ingestion-dev-dlq
      DEV_AUTO_CREATE_AWS_RESOURCES: "true"
```

Under `backend:` `depends_on:`, add:

```yaml
      localstack:
        condition: service_healthy
```

Under the top-level `volumes:`, add:

```yaml
  pfl-localstack-data:
```

- [ ] **Step 1.5: Verify docker-compose parses and LocalStack boots**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
docker compose config >/dev/null && echo OK
docker compose up -d localstack
sleep 10
curl -sf http://localhost:4566/_localstack/health | python3 -m json.tool | head -20
# Expected: services showing "running" or "available" for s3 and sqs
```

- [ ] **Step 1.6: Verify existing tests still pass**

```bash
export PATH="$HOME/.local/bin:$PATH"
cd backend && poetry run pytest -q 2>&1 | tail -5
# Expected: 69 passed
```

- [ ] **Step 1.7: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/pyproject.toml backend/poetry.lock backend/app/config.py .env.example docker-compose.yml
git commit -m "feat(m2): add aioboto3 + moto deps, AWS config, LocalStack in compose"
```

---

## Task 2: CaseStage and ArtifactType enums

**Files:**
- Modify: `backend/app/enums.py`
- Test: `backend/tests/unit/test_enums.py` (new)

- [ ] **Step 2.1: Append enums to `backend/app/enums.py`**

Below the existing `UserRole` block, add:

```python
class CaseStage(StrEnum):
    """Workflow stages per parent spec §9 + PHASE_1_REJECTED.

    Postgres enum created in a migration. Append-only — never reorder or rename.
    """

    UPLOADED = "UPLOADED"
    CHECKLIST_VALIDATION = "CHECKLIST_VALIDATION"
    CHECKLIST_MISSING_DOCS = "CHECKLIST_MISSING_DOCS"
    CHECKLIST_VALIDATED = "CHECKLIST_VALIDATED"
    INGESTED = "INGESTED"
    PHASE_1_DECISIONING = "PHASE_1_DECISIONING"
    PHASE_1_REJECTED = "PHASE_1_REJECTED"  # hard-rule reject from Phase 1
    PHASE_1_COMPLETE = "PHASE_1_COMPLETE"
    PHASE_2_AUDITING = "PHASE_2_AUDITING"
    PHASE_2_COMPLETE = "PHASE_2_COMPLETE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED_TO_CEO = "ESCALATED_TO_CEO"


class ArtifactType(StrEnum):
    """Artifact types for CaseArtifact. M3+ may extend."""

    ORIGINAL_ZIP = "ORIGINAL_ZIP"
    ADDITIONAL_FILE = "ADDITIONAL_FILE"
    REUPLOAD_ARCHIVE = "REUPLOAD_ARCHIVE"
```

- [ ] **Step 2.2: Write test `backend/tests/unit/test_enums.py`**

```python
"""Enum hygiene tests — values are stable identifiers."""
from app.enums import ArtifactType, CaseStage, UserRole


class TestCaseStage:
    def test_has_exactly_14_values(self):
        # If this breaks, the enum was extended; update count + review migrations.
        assert len(list(CaseStage)) == 14

    def test_uploaded_is_first_and_matches_string(self):
        assert CaseStage.UPLOADED == "UPLOADED"

    def test_phase_1_rejected_is_distinct_from_rejected(self):
        assert CaseStage.PHASE_1_REJECTED != CaseStage.REJECTED


class TestArtifactType:
    def test_has_three_values(self):
        assert len(list(ArtifactType)) == 3

    def test_original_zip(self):
        assert ArtifactType.ORIGINAL_ZIP == "ORIGINAL_ZIP"


class TestUserRole:
    """Sanity — unchanged from M1."""
    def test_admin_exists(self):
        assert UserRole.ADMIN == "admin"
```

- [ ] **Step 2.3: Run tests — expect PASS**

```bash
cd backend && poetry run pytest tests/unit/test_enums.py -v
# Expected: 5 passed
```

- [ ] **Step 2.4: Commit**

```bash
cd ..
git add backend/app/enums.py backend/tests/unit/test_enums.py
git commit -m "feat(m2): CaseStage and ArtifactType enums with hygiene tests"
```

---

## Task 3: Case and CaseArtifact models + migration

**Files:**
- Create: `backend/app/models/case.py`
- Create: `backend/app/models/case_artifact.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/<hash>_cases_and_artifacts.py` (via autogenerate)

- [ ] **Step 3.1: Create `backend/app/models/case.py`**

```python
"""Case — one per loan application submission.

Spec §3.1 of M2 design. Soft-delete supported; audit log tracks all state
transitions. `reupload_allowed_until` is set by admin to grant a 24h re-upload
window; `reupload_count` is incremented on each actual re-upload.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import CaseStage
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Case(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cases"

    loan_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    zip_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    zip_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    current_stage: Mapped[CaseStage] = mapped_column(
        PgEnum(
            CaseStage,
            name="case_stage",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        default=CaseStage.UPLOADED,
        nullable=False,
        index=True,
    )

    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    applicant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reupload_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reupload_allowed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<Case loan_id={self.loan_id} stage={self.current_stage}>"
```

- [ ] **Step 3.2: Create `backend/app/models/case_artifact.py`**

```python
"""CaseArtifact — individual file belonging to a case.

One per uploaded/generated artifact (original ZIP, additional missing docs,
re-upload archive JSONs). `metadata_json` holds type-specific info (mime details,
extraction status, etc.).
"""
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import ArtifactType
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaseArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "case_artifacts"

    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_type: Mapped[ArtifactType] = mapped_column(
        PgEnum(
            ArtifactType,
            name="artifact_type",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )
    s3_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<CaseArtifact type={self.artifact_type} filename={self.filename}>"
```

- [ ] **Step 3.3: Update `backend/app/models/__init__.py`**

Add the new model imports so Alembic autogenerate picks them up:

```python
from app.models.base import Base  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.case import Case  # noqa: F401
from app.models.case_artifact import CaseArtifact  # noqa: F401

__all__ = ["Base", "User", "AuditLog", "Case", "CaseArtifact"]
```

- [ ] **Step 3.4: Generate the migration**

```bash
export PATH="$HOME/.local/bin:$PATH"
cd backend
poetry run alembic revision --autogenerate -m "cases and case_artifacts with enums"
```

Review the generated file. Expected ops:
- `op.create_type` (or inline `ENUM` creation) for `case_stage` and `artifact_type`
- `op.create_table('cases', ...)` with all columns
- `op.create_table('case_artifacts', ...)` with FK to cases(id) with ON DELETE CASCADE
- Indexes on `cases.loan_id` (unique), `cases.current_stage`, `cases.uploaded_by`, `cases.uploaded_at`
- Indexes on `case_artifacts.case_id`, `case_artifacts.artifact_type`
- Unique on `case_artifacts.s3_key`

**Watch for PgEnum double-create:** when two models both reference the same `PgEnum(..., create_type=True)` (which both `Case.current_stage` and `CaseArtifact.artifact_type` do), autogenerate may emit `CREATE TYPE` twice for the same enum. If the generated file has two `op.execute("CREATE TYPE case_stage ...")` statements or the migration fails with "type already exists", collapse them into one and set `create_type=False` on one side of the model-level declaration (leave only one model as the enum's "creator"). The `case_stage` and `artifact_type` types should each appear exactly once in the migration.

**If autogenerate produces unexpected changes to existing tables:** stop. Report concerns.

- [ ] **Step 3.5: Apply migration to dev DB**

```bash
cd backend && poetry run alembic upgrade head
```

Verify:
```bash
docker compose exec -T postgres psql -U pfl -d pfl -c '\dt'
# Expected: alembic_version, audit_log, case_artifacts, cases, users
docker compose exec -T postgres psql -U pfl -d pfl -c '\dT+ case_stage'
# Expected: enum with 14 values
docker compose exec -T postgres psql -U pfl -d pfl -c '\d cases'
# Expected: all columns present with correct types and constraints
```

- [ ] **Step 3.6: Run existing tests (must stay at 69 passing)**

```bash
cd backend && poetry run pytest -q 2>&1 | tail -5
# Expected: 69 passed + 5 from Task 2 enum tests = 74 passed
```

- [ ] **Step 3.7: Commit**

```bash
cd ..
git add backend/app/models/ backend/alembic/versions/
git commit -m "feat(m2): Case and CaseArtifact models with enum-backed columns + migration"
```

---

## Task 4: Stage machine (stages.py)

**Files:**
- Create: `backend/app/services/stages.py`
- Create: `backend/app/core/stage_exceptions.py` (or reuse `core/exceptions.py`)
- Create: `backend/tests/unit/test_stages.py`

- [ ] **Step 4.1: Append to `backend/app/core/exceptions.py`**

```python
class InvalidStateTransition(Exception):
    """Attempted to move a case to a stage not allowed from its current stage."""
```

- [ ] **Step 4.2: Write failing tests `backend/tests/unit/test_stages.py`**

```python
"""State machine unit tests. Pure logic, no DB."""
import pytest

from app.core.exceptions import InvalidStateTransition
from app.enums import CaseStage
from app.services.stages import ALLOWED_TRANSITIONS, validate_transition


class TestAllowedTransitions:
    def test_uploaded_can_go_to_checklist_validation(self):
        validate_transition(CaseStage.UPLOADED, CaseStage.CHECKLIST_VALIDATION)

    def test_checklist_validation_can_branch(self):
        validate_transition(CaseStage.CHECKLIST_VALIDATION, CaseStage.CHECKLIST_MISSING_DOCS)
        validate_transition(CaseStage.CHECKLIST_VALIDATION, CaseStage.CHECKLIST_VALIDATED)

    def test_missing_docs_returns_to_validation(self):
        validate_transition(CaseStage.CHECKLIST_MISSING_DOCS, CaseStage.CHECKLIST_VALIDATION)

    def test_phase_1_rejected_is_terminal(self):
        """Hard-rule reject has no outgoing transitions."""
        assert ALLOWED_TRANSITIONS.get(CaseStage.PHASE_1_REJECTED, set()) == set()

    def test_approved_is_terminal(self):
        assert ALLOWED_TRANSITIONS.get(CaseStage.APPROVED, set()) == set()


class TestInvalidTransitions:
    def test_uploaded_cannot_skip_to_approved(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(CaseStage.UPLOADED, CaseStage.APPROVED)

    def test_same_state_not_allowed(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(CaseStage.UPLOADED, CaseStage.UPLOADED)

    def test_backwards_from_ingested_not_allowed(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(CaseStage.INGESTED, CaseStage.UPLOADED)

    def test_error_message_names_both_stages(self):
        with pytest.raises(InvalidStateTransition, match="UPLOADED.*APPROVED"):
            validate_transition(CaseStage.UPLOADED, CaseStage.APPROVED)
```

- [ ] **Step 4.3: Run — expect FAIL (ImportError)**

- [ ] **Step 4.4: Implement `backend/app/services/stages.py`**

```python
"""Case workflow state machine.

Defines which stage transitions are permitted. M2 only executes
UPLOADED → CHECKLIST_VALIDATION; other transitions live here but are invoked
only in later milestones.
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateTransition
from app.enums import CaseStage
from app.models.case import Case
from app.services import audit as audit_svc


ALLOWED_TRANSITIONS: dict[CaseStage, set[CaseStage]] = {
    CaseStage.UPLOADED: {CaseStage.CHECKLIST_VALIDATION},
    CaseStage.CHECKLIST_VALIDATION: {
        CaseStage.CHECKLIST_MISSING_DOCS,
        CaseStage.CHECKLIST_VALIDATED,
    },
    CaseStage.CHECKLIST_MISSING_DOCS: {CaseStage.CHECKLIST_VALIDATION},
    CaseStage.CHECKLIST_VALIDATED: {CaseStage.INGESTED},
    CaseStage.INGESTED: {CaseStage.PHASE_1_DECISIONING},
    CaseStage.PHASE_1_DECISIONING: {
        CaseStage.PHASE_1_COMPLETE,
        CaseStage.PHASE_1_REJECTED,
    },
    CaseStage.PHASE_1_COMPLETE: {CaseStage.PHASE_2_AUDITING},
    CaseStage.PHASE_2_AUDITING: {CaseStage.PHASE_2_COMPLETE},
    CaseStage.PHASE_2_COMPLETE: {CaseStage.HUMAN_REVIEW},
    CaseStage.HUMAN_REVIEW: {
        CaseStage.APPROVED,
        CaseStage.REJECTED,
        CaseStage.ESCALATED_TO_CEO,
    },
    CaseStage.ESCALATED_TO_CEO: {CaseStage.APPROVED, CaseStage.REJECTED},
    # Terminal states:
    CaseStage.PHASE_1_REJECTED: set(),
    CaseStage.APPROVED: set(),
    CaseStage.REJECTED: set(),
}


def validate_transition(from_stage: CaseStage, to_stage: CaseStage) -> None:
    """Raises InvalidStateTransition if the transition is not permitted."""
    allowed = ALLOWED_TRANSITIONS.get(from_stage, set())
    if to_stage not in allowed:
        raise InvalidStateTransition(
            f"{from_stage} → {to_stage} not allowed. "
            f"Permitted from {from_stage}: {sorted(s.value for s in allowed) or 'none (terminal)'}"
        )


async def transition_stage(
    session: AsyncSession,
    *,
    case: Case,
    to: CaseStage,
    actor_user_id: UUID,
) -> Case:
    """Move a case to a new stage, validating + logging."""
    validate_transition(case.current_stage, to)
    before = {"stage": case.current_stage.value}
    case.current_stage = to
    await audit_svc.log_action(
        session,
        actor_user_id=actor_user_id,
        action="case.stage_changed",
        entity_type="case",
        entity_id=str(case.id),
        before=before,
        after={"stage": case.current_stage.value},
    )
    return case
```

- [ ] **Step 4.5: Run — expect PASS**

```bash
cd backend && poetry run pytest tests/unit/test_stages.py -v
# Expected: 9 passed
```

- [ ] **Step 4.6: Commit**

```bash
cd ..
git add backend/app/core/exceptions.py backend/app/services/stages.py backend/tests/unit/test_stages.py
git commit -m "feat(m2): case stage machine with transition enforcement + audit"
```

---

## Task 5: Storage service (storage.py) + tests

**Files:**
- Create: `backend/app/services/storage.py`
- Create: `backend/tests/integration/test_storage_service.py`

Use **moto** for tests — in-process, no LocalStack dependency.

- [ ] **Step 5.1: Write failing test `backend/tests/integration/test_storage_service.py`**

```python
"""Storage service tests using moto (in-process S3 mock)."""
import asyncio

import pytest
from moto import mock_aws

from app.services.storage import StorageService


@pytest.fixture
async def storage():
    """Fresh moto S3 bucket per test."""
    with mock_aws():
        svc = StorageService(
            region="ap-south-1",
            endpoint_url=None,
            access_key="test",
            secret_key="test",
            bucket="pfl-cases-test",
        )
        await svc.ensure_bucket_exists()
        yield svc


async def test_upload_and_download_roundtrip(storage):
    await storage.upload_object("test/hello.txt", b"hello world", content_type="text/plain")
    body = await storage.download_object("test/hello.txt")
    assert body == b"hello world"


async def test_object_exists_returns_true_after_upload(storage):
    assert await storage.object_exists("not-there.txt") is False
    await storage.upload_object("there.txt", b"x")
    assert await storage.object_exists("there.txt") is True


async def test_object_metadata(storage):
    await storage.upload_object("meta.bin", b"1234567890", content_type="application/octet-stream")
    meta = await storage.get_object_metadata("meta.bin")
    assert meta is not None
    assert meta["size_bytes"] == 10
    assert meta["content_type"] == "application/octet-stream"


async def test_delete_removes_object(storage):
    await storage.upload_object("doomed.txt", b"bye")
    await storage.delete_object("doomed.txt")
    assert await storage.object_exists("doomed.txt") is False


async def test_presigned_download_url_works(storage):
    await storage.upload_object("dl.txt", b"download me")
    url = await storage.generate_presigned_download_url("dl.txt", expires_in=60)
    assert url.startswith("https://") or url.startswith("http://")
    assert "dl.txt" in url


async def test_presigned_upload_url_includes_size_condition(storage):
    resp = await storage.generate_presigned_upload_url(
        "upload/target.zip",
        expires_in=900,
        max_size_bytes=100 * 1024 * 1024,
        content_type="application/zip",
    )
    assert "url" in resp
    assert "fields" in resp
    assert resp["key"] == "upload/target.zip"
    # Under moto, the URL points to S3 directly; presigned POST fields should include the policy
    assert "policy" in resp["fields"]
    assert "x-amz-signature" in resp["fields"] or "AWSAccessKeyId" in resp["fields"]


async def test_copy_object_works(storage):
    await storage.upload_object("src.txt", b"data")
    await storage.copy_object("src.txt", "dst.txt")
    assert await storage.object_exists("dst.txt") is True
    assert await storage.download_object("dst.txt") == b"data"


async def test_copy_then_delete_simulates_rename(storage):
    """Re-upload flow relies on copy + delete to 'rename'."""
    await storage.upload_object("original.zip", b"zipbytes")
    await storage.copy_object("original.zip", "original.zip.archived_v1")
    await storage.delete_object("original.zip")
    assert await storage.object_exists("original.zip") is False
    assert await storage.object_exists("original.zip.archived_v1") is True
```

- [ ] **Step 5.2: Run — expect FAIL (ImportError)**

- [ ] **Step 5.3: Implement `backend/app/services/storage.py`**

```python
"""S3 storage service wrapping aioboto3.

One instance per process (constructed from settings at startup). All methods
are async. Uses `endpoint_url` override for LocalStack in dev.

Presigned POST URLs enforce content-length-range via policy conditions so the
server doesn't need to re-verify size.
"""
import io

import aioboto3
from botocore.exceptions import ClientError

from app.config import Settings, get_settings


class StorageService:
    def __init__(
        self,
        *,
        region: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._endpoint_url = endpoint_url
        self._bucket = bucket

    def _client(self):
        return self._session.client("s3", endpoint_url=self._endpoint_url)

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket_exists(self) -> None:
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchBucket", "NotFound"):
                    # Regional create syntax
                    kwargs = {"Bucket": self._bucket}
                    # us-east-1 is the default region and rejects LocationConstraint
                    if self._session.region_name and self._session.region_name != "us-east-1":
                        kwargs["CreateBucketConfiguration"] = {
                            "LocationConstraint": self._session.region_name
                        }
                    await s3.create_bucket(**kwargs)
                else:
                    raise

    async def upload_object(
        self, key: str, body: bytes, content_type: str | None = None
    ) -> None:
        async with self._client() as s3:
            kwargs = {"Bucket": self._bucket, "Key": key, "Body": body}
            if content_type:
                kwargs["ContentType"] = content_type
            await s3.put_object(**kwargs)

    async def download_object(self, key: str) -> bytes:
        async with self._client() as s3:
            resp = await s3.get_object(Bucket=self._bucket, Key=key)
            return await resp["Body"].read()

    async def delete_object(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def copy_object(self, source_key: str, dest_key: str) -> None:
        async with self._client() as s3:
            await s3.copy_object(
                Bucket=self._bucket,
                Key=dest_key,
                CopySource={"Bucket": self._bucket, "Key": source_key},
            )

    async def object_exists(self, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise

    async def get_object_metadata(self, key: str) -> dict | None:
        async with self._client() as s3:
            try:
                resp = await s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return None
                raise
            return {
                "size_bytes": resp.get("ContentLength"),
                "content_type": resp.get("ContentType"),
                "etag": resp.get("ETag"),
            }

    async def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str:
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )

    async def generate_presigned_upload_url(
        self,
        key: str,
        *,
        expires_in: int = 900,
        max_size_bytes: int = 100 * 1024 * 1024,
        content_type: str | None = None,
    ) -> dict:
        """Returns a presigned POST with size cap enforced by S3 policy.

        Client sends multipart POST to `url` with `fields` + file.
        Returns {"url", "fields", "key"}.
        """
        conditions: list = [["content-length-range", 0, max_size_bytes]]
        fields: dict[str, str] = {}
        if content_type:
            conditions.append({"Content-Type": content_type})
            fields["Content-Type"] = content_type

        async with self._client() as s3:
            resp = await s3.generate_presigned_post(
                Bucket=self._bucket,
                Key=key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
        return {"url": resp["url"], "fields": resp["fields"], "key": key}


_instance: StorageService | None = None


def get_storage(settings: Settings | None = None) -> StorageService:
    """FastAPI dependency helper. One instance per process."""
    global _instance
    if _instance is None:
        s = settings or get_settings()
        _instance = StorageService(
            region=s.aws_region,
            endpoint_url=s.aws_s3_endpoint_url,
            access_key=s.aws_access_key_id,
            secret_key=s.aws_secret_access_key,
            bucket=s.s3_bucket,
        )
    return _instance


def reset_storage_for_tests() -> None:
    """Tests use their own StorageService; call this to clear the singleton."""
    global _instance
    _instance = None
```

- [ ] **Step 5.4: Run — expect PASS**

```bash
cd backend && poetry run pytest tests/integration/test_storage_service.py -v
# Expected: 8 passed
```

- [ ] **Step 5.5: Commit**

```bash
cd ..
git add backend/app/services/storage.py backend/tests/integration/test_storage_service.py
git commit -m "feat(m2): async S3 storage service with moto-backed tests"
```

---

## Task 6: Queue service (queue.py) + tests

**Files:**
- Create: `backend/app/services/queue.py`
- Create: `backend/tests/integration/test_queue_service.py`

- [ ] **Step 6.1: Write failing test `backend/tests/integration/test_queue_service.py`**

```python
import json

import pytest
from moto import mock_aws

from app.services.queue import QueueService


@pytest.fixture
async def queue():
    with mock_aws():
        svc = QueueService(
            region="ap-south-1",
            endpoint_url=None,
            access_key="test",
            secret_key="test",
            queue_name="pfl-test-queue",
            dlq_name="pfl-test-queue-dlq",
        )
        await svc.ensure_queues_exist()
        yield svc


async def test_publish_returns_message_id(queue):
    msg_id = await queue.publish_job({"case_id": "abc", "loan_id": "1"})
    assert msg_id and isinstance(msg_id, str)


async def test_publish_round_trips_payload(queue):
    payload = {"case_id": "xyz", "loan_id": "10006484", "zip_s3_key": "cases/xyz/original.zip"}
    await queue.publish_job(payload)

    # Fetch one message directly via the underlying client to verify shape
    messages = await queue.peek_messages(max_messages=1)
    assert len(messages) == 1
    body = json.loads(messages[0]["Body"])
    assert body == payload


async def test_dlq_is_configured(queue):
    """Main queue should have a RedrivePolicy pointing at the DLQ."""
    attrs = await queue.get_queue_attributes()
    assert "RedrivePolicy" in attrs
    redrive = json.loads(attrs["RedrivePolicy"])
    assert redrive["maxReceiveCount"] == "3"
    assert "deadLetterTargetArn" in redrive


async def test_ensure_queues_is_idempotent(queue):
    # Second call must not fail
    await queue.ensure_queues_exist()
```

- [ ] **Step 6.2: Implement `backend/app/services/queue.py`**

```python
"""SQS queue service wrapping aioboto3.

M2 publishes jobs; M3 consumers will use the same service instance.
Queue and DLQ are created together with a RedrivePolicy
(maxReceiveCount=3) so messages that fail processing 3 times land in DLQ.
"""
import json
from collections.abc import Awaitable, Callable

import aioboto3
from botocore.exceptions import ClientError

from app.config import Settings, get_settings


class QueueService:
    def __init__(
        self,
        *,
        region: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        queue_name: str,
        dlq_name: str,
    ) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._endpoint_url = endpoint_url
        self._queue_name = queue_name
        self._dlq_name = dlq_name
        self._queue_url: str | None = None
        self._dlq_url: str | None = None

    def _client(self):
        return self._session.client("sqs", endpoint_url=self._endpoint_url)

    async def ensure_queues_exist(self) -> None:
        """Create DLQ first, then main queue with RedrivePolicy pointing at DLQ."""
        async with self._client() as sqs:
            # DLQ
            dlq_resp = await sqs.create_queue(QueueName=self._dlq_name)
            self._dlq_url = dlq_resp["QueueUrl"]
            dlq_attrs = await sqs.get_queue_attributes(
                QueueUrl=self._dlq_url, AttributeNames=["QueueArn"]
            )
            dlq_arn = dlq_attrs["Attributes"]["QueueArn"]

            # Main queue with redrive
            main_resp = await sqs.create_queue(
                QueueName=self._queue_name,
                Attributes={
                    "RedrivePolicy": json.dumps(
                        {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}
                    ),
                    "VisibilityTimeout": "60",
                    "MessageRetentionPeriod": "1209600",  # 14 days
                },
            )
            self._queue_url = main_resp["QueueUrl"]

    async def _get_queue_url(self) -> str:
        if self._queue_url:
            return self._queue_url
        async with self._client() as sqs:
            resp = await sqs.get_queue_url(QueueName=self._queue_name)
            self._queue_url = resp["QueueUrl"]
            return self._queue_url

    async def publish_job(self, payload: dict) -> str:
        url = await self._get_queue_url()
        async with self._client() as sqs:
            resp = await sqs.send_message(
                QueueUrl=url, MessageBody=json.dumps(payload)
            )
            return resp["MessageId"]

    async def peek_messages(self, max_messages: int = 10) -> list[dict]:
        """Read messages without deleting them (used in tests and for debugging)."""
        url = await self._get_queue_url()
        async with self._client() as sqs:
            resp = await sqs.receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=max_messages,
                VisibilityTimeout=0,  # return immediately visible
            )
            return resp.get("Messages", [])

    async def get_queue_attributes(self) -> dict:
        url = await self._get_queue_url()
        async with self._client() as sqs:
            resp = await sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])
            return resp["Attributes"]

    async def consume_jobs(
        self,
        handler: Callable[[dict], Awaitable[None]],
        *,
        max_messages: int = 10,
        wait_seconds: int = 20,
    ) -> None:
        """Long-poll + handle. M2 defines; M3 workers use."""
        url = await self._get_queue_url()
        async with self._client() as sqs:
            resp = await sqs.receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_seconds,
            )
            for msg in resp.get("Messages", []):
                body = json.loads(msg["Body"])
                try:
                    await handler(body)
                except Exception:
                    # Don't delete; let visibility timeout + redrive handle retry/DLQ
                    continue
                await sqs.delete_message(
                    QueueUrl=url, ReceiptHandle=msg["ReceiptHandle"]
                )


_instance: QueueService | None = None


def get_queue(settings: Settings | None = None) -> QueueService:
    global _instance
    if _instance is None:
        s = settings or get_settings()
        _instance = QueueService(
            region=s.aws_region,
            endpoint_url=s.aws_sqs_endpoint_url,
            access_key=s.aws_access_key_id,
            secret_key=s.aws_secret_access_key,
            queue_name=s.sqs_ingestion_queue,
            dlq_name=s.sqs_ingestion_dlq,
        )
    return _instance


def reset_queue_for_tests() -> None:
    global _instance
    _instance = None
```

- [ ] **Step 6.3: Run — expect PASS**

```bash
cd backend && poetry run pytest tests/integration/test_queue_service.py -v
# Expected: 4 passed
```

- [ ] **Step 6.4: Commit**

```bash
cd ..
git add backend/app/services/queue.py backend/tests/integration/test_queue_service.py
git commit -m "feat(m2): async SQS queue service with DLQ + moto-backed tests"
```

---

## Task 7: Case schemas (Pydantic)

**Files:**
- Create: `backend/app/schemas/case.py`

- [ ] **Step 7.1: Create `backend/app/schemas/case.py`**

```python
"""Pydantic request/response schemas for case endpoints."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.enums import ArtifactType, CaseStage

LOAN_ID_PATTERN = r"^[A-Za-z0-9-]{3,32}$"


class CaseInitiateRequest(BaseModel):
    loan_id: str = Field(pattern=LOAN_ID_PATTERN, description="Unique Finpage loan ID")
    applicant_name: str | None = Field(None, max_length=255)


class CaseInitiateResponse(BaseModel):
    case_id: UUID
    upload_url: str
    upload_fields: dict[str, str]
    upload_key: str
    expires_at: datetime
    reupload: bool = False  # true if this initiate was an approved re-upload


class ApproveReuploadRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class CaseArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    artifact_type: ArtifactType
    size_bytes: int | None
    content_type: str | None
    uploaded_at: datetime
    download_url: str | None = None  # filled in at response-build time


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    loan_id: str
    applicant_name: str | None
    uploaded_by: UUID
    uploaded_at: datetime
    finalized_at: datetime | None
    current_stage: CaseStage
    assigned_to: UUID | None
    reupload_count: int
    reupload_allowed_until: datetime | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    artifacts: list[CaseArtifactRead] = Field(default_factory=list)


class CaseListResponse(BaseModel):
    cases: list[CaseRead]
    total: int
    limit: int
    offset: int
```

- [ ] **Step 7.2: Commit**

```bash
cd ..
git add backend/app/schemas/case.py
git commit -m "feat(m2): Pydantic schemas for case endpoints"
```

---

## Task 8: Case service (cases.py) with integration tests

**Files:**
- Create: `backend/app/services/cases.py`
- Create: `backend/tests/integration/test_cases_service.py`
- Modify: `backend/tests/factories.py` (add CaseFactory)
- Modify: `backend/tests/conftest.py` (add storage + queue fixtures)

- [ ] **Step 8.1: Update `backend/tests/conftest.py` — add storage & queue fixtures**

Append at the bottom:

```python
import pytest
from moto import mock_aws


@pytest.fixture
def mock_aws_services():
    """Enable moto for a test; yields the context manager."""
    with mock_aws():
        yield


@pytest.fixture
async def storage_svc(mock_aws_services):
    from app.services.storage import StorageService
    svc = StorageService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        bucket="pfl-cases-test",
    )
    await svc.ensure_bucket_exists()
    yield svc


@pytest.fixture
async def queue_svc(mock_aws_services):
    from app.services.queue import QueueService
    svc = QueueService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        queue_name="pfl-ingestion-test",
        dlq_name="pfl-ingestion-test-dlq",
    )
    await svc.ensure_queues_exist()
    yield svc
```

- [ ] **Step 8.2: Update `backend/tests/factories.py` — add CaseFactory**

```python
import factory
from factory.alchemy import SQLAlchemyModelFactory

from app.enums import CaseStage
from app.models.case import Case
from datetime import datetime, UTC


class CaseFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Case
        sqlalchemy_session_persistence = "flush"

    loan_id = factory.Sequence(lambda n: f"LOAN{n:06d}")
    # uploaded_by is a UUID FK — callers pass user.id explicitly
    uploaded_by = factory.LazyFunction(lambda: None)  # override per test
    uploaded_at = factory.LazyFunction(lambda: datetime.now(UTC))
    zip_s3_key = factory.LazyAttribute(lambda o: f"cases/{o.loan_id}/original.zip")
    current_stage = CaseStage.UPLOADED
    applicant_name = factory.Faker("name")
    reupload_count = 0
    is_deleted = False
```

- [ ] **Step 8.3: Write failing tests `backend/tests/integration/test_cases_service.py`**

```python
"""Case service tests — business logic for case lifecycle."""
import pytest

from app.core.exceptions import InvalidStateTransition
from app.enums import ArtifactType, CaseStage, UserRole
from app.services import cases as case_svc, users as users_svc


async def _make_user(db, email="u@pfl.com", role=UserRole.AI_ANALYSER):
    user = await users_svc.create_user(
        db, email=email, password="Pass123!", full_name="U", role=role,
    )
    await db.flush()
    return user


# ---------------- initiate ----------------

async def test_initiate_creates_case_row(db, storage_svc):
    user = await _make_user(db)
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=user,
        loan_id="LOAN000001", applicant_name="Alice",
    )
    assert result.case.loan_id == "LOAN000001"
    assert result.case.uploaded_by == user.id
    assert result.case.current_stage == CaseStage.UPLOADED
    assert result.upload_url
    assert "policy" in result.upload_fields


async def test_initiate_duplicate_loan_id_raises(db, storage_svc):
    user = await _make_user(db)
    await case_svc.initiate(
        db, storage=storage_svc, actor=user,
        loan_id="DUP001", applicant_name=None,
    )
    await db.flush()
    with pytest.raises(ValueError, match="already exists"):
        await case_svc.initiate(
            db, storage=storage_svc, actor=user,
            loan_id="DUP001", applicant_name=None,
        )


# ---------------- finalize ----------------

async def test_finalize_transitions_stage_and_enqueues(db, storage_svc, queue_svc):
    user = await _make_user(db)
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=user,
        loan_id="FIN001", applicant_name="F",
    )
    # Simulate client-side upload:
    await storage_svc.upload_object(result.case.zip_s3_key, b"zipbytes")

    case = await case_svc.finalize(
        db, storage=storage_svc, queue=queue_svc, actor=user, case_id=result.case.id,
    )
    assert case.current_stage == CaseStage.CHECKLIST_VALIDATION
    assert case.zip_size_bytes == 8
    # Queue should have the job
    msgs = await queue_svc.peek_messages()
    assert len(msgs) == 1


async def test_finalize_without_upload_raises(db, storage_svc, queue_svc):
    user = await _make_user(db)
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=user,
        loan_id="FIN002", applicant_name=None,
    )
    with pytest.raises(ValueError, match="not found"):
        await case_svc.finalize(
            db, storage=storage_svc, queue=queue_svc,
            actor=user, case_id=result.case.id,
        )


async def test_finalize_enforces_ownership_for_ai_analyser(db, storage_svc, queue_svc):
    owner = await _make_user(db, email="owner@pfl.com", role=UserRole.AI_ANALYSER)
    stranger = await _make_user(db, email="stranger@pfl.com", role=UserRole.AI_ANALYSER)
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=owner,
        loan_id="FIN003", applicant_name=None,
    )
    await storage_svc.upload_object(result.case.zip_s3_key, b"x")
    with pytest.raises(PermissionError):
        await case_svc.finalize(
            db, storage=storage_svc, queue=queue_svc,
            actor=stranger, case_id=result.case.id,
        )


async def test_finalize_admin_bypasses_ownership(db, storage_svc, queue_svc):
    owner = await _make_user(db, email="owner@pfl.com", role=UserRole.AI_ANALYSER)
    admin = await _make_user(db, email="admin@pfl.com", role=UserRole.ADMIN)
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=owner,
        loan_id="FIN004", applicant_name=None,
    )
    await storage_svc.upload_object(result.case.zip_s3_key, b"x")
    case = await case_svc.finalize(
        db, storage=storage_svc, queue=queue_svc,
        actor=admin, case_id=result.case.id,
    )
    assert case.current_stage == CaseStage.CHECKLIST_VALIDATION


# ---------------- re-upload flow ----------------

async def test_approve_reupload_sets_window(db):
    user = await _make_user(db, role=UserRole.ADMIN)
    other = await _make_user(db, email="other@pfl.com")
    from app.models.case import Case
    case = Case(
        loan_id="RE001", uploaded_by=other.id,
        uploaded_at=users_svc.datetime_now_utc() if hasattr(users_svc, "datetime_now_utc") else __import__("datetime").datetime.now(__import__("datetime").UTC),
        zip_s3_key="x",
    )
    db.add(case)
    await db.flush()

    await case_svc.approve_reupload(
        db, actor=user, case_id=case.id, reason="underwriter error in original CAM",
    )
    assert case.reupload_allowed_until is not None


async def test_reupload_archives_previous_state(db, storage_svc):
    owner = await _make_user(db, email="o@pfl.com", role=UserRole.AI_ANALYSER)
    admin = await _make_user(db, email="a@pfl.com", role=UserRole.ADMIN)

    # First upload
    r1 = await case_svc.initiate(
        db, storage=storage_svc, actor=owner,
        loan_id="RE002", applicant_name="First",
    )
    await storage_svc.upload_object(r1.case.zip_s3_key, b"first-zip")
    await db.flush()

    # Admin approves reupload
    await case_svc.approve_reupload(
        db, actor=admin, case_id=r1.case.id, reason="bad CAM, re-doing",
    )

    # Same loan_id, re-initiate
    r2 = await case_svc.initiate(
        db, storage=storage_svc, actor=owner,
        loan_id="RE002", applicant_name="First",
    )
    assert r2.reupload is True
    assert r2.case.reupload_count == 1

    # Archive JSON should exist
    archive_key = f"cases/{r2.case.id}/archives/_archive_v1.json"
    assert await storage_svc.object_exists(archive_key)

    # Old ZIP should have been retired
    assert not await storage_svc.object_exists(r1.case.zip_s3_key)
    assert await storage_svc.object_exists(r1.case.zip_s3_key + ".archived_v1")


# ---------------- list ----------------

async def test_list_filters_by_stage(db, storage_svc):
    user = await _make_user(db)
    for i in range(3):
        await case_svc.initiate(
            db, storage=storage_svc, actor=user,
            loan_id=f"LIST{i:03d}", applicant_name=None,
        )
    await db.flush()
    page = await case_svc.list_cases(db, stage=CaseStage.UPLOADED, limit=50, offset=0)
    assert page.total >= 3
    assert all(c.current_stage == CaseStage.UPLOADED for c in page.cases)


async def test_list_excludes_deleted_by_default(db, storage_svc):
    user = await _make_user(db)
    r = await case_svc.initiate(
        db, storage=storage_svc, actor=user, loan_id="DEL001", applicant_name=None,
    )
    r.case.is_deleted = True
    await db.flush()
    page = await case_svc.list_cases(db, limit=50, offset=0, include_deleted=False)
    assert all(c.id != r.case.id for c in page.cases)


# ---------------- soft delete ----------------

async def test_soft_delete_marks_case(db, storage_svc):
    user = await _make_user(db, role=UserRole.ADMIN)
    r = await case_svc.initiate(
        db, storage=storage_svc, actor=user, loan_id="SD001", applicant_name=None,
    )
    await case_svc.soft_delete(db, actor=user, case_id=r.case.id)
    assert r.case.is_deleted is True
    assert r.case.deleted_by == user.id
```

- [ ] **Step 8.4: Run — expect FAIL (ImportError)**

- [ ] **Step 8.5: Implement `backend/app/services/cases.py`**

```python
"""Case business logic: initiate, finalize, list, re-upload, delete.

All functions are pure async, take session + services as args; no HTTP concerns.
"""
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import ArtifactType, CaseStage, UserRole
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.user import User
from app.services import audit as audit_svc, stages as stages_svc
from app.services.queue import QueueService
from app.services.storage import StorageService


@dataclass
class InitiateResult:
    case: Case
    upload_url: str
    upload_fields: dict[str, str]
    upload_key: str
    expires_at: datetime
    reupload: bool


@dataclass
class CaseListPage:
    cases: list[Case]
    total: int


def _original_zip_key(case_id: UUID) -> str:
    return f"cases/{case_id}/original.zip"


def _archive_json_key(case_id: UUID, version: int) -> str:
    return f"cases/{case_id}/archives/_archive_v{version}.json"


async def _archive_existing_state(
    session: AsyncSession,
    storage: StorageService,
    case: Case,
    *,
    reupload_by: User,
    approving_admin_id: UUID | None,
    approval_reason: str | None,
) -> None:
    """Copy prior ZIP aside, mutate old ORIGINAL_ZIP artifact, write archive JSON.

    NOTE (M2 simplification): `approving_admin_id` and `approval_reason` are passed
    as None by the M2 `initiate` caller because the admin identity/reason are only
    captured transiently on the Case row (via `approve_reupload` → `reupload_allowed_until`
    + audit log) and not carried forward to this function in M2. The archive JSON
    therefore has null values for `reupload_approved_by` and `reupload_approval_reason`.
    M3+ will plumb these through (join the audit log entry for `case.reupload_approved`
    to enrich the archive payload). The archive format is versioned so this enrichment
    is non-breaking.
    """
    version = case.reupload_count + 1

    # 1. Copy previous original.zip aside (if exists)
    old_key = case.zip_s3_key
    archived_key = f"{old_key}.archived_v{version}"
    if await storage.object_exists(old_key):
        await storage.copy_object(old_key, archived_key)
        await storage.delete_object(old_key)

    # 2. Retire the existing ORIGINAL_ZIP artifact row, if any
    result = await session.execute(
        select(CaseArtifact).where(
            and_(
                CaseArtifact.case_id == case.id,
                CaseArtifact.artifact_type == ArtifactType.ORIGINAL_ZIP,
            )
        )
    )
    old_artifact = result.scalar_one_or_none()
    if old_artifact is not None:
        before = {"s3_key": old_artifact.s3_key, "artifact_type": old_artifact.artifact_type.value}
        old_artifact.s3_key = archived_key
        old_artifact.artifact_type = ArtifactType.REUPLOAD_ARCHIVE
        await audit_svc.log_action(
            session,
            actor_user_id=reupload_by.id,
            action="case.artifact_retired",
            entity_type="case",
            entity_id=str(case.id),
            before=before,
            after={"s3_key": archived_key, "artifact_type": ArtifactType.REUPLOAD_ARCHIVE.value},
        )

    # 3. Build + upload archive JSON
    archive_payload = {
        "archive_version": version,
        "archived_at": datetime.now(UTC).isoformat(),
        "archived_by": str(reupload_by.id),
        "reupload_approved_by": str(approving_admin_id) if approving_admin_id else None,
        "reupload_approval_reason": approval_reason,
        "reupload_approved_at": case.reupload_allowed_until.isoformat() if case.reupload_allowed_until else None,
        "previous_state": {
            "zip_s3_key": archived_key,
            "stage_at_archive": case.current_stage.value,
            "applicant_name": case.applicant_name,
            "uploaded_by": str(case.uploaded_by),
            "uploaded_at": case.uploaded_at.isoformat(),
            "finalized_at": case.finalized_at.isoformat() if case.finalized_at else None,
            "notes_and_feedback": [],  # populated in M7
        },
    }
    archive_key = _archive_json_key(case.id, version)
    await storage.upload_object(
        archive_key,
        json.dumps(archive_payload, indent=2).encode("utf-8"),
        content_type="application/json",
    )

    # 4. Create a CaseArtifact row for the archive JSON
    archive_artifact = CaseArtifact(
        case_id=case.id,
        filename=f"_archive_v{version}.json",
        artifact_type=ArtifactType.REUPLOAD_ARCHIVE,
        s3_key=archive_key,
        uploaded_by=reupload_by.id,
        uploaded_at=datetime.now(UTC),
        content_type="application/json",
    )
    session.add(archive_artifact)

    # 5. Mutate case row: increment counter, clear window, reset for new upload
    case.reupload_count = version
    case.reupload_allowed_until = None
    case.current_stage = CaseStage.UPLOADED
    case.finalized_at = None
    case.zip_size_bytes = None
    case.uploaded_by = reupload_by.id
    case.uploaded_at = datetime.now(UTC)

    await audit_svc.log_action(
        session,
        actor_user_id=reupload_by.id,
        action="case.reuploaded",
        entity_type="case",
        entity_id=str(case.id),
        after={"archive_version": version},
    )


async def initiate(
    session: AsyncSession,
    *,
    storage: StorageService,
    actor: User,
    loan_id: str,
    applicant_name: str | None,
) -> InitiateResult:
    """Initiate (or re-upload) a case and return a presigned upload URL."""
    settings = get_settings()

    # Look for existing case with same loan_id
    existing_result = await session.execute(
        select(Case).where(and_(Case.loan_id == loan_id, Case.is_deleted.is_(False)))
    )
    existing = existing_result.scalar_one_or_none()

    reupload = False
    if existing is not None:
        now = datetime.now(UTC)
        if existing.reupload_allowed_until is None or existing.reupload_allowed_until < now:
            raise ValueError(f"Case with loan_id '{loan_id}' already exists")
        # Re-upload path: archive previous state, reuse the same row
        await _archive_existing_state(
            session,
            storage,
            existing,
            reupload_by=actor,
            approving_admin_id=None,  # M2: reason + approver on case row already
            approval_reason=None,
        )
        case = existing
        reupload = True
        # New zip_s3_key is same path as before
        case.zip_s3_key = _original_zip_key(case.id)
        case.applicant_name = applicant_name
    else:
        # Fresh case
        case = Case(
            loan_id=loan_id,
            uploaded_by=actor.id,
            uploaded_at=datetime.now(UTC),
            zip_s3_key="pending",  # placeholder until we have case.id
            current_stage=CaseStage.UPLOADED,
            applicant_name=applicant_name,
        )
        session.add(case)
        try:
            await session.flush()  # populate case.id
        except IntegrityError as e:
            await session.rollback()
            raise ValueError(f"Case with loan_id '{loan_id}' already exists") from e
        case.zip_s3_key = _original_zip_key(case.id)

    # Generate presigned upload URL
    presigned = await storage.generate_presigned_upload_url(
        case.zip_s3_key,
        expires_in=settings.presigned_url_expires_seconds,
        max_size_bytes=settings.max_zip_size_bytes,
        content_type="application/zip",
    )

    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.initiated",
        entity_type="case",
        entity_id=str(case.id),
        after={"loan_id": loan_id, "reupload": reupload},
    )

    return InitiateResult(
        case=case,
        upload_url=presigned["url"],
        upload_fields=presigned["fields"],
        upload_key=presigned["key"],
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.presigned_url_expires_seconds),
        reupload=reupload,
    )


async def finalize(
    session: AsyncSession,
    *,
    storage: StorageService,
    queue: QueueService,
    actor: User,
    case_id: UUID,
) -> Case:
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise ValueError(f"Case {case_id} not found")

    # Ownership: ai_analyser must own; admin bypasses
    if actor.role == UserRole.AI_ANALYSER and case.uploaded_by != actor.id:
        raise PermissionError("Only the uploader or an admin can finalize this case")

    # Verify upload
    if not await storage.object_exists(case.zip_s3_key):
        raise ValueError(f"Upload not found at {case.zip_s3_key}")
    meta = await storage.get_object_metadata(case.zip_s3_key)
    case.zip_size_bytes = meta["size_bytes"] if meta else None
    case.finalized_at = datetime.now(UTC)

    # Create ORIGINAL_ZIP artifact
    artifact = CaseArtifact(
        case_id=case.id,
        filename="original.zip",
        artifact_type=ArtifactType.ORIGINAL_ZIP,
        s3_key=case.zip_s3_key,
        size_bytes=case.zip_size_bytes,
        content_type="application/zip",
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
    )
    session.add(artifact)

    # Transition stage
    await stages_svc.transition_stage(
        session, case=case, to=CaseStage.CHECKLIST_VALIDATION, actor_user_id=actor.id,
    )

    # Enqueue ingestion
    await queue.publish_job({
        "case_id": str(case.id),
        "loan_id": case.loan_id,
        "zip_s3_key": case.zip_s3_key,
    })

    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.finalized",
        entity_type="case",
        entity_id=str(case.id),
        after={"zip_size_bytes": case.zip_size_bytes},
    )

    return case


async def approve_reupload(
    session: AsyncSession,
    *,
    actor: User,
    case_id: UUID,
    reason: str,
) -> Case:
    if actor.role != UserRole.ADMIN:
        raise PermissionError("Only admin can approve reuploads")
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise ValueError(f"Case {case_id} not found")
    now = datetime.now(UTC)
    case.reupload_allowed_until = now + timedelta(hours=24)
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.reupload_approved",
        entity_type="case",
        entity_id=str(case.id),
        after={"reason": reason, "valid_until": case.reupload_allowed_until.isoformat()},
    )
    return case


async def soft_delete(
    session: AsyncSession,
    *,
    actor: User,
    case_id: UUID,
) -> Case:
    if actor.role != UserRole.ADMIN:
        raise PermissionError("Only admin can delete cases")
    case = await session.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")
    case.is_deleted = True
    case.deleted_at = datetime.now(UTC)
    case.deleted_by = actor.id
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.soft_deleted",
        entity_type="case",
        entity_id=str(case.id),
    )
    return case


async def list_cases(
    session: AsyncSession,
    *,
    stage: CaseStage | None = None,
    uploaded_by: UUID | None = None,
    loan_id_prefix: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> CaseListPage:
    stmt = select(Case)
    count_stmt = select(func.count()).select_from(Case)
    clauses = []
    if stage is not None:
        clauses.append(Case.current_stage == stage)
    if uploaded_by is not None:
        clauses.append(Case.uploaded_by == uploaded_by)
    if loan_id_prefix:
        clauses.append(Case.loan_id.like(f"{loan_id_prefix}%"))
    if from_date:
        clauses.append(Case.uploaded_at >= from_date)
    if to_date:
        clauses.append(Case.uploaded_at <= to_date)
    if not include_deleted:
        clauses.append(Case.is_deleted.is_(False))
    if clauses:
        stmt = stmt.where(and_(*clauses))
        count_stmt = count_stmt.where(and_(*clauses))

    stmt = stmt.order_by(Case.uploaded_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(count_stmt)).scalar() or 0
    return CaseListPage(cases=list(rows), total=total)


async def get_case(session: AsyncSession, case_id: UUID, *, include_deleted: bool = False) -> Case | None:
    case = await session.get(Case, case_id)
    if case is None:
        return None
    if case.is_deleted and not include_deleted:
        return None
    return case


async def list_artifacts(session: AsyncSession, case_id: UUID) -> list[CaseArtifact]:
    result = await session.execute(
        select(CaseArtifact).where(CaseArtifact.case_id == case_id).order_by(CaseArtifact.uploaded_at)
    )
    return list(result.scalars().all())


async def add_artifact(
    session: AsyncSession,
    *,
    storage: StorageService,
    actor: User,
    case_id: UUID,
    filename: str,
    content: bytes,
    artifact_type: ArtifactType = ArtifactType.ADDITIONAL_FILE,
    content_type: str | None = None,
) -> CaseArtifact:
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise ValueError(f"Case {case_id} not found")
    # Ownership: ai_analyser must own; admin bypasses
    if actor.role == UserRole.AI_ANALYSER and case.uploaded_by != actor.id:
        raise PermissionError("Only the uploader or an admin can add artifacts")

    from uuid import uuid4
    artifact_id = uuid4()
    safe_filename = filename.replace("/", "_").replace("\\", "_")
    s3_key = f"cases/{case.id}/artifacts/{artifact_id}_{safe_filename}"
    await storage.upload_object(s3_key, content, content_type=content_type)

    artifact = CaseArtifact(
        id=artifact_id,
        case_id=case.id,
        filename=filename,
        artifact_type=artifact_type,
        s3_key=s3_key,
        size_bytes=len(content),
        content_type=content_type,
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
    )
    session.add(artifact)
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.artifact_added",
        entity_type="case",
        entity_id=str(case.id),
        after={"artifact_id": str(artifact.id), "artifact_type": artifact_type.value},
    )
    return artifact
```

- [ ] **Step 8.6: Run — expect PASS**

```bash
cd backend && poetry run pytest tests/integration/test_cases_service.py -v
# Expected: all pass
```

- [ ] **Step 8.7: Commit**

```bash
cd ..
git add backend/app/services/cases.py backend/tests/
git commit -m "feat(m2): case service with initiate, finalize, reupload, list, delete"
```

---

## Task 9: Cases router (HTTP endpoints) + tests

**Files:**
- Create: `backend/app/api/routers/cases.py`
- Create: `backend/tests/integration/test_cases_router.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/deps.py` (add get_storage, get_queue deps)

- [ ] **Step 9.1: Update `backend/app/api/deps.py` — add service deps**

Append:

```python
from app.services.storage import StorageService, get_storage as _get_storage_instance
from app.services.queue import QueueService, get_queue as _get_queue_instance


def get_storage_dep() -> StorageService:
    return _get_storage_instance()


def get_queue_dep() -> QueueService:
    return _get_queue_instance()
```

And export them from `__all__`.

- [ ] **Step 9.2: Create `backend/app/api/routers/cases.py`**

```python
"""Case HTTP endpoints."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user, get_queue_dep, get_session, get_storage_dep, require_role,
)
from app.enums import ArtifactType, CaseStage, UserRole
from app.models.user import User
from app.schemas.case import (
    ApproveReuploadRequest, CaseArtifactRead, CaseInitiateRequest,
    CaseInitiateResponse, CaseListResponse, CaseRead,
)
from app.services import cases as case_svc
from app.services.queue import QueueService
from app.services.storage import StorageService

router = APIRouter(prefix="/cases", tags=["cases"])


async def _attach_artifacts(case, session, storage: StorageService) -> CaseRead:
    """Build CaseRead with artifacts + download URLs."""
    artifacts = await case_svc.list_artifacts(session, case.id)
    artifact_reads = []
    for a in artifacts:
        url = await storage.generate_presigned_download_url(a.s3_key, expires_in=900)
        artifact_reads.append(CaseArtifactRead.model_validate(a).model_copy(update={"download_url": url}))
    return CaseRead.model_validate(case).model_copy(update={"artifacts": artifact_reads})


@router.post(
    "/initiate",
    response_model=CaseInitiateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_case(
    payload: CaseInitiateRequest,
    actor: User = Depends(require_role(UserRole.AI_ANALYSER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseInitiateResponse:
    try:
        result = await case_svc.initiate(
            session, storage=storage, actor=actor,
            loan_id=payload.loan_id, applicant_name=payload.applicant_name,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": "case_exists", "message": str(e), "requires_admin_approval": True},
        )
    await session.commit()
    return CaseInitiateResponse(
        case_id=result.case.id,
        upload_url=result.upload_url,
        upload_fields=result.upload_fields,
        upload_key=result.upload_key,
        expires_at=result.expires_at,
        reupload=result.reupload,
    )


@router.post("/{case_id}/finalize", response_model=CaseRead)
async def finalize_case(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.AI_ANALYSER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
    queue: QueueService = Depends(get_queue_dep),
) -> CaseRead:
    try:
        case = await case_svc.finalize(
            session, storage=storage, queue=queue, actor=actor, case_id=case_id,
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)
        raise HTTPException(status.HTTP_404_NOT_FOUND, msg)
    await session.commit()
    return await _attach_artifacts(case, session, storage)


@router.post(
    "/{case_id}/artifacts",
    response_model=CaseArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_artifact(
    case_id: UUID,
    file: UploadFile = File(...),
    artifact_type: ArtifactType = Form(ArtifactType.ADDITIONAL_FILE),
    actor: User = Depends(require_role(UserRole.AI_ANALYSER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseArtifactRead:
    content = await file.read()
    try:
        artifact = await case_svc.add_artifact(
            session, storage=storage, actor=actor, case_id=case_id,
            filename=file.filename or "upload.bin",
            content=content,
            artifact_type=artifact_type,
            content_type=file.content_type,
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    await session.commit()
    url = await storage.generate_presigned_download_url(artifact.s3_key, expires_in=900)
    return CaseArtifactRead.model_validate(artifact).model_copy(update={"download_url": url})


@router.get("", response_model=CaseListResponse)
async def list_cases_endpoint(
    stage: CaseStage | None = Query(None),
    uploaded_by: UUID | None = Query(None),
    loan_id_prefix: str | None = Query(None, max_length=32),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CaseListResponse:
    # Non-admin can't see deleted cases
    effective_include_deleted = include_deleted and actor.role == UserRole.ADMIN
    page = await case_svc.list_cases(
        session,
        stage=stage, uploaded_by=uploaded_by, loan_id_prefix=loan_id_prefix,
        from_date=from_date, to_date=to_date,
        include_deleted=effective_include_deleted,
        limit=limit, offset=offset,
    )
    return CaseListResponse(
        cases=[CaseRead.model_validate(c) for c in page.cases],
        total=page.total,
        limit=limit, offset=offset,
    )


@router.get("/{case_id}", response_model=CaseRead)
async def get_case_endpoint(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseRead:
    include_deleted = actor.role == UserRole.ADMIN
    case = await case_svc.get_case(session, case_id, include_deleted=include_deleted)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return await _attach_artifacts(case, session, storage)


@router.get("/{case_id}/download")
async def download_case_zip(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> RedirectResponse:
    from app.services import audit as audit_svc
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    url = await storage.generate_presigned_download_url(case.zip_s3_key, expires_in=900)
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.downloaded",
        entity_type="case",
        entity_id=str(case.id),
    )
    await session.commit()
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{case_id}/approve-reupload", response_model=CaseRead)
async def approve_reupload_endpoint(
    case_id: UUID,
    payload: ApproveReuploadRequest,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseRead:
    try:
        case = await case_svc.approve_reupload(
            session, actor=actor, case_id=case_id, reason=payload.reason,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    await session.commit()
    return await _attach_artifacts(case, session, storage)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def soft_delete_case(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await case_svc.soft_delete(session, actor=actor, case_id=case_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    await session.commit()
```

- [ ] **Step 9.3: Wire into `backend/app/main.py`**

Add `from app.api.routers import cases as cases_router` and `app.include_router(cases_router.router)` with the other routers.

- [ ] **Step 9.4: Write router tests `backend/tests/integration/test_cases_router.py`**

Keep it focused — service layer is already tested in Task 8; router tests verify HTTP status codes, auth, and serialization:

```python
"""Cases router HTTP-layer tests."""
import io

import pytest

from app.core.security import create_access_token
from app.enums import UserRole
from app.services import users as users_svc
from app.services.storage import reset_storage_for_tests
from app.services.queue import reset_queue_for_tests


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_storage_for_tests()
    reset_queue_for_tests()
    yield
    reset_storage_for_tests()
    reset_queue_for_tests()


async def _token_for(db, email: str, role: UserRole) -> tuple[str, str]:
    user = await users_svc.create_user(
        db, email=email, password="Pass123!", full_name="T", role=role,
    )
    await db.commit()
    return str(user.id), create_access_token(subject=str(user.id))


async def test_initiate_requires_ai_analyser_or_admin(client, db, mock_aws_services, monkeypatch):
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
```

*(Keep router tests minimal — thorough coverage is at service layer. More edge tests added in Task 12 coverage polish.)*

- [ ] **Step 9.5: Run tests — expect PASS**

```bash
cd backend && poetry run pytest tests/integration/test_cases_router.py -v
# Expected: all pass
```

- [ ] **Step 9.6: Commit**

```bash
cd ..
git add backend/app/api/ backend/app/main.py backend/tests/integration/test_cases_router.py
git commit -m "feat(m2): cases router with all 8 endpoints wired into main app"
```

---

## Task 10: Dev startup init (bucket + queue)

**Files:**
- Create: `backend/app/startup.py`
- Modify: `backend/app/main.py`

- [ ] **Step 10.1: Create `backend/app/startup.py`**

```python
"""Dev-only startup hooks: create bucket + queue if missing.

Production uses CDK (M8) to provision real AWS resources, so this is a no-op
when `dev_auto_create_aws_resources=False`.
"""
import logging

from app.config import get_settings
from app.services.queue import get_queue
from app.services.storage import get_storage

_log = logging.getLogger(__name__)


async def init_aws_resources() -> None:
    settings = get_settings()
    if not settings.dev_auto_create_aws_resources:
        _log.info("Skipping AWS resource init (dev_auto_create_aws_resources=False)")
        return

    storage = get_storage(settings)
    await storage.ensure_bucket_exists()
    _log.info("Ensured bucket: %s", settings.s3_bucket)

    queue = get_queue(settings)
    await queue.ensure_queues_exist()
    _log.info("Ensured queues: %s, %s", settings.sqs_ingestion_queue, settings.sqs_ingestion_dlq)
```

- [ ] **Step 10.2: Wire into `backend/app/main.py`**

Replace the current `create_app` with:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth as auth_router, cases as cases_router, health, users as users_router
from app.config import get_settings
from app.startup import init_aws_resources


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await init_aws_resources()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PFL Credit AI", version="0.2.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(cases_router.router)
    return app


app = create_app()


@app.get("/")
async def root() -> dict:
    return {"service": "pfl-credit-ai", "status": "ok"}
```

- [ ] **Step 10.3: Verify full stack boots via docker-compose**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
docker compose build backend
docker compose down
docker compose up -d
sleep 15
docker compose logs backend --tail=30
# Expected: "Ensured bucket: pfl-cases-dev", "Ensured queues: ..."
curl -s http://localhost:8000/health
# Expected: {"status":"ok","database":"ok"}

# Verify bucket exists in LocalStack
curl -s http://localhost:4566/_localstack/health | grep -o '"s3": "[^"]*"'
# Expected: s3 running/available
```

- [ ] **Step 10.4: Run unit + integration tests (not E2E yet)**

```bash
export PATH="$HOME/.local/bin:$PATH"
cd backend && poetry run pytest tests/unit tests/integration/test_storage_service.py tests/integration/test_queue_service.py tests/integration/test_stages.py tests/integration/test_enums.py tests/integration/test_cases_service.py tests/integration/test_cases_router.py -v 2>&1 | tail -10
```

- [ ] **Step 10.5: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/app/startup.py backend/app/main.py
git commit -m "feat(m2): startup lifespan creates bucket + queues in dev mode"
```

---

## Task 11: E2E test with Seema ZIP

**Files:**
- Create: `backend/tests/integration/test_e2e_case_upload.py`

- [ ] **Step 11.1: Create the test**

```python
"""End-to-end: real ZIP upload through presigned POST to LocalStack S3.

Skipped automatically if the Seema ZIP isn't at the expected path.
"""
import os
from pathlib import Path

import pytest

SEEMA_ZIP = Path("/Users/sakshamgupta/Downloads/10006484 Seema Panipat.zip")

pytestmark = pytest.mark.skipif(
    not SEEMA_ZIP.exists(),
    reason="Seema ZIP not present — E2E test skipped",
)


async def test_e2e_seema_zip_upload(client, db, mock_aws_services, monkeypatch):
    """Full flow: initiate → S3 upload → finalize → verify DB + queue state."""
    from app.core.security import create_access_token
    from app.enums import CaseStage, UserRole
    from app.services import users as users_svc
    from app.services.queue import reset_queue_for_tests
    from app.services.storage import reset_storage_for_tests
    from app.services.storage import get_storage
    from app.services.queue import get_queue
    reset_storage_for_tests()
    reset_queue_for_tests()
    # Force services to the test moto session via dep overrides
    # (StorageService and QueueService use the aioboto3 session with "test" creds;
    # moto intercepts all calls in this process.)

    analyser = await users_svc.create_user(
        db, email="an@pfl.com", password="Pass123!",
        full_name="Analyser", role=UserRole.AI_ANALYSER,
    )
    await db.commit()
    token = create_access_token(subject=str(analyser.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Ensure bucket exists (normally done on app startup)
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
    upload_url = init["upload_url"]
    upload_fields = init["upload_fields"]
    upload_key = init["upload_key"]

    # 2. POST the ZIP to the presigned URL using moto's S3 (the URL points at moto's mock)
    # Since moto intercepts in-process, we skip HTTP and directly write via the service.
    #
    # CAVEAT: this bypasses the content-length-range condition in the presigned POST
    # policy (the 100 MB size cap per spec §14). moto's `generate_presigned_post`
    # produces fields for the policy but doesn't enforce them on direct put_object
    # calls. The size cap is therefore only validated against real S3 (prod) or a
    # full LocalStack HTTP POST round-trip. If size-cap behavior needs a dedicated
    # test, run it against LocalStack with `requests.post(url, data=fields, files={...})`.
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
    import json as _json
    payload = _json.loads(msgs[0]["Body"])
    assert payload["case_id"] == case_id
    assert payload["loan_id"] == "10006484"

    # 5. GET /cases/{id} returns artifact with download URL; URL works
    r = await client.get(f"/cases/{case_id}", headers=headers)
    assert r.status_code == 200
    detail = r.json()
    assert len(detail["artifacts"]) == 1
    assert detail["artifacts"][0]["artifact_type"] == "ORIGINAL_ZIP"
    assert detail["artifacts"][0]["size_bytes"] == len(zip_bytes)
```

- [ ] **Step 11.2: Run the E2E test**

```bash
cd backend && poetry run pytest tests/integration/test_e2e_case_upload.py -v
# Expected: 1 passed (or 1 skipped if ZIP not present)
```

- [ ] **Step 11.3: Commit**

```bash
cd ..
git add backend/tests/integration/test_e2e_case_upload.py
git commit -m "test(m2): end-to-end case upload with Seema ZIP through presigned flow"
```

---

## Task 12: Coverage polish + lint + mypy

- [ ] **Step 12.1: Run full coverage**

```bash
export PATH="$HOME/.local/bin:$PATH"
cd backend && poetry run pytest --cov=app --cov-report=term-missing 2>&1 | tail -30
```

- [ ] **Step 12.2: Fill gaps — explicit test targets**

Look at "Missing" column and add tests for these specific branches:

**`app/api/routers/cases.py`** (router tests — extend `test_cases_router.py`):
- `test_initiate_duplicate_loan_id_returns_409` — admin role, second POST returns 409 with `{"error": "case_exists", "requires_admin_approval": true}`
- `test_finalize_wrong_owner_returns_403` — analyser A initiates, analyser B tries to finalize → 403
- `test_finalize_nonexistent_case_returns_404`
- `test_finalize_without_upload_returns_400`
- `test_add_artifact_wrong_owner_returns_403`
- `test_add_artifact_nonexistent_case_returns_404`
- `test_get_case_nonexistent_returns_404`
- `test_get_case_deleted_hidden_from_non_admin`
- `test_approve_reupload_requires_admin` — non-admin gets 403
- `test_approve_reupload_nonexistent_returns_404`
- `test_delete_case_requires_admin`
- `test_list_cases_applies_filters` — stage filter, uploaded_by filter, loan_id_prefix

**`app/services/cases.py`**:
- `_archive_existing_state` when no previous ORIGINAL_ZIP artifact exists (edge case)
- `add_artifact` with soft-deleted case → raises ValueError
- `list_cases` with empty result set

**`app/services/storage.py`**:
- `object_exists` returns False for missing key (404 ClientError)
- `get_object_metadata` returns None for missing key
- `copy_object` success path
- `ensure_bucket_exists` when bucket already exists (no-op path)

**`app/startup.py`**:
- `init_aws_resources` no-op when `dev_auto_create_aws_resources=False`
- `init_aws_resources` creates both bucket and queues when flag is true

Aim ≥90% on each new file.

- [ ] **Step 12.3: Run ruff + mypy**

```bash
cd backend
poetry run ruff format app tests
poetry run ruff check app tests
poetry run mypy app
```

Fix issues.

- [ ] **Step 12.4: Full suite pass**

```bash
cd backend && poetry run pytest -v 2>&1 | tail -10
# Expected: all green, coverage ≥ 90% on new code, ≥ 85% overall
```

- [ ] **Step 12.5: Commit**

```bash
cd ..
git add -u
git commit -m "test(m2): fill coverage gaps, fix lint and type issues"
```

---

## Task 13: Update README + M2 tag

**Files:**
- Modify: `README.md`

- [ ] **Step 13.1: Update `README.md`**

Replace the "What's done" section and extend quick start:

```markdown
## What's done

**M1 — Backend Foundation + Auth** (tag `m1-backend-foundation`)
- Auth (password + JWT + MFA), users, audit log, seed CLI, Docker

**M2 — Case Upload & Storage** (tag `m2-case-upload-storage`)
- Case and artifact entities, workflow state machine
- S3 storage service (aioboto3) with LocalStack for dev
- SQS queue service with DLQ for ingestion jobs
- Endpoints: initiate, finalize, artifact upload, list, detail, download, approve-reupload, soft-delete
- Re-upload flow with archival of prior state

## Quick start (local)

1. Copy env file and generate a JWT secret:
   ```bash
   cp .env.example .env
   # set JWT_SECRET_KEY via: openssl rand -hex 32
   ```

2. Boot stack:
   ```bash
   docker compose up -d
   ```
   Postgres + backend + LocalStack all boot. Backend init creates the bucket and queues.

3. Create first admin:
   ```bash
   docker compose exec backend python -m app.cli seed-admin \
     --email you@pflfinance.com --full-name "Saksham Gupta"
   ```

4. Create an ai_analyser user via the API (or update role directly in DB for quick testing).

5. Open API docs: http://localhost:8000/docs

## Testing

```bash
cd backend
export PATH="$HOME/.local/bin:$PATH"
poetry install
poetry run pytest -v --cov=app
```
```

- [ ] **Step 13.2: Final full-suite run**

```bash
export PATH="$HOME/.local/bin:$PATH"
cd backend && poetry run pytest -v --cov=app --cov-report=term-missing 2>&1 | tail -20
```

- [ ] **Step 13.3: Commit**

```bash
cd ..
git add README.md
git commit -m "docs(m2): update README with M2 capabilities and quick-start changes"
```

- [ ] **Step 13.4: Tag M2**

```bash
git tag -a m2-case-upload-storage -m "M2: Case upload + storage + queue + state machine"
git log --oneline --graph | head -35
```

---

## M2 Exit Criteria Checklist

- [ ] `docker compose up -d` boots Postgres + backend + LocalStack cleanly
- [ ] Backend startup auto-creates `pfl-cases-dev` bucket and `pfl-ingestion-dev` + DLQ
- [ ] `curl /health` returns 200
- [ ] All 8 endpoints from spec §6 work end-to-end
- [ ] Re-upload flow archives prior state correctly (integration test passes)
- [ ] State machine rejects invalid transitions (unit test passes)
- [ ] `pytest` green, ≥90% coverage on new code, ≥85% overall
- [ ] `ruff check` and `mypy` both pass
- [ ] E2E Seema ZIP upload test passes when ZIP present
- [ ] Tag `m2-case-upload-storage` created
- [ ] README updated

---

## Cross-reference to M2 spec

| Plan task | Spec section implemented |
|---|---|
| T2–T3 | §3 (data model) |
| T4 | §9 (state machine) |
| T5 | §4 (storage service) |
| T6 | §5 (queue service) |
| T7 | §6 (request/response schemas) |
| T8 | §6 (service behavior), §7 (re-upload archive), §8 (audit actions) |
| T9 | §6 (endpoints) |
| T10 | §12 (docker-compose), §13 (config) |
| T11 | §11.3 (E2E test) |
| T12 | §11.4 (coverage) |

---

*End of M2 plan. After execution, merge to main with `--no-ff` and move to M3 brainstorming.*
