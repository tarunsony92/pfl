# Milestone 3: Ingestion Workers — Design Spec

**Project:** PFL Finance Credit AI Platform
**Milestone:** M3
**Spec date:** 2026-04-18
**Author:** Saksham Gupta (with Claude)
**Status:** Auto-approved under orchestration-authority grant; spec-review required
**Builds on:** M2 (tag `m2-case-upload-storage`)
**Parent design:** `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md`

---

## 1. Purpose

Consume the ingestion jobs that M2's `/cases/{id}/finalize` endpoint publishes to SQS. For each job: unpack the case ZIP, classify every file by type (Aadhaar, PAN, Auto CAM, Checklist, PD Sheet, Equifax report, bank statement, visit photos, KYC video, electricity bill, loan documents, other), extract structured data from the parseable sources (xlsx, docx, html, pdf), persist extractions in Postgres, run checklist completeness validation, match against the dedupe database, transition the case stage, and notify the uploader if documents are missing.

**This is the "structured-data ingestion" layer.** It turns a raw ZIP into a normalized set of extracted fields that M5's decisioning engine and M6's audit engine can reason over. No AI judgement in M3 — only deterministic parsing and pattern matching.

---

## 2. Scope

### 2.1 In scope for M3

- Dedicated worker process (separate container in docker-compose)
- SQS consumer loop that calls an ingestion pipeline for each case
- Pipeline stages (in order):
  1. Download ZIP from S3
  2. Unpack ZIP, upload each file as a `CaseArtifact` (S3 + DB row)
  3. Classify each artifact by filename pattern + MIME/content heuristics
  4. Extract structured data from parseable artifacts
  5. Run dedupe match against uploaded Customer_Dedupe snapshot
  6. Run checklist completeness validation
  7. Transition case stage to `CHECKLIST_MISSING_DOCS` or `CHECKLIST_VALIDATED`, then automatically to `INGESTED` if validated
  8. Send email to uploader if missing docs
- New models:
  - `case_extraction` — JSONB store per artifact/extractor, with schema_version
  - `checklist_validation_result` — boolean checklist state + missing docs list
  - `dedupe_match` — hits against Customer_Dedupe rows
  - `dedupe_snapshot` — uploaded Customer_Dedupe.xlsx versioned
- Extractors (deterministic, no LLM):
  - **Auto CAM xlsx** → 50+ structured fields across personal/co-borrower/product/financials sheets plus Health Sheet scoring
  - **Checklist xlsx** → boolean checks + remarks per section
  - **PD Sheet docx** → paragraphs + table data + structured PD fields
  - **Equifax HTML** → score, name/DOB/addr, account list, enquiries, DPDs
  - **Bank statement PDF** → raw text + basic transaction patterns (amount, date, balance if extractable; no vendor-specific parsing yet)
- File classifier — filename-regex + content-type heuristics
- Dedupe service — exact+fuzzy match on Aadhaar/PAN/Mobile/DOB against uploaded snapshot
- Email service (SES wrapper, LocalStack SES for dev)
- Missing-docs email template + sender
- Stage machine transitions added (per §3.5 below)
- New endpoints for dedupe snapshot upload + viewing extractions
- ≥85% coverage on new code

### 2.2 Deferred to later milestones

- **M5:** Claude API calls for enhanced parsing (bank statement deep analysis, vision on photos)
- **M5:** KYC video liveness/face-match
- **M5:** Photo classification and content analysis
- **M6:** Audit engine (consumes M3 extractions)
- **M7:** Feedback integration, heuristic memory
- **M8:** Real AWS SES + CDK provisioning

### 2.3 Non-goals

- The worker does not decide credit outcomes — only extracts and persists
- Extractors don't interpret semantics (e.g., "is this a good income?") — M5/M6 do that
- No Claude API calls in M3 (keeps M3 cost-free + deterministic for testing)
- No Finpage API integration (still manual upload per M2)

---

## 3. Data Model Additions

On top of M1+M2's existing tables:

### 3.1 `case_extractions`

One row per (case, extractor) pair. JSONB for flexibility; schema_version field tracks format.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `case_id` | UUID FK → cases(id) ON DELETE CASCADE, indexed | |
| `artifact_id` | UUID FK → case_artifacts(id) NULL | null for aggregate extractions |
| `extractor_name` | varchar(64) NOT NULL, indexed | e.g. "auto_cam", "checklist", "pd_sheet", "equifax", "bank_statement" |
| `schema_version` | varchar(16) NOT NULL DEFAULT "1.0" | format evolution |
| `status` | enum(`SUCCESS`, `PARTIAL`, `FAILED`) NOT NULL | |
| `data` | JSONB NOT NULL | extracted fields |
| `warnings` | JSONB NULL | list of soft-warnings (field missing, ambiguous parse, etc.) |
| `error_message` | text NULL | populated when status=FAILED |
| `extracted_at` | timestamptz NOT NULL | |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Uniqueness: one extraction per (case, extractor, artifact) tuple. Postgres treats NULLs as distinct in regular unique indexes, so a single `UNIQUE (case_id, extractor_name, artifact_id)` would allow duplicate rows for aggregate extractors (where `artifact_id IS NULL`). M3 implements uniqueness as **two partial unique indexes**:

```sql
-- Per-artifact extractions
CREATE UNIQUE INDEX uq_case_extractions_per_artifact
    ON case_extractions (case_id, extractor_name, artifact_id)
    WHERE artifact_id IS NOT NULL;

-- Aggregate (artifact-independent) extractions
CREATE UNIQUE INDEX uq_case_extractions_aggregate
    ON case_extractions (case_id, extractor_name)
    WHERE artifact_id IS NULL;
```

Upsert uses `ON CONFLICT (...) DO UPDATE SET data = EXCLUDED.data, warnings = EXCLUDED.warnings, status = EXCLUDED.status, extracted_at = EXCLUDED.extracted_at`. Two separate INSERT ... ON CONFLICT statements are used (one per index), dispatched based on whether `artifact_id` is set.

### 3.2 `checklist_validation_results`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `case_id` | UUID FK → cases(id) ON DELETE CASCADE, unique | one validation result per case |
| `is_complete` | bool NOT NULL | |
| `missing_docs` | JSONB NOT NULL | list of `{doc_type, reason}` |
| `present_docs` | JSONB NOT NULL | list of `{doc_type, artifact_id}` |
| `validated_at` | timestamptz NOT NULL | |
| `created_at` / `updated_at` | timestamptz | |

The Case model's `current_stage` transitioning to `CHECKLIST_MISSING_DOCS` vs `CHECKLIST_VALIDATED` is derived from `is_complete`. Re-validations upsert this row.

### 3.3 `dedupe_snapshots`

Versioned uploaded Customer_Dedupe.xlsx files.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `uploaded_by` | UUID FK → users(id) | admin who uploaded |
| `uploaded_at` | timestamptz | |
| `s3_key` | varchar(512) UNIQUE | `dedupe/{id}_{filename}` |
| `row_count` | int | |
| `is_active` | bool DEFAULT true | only one active per system |
| `created_at` / `updated_at` | timestamptz | |

Partial unique index: `WHERE is_active = true` ensures at most one active snapshot at any time.

### 3.4 `dedupe_matches`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `case_id` | UUID FK → cases(id) ON DELETE CASCADE, indexed | |
| `snapshot_id` | UUID FK → dedupe_snapshots(id) | |
| `match_type` | enum(`AADHAAR`, `PAN`, `MOBILE`, `DOB_NAME`) NOT NULL | |
| `match_score` | float NOT NULL | 0.0–1.0 |
| `matched_customer_id` | varchar(64) | Finpage customer id from dedupe sheet |
| `matched_details_json` | JSONB | full row from snapshot |
| `created_at` / `updated_at` | timestamptz | |

### 3.5 New Case stage transitions executed in M3

M3 extends M2's stage machine with reverse transitions needed for re-ingestion + re-validation. M2's `ALLOWED_TRANSITIONS` is updated (additive, non-breaking) with:

| From | To | Reason |
|---|---|---|
| `INGESTED` | `CHECKLIST_VALIDATION` | Re-ingestion (admin-triggered, §5.3) |
| `CHECKLIST_VALIDATED` | `CHECKLIST_VALIDATION` | Re-ingestion before extractors re-ran |
| `CHECKLIST_MISSING_DOCS` | `CHECKLIST_VALIDATION` | Already declared in M2 ALLOWED_TRANSITIONS (auto-triggered when user adds missing artifact) |

M3 executes, in normal flow:
- `CHECKLIST_VALIDATION → CHECKLIST_MISSING_DOCS` (missing docs found)
- `CHECKLIST_VALIDATION → CHECKLIST_VALIDATED` (all required docs present)
- `CHECKLIST_VALIDATED → INGESTED` (automatic after extractors complete successfully)

**Re-validation trigger on `add_artifact`:** M3 modifies `case_svc.add_artifact` (existing in M2) so that when it adds an artifact to a case whose `current_stage == CHECKLIST_MISSING_DOCS`, it:
1. Transitions the case back to `CHECKLIST_VALIDATION`
2. Publishes a new ingestion job to SQS (same payload shape as finalize uses)

The worker then re-runs the pipeline (which is idempotent — see §7). This gives the user a self-serve path: upload the missing doc, validation re-runs automatically, stage updates accordingly.

**Re-ingestion pre-flight:** The worker's pipeline (§4.2) checks the case's current_stage at step 0. If the stage is one of `INGESTED`, `CHECKLIST_VALIDATED`, or `CHECKLIST_MISSING_DOCS`, the worker first transitions the case to `CHECKLIST_VALIDATION` before proceeding. This lets steps 4–10 run unconditionally.

**System-user attribution:** All stage transitions performed by the worker are audited with `actor_user_id = SYSTEM_WORKER_USER_ID`, a well-known seed user created at first boot (see §4.2a). Alternative would be embedding `uploaded_by` in the SQS payload, but (a) re-ingestion triggers may originate from admins not the original uploader, and (b) the worker acts as a system, not a user.

---

## 4. Worker Architecture

### 4.1 Worker process

Separate container `pfl-worker` in docker-compose. Same Docker image as `pfl-backend` but launched with a different command (`python -m app.worker`).

Worker main loop:
```
while True:
    messages = await queue.consume_jobs(handler=process_ingestion_job, wait_seconds=20)
```

Each job payload (from M2 finalize + M3 re-trigger paths):
```json
{"case_id": "uuid", "loan_id": "str", "zip_s3_key": "str", "trigger": "finalize|reingest|artifact_added"}
```

(M2's finalize code sets `trigger="finalize"` — M2's current payload doesn't include this field, so M3 makes the `trigger` field optional with a default of `"finalize"` for backward compat.)

### 4.2a System-worker user (seed)

On worker startup (once per process), the worker ensures a well-known user exists:

```
email:     worker@system.pflfinance.internal
role:      ai_analyser  (for permission semantics; worker is not a real user)
is_active: true
mfa:       disabled (worker never logs in via HTTP)
password:  random unguessable hash (never used for login)
```

Created with `get_or_create` logic in `app/worker/system_user.py`. The UUID is captured once and exposed as `SYSTEM_WORKER_USER_ID` for use in `transition_stage(actor_user_id=...)` and audit entries.

### 4.2 Pipeline

`backend/app/worker/pipeline.py::process_ingestion_job(payload)`:

```
0. Load case from DB. If is_deleted: log + skip (message deleted by consumer).
0a. Re-ingestion pre-flight: if case.current_stage in
    {INGESTED, CHECKLIST_VALIDATED, CHECKLIST_MISSING_DOCS}, transition
    to CHECKLIST_VALIDATION (new M3 transitions enable this).
    If current_stage is not CHECKLIST_VALIDATION (nor the 3 above),
    log a warning and skip (message will be deleted — stage invalid for ingestion).
0b. Clear prior per-case state to prevent duplicates on re-ingestion:
    - DELETE FROM dedupe_matches WHERE case_id = X
    - (case_extractions and checklist_validation_results upsert — no pre-clear needed)
    - (existing case_artifacts of artifact_type != ORIGINAL_ZIP are kept;
      re-unpacking skips artifacts whose s3_key already exists via the
      unique constraint — idempotent by design)
1. Download ZIP from S3 (case.zip_s3_key)
2. Unpack → list of (filename, bytes, mime)
3. For each file:
   a. Compute target s3_key = cases/{case_id}/artifacts/{stable_hash}_{safe_filename}
      (stable_hash = first 12 chars of sha256(filename) — deterministic across
       re-runs so the same source file maps to the same S3 key)
   b. If s3_key already exists on S3 AND a CaseArtifact row exists for it → skip
   c. Else upload + create CaseArtifact row with metadata_json.subtype = classified_subtype
4. Classify each ingested artifact subtype (classifier.classify)
5. For each parseable artifact, dispatch to matching extractor; upsert CaseExtraction
6. Run dedupe match using extracted fields (if active snapshot exists)
7. Run checklist completeness validation → upsert ChecklistValidationResult
8. Transition stage:
    - if missing: CHECKLIST_VALIDATION → CHECKLIST_MISSING_DOCS + email uploader
    - if complete: CHECKLIST_VALIDATION → CHECKLIST_VALIDATED → INGESTED
9. Commit DB transaction
10. Delete message from queue (handled by consume_jobs on success)
```

Failures at any step raise an exception — the message is returned to SQS without deletion, retries happen via visibility timeout, and after 3 attempts the message lands in the DLQ.

### 4.3 File classifier

`backend/app/worker/classifier.py::classify(filename: str, body_bytes: bytes) -> ArtifactSubtype`

Returns enum `ArtifactSubtype`:
- `KYC_AADHAAR`, `KYC_PAN`, `KYC_VOTER`, `KYC_DL`, `KYC_PASSPORT`
- `RATION_CARD`, `ELECTRICITY_BILL`, `BANK_ACCOUNT_PROOF`
- `INCOME_PROOF`
- `CO_APPLICANT_AADHAAR`, `CO_APPLICANT_PAN`
- `AUTO_CAM`, `CHECKLIST`, `PD_SHEET`
- `EQUIFAX_HTML`, `CIBIL_HTML`, `HIGHMARK_HTML`, `EXPERIAN_HTML`
- `BANK_STATEMENT`
- `HOUSE_VISIT_PHOTO`, `BUSINESS_PREMISES_PHOTO`
- `KYC_VIDEO`
- `LOAN_AGREEMENT`, `DPN`, `LAPP`, `LAGR`, `NACH`, `KFS`
- `UDYAM_REG`
- `UNKNOWN`

Classification rules:
1. Filename regex patterns (primary) — e.g. `AUTO_CAM.*\.xlsx$` → `AUTO_CAM`, `*AADHAR*\.jpe?g$` → `KYC_AADHAAR`
2. MIME/content fallback — e.g. `.xlsx` with structured "credit assessment" markers → likely AUTO_CAM; `.html` with "EQUIFAX" string → Equifax
3. Folder-path heuristics — items under `*BUSINESS_PREMISES*/` → `BUSINESS_PREMISES_PHOTO`, items under `*HOUSE_VISIT*/` → `HOUSE_VISIT_PHOTO`

Written as a deterministic decision tree in Python; tested with the Seema case's real file names.

### 4.4 Extractors

Each extractor is a class with a single async method `extract(artifact: CaseArtifact, body_bytes: bytes) -> ExtractionResult`.

`ExtractionResult` dataclass:
```python
@dataclass
class ExtractionResult:
    status: Literal["SUCCESS", "PARTIAL", "FAILED"]
    schema_version: str
    data: dict
    warnings: list[str]
    error_message: str | None = None
```

Extractors implemented:

#### 4.4.1 `AutoCamExtractor` (xlsx)

Parses the Auto CAM xlsx. Four sheets: `SystemCam`, `Elegibilty`, `CM CAM IL`, `Health Sheet`. Extracts:
- Personal details (name, DOB, age, gender, religion, marital status, qualification, KYC IDs)
- Co-borrower details (same fields)
- Product details (loan amount, tenure, ROI, EMI, product type)
- Business details (occupation, firm type, annual revenue, GSTIN, vintage, premises, stability)
- Address details (residence + per-address arrays)
- Bank details (name, account no, IFSC, branch)
- References (up to 2)
- Guarantor (if present)
- Income details (salary, manufacturing, dairy, business income, other; monthly + annual)
- Eligibility calc results (FOIR, DSCR, LTV, DTI, proposed EMI, existing EMIs)
- Deviations flagged (ITR Multiplier, ABB, DTI, LTV, Double Whammy, CIBIL, CRIF, Business Vintage, Monthly Income, Business T/O GSTN, Assessed Sales, 3rd ITR, Bank >10KM)
- Health Sheet scoring (score per category, total, maximum, overall %)
- CM CAM IL section (profile screening, family details, business details, income assessment, CB summary, obligation list, banking summary, end-use)

Extractor uses openpyxl (already in deps). Schema version 1.0 expects the Seema-style Auto CAM layout; variants handled as warnings.

#### 4.4.2 `ChecklistExtractor` (xlsx)

Parses checklist xlsx. Sections:
- KYC (Aadhaar+PAN match, IDs count, residence proof, address match, GPS, screenshots)
- Basic (age, spouse, household income, distances, addresses, loan purpose, business profile, contact, business vintage, applicant income)
- Product details (amount, tenure, product, interest, net-off, hospi-cash, etc.)
- Financials — Applicant (income proof, ITR, banking, vintage, GST, Udyam)
- Financials — Co-Applicant (mirror)
- Assets (vehicle, TV, house condition, house ownership, business ownership)
- Credit details (CIBIL scores, unsecured outstanding, DPDs, writeoffs, enquiries, address match, FOIR, negative areas)
- Dedupe (dedupe check, fraud watchlist, willful defaulter list, negative business profiles)
- Documents (loan agreement, sanction letter signed)

Output: `{section_name: {item_name: {value, remarks}}}` plus aggregate `yes_count`, `no_count`, `na_count`.

#### 4.4.3 `PDSheetExtractor` (docx)

Parses PD Sheet docx using python-docx. Extracts:
- Header fields (applicant name, date of PD, conducted by, location)
- Table data (structured Q/A per section)
- Paragraphs (free-form observations)
- Signatures and sign-off status

Output: `{fields: {...}, tables: [...], paragraphs: [...]}`.

#### 4.4.4 `EquifaxHtmlExtractor` (html)

Parses Equifax HTML using BeautifulSoup. Extracts:
- Customer info (name, DOB, gender, PAN, address variants)
- Credit score
- Summary: total accounts, open accounts, closed, enquiries, delinquent
- Account details list: lender, account type, open date, close date, balance, monthly instalment, status, DPD array (last 24 months)
- Enquiries list: lender, amount, enquiry date, purpose
- Addresses list: address, reported on
- Phones list

Schema version 1.0 targets the format in the Seema case's Equifax HTML. Variants produce warnings.

#### 4.4.5 `BankStatementExtractor` (pdf)

Uses pdfplumber to extract text. M3 scope: **text + basic metadata only**.
- Extract full text (all pages)
- Detect account number patterns (common Indian bank formats)
- Detect opening/closing balance, period, account holder name (via regex)
- Extract transaction-like lines (date | description | amount | balance) into a raw list

Deep parsing (per-transaction categorization, bounce detection, ABB calculation) is deferred to M5's Claude-assisted processing. M3 just turns the PDF into structured text that M5 can reason over efficiently.

Schema version 1.0 is intentionally loose — M5 may re-extract with better logic.

### 4.5 Dedupe service

`backend/app/worker/dedupe.py`:

On case ingestion:
1. Load the active dedupe snapshot (latest `is_active=true` row from `dedupe_snapshots`).
   - **If no active snapshot exists:** log `dedupe.skipped_no_snapshot` audit entry; record a warning
     in `case_extractions` with `extractor_name="dedupe"`, `status="PARTIAL"`, `warnings=["no_active_snapshot"]`;
     skip dedupe matching; continue the pipeline. This is expected for the first N cases before
     an admin has uploaded the Customer_Dedupe file.
2. Read the xlsx via openpyxl — columns expected: Customer Id, Full Name, Aadhaar Id, Pan Card, Date Of Birth, Mobile No, etc.
3. For the case's applicant + co-borrower (from Auto CAM extraction):
   - Exact match on Aadhaar → DedupeMatch(type=AADHAAR, score=1.0)
   - Exact match on PAN → DedupeMatch(type=PAN, score=1.0)
   - Exact match on Mobile → DedupeMatch(type=MOBILE, score=0.9)
   - Fuzzy match on (full_name + DOB) → DedupeMatch(type=DOB_NAME, score=fuzz_score) — only if score ≥ 0.85
4. Store all matches.

Fuzzy match uses `rapidfuzz` library (to be added as dep). Name normalization: uppercase, strip whitespace, remove special chars.

### 4.6 Checklist completeness validator

`backend/app/worker/checklist_validator.py`:

Required docs for an IL case (from parent spec §13):
- KYC: Aadhaar + PAN for applicant + co-applicant (4 docs)
- Residence proof (1 of: voter/DL/electricity bill/ration card)
- Bank statement (6 months min)
- Business premises photos (≥3)
- Residence photos (≥3)
- Equifax / CIBIL report (1+)
- PD Sheet
- Auto CAM
- Checklist xlsx
- KYC video

Validator input: list of `CaseArtifact` with classified subtypes.
Output: `{is_complete: bool, missing_docs: [{doc_type, reason}], present_docs: [...]}`.

Soft requirements (warning not fail): electricity bill, Udyam registration, bank account proof, references.

### 4.7 Email service

`backend/app/services/email.py` — SES wrapper (LocalStack SES in dev).

Templates as Jinja2 strings in `backend/app/templates/`:
- `missing_docs.html` + `missing_docs.txt`
- Variables: `case_id`, `loan_id`, `applicant_name`, `missing_docs_list`, `link_to_case_url`

Worker calls `email_svc.send(to=uploader.email, template="missing_docs", vars={...})`.

SES sender domain: `no-reply@pflfinance.com` (dev uses the LocalStack SES free-for-all).

---

## 5. New Endpoints

### 5.1 Dedupe snapshot upload (admin only)

- `POST /dedupe-snapshots` — multipart upload Customer_Dedupe.xlsx. Marks as `is_active=true`, deactivates previous.
- `GET /dedupe-snapshots` — list versioned snapshots
- `GET /dedupe-snapshots/active` — current active one

### 5.2 Case extractions read endpoints

- `GET /cases/{id}/extractions` — all extraction rows for a case
- `GET /cases/{id}/extractions/{extractor_name}` — specific extractor output
- `GET /cases/{id}/checklist-validation` — current validation result
- `GET /cases/{id}/dedupe-matches` — all dedupe matches for this case

All read endpoints auth-gated as `any authenticated user`; admin sees deleted cases too.

### 5.3 Manual re-ingestion trigger (admin only)

- `POST /cases/{id}/reingest` — re-enqueues the ingestion job. Useful when an extractor bug is fixed.
  - Pre-condition: current_stage ∈ {`INGESTED`, `CHECKLIST_MISSING_DOCS`, `CHECKLIST_VALIDATED`}
  - Endpoint does NOT clear any DB state itself (keeps endpoint simple + safe). The worker's pipeline step 0a/0b handles the stage reset and DedupeMatch clearing; CaseExtraction upserts and CaseArtifact idempotent deduplication (via stable s3_key hash) keep the re-run clean.
  - Publishes SQS payload with `trigger="reingest"` for observability.

---

## 6. Audit Actions

- `case.ingestion_started` — worker picked up job
- `case.ingestion_completed` — pipeline finished; after_json has summary counts
- `case.ingestion_failed` — pipeline raised; error details in after_json
- `case.artifact_classified` — each artifact subtype identified
- `case.extraction_succeeded` / `case.extraction_failed` — per-extractor
- `case.checklist_validated` — with missing/present counts
- `case.dedupe_match_found` — each match row
- `case.email_sent` — missing-docs email sent to uploader
- `case.reingestion_triggered` — admin manually re-enqueued
- `dedupe_snapshot.uploaded` — admin uploaded new snapshot
- `dedupe_snapshot.activated` — one becomes active, previous deactivated

---

## 7. Error Handling

- **ZIP download fails** → retry 3x, then DLQ + `case.ingestion_failed` audit
- **Individual extractor fails** → log warning, store CaseExtraction with `status=FAILED`, continue pipeline. The case may still reach `INGESTED` if checklist is complete.
- **Checklist validation fails** (missing docs) → normal flow, stage `CHECKLIST_MISSING_DOCS`, email sent
- **Email send fails** → log warning; do NOT retry the whole ingestion. Email failure is non-fatal.
- **DB transaction fails** → full rollback, message returns to queue, retry
- **Message poison** → DLQ after 3 attempts; admin can inspect

Idempotency: extractions and checklist results are upserted (unique on case_id+extractor_name). Artifacts created during unpack are guarded against double-creation via `s3_key` unique constraint — second ingestion attempt will skip existing artifacts. Dedupe matches are cleared + re-inserted on re-ingestion.

---

## 8. LocalStack Additions

Extend existing LocalStack container to include SES:
```yaml
environment:
  - SERVICES=s3,sqs,ses
```

On startup (dev only, guarded by `settings.ses_verify_on_startup`), `init_aws_resources` also verifies the SES sender identity `no-reply@pflfinance.com` via `verify_email_identity`. In prod, SES identities are managed via CDK/console in M8, and the startup verify call is skipped (`ses_verify_on_startup=False` in prod env).

---

## 9. Tests

### 9.1 Unit tests
- Classifier — 50+ filename/content combinations (one per real Seema file name + edge cases)
- Each extractor — uses synthetic fixture xlsx/docx/html/pdf files created from scratch (no real customer data)
- Dedupe — exact + fuzzy scenarios with fixture snapshot
- Checklist validator — all required doc combinations

### 9.2 Integration tests
- Pipeline end-to-end with LocalStack: upload fixture ZIP, run pipeline, verify extractions + stage transitions + audit entries
- Missing-docs path: pipeline transitions case to MISSING_DOCS + sends email (verified via LocalStack SES send-statistics)
- Re-ingestion is idempotent

### 9.3 E2E with Seema ZIP
- Skipped if the real Seema ZIP isn't present (same pattern as M2)
- Runs full pipeline, asserts on specific extracted values (e.g., CIBIL score 769, loan amount 150000, applicant name SEEMA)

### 9.4 Coverage target

≥85% on new code.

---

## 10. Fixture Files

Create synthetic test fixtures in `backend/tests/fixtures/`:
- `auto_cam_fixture.xlsx` — minimal but valid Auto CAM layout
- `checklist_fixture.xlsx` — minimal valid checklist
- `pd_sheet_fixture.docx` — minimal valid PD sheet
- `equifax_fixture.html` — minimal valid Equifax HTML
- `bank_statement_fixture.pdf` — minimal PDF with a few transaction lines
- `dedupe_fixture.xlsx` — Customer_Dedupe sheet with 3 synthetic rows
- `case_zip_fixture.zip` — a ZIP combining all above + fake JPEG images

**No real customer data.** Fixtures are generated via small helper scripts in `backend/tests/fixtures/builders/` so the fixtures can be regenerated if file formats change.

---

## 11. New dependencies

- `pdfplumber` ^0.11 — PDF text extraction
- `beautifulsoup4` ^4.12 — HTML parsing
- `rapidfuzz` ^3.9 — fuzzy name matching
- `jinja2` ^3.1 — email template rendering
- `lxml` ^5.3 — HTML/XML parser backend (optional but speeds up BS4)
- Existing `openpyxl`, `python-docx`, `aioboto3`, `moto` — reused

---

## 12. Configuration additions

`backend/app/config.py`:

```python
# SES
ses_sender: str = "no-reply@pflfinance.com"
ses_verify_on_startup: bool = True  # dev: auto-verify sender identity

# Worker
worker_poll_interval_seconds: int = 20
worker_concurrency: int = 1  # single-process single-consumer in M3; scale out in M8

# Ingestion behavior
reingestion_allowed_stages: set = {"INGESTED", "CHECKLIST_MISSING_DOCS", "CHECKLIST_VALIDATED"}
```

---

## 13. docker-compose changes

New `worker` service:

```yaml
  worker:
    build: ./backend
    container_name: pfl-worker
    environment:
      # same as backend (DB url, AWS endpoints, secrets)
    depends_on:
      postgres: { condition: service_healthy }
      localstack: { condition: service_healthy }
    command: python -m app.worker
```

Same image, different command. In M8's AWS deploy, this is a separate ECS task definition.

---

## 14. Feature flags / future-proofing

`config.py`:
```python
enable_bank_statement_deep_parse: bool = False  # M5 flag
enable_photo_classification: bool = False  # M5 flag
enable_kyc_video_analysis: bool = False  # M5 flag
```

Workers check these flags; M3 defaults all to false.

---

## 15. M3 Definition of Done

- [ ] Worker container builds and boots
- [ ] Worker consumes ingestion jobs and runs pipeline end-to-end on fixture ZIP
- [ ] All 5 extractors work on fixture files
- [ ] Checklist validation produces correct missing-docs output
- [ ] Dedupe match against fixture snapshot works (exact + fuzzy)
- [ ] Missing-docs email sent via LocalStack SES
- [ ] Stage transitions CHECKLIST_VALIDATION → MISSING_DOCS/VALIDATED → INGESTED work correctly
- [ ] Re-ingestion is idempotent (no duplicate artifacts/extractions)
- [ ] ≥85% coverage on new code
- [ ] Ruff + mypy clean
- [ ] Tag `m3-ingestion-workers` on merge commit

---

## 16. Cross-reference to parent spec

- §4.1 (Ingestion pipeline) — M3 implements this
- §5.3 Steps 1-10 (decisioning pipeline pre-requisites — extractions feed into these)
- §7 (memory layers — M3 extractions feed the case library in M7)
- §8 (data model — adds case_extractions, checklist_validation_results, dedupe_matches, dedupe_snapshots)
- §9 (workflow stages — M3 activates CHECKLIST_* and INGESTED transitions)

---

*End of M3 spec. Next: spec review → plan → execute → merge.*
