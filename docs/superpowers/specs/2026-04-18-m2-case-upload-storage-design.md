# Milestone 2: Case Upload & Storage — Design Spec

**Project:** PFL Finance Credit AI Platform
**Milestone:** M2
**Spec date:** 2026-04-18
**Author:** Saksham Gupta (with Claude)
**Status:** Draft — pending spec review + user sign-off
**Builds on:** M1 (Backend Foundation + Auth, merged at `ad0c98f`, tagged `m1-backend-foundation`)
**Parent design:** `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md`

---

## 1. Purpose

Enable the `ai_analyser` role to upload case ZIP files into the system. Each case persists in Postgres with metadata; ZIP binaries live in object storage (S3 in prod, LocalStack S3 in dev). A workflow state machine tracks each case through its lifecycle; M2 implements the first two states (`UPLOADED`, `CHECKLIST_VALIDATION`). M2 also stands up the queue service interface that M3 ingestion workers will consume.

**This is the plumbing layer.** No ZIP extraction, no field parsing, no AI — those come in M3+. At the end of M2, the system accepts ZIPs, stores them, tracks them, and hands them to a queue for a future worker to pick up.

---

## 2. Scope

### 2.1 In scope for M2

- `Case` and `CaseArtifact` data models + migrations
- Workflow stage Postgres enum with all 10 states from parent spec §9
- Storage service (S3 wrapper with LocalStack support for dev)
- Queue service (SQS wrapper with LocalStack support for dev) — publishing works; consumption is M3
- Endpoints:
  - `POST /cases/initiate` — create case metadata + return presigned upload URL
  - `POST /cases/{id}/finalize` — confirm upload complete, enqueue ingestion job, transition to `CHECKLIST_VALIDATION`
  - `POST /cases/{id}/artifacts` — upload one additional file (e.g. missing doc) and attach
  - `GET /cases` — list cases with filters (stage, uploaded_by, loan_id prefix, date range) + pagination
  - `GET /cases/{id}` — case detail with artifact list + presigned download URLs
  - `GET /cases/{id}/download` — get a presigned URL for the primary ZIP
  - `POST /cases/{id}/approve-reupload` (admin only) — permits one re-upload with same loan_id within 24h
  - `DELETE /cases/{id}` (admin only) — soft delete (sets `is_deleted=true`; S3 objects retained 30 days before hard-delete)
- Re-upload flow with archival of prior state to `_archive_v{N}.json` in the case's S3 folder
- Audit log entries for every case state change and every upload
- LocalStack S3 + SQS wired into docker-compose
- ≥90% test coverage for new code
- End-to-end integration test: upload a real ZIP through presigned flow, verify DB + S3 state

### 2.2 Deferred to later milestones

- **M3:** ZIP unzipping, file classification, field extraction (Auto CAM xlsx, PD sheet docx, Equifax HTML), checklist completeness validation, `CHECKLIST_VALIDATION → CHECKLIST_MISSING_DOCS/CHECKLIST_VALIDATED` stage transitions
- **M4:** Frontend upload UI (but the API it'll call is complete in M2)
- **M5:** Phase 1 decisioning engine
- **M6:** Phase 2 audit engine
- **M7:** Memory / NPA / feedback subsystems
- **M8:** Real AWS S3/SQS/SES in Mumbai (same code, different config)

### 2.3 Non-goals

- No attempt to read the contents of the ZIP in M2 — just store and track
- No email notifications in M2 (email is spec §11.2 / comes later)
- No frontend
- No Finpage integration (loan_id is user-supplied on upload)
- No dedupe check against Customer_Dedupe.xlsx (that's M3)

---

## 3. Data Model Additions

New tables on top of M1's `users` + `audit_log`:

### 3.1 `cases`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `loan_id` | varchar(32) UNIQUE NOT NULL | From Finpage (user-supplied in M2) |
| `uploaded_by` | UUID FK → users(id) NOT NULL | ai_analyser or admin |
| `uploaded_at` | timestamptz NOT NULL | When the initiate call was made |
| `finalized_at` | timestamptz NULL | When the upload completed + transitioned to CHECKLIST_VALIDATION |
| `zip_s3_key` | varchar(512) NOT NULL | `cases/{id}/original.zip` |
| `zip_size_bytes` | bigint NULL | populated on finalize |
| `current_stage` | `case_stage` enum NOT NULL DEFAULT 'UPLOADED' | Postgres enum, see §3.3 |
| `assigned_to` | UUID FK → users(id) NULL | for future M5+ review assignment |
| `applicant_name` | varchar(255) NULL | user-supplied on initiate for searchability |
| `reupload_count` | int NOT NULL DEFAULT 0 | incremented on each reupload |
| `reupload_allowed_until` | timestamptz NULL | admin grant, 24h window |
| `is_deleted` | bool NOT NULL DEFAULT false | soft delete |
| `deleted_at` | timestamptz NULL | when soft-deleted |
| `deleted_by` | UUID FK → users(id) NULL | admin who soft-deleted |
| `created_at` | timestamptz NOT NULL | |
| `updated_at` | timestamptz NOT NULL | |

**Indexes:** unique on `loan_id`, btree on `current_stage`, btree on `uploaded_by`, btree on `uploaded_at` (for list queries).

### 3.2 `case_artifacts`

Individual files belonging to a case. The primary ZIP is one artifact; additional uploads (missing docs, re-upload archives) are others.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `case_id` | UUID FK → cases(id) NOT NULL | cascade delete |
| `filename` | varchar(512) NOT NULL | original filename |
| `artifact_type` | `artifact_type` enum NOT NULL | see §3.4 |
| `s3_key` | varchar(512) NOT NULL UNIQUE | `cases/{case_id}/artifacts/{uuid}_{filename}` |
| `size_bytes` | bigint NULL | |
| `content_type` | varchar(128) NULL | MIME, if known |
| `uploaded_by` | UUID FK → users(id) NOT NULL | |
| `uploaded_at` | timestamptz NOT NULL | |
| `metadata_json` | jsonb NULL | extra per-type metadata |
| `created_at` | timestamptz NOT NULL | |
| `updated_at` | timestamptz NOT NULL | |

**Indexes:** btree on `case_id`, btree on `artifact_type`.

### 3.3 `case_stage` enum (Postgres)

Values (spec §9 + parent spec §5.4 hard-rule reject branch):
- `UPLOADED`
- `CHECKLIST_VALIDATION`
- `CHECKLIST_MISSING_DOCS`
- `CHECKLIST_VALIDATED`
- `INGESTED`
- `PHASE_1_DECISIONING`
- `PHASE_1_REJECTED` (terminal; hard-rule short-circuit from Phase 1 per parent §5.4 — CIBIL<700, negative business, etc.)
- `PHASE_1_COMPLETE`
- `PHASE_2_AUDITING`
- `PHASE_2_COMPLETE`
- `HUMAN_REVIEW`
- `APPROVED`
- `REJECTED`
- `ESCALATED_TO_CEO`

**Why define the full enum in M2:** Postgres enum additions are append-only and costly to reorder or rename. Creating the full enum now (even though only `UPLOADED` and `CHECKLIST_VALIDATION` are reached in M2) avoids `ALTER TYPE` migrations in M3/M5/M6. M2 only executes transitions `UPLOADED → CHECKLIST_VALIDATION`; other transitions live dormant until their milestone.

### 3.4 `artifact_type` enum (Postgres)

Values:
- `ORIGINAL_ZIP` — the primary uploaded case kit
- `ADDITIONAL_FILE` — user-uploaded missing doc (generic in M2; M3 will introduce more specific subtypes like `KYC_IMAGE`, `EQUIFAX_HTML`, `PD_SHEET` etc. via a separate `extracted_artifacts` table or column rename)
- `REUPLOAD_ARCHIVE` — the JSON blob preserving prior case state

M2 uses these three values; M3 may add more or migrate to a more fine-grained scheme. Keeping it small to avoid churn.

### 3.5 State transition rules (M2 only implements first two)

| From stage | Allowed next | Actor/trigger |
|---|---|---|
| `UPLOADED` | `CHECKLIST_VALIDATION` | automatic on finalize |
| `CHECKLIST_VALIDATION` | `CHECKLIST_MISSING_DOCS`, `CHECKLIST_VALIDATED` | M3 worker |
| *later states* | *later milestones* | - |

State machine enforced in `app/services/cases.py::transition_stage(from, to)` — raises `InvalidStateTransition` if disallowed. Every transition logs to `audit_log`.

---

## 4. Storage Service

### 4.1 Interface

`backend/app/services/storage.py`:

```python
class StorageService:
    async def upload_object(self, key: str, body: bytes, content_type: str | None = None) -> None: ...
    async def download_object(self, key: str) -> bytes: ...
    async def delete_object(self, key: str) -> None: ...
    async def generate_presigned_upload_url(self, key: str, expires_in: int = 900) -> dict:
        """Returns {"url": "...", "fields": {...}, "key": "..."} for POST upload."""
    async def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str: ...
    async def object_exists(self, key: str) -> bool: ...
    async def get_object_metadata(self, key: str) -> dict | None: ...
```

### 4.2 Implementation

- Uses `aioboto3` for async S3 calls
- Endpoint URL configurable via env (`AWS_S3_ENDPOINT_URL`) — points at `http://localstack:4566` in dev, unset in prod (uses real AWS)
- Region: `ap-south-1` (Mumbai)
- Bucket name: `pfl-cases-{env}` (`pfl-cases-dev` locally)
- Bucket auto-created on startup if missing (dev only; prod buckets created via CDK in M8)
- All uploads use server-side encryption (SSE-S3 for dev; SSE-KMS for prod)

### 4.3 Object key conventions

```
cases/
  {case_uuid}/
    original.zip                    # the ORIGINAL_ZIP artifact
    artifacts/
      {artifact_uuid}_{filename}    # ADDITIONAL_FILE artifacts
    archives/
      _archive_v1.json              # REUPLOAD_ARCHIVE v1
      _archive_v2.json              # REUPLOAD_ARCHIVE v2
```

Archive path is inside the same case folder so a delete of the case prefix cleans everything.

---

## 5. Queue Service

### 5.1 Interface

`backend/app/services/queue.py`:

```python
class QueueService:
    async def publish_job(self, queue_name: str, payload: dict) -> str:
        """Returns message ID."""
    async def consume_jobs(
        self, queue_name: str, handler: Callable[[dict], Awaitable[None]], max_messages: int = 10
    ) -> None:
        """Long-poll + handle. (Implemented in M3 worker; M2 only tests publish.)"""
```

### 5.2 Queues used in M2

- `pfl-ingestion-{env}` — published-to on case finalize. Payload: `{"case_id": "uuid", "loan_id": "str", "zip_s3_key": "str"}`

**Dead-letter queue:** `pfl-ingestion-{env}-dlq` (messages that fail processing >3 times). Receive queue configured with `maxReceiveCount=3`. Consumer implementation is M3; queues themselves are created in M2.

### 5.3 Dev setup

LocalStack SQS at `http://localstack:4566`. Queue auto-created on startup if missing (dev only).

---

## 6. Endpoints

### 6.1 `POST /cases/initiate`

**Role:** `ai_analyser` or `admin`

**Request body:**
```json
{
  "loan_id": "10006484",
  "applicant_name": "SEEMA"
}
```

**Behavior:**
1. Check `loan_id` doesn't already exist in `cases` table (or, if exists, `reupload_allowed_until > now()`).
   - If exists and not approved → `409 Conflict` with `{"error": "case_exists", "requires_admin_approval": true}`.
   - If exists and approved for reupload → archive current state to `REUPLOAD_ARCHIVE` artifact, reset `current_stage = 'UPLOADED'`, increment `reupload_count`, clear `reupload_allowed_until`, proceed.
2. Create new `Case` row (or update the existing one for reupload).
3. Generate presigned POST URL for `cases/{case_id}/original.zip`, expires 15 min.
4. Log `case.initiated` audit entry.
5. Return:
```json
{
  "case_id": "uuid",
  "upload_url": "...",
  "upload_fields": {...},
  "upload_key": "cases/{case_id}/original.zip",
  "expires_at": "..."
}
```

### 6.2 `POST /cases/{id}/finalize`

**Role:** `ai_analyser` or `admin`. Ownership check: if caller role is `ai_analyser`, `case.uploaded_by` must equal `current_user.id`. Admin bypasses this check. (No separate `initiated_by` field — `uploaded_by` set at `/cases/initiate` is the ownership anchor.)

**Request body:** empty

**Behavior:**
1. Verify ownership per above; else `403 Forbidden`.
2. Verify ZIP exists at expected S3 key via `storage.object_exists`.
3. If missing → `400 Bad Request` "Upload not found".
4. Fetch S3 object metadata, record `zip_size_bytes`.
5. Create `CaseArtifact` row with type `ORIGINAL_ZIP`.
6. Transition stage `UPLOADED → CHECKLIST_VALIDATION`.
7. Publish job to `pfl-ingestion-dev` queue (payload above).
8. Log `case.finalized` audit entry.
9. Return case detail.

### 6.3 `POST /cases/{id}/artifacts`

**Role:** `ai_analyser` or `admin`

**Behavior:** multipart/form-data with file + optional `artifact_type` (defaults to `ADDITIONAL_FILE`). Server uploads directly to S3 (small files, no presigned for simplicity), creates `CaseArtifact` row, logs audit. Returns artifact metadata.

M2 note: accepts any file type. M3 will add type-specific handling (e.g., validating extra CIBIL reports against known schema).

### 6.4 `GET /cases`

**Role:** any authenticated user

**Query params:**
- `stage` (optional, enum value) — filter by current_stage
- `uploaded_by` (optional, user UUID) — filter by uploader
- `loan_id_prefix` (optional) — prefix match on loan_id
- `from_date`, `to_date` (optional, ISO) — filter by uploaded_at
- `include_deleted` (optional, default false; admin-only effect)
- `limit` (default 50, max 200), `offset`

**Returns:** `{cases: [...], total: int}`.

**Ordering:** by `uploaded_at` desc.

### 6.5 `GET /cases/{id}`

**Role:** any authenticated user (soft-deleted cases only visible to admin)

**Returns:** full case detail with `artifacts: [{id, filename, artifact_type, size_bytes, uploaded_at, download_url}]`. Download URL is a 15-min presigned S3 URL.

### 6.6 `GET /cases/{id}/download`

**Role:** any authenticated user

**Returns:** redirect (303) to presigned download URL for the ORIGINAL_ZIP. Audit log entry `case.downloaded`.

### 6.7 `POST /cases/{id}/approve-reupload`

**Role:** `admin` only

**Request body:**
```json
{
  "reason": "Original CAM had errors; underwriter re-creating"
}
```

**Behavior:**
1. Verify case exists and isn't soft-deleted.
2. Set `reupload_allowed_until = now() + 24h`.
3. Log `case.reupload_approved` audit entry with reason in `after_json`.
4. Return updated case.

### 6.8 `DELETE /cases/{id}`

**Role:** `admin` only

**Behavior:**
1. Soft-delete: `is_deleted=true, deleted_at=now, deleted_by=admin_id`.
2. Log `case.soft_deleted` audit entry.
3. S3 objects NOT immediately deleted — scheduled hard-delete 30 days later (lifecycle rule in S3 bucket; implemented fully in M8 CDK, but the bucket lifecycle config is scaffolded in M2's LocalStack setup).

---

## 7. Re-upload Archive Format

When `POST /cases/initiate` is called for an existing loan_id with `reupload_allowed_until > now()`:

1. Serialize current case state to JSON:
```json
{
  "archive_version": 1,
  "archived_at": "2026-04-18T12:34:56Z",
  "archived_by": "uuid-of-user-who-reuploaded",
  "reupload_approved_by": "uuid-of-admin",
  "reupload_approval_reason": "<reason from approve-reupload>",
  "reupload_approved_at": "...",
  "previous_state": {
    "case": {...full case row...},
    "artifacts": [...all artifact rows...],
    "zip_s3_key": "cases/{id}/original.zip.archived_v1",
    "stage_at_archive": "CHECKLIST_MISSING_DOCS",
    "audit_entries_summary": [...case-level audit entries from audit_log...],
    "notes_and_feedback": [
      // Empty in M2; populated in M7 when feedback entities exist
    ]
  }
}
```

2. Upload to `cases/{case_id}/archives/_archive_v{reupload_count+1}.json`.

3. The previous `original.zip` is renamed (copy + delete) to `original.zip.archived_v{N}` in the same folder so the archive JSON can reference it.

4. **Retire the old ORIGINAL_ZIP artifact row:** the existing `CaseArtifact` row with `artifact_type=ORIGINAL_ZIP` has its `s3_key` updated to the new `.archived_v{N}` path AND its `artifact_type` changed to `REUPLOAD_ARCHIVE` so artifact queries (`GET /cases/{id}`) only show one current `ORIGINAL_ZIP` per case. Audit log entry `case.artifact_retired` captures the old-to-new s3_key transition.

5. Create a NEW `CaseArtifact` row for the archive JSON (also `artifact_type=REUPLOAD_ARCHIVE`, pointing at `cases/{id}/archives/_archive_v{N}.json`).

6. Then proceed with new upload flow (fresh presigned URL for `original.zip`, case row fields reset except id/loan_id/created_at/reupload_count). After the new finalize call, a new `CaseArtifact` row for the new `ORIGINAL_ZIP` is created per the normal finalize flow.

Future milestones (M5–M7) will expand `notes_and_feedback` and `audit_entries_summary` content without schema churn to the archive format — `archive_version` integer allows format evolution.

---

## 8. Audit Actions

New actions logged in `audit_log` (all use JSONB `after_json` for payload):

- `case.initiated` — `{"loan_id": "...", "case_id": "..."}`
- `case.finalized` — `{"case_id": "...", "zip_size_bytes": N}`
- `case.artifact_added` — `{"case_id": "...", "artifact_id": "...", "artifact_type": "..."}`
- `case.downloaded` — `{"case_id": "..."}`
- `case.reupload_approved` — `{"case_id": "...", "reason": "...", "valid_until": "..."}`
- `case.reuploaded` — `{"case_id": "...", "archive_version": N}`
- `case.soft_deleted` — `{"case_id": "..."}`
- `case.stage_changed` — `before={"stage": "UPLOADED"}, after={"stage": "CHECKLIST_VALIDATION"}`
- `case.artifact_retired` — `before={"s3_key": "cases/{id}/original.zip", "artifact_type": "ORIGINAL_ZIP"}, after={"s3_key": "cases/{id}/original.zip.archived_v{N}", "artifact_type": "REUPLOAD_ARCHIVE"}`

Entity type is `"case"` for all; `entity_id` = case UUID as string.

---

## 9. Workflow State Machine Implementation

`backend/app/services/stages.py`:

```python
_ALLOWED_TRANSITIONS: dict[CaseStage, set[CaseStage]] = {
    CaseStage.UPLOADED: {CaseStage.CHECKLIST_VALIDATION},
    CaseStage.CHECKLIST_VALIDATION: {CaseStage.CHECKLIST_MISSING_DOCS, CaseStage.CHECKLIST_VALIDATED},
    # M3+ will flesh out the rest; for M2 these exist but are never invoked:
    CaseStage.CHECKLIST_MISSING_DOCS: {CaseStage.CHECKLIST_VALIDATION},
    CaseStage.CHECKLIST_VALIDATED: {CaseStage.INGESTED},
    # ... etc
}


async def transition_stage(
    session: AsyncSession, *, case: Case, to: CaseStage, actor_user_id: UUID
) -> Case:
    if to not in _ALLOWED_TRANSITIONS.get(case.current_stage, set()):
        raise InvalidStateTransition(f"{case.current_stage} → {to} not allowed")
    before = {"stage": case.current_stage}
    case.current_stage = to
    await audit_svc.log_action(
        session, actor_user_id=actor_user_id, action="case.stage_changed",
        entity_type="case", entity_id=str(case.id),
        before=before, after={"stage": case.current_stage},
    )
    return case
```

Tests verify: valid transition succeeds and logs; invalid transition raises without mutating.

---

## 10. Error Handling

- **409 Conflict** — duplicate loan_id without re-upload approval; state transition not allowed
- **404 Not Found** — case doesn't exist or soft-deleted (non-admin)
- **403 Forbidden** — wrong role for action
- **400 Bad Request** — ZIP not uploaded when finalize called; malformed input
- **500 Internal Server Error** — storage/queue infra failure; logged to Sentry (prod)
- **422 Unprocessable Entity** — Pydantic validation failure (loan_id format, missing fields)

All errors return `{"error": "code", "message": "human text", "details": {...}}` shape for predictable frontend handling in M4.

---

## 11. Tests

### 11.1 Unit tests

- `storage.py` — mocked boto3 (use `moto`): presigned URL generation, upload/download, object_exists
- `queue.py` — mocked boto3: publish format, DLQ config
- `stages.py` — transition table correctness, invalid transitions raise

### 11.2 Integration tests (LocalStack-backed)

- `test_case_initiate_creates_row_and_presigned_url` — calls endpoint, verifies DB row, verifies presigned URL usable
- `test_case_initiate_duplicate_loan_id_returns_409`
- `test_case_finalize_transitions_stage_and_enqueues`
- `test_case_finalize_without_upload_returns_400`
- `test_case_list_with_filters`
- `test_case_detail_includes_artifact_download_urls`
- `test_case_artifact_upload_adds_row`
- `test_case_reupload_flow` — admin approves, underwriter re-initiates, archive JSON created, new ZIP replaces old
- `test_case_soft_delete_hides_from_non_admin`
- `test_stage_machine_rejects_invalid_transition`

### 11.3 End-to-end test

`test_e2e_upload_seema_case.py`:

1. Seed an `ai_analyser` user
2. POST `/cases/initiate` with loan_id=10006484
3. Upload the actual `10006484 Seema Panipat.zip` (from `/Users/sakshamgupta/Downloads/`) to the presigned URL
4. POST `/cases/{id}/finalize`
5. Verify stage = `CHECKLIST_VALIDATION`
6. Verify SQS has 1 message on `pfl-ingestion-dev`
7. GET `/cases/{id}` returns artifact with download URL; download URL actually returns the ZIP bytes
8. Verify audit log has 3 entries: initiated, finalized, stage_changed

Test skipped if the Seema ZIP isn't present (not checked into repo).

### 11.4 Coverage target

≥90% on new code (`app/services/storage.py`, `app/services/queue.py`, `app/services/cases.py`, `app/services/stages.py`, `app/api/routers/cases.py`, `app/schemas/cases.py`, `app/models/case.py`, `app/models/case_artifact.py`).

---

## 12. Docker-compose changes

Activate LocalStack (commented placeholder from M1 now enabled):

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
      test: ["CMD", "curl", "-f", "http://localhost:4566/_localstack/health"]
      interval: 10s
      timeout: 5s
      retries: 10

  backend:
    # ... existing ...
    environment:
      # existing +
      AWS_S3_ENDPOINT_URL: http://localstack:4566
      AWS_SQS_ENDPOINT_URL: http://localstack:4566
      AWS_REGION: ap-south-1
      AWS_ACCESS_KEY_ID: test
      AWS_SECRET_ACCESS_KEY: test
      S3_BUCKET: pfl-cases-dev
      SQS_INGESTION_QUEUE: pfl-ingestion-dev
    depends_on:
      postgres:
        condition: service_healthy
      localstack:
        condition: service_healthy
```

On backend startup, run a one-shot init script that creates bucket + queue + DLQ if missing (dev only). In prod, these are provisioned by CDK in M8.

---

## 13. Configuration additions

`backend/app/config.py` Settings:

```python
aws_region: str = "ap-south-1"
aws_s3_endpoint_url: str | None = None  # None = real AWS; set to localstack URL for dev
aws_sqs_endpoint_url: str | None = None
aws_access_key_id: str = "test"  # overridden in prod via IAM role
aws_secret_access_key: str = "test"
s3_bucket: str = "pfl-cases-dev"
sqs_ingestion_queue: str = "pfl-ingestion-dev"
sqs_ingestion_dlq: str = "pfl-ingestion-dev-dlq"
presigned_url_expires_seconds: int = 900  # 15 min
```

`.env.example` updated accordingly.

---

## 14. Resolved design decisions

1. **ZIP size cap: 100 MB.** Enforced via S3 presigned POST condition `content-length-range: 0–104857600` (100 MiB). Rationale: Seema ZIP was 37 MB; 100 MB gives 2.5× headroom for cases with many photos/videos. Server rejects the S3 upload itself if a client sends a larger file, so the API doesn't need to re-check size. Configurable via `max_zip_size_bytes` setting.
2. **Rate limiting on initiate:** none in M2 (peak is ~20/day). Revisit if abuse appears.
3. **Multi-part upload:** not used (presigned POST handles up to 5 GB; we cap at 100 MB anyway).

## 14b. Open questions / TBD

None blocking.

---

## 15. M2 Definition of Done

- [ ] All endpoints in §6 implemented and tested
- [ ] Case and CaseArtifact models migrated on both dev (Postgres) and test DBs
- [ ] `case_stage` and `artifact_type` Postgres enums created via migration
- [ ] LocalStack S3 + SQS running in docker-compose
- [ ] Bucket + queue + DLQ auto-created on backend startup (dev only)
- [ ] ≥90% coverage on new code; full suite passing
- [ ] Ruff + mypy clean
- [ ] End-to-end Seema ZIP test passes (when ZIP is present locally)
- [ ] `docs/superpowers/FOLLOW_UPS.md` updated with any new deferrals
- [ ] M2 tag on the merge commit: `m2-case-upload-storage`

---

## 16. Cross-reference to parent spec

- §2.3 (case retention 7 years): soft delete + 30-day S3 hold is the first hop; full retention handled in M8 via lifecycle
- §8 (data model — `cases`, `case_artifacts`): M2 implements these entities
- §9 (workflow stages): enum with all 10 stages created; only first 2 transitions executed
- §12 (security): case data encrypted at rest (SSE-S3 dev, SSE-KMS prod); access via presigned URLs only
- §11 (infrastructure): LocalStack scaffolds the AWS services; CDK stack in M8 deploys the real ones

---

*End of M2 spec. Next: spec review loop → user review → writing-plans.*
