# Milestone 5: Phase 1 Decisioning Engine — Design Spec

**Project:** PFL Finance Credit AI Platform
**Milestone:** M5
**Spec date:** 2026-04-18
**Author:** Saksham Gupta (with Claude)
**Status:** Draft — pending spec review
**Builds on:** M3 (tag `m3-ingestion-workers`), M4 (frontend shell)
**Parent design:** `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md`

---

## 1. Executive Summary

M5 implements the Phase 1 Decisioning Engine — the "Saksham-as-credit-head" AI that reads a fully-ingested case kit and produces an APPROVE / APPROVE_WITH_CONDITIONS / REJECT / ESCALATE_TO_CEO recommendation backed by evidence-cited reasoning. The engine runs as an independent worker container (`pfl-decisioning-worker`) consuming a dedicated SQS queue. It executes an 11-step sequential pipeline: pure-Python policy gates first, then a Haiku → Sonnet → Opus model cascade, with Opus doing final judgment synthesis. Every factual claim is tagged with a citation to the source artifact and field. Total target cost is under $0.50 per case (average), under $1.50 p99. M5 is spec-only for KYC vision, live bureau API, signature matching, and face matching — those ship in later milestones.

---

## 2. Scope

### 2.1 In scope for M5

- New `app/decisioning/` package (worker, steps, prompts, parsers)
- New SQS queue `pfl-decisioning-jobs` + DLQ `pfl-decisioning-dlq`
- New ORM models: `decision_results`, `decision_steps`, `mrp_entries`
- New enums: `DecisionStatus`, `DecisionOutcome`, `StepStatus`, `MrpSource`
- Alembic migration for the above
- 11-step pipeline (Steps 1–11 per §6 below)
- `policy.yaml` + `heuristics.md` static files under `backend/app/memory/`
- Case library retrieval via pgvector similarity (graceful skip if empty)
- MRP lookup via `mrp_entries` table
- Prompt caching on policy + heuristics + case-library snapshot
- All audit log actions for decisioning lifecycle (§11)
- Stage machine: `INGESTED → PHASE_1_DECISIONING → PHASE_1_COMPLETE | PHASE_1_REJECTED`
- API endpoints: trigger, read, steps, cancel (§5)
- Shadow mode + feature flags (§10)
- Email notifications for REJECT, ESCALATE_TO_CEO, APPROVE_WITH_CONDITIONS (using M3's SES wrapper)
- New worker container `pfl-decisioning-worker` in docker-compose
- ≥85% coverage on new code

### 2.2 Out of scope (deferred)

- KYC vision (Aadhaar/PAN OCR via image) — Step 4 uses M3 OCR text only
- Live bureau API pull (CIBIL/Equifax) — still manual HTML upload
- Signature matching across documents
- Face match (Aadhaar photo ↔ KYC video)
- Business premises vision analysis — Step 6 uses PD/photo metadata only
- Stock quantification vision — Step 7 writes a stub output + MRP lookups only
- Phase 2 Audit Engine (M6)
- Heuristic distillation from feedback (M7)
- Embedding generation for new cases (pgvector index population — M7)

### 2.3 Non-goals

- M5 does not replace the human approver; it produces a recommendation only.
- M5 does not fine-tune any LLM.
- M5 does not call external APIs (bureau, Finpage, MCA) — reads existing artifacts only.
- M5 does not generate output Word/Excel reports — that is M6's job.

---

## 3. High-Level Architecture

```
FastAPI (pfl-backend)
  POST /cases/{id}/phase1
        │
        │  publishes SQS message
        ▼
  SQS: pfl-decisioning-jobs
        │  (DLQ: pfl-decisioning-dlq, maxReceiveCount=3)
        ▼
  ECS: pfl-decisioning-worker
        │
        ├── app/decisioning/__main__.py   (consumer loop)
        ├── app/decisioning/pipeline.py   (orchestrates steps 1–11)
        ├── app/decisioning/steps/        (step_01.py … step_11.py)
        ├── app/decisioning/prompts/      (Jinja2 .txt templates)
        ├── app/decisioning/parsers/      (output JSON parsers per step)
        ├── app/memory/policy.yaml        (static for M5)
        └── app/memory/heuristics.md      (static for M5)
        │
        ├── reads: case_extractions, case_artifacts, dedupe_matches
        ├── reads: decision_results (idempotency), mrp_entries
        ├── reads: pgvector case library (decision_results embedding col)
        ├── writes: decision_results, decision_steps, mrp_entries
        └── writes: audit_log, case.current_stage
```

New package layout under `backend/app/decisioning/`:

```
decisioning/
  __init__.py
  __main__.py          # SQS consumer loop
  pipeline.py          # run_pipeline(case_id) → DecisionResult
  context.py           # DecisionContext dataclass (assembled from DB reads)
  steps/
    __init__.py
    step_01_policy_gates.py
    step_02_banking.py
    step_03_income_classification.py
    step_04_kyc_match.py
    step_05_address_verification.py
    step_06_business_premises.py
    step_07_stock_quantification.py
    step_08_reconciliation.py
    step_09_pd_analysis.py
    step_10_case_library.py
    step_11_synthesis.py
  prompts/             # Jinja2 .txt templates (one per LLM step)
  parsers/             # parse_step_N_output(raw: str) → dict
  citations.py         # Citation dataclass + helpers
  cost.py              # token → cost_usd calculator
  memory.py            # load policy.yaml + heuristics.md; pgvector query
```

---

## 4. Data Model

### 4.1 New enums (append to `backend/app/enums.py`)

```python
class DecisionStatus(StrEnum):
    """Lifecycle state of a decision_result run."""
    PENDING    = "PENDING"     # enqueued, not started
    RUNNING    = "RUNNING"     # pipeline in progress
    COMPLETED  = "COMPLETED"   # all steps done; final_decision set
    FAILED     = "FAILED"      # unrecoverable error
    CANCELLED  = "CANCELLED"   # admin cancelled mid-run

class DecisionOutcome(StrEnum):
    """The recommendation produced by Step 11."""
    APPROVE                = "APPROVE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    REJECT                 = "REJECT"
    ESCALATE_TO_CEO        = "ESCALATE_TO_CEO"

class StepStatus(StrEnum):
    PENDING  = "PENDING"
    RUNNING  = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED   = "FAILED"
    SKIPPED  = "SKIPPED"   # e.g., Step 10 skipped when case library empty

class MrpSource(StrEnum):
    CASE_PHOTO    = "CASE_PHOTO"    # extracted from a past case's photo
    LLM_ESTIMATE  = "LLM_ESTIMATE"  # Opus fallback estimate
    MANUAL_ENTRY  = "MANUAL_ENTRY"  # admin-entered
```

### 4.2 `decision_results` table

One row per Phase 1 run per case. Multiple runs allowed (re-runs create new rows; latest is canonical).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `case_id` | UUID FK → cases(id) ON DELETE CASCADE, indexed | |
| `phase` | varchar(8) NOT NULL DEFAULT `'1'` | `'1'` for Phase 1; reserved for Phase 2 |
| `status` | `DecisionStatus` enum NOT NULL DEFAULT `PENDING` | |
| `final_decision` | `DecisionOutcome` enum NULL | set when status=COMPLETED |
| `recommended_amount` | integer NULL | INR; one of the ticket-grid values |
| `recommended_tenure` | integer NULL | months |
| `conditions` | JSONB NULL | `[{text: str, type: str}]` |
| `reasoning_markdown` | text NULL | full narrative, every claim cited |
| `pros_cons` | JSONB NULL | `{pros: [str], cons: [str]}` |
| `deviations` | JSONB NULL | `[{name, policy_rule, severity, citation}]` |
| `risk_summary` | JSONB NULL | `{top_risks: [str], confidence_score: int}` |
| `confidence_score` | smallint NULL | 0–100 |
| `token_usage` | JSONB NULL | aggregate across all steps |
| `total_cost_usd` | numeric(10,6) NULL | sum of all step costs |
| `error_message` | text NULL | populated when status=FAILED |
| `triggered_by` | UUID FK → users(id) NULL | who clicked "Run Phase 1" |
| `started_at` | timestamptz NULL | |
| `completed_at` | timestamptz NULL | |
| `created_at` | timestamptz NOT NULL | |
| `updated_at` | timestamptz NOT NULL | |

Index: `(case_id, created_at DESC)` for "latest result" queries.

### 4.3 `decision_steps` table

One row per step per decision_result run. Steps 1–11.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `decision_result_id` | UUID FK → decision_results(id) ON DELETE CASCADE, indexed | |
| `step_number` | smallint NOT NULL | 1–11 |
| `step_name` | varchar(64) NOT NULL | e.g. `"policy_gates"` |
| `model_used` | varchar(64) NULL | `"claude-haiku-4-7"` / `"none"` for Step 1 |
| `status` | `StepStatus` enum NOT NULL DEFAULT `PENDING` | |
| `input_tokens` | integer NULL | |
| `output_tokens` | integer NULL | |
| `cache_read_tokens` | integer NULL | prompt-cache hit tokens |
| `cache_creation_tokens` | integer NULL | prompt-cache write tokens |
| `cost_usd` | numeric(10,6) NULL | |
| `output_data` | JSONB NULL | step-specific output (per §6 schemas) |
| `citations` | JSONB NULL | `[{artifact_id, locator, quoted_text}]` |
| `error_message` | text NULL | |
| `started_at` | timestamptz NULL | |
| `completed_at` | timestamptz NULL | |
| `created_at` | timestamptz NOT NULL | |
| `updated_at` | timestamptz NOT NULL | |

Unique index: `(decision_result_id, step_number)` — one row per step per run. Upsert on conflict.

### 4.4 `mrp_entries` table

Shared price catalog; grows as Step 7 processes cases.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `item_normalized_name` | varchar(256) NOT NULL | lowercased, whitespace-stripped |
| `category` | varchar(64) NOT NULL | e.g. `"cosmetics"`, `"grocery"`, `"hardware"` |
| `unit_price_min_inr` | numeric(12,2) NOT NULL | |
| `unit_price_median_inr` | numeric(12,2) NOT NULL | |
| `unit_price_max_inr` | numeric(12,2) NOT NULL | |
| `source` | `MrpSource` enum NOT NULL | |
| `source_case_id` | UUID FK → cases(id) NULL | if source=CASE_PHOTO |
| `observation_count` | smallint NOT NULL DEFAULT 1 | updated on each new sighting |
| `verified_at` | timestamptz NULL | admin-verified entries |
| `created_at` | timestamptz NOT NULL | |
| `updated_at` | timestamptz NOT NULL | |

Unique index: `(item_normalized_name)` — upsert updates price range + observation_count.

### 4.5 Alembic migration

New revision after M3's latest (chain: `m4_frontend_schema → m5_decisioning`):

- Create Postgres enums: `decision_status`, `decision_outcome`, `step_status`, `mrp_source`
- `CREATE TABLE decision_results (...)`
- `CREATE TABLE decision_steps (...)`
- `CREATE TABLE mrp_entries (...)`
- `ALTER TYPE case_stage ADD VALUE 'PHASE_1_DECISIONING'` — already present in M2 enums.py; migration confirms Postgres enum is up to date
- `CREATE INDEX ix_decision_results_case_id_created ON decision_results (case_id, created_at DESC)`
- `CREATE UNIQUE INDEX uq_decision_steps_result_step ON decision_steps (decision_result_id, step_number)`
- `CREATE UNIQUE INDEX uq_mrp_entries_name ON mrp_entries (item_normalized_name)`

---

## 5. API Endpoints

All endpoints under `backend/app/api/routers/decisioning.py`, mounted at `/cases/{case_id}`.

### 5.1 `POST /cases/{id}/phase1`

Auth: `admin`, `ai_analyser`. Returns `202 Accepted`.

Pre-conditions checked synchronously:
1. Case exists + not soft-deleted.
2. `current_stage == INGESTED` (else 409).
3. `decisioning_enabled` feature flag is `true` (else 503).
4. No existing `decision_result` with `status IN (PENDING, RUNNING)` (else 409 — run already in flight).

On success:
- Creates a `decision_result` row with `status=PENDING`, `triggered_by=current_user.id`.
- Transitions case stage `INGESTED → PHASE_1_DECISIONING` (audited).
- Publishes SQS message `{"case_id": "uuid", "decision_result_id": "uuid"}`.
- Returns `{"decision_result_id": "uuid", "status": "PENDING"}`.

### 5.2 `GET /cases/{id}/phase1`

Auth: any authenticated user. Returns latest `DecisionResultRead` schema (most recent `created_at`). 404 if no runs exist.

### 5.3 `GET /cases/{id}/phase1/steps`

Auth: any authenticated user. Returns `list[DecisionStepRead]` ordered by `step_number`. Includes `output_data` and `citations`.

### 5.4 `GET /cases/{id}/phase1/steps/{n}`

Auth: any authenticated user. Returns single `DecisionStepRead` for step number `n` (1–11). 404 if not yet started.

### 5.5 `POST /cases/{id}/phase1/cancel`

Auth: `admin` only. Returns `200` if cancelled, `409` if run is already COMPLETED or FAILED.

Sets `decision_result.status = CANCELLED`. Worker checks cancellation flag at the start of each step and exits cleanly. Stage reverts to `INGESTED`.

### 5.6 Stage machine additions

| From | To | Trigger |
|---|---|---|
| `INGESTED` | `PHASE_1_DECISIONING` | POST /phase1 (sync, in endpoint) |
| `PHASE_1_DECISIONING` | `PHASE_1_COMPLETE` | Worker: all steps done, decision set |
| `PHASE_1_DECISIONING` | `PHASE_1_REJECTED` | Worker: hard-rule fail in Step 1 |
| `PHASE_1_DECISIONING` | `INGESTED` | Worker: cancel or unrecoverable failure |

`PHASE_1_FAILED` is NOT a separate case stage — failure is tracked on `decision_result.status`. The case stage reverts to `INGESTED` so a re-run can be triggered after fixing the underlying issue.

---

## 6. The 11 Steps

### Step 1: Hard Policy Gates

**Model:** None (pure Python).
**Input context:** Auto CAM extraction, Equifax/CIBIL extraction, checklist extraction, dedupe matches, `policy.yaml`.
**Output JSON schema:**
```json
{
  "passed": true,
  "failures": [{"rule": "cibil_min", "value": 650, "threshold": 700, "severity": "HARD_REJECT"}],
  "warnings": []
}
```
**Hard-fail conditions:** CIBIL < 700 (applicant or co-applicant), written-off/suit-filed/LSS status present, negative business list match, total indebtedness ≥ ₹5L including proposed loan, applicant age outside [21,60] or co-applicant outside [21,65], business > 25 km from branch, required docs checklist incomplete. Any failure → short-circuit: `final_decision = REJECT` (or `ESCALATE_TO_CEO` for negative business match), remaining steps skipped.
**Expected latency:** < 200 ms.

### Step 2: Banking Check

**Model:** `claude-haiku-4-7`.
**Input context:** M3's `BankStatementExtractor` raw text output for the 6-month bank statement.
**Output JSON schema:**
```json
{
  "abb_inr": 18500,
  "bounce_count": 0,
  "foir_feasibility": "FEASIBLE",
  "flags": ["high_round_number_deposit_on_2026-02-01"]
}
```
**Hard-fail conditions:** ABB < proposed monthly EMI. Bounce count > 3 escalates (does not hard-fail alone).
**Expected latency:** 8–15 s.

### Step 3: Income Classification

**Model:** `claude-haiku-4-7`.
**Input context:** Bank statement raw text (transactions), Auto CAM income fields, PD Sheet income section.
**Output JSON schema:**
```json
{
  "business_income_share_pct": 78,
  "income_sources_count": 2,
  "earning_family_members": 3,
  "classification_summary": [{"type": "BUSINESS", "monthly_inr": 42000}]
}
```
**Hard-fail conditions:** None. Low `business_income_share_pct` is a risk flag only.
**Expected latency:** 8–15 s.

### Step 4: KYC & Demographic Match

**Model:** `claude-haiku-4-7`.
**Input context:** M3 OCR text extracted from Aadhaar, PAN, Voter ID, DL artifacts (text-based; vision deferred). Auto CAM personal details.
**Output JSON schema:**
```json
{
  "name_consistent": true,
  "dob_consistent": true,
  "mismatches": [],
  "kyc_confidence": "HIGH"
}
```
**Note (M5 scope):** Face match and vision-based KYC are deferred. This step compares extracted text fields only. If M3 produced no OCR text for a KYC artifact (common for image-only files), the step marks `kyc_confidence = "LOW"` and adds a flag rather than failing.
**Hard-fail conditions:** DOB mismatch across two or more IDs with text coverage.
**Expected latency:** 8–15 s.

### Step 5: Six-Way Address Verification

**Model:** `claude-sonnet-4-7`.
**Input context:** Addresses extracted from (a) Aadhaar, (b) PAN, (c) Equifax/CIBIL report, (d) electricity bill, (e) bank statement header, (f) GPS metadata from house-visit photo (if present in artifact metadata). Policy: ≥4 of 6 must match (same village + pincode).
**Output JSON schema:**
```json
{
  "match_count": 5,
  "sources_matched": ["aadhaar", "equifax", "electricity_bill", "bank_statement", "gps"],
  "sources_mismatched": ["pan"],
  "mismatch_details": [{"source": "pan", "address": "...", "reason": "different pincode"}],
  "verdict": "PASS"
}
```
**Hard-fail conditions:** `match_count < 4` → REJECT.
**Expected latency:** 15–25 s.

### Step 6: Business Premises Check

**Model:** `claude-sonnet-4-7`.
**Input context:** PD Sheet business section (structure quality, ownership), Auto CAM premises fields, business-visit GPS metadata from `BUSINESS_PREMISES_PHOTO` artifact (M5 uses metadata only — no image content analysis). Residence GPS from house-visit photo metadata.
**Output JSON schema:**
```json
{
  "business_distance_km": 3.2,
  "premises_owned": true,
  "structure_type": "PERMANENT_RCC",
  "verdict": "PASS",
  "flags": []
}
```
**Hard-fail conditions:** Business > 25 km from branch. Structure type = `THELA` / `REHDI` / `TEMPORARY`. Both residence and business rented.
**Expected latency:** 15–25 s.

### Step 7: Stock Quantification

**Model:** `claude-opus-4-7` (Step 11 is the other Opus call; Step 7 is intentionally Opus because stock estimation is high-value and nuanced).
**Input context:** PD Sheet business section (stated stock value, items described), Auto CAM business details (annual turnover, business type), MRP database lookup results for items mentioned in PD Sheet.
**M5 scope note:** Vision analysis of business photos is deferred. This step reads item descriptions from the PD Sheet text, looks up each item in `mrp_entries`, and falls back to Opus estimation for unmatched items. A `stub_mode: true` flag is set in `output_data` to signal downstream steps that stock value is estimated, not vision-verified.
**Output JSON schema:**
```json
{
  "stub_mode": true,
  "total_stock_value_inr": 185000,
  "items": [{"name": "Lakme Foundation", "qty": 50, "unit_price_inr": 320, "total_inr": 16000, "mrp_source": "mrp_entries"}],
  "stock_to_loan_ratio": 1.23,
  "verdict": "PASS"
}
```
**Hard-fail conditions:** `stock_to_loan_ratio < 1.0` → REJECT.
**Expected latency:** 25–45 s (Opus + MRP lookups).

### Step 8: Income / Stock / Bank Reconciliation

**Model:** `claude-sonnet-4-7`.
**Input context:** Step 2 output (ABB, FOIR), Step 3 output (income classification), Step 7 output (stock value), Auto CAM income fields, Equifax account list (existing EMIs).
**Output JSON schema:**
```json
{
  "bank_vs_declared_variance_pct": 8,
  "foir_pct": 38,
  "idir_pct": 42,
  "income_stock_aligned": true,
  "verdict": "PASS",
  "flags": ["foir_in_alert_zone"]
}
```
**Hard-fail conditions:** `bank_vs_declared_variance_pct > 15`. `foir_pct > 50`. `idir_pct > 50`.
**Expected latency:** 15–25 s.

### Step 9: PD Sheet Analysis

**Model:** `claude-sonnet-4-7`.
**Input context:** Full PD Sheet extracted content (M3 `PDSheetExtractor` output: fields, tables, paragraphs).
**Output JSON schema:**
```json
{
  "consistency_with_cam": "CONSISTENT",
  "red_flags": [],
  "notable_observations": ["Business vintage confirmed 6 years by neighbor reference"],
  "interview_quality": "THOROUGH"
}
```
**Hard-fail conditions:** None (advisory only; flags feed Step 11 synthesis).
**Expected latency:** 15–30 s.

### Step 10: Case Library Retrieval

**Model:** None (pgvector similarity query).
**Input context:** Current case feature vector (constructed from Auto CAM fields: loan amount, CIBIL score, business type, income, location district, FOIR). pgvector `decision_results` embedding column.
**Process:** `SELECT ... ORDER BY embedding <=> $case_vec LIMIT 10` on `decision_results`. Fetch associated step outputs and final decisions.
**Output JSON schema:**
```json
{
  "retrieved_count": 5,
  "cases": [{"case_id": "...", "similarity": 0.92, "final_decision": "APPROVE", "key_factors": ["..."] }],
  "library_empty": false
}
```
**Graceful degradation:** If `retrieved_count == 0` (library empty in shadow mode), `library_empty = true`, step status = `SKIPPED`. Step 11 proceeds without case library context.
**Expected latency:** < 500 ms (pgvector index scan).

### Step 11: Judgment Synthesis

**Model:** `claude-opus-4-7`.
**Input context:** All prior step outputs (1–10), `policy.yaml` (cached), `heuristics.md` (cached), case library results (if any), NPA pattern summary (extracted from heuristics.md `## NPA Patterns` section).
**Process:** Single large prompt assembling all evidence. Opus produces the final decision narrative, citations, confidence, and any deviations. If any deviation is present or confidence < 60, output is `ESCALATE_TO_CEO`.
**Output JSON schema:**
```json
{
  "final_decision": "APPROVE_WITH_CONDITIONS",
  "recommended_amount": 100000,
  "recommended_tenure": 24,
  "conditions": [{"text": "...", "type": "ADDITIONAL_DOC"}],
  "reasoning_markdown": "...",
  "pros": ["..."],
  "cons": ["..."],
  "deviations": [{"name": "FOIR_ALERT_ZONE", "policy_rule": "foir_cap_pct: 50", "severity": "SOFT"}],
  "risk_summary": {"top_risks": ["..."], "confidence_score": 78},
  "confidence_score": 78
}
```
**Hard-fail conditions:** Any API error after 3 retries → `decision_result.status = FAILED`.
**Expected latency:** 45–90 s (Opus, large context).

---

## 7. Model Cascade + Prompt Caching

### 7.1 Model assignment summary

| Steps | Model | Rationale |
|---|---|---|
| 1 | Python only | Deterministic; no inference needed |
| 2, 3, 4 | claude-haiku-4-7 | High-volume, well-scoped extraction tasks |
| 5, 6, 8, 9 | claude-sonnet-4-7 | Multi-source reasoning, moderate context |
| 7, 11 | claude-opus-4-7 | High-stakes judgment; complex estimation |
| 10 | pgvector | Non-LLM; pure similarity retrieval |

### 7.2 Prompt caching targets

Cache blocks (sent as `cache_control: {"type": "ephemeral"}` with 5-minute TTL):

1. **`policy.yaml` block** — prepended to all LLM steps (Steps 2–9, 11). ~1,500 tokens. Cache creation cost paid once; subsequent steps within the same run hit the cache.
2. **`heuristics.md` block** — prepended to Steps 9 and 11. ~3,000 tokens.
3. **Case library snapshot block** — passed to Step 11 only. Up to 8,000 tokens (top-10 past cases). Cache creation amortized across retries.

Steps 2–9 share the policy block. For a single pipeline run, cache creation is charged once (Step 2); Steps 3–9 and 11 pay the cache-read rate (≈10% of input token cost).

### 7.3 Per-step token caps

| Step | Max input tokens | Max output tokens |
|---|---|---|
| 2 | 8,000 | 512 |
| 3 | 10,000 | 1,024 |
| 4 | 6,000 | 512 |
| 5 | 8,000 | 1,024 |
| 6 | 6,000 | 512 |
| 7 | 12,000 | 2,048 |
| 8 | 8,000 | 1,024 |
| 9 | 10,000 | 2,048 |
| 11 | 32,000 | 4,096 |

If input context exceeds the cap, `pipeline.py` truncates lower-priority context (raw bank statement text first, then PD paragraphs, then CAM narrative sections) and logs a `context.truncated` warning.

### 7.4 Cost budget

- Target average: **< $0.50/case**
- p99 ceiling: **< $1.50/case**
- Hard abort if `total_cost_usd > 2.00` within a single run (safety valve; logs `decision.cost_exceeded`).

Approximate per-step cost breakdown (with cache hits in steady state):

| Step | Est. cost |
|---|---|
| 2–4 (Haiku ×3) | $0.02–0.04 |
| 5–6, 8–9 (Sonnet ×4) | $0.06–0.12 |
| 7 (Opus, stock stub) | $0.05–0.10 |
| 11 (Opus, synthesis) | $0.20–0.40 |
| **Total** | **$0.33–0.66** |

---

## 8. Citations + Evidence Tracking

Every factual claim in reasoning output must include a citation. Citations are tracked at the step level in `decision_steps.citations` and at the result level in `decision_results.reasoning_markdown` (inline `[^n]` references).

**Citation schema:**
```json
{
  "artifact_id": "uuid-of-CaseArtifact",
  "locator": "row:42:col:B",
  "quoted_text": "CIBIL Score: 769"
}
```

`locator` format conventions:
- xlsx: `"sheet:{SheetName}:row:{n}:col:{letter}"`
- docx: `"para:{n}"` or `"table:{n}:row:{r}:col:{c}"`
- html: `"css:{selector}"` (Equifax report)
- pdf: `"page:{n}:line:{l}"` (bank statement)
- metadata: `"artifact_metadata:{field}"` (GPS coordinates, MIME type)

**Uncited claim policy:** If the LLM output contains a factual statement without a citation, the parser emits a `citation_missing` warning into `decision_steps.output_data.warnings`. The step is still marked COMPLETE; Step 11 synthesis notes the uncited claims in its confidence assessment.

**Citation injection in prompts:** Each step prompt template includes the relevant artifact IDs and their locator ranges, instructing the model to use them. The parser validates that every cited `artifact_id` exists in the case's `CaseArtifact` rows.

---

## 9. Memory Subsystem Interfaces

M5 reads all memory stores. M7 owns editing.

### 9.1 `policy.yaml`

Location: `backend/app/memory/policy.yaml`. Loaded once per worker startup via `memory.load_policy()`. Validated against a Pydantic schema. Cached in-process for the duration of the run. Structure follows the example in parent spec §7.1.

### 9.2 `heuristics.md`

Location: `backend/app/memory/heuristics.md`. Loaded once per worker startup via `memory.load_heuristics()`. Plain markdown; passed verbatim as a cache block. Seed content from parent spec §7.1 (11 hard rules + soft signals).

### 9.3 Case library (pgvector)

`memory.retrieve_similar_cases(case_feature_vector, k=10)`:
- Queries `decision_results` where `status = COMPLETED` and `embedding IS NOT NULL`.
- Computes cosine distance via pgvector `<=>` operator.
- Returns top-K rows with `final_decision`, `confidence_score`, `conditions`, `reasoning_markdown` summary (first 500 chars).
- If `pgvector` extension is not installed or no rows qualify: returns empty list; Step 10 sets `library_empty = true`.

**Feature vector construction** (Step 10 input, M5 scope):
- 8-dimensional float array: `[loan_amount_normalized, cibil_score_normalized, foir_pct, business_type_hash, district_hash, income_inr_normalized, abb_inr_normalized, tenure_months_normalized]`
- Embeddings are stored as-is in a `vector(8)` pgvector column on `decision_results`. Full sentence-embedding via Voyage is deferred to M7 — M5 uses this lightweight numerical vector for basic similarity.

### 9.4 MRP database

`memory.lookup_mrp(item_name: str) -> MrpEntry | None`:
- Normalizes `item_name` (lowercase, strip).
- Queries `mrp_entries` on `item_normalized_name` exact match, then trigram fuzzy match (pg_trgm similarity > 0.7).
- Returns the best match or `None` (Step 7 falls back to Opus estimate).

`memory.upsert_mrp(item_name, category, unit_price, source, case_id)`:
- On new item: insert.
- On existing item: recalculate median price from new observation; increment `observation_count`.

---

## 10. Shadow Mode + Feature Flags

Three config flags in `backend/app/config.py`:

```python
decisioning_enabled: bool = False          # master on/off; False until shadow-mode approval
decisioning_shadow_only: bool = True       # True = run pipeline but suppress email notifications
                                           # and do not surface recommendation in UI
decisioning_step_flags: dict[str, bool] = {  # per-step enable/disable for debugging
    "step_01": True,
    "step_02": True,
    ...
    "step_11": True,
}
```

**Shadow mode behaviour:**
- `decisioning_shadow_only = True`: pipeline runs fully, all DB writes persist, but:
  - Decision recommendation is NOT shown in the frontend case detail (hidden behind a flag check).
  - No CEO/underwriter email notifications are sent.
  - Audit log still records all decision events (for retrospective analysis).
- After 100 shadow cases reviewed and Saksham approves: flip `decisioning_shadow_only = False`.
- `decisioning_enabled = False` prevents the `POST /phase1` endpoint from enqueueing any job (returns 503).

**Per-step flags:** `decisioning_step_flags["step_07"] = False` causes the pipeline to skip Step 7 and write a `SKIPPED` step row. Step 11 adapts by noting stock data unavailable.

---

## 11. Audit Actions

All audit actions recorded to `audit_log` with `entity_type = "decision_result"` or `"mrp_entry"` and the relevant entity ID.

| Action | When | Notes |
|---|---|---|
| `decision.started` | Worker picks up job; pipeline begins | |
| `decision.completed` | Pipeline finishes; `status → COMPLETED` | includes `final_decision`, `confidence_score`, `total_cost_usd` in `after_json` |
| `decision.failed` | Unrecoverable error; `status → FAILED` | `after_json` has error_message + last completed step |
| `decision.canceled` | Admin cancels; `status → CANCELLED` | |
| `decision.step_started` | Each step begins | `after_json: {step_number, step_name}` |
| `decision.step_completed` | Each step finishes | `after_json: {step_number, status, cost_usd}` |
| `decision.step_failed` | A step fails (may retry) | |
| `decision.hard_reject_shortcircuit` | Step 1 finds a hard-fail | `after_json: {failures: [...]}` |
| `decision.escalated_to_ceo` | Step 11 sets `ESCALATE_TO_CEO` | |
| `decision.cost_exceeded` | `total_cost_usd > 2.00` safety abort | |
| `mrp.entry_created` | New item inserted into `mrp_entries` | |
| `mrp.entry_updated` | Existing item price updated | `before_json` / `after_json` have price range |

Actor for all worker-originated events: `SYSTEM_WORKER_USER_ID` (same seed user as M3's `worker@system.pflfinance.internal`).

---

## 12. Worker Integration

### Option A: Extend existing `pfl-worker`

Add a second SQS queue consumer to M3's `app/worker/__main__.py`. Keeps one container; reduces operational complexity.

### Option B: New `pfl-decisioning-worker` container

Separate ECS task definition and docker-compose service. Consumes only `pfl-decisioning-jobs`.

**Decision: Option B.**

Rationale:
- Different scaling profile: ingestion is fast (< 30 s/case, CPU-bound), decisioning is slow (2–5 min/case, I/O-bound on Anthropic API). They must scale independently.
- Decisioning worker needs `ANTHROPIC_API_KEY`; ingestion worker does not. Separate containers minimize credential surface.
- Fault isolation: an Anthropic API outage should not block M3 ingestion jobs.
- Cleaner `requirements.txt` separation (decisioning adds `anthropic`, `pgvector`; ingestion does not need these).

### 12.1 Worker process

`backend/app/decisioning/__main__.py`:

```python
while True:
    messages = await decisioning_queue.consume_jobs(
        handler=process_decisioning_job,
        wait_seconds=20
    )
```

Job payload:
```json
{"case_id": "uuid", "decision_result_id": "uuid"}
```

On pickup: set `decision_result.status = RUNNING`, record `started_at`.

### 12.2 docker-compose service

```yaml
  decisioning-worker:
    build: ./backend
    container_name: pfl-decisioning-worker
    environment:
      # same DB url, AWS endpoints as pfl-backend
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      postgres: { condition: service_healthy }
      localstack: { condition: service_healthy }
    command: python -m app.decisioning
```

---

## 13. Error Handling + Retries

### 13.1 Anthropic API errors

- `RateLimitError` / `OverloadedError`: exponential backoff, 3 attempts (delays: 5 s, 20 s, 60 s). On 3rd failure: step `status = FAILED`, decision `status = FAILED`, case reverts to `INGESTED`.
- `AuthenticationError`: immediate fail, no retry (config issue — alert required).
- `APIStatusError` (5xx): same as rate limit retry policy.

### 13.2 Step-level idempotency

Each step uses an upsert on `(decision_result_id, step_number)`. If the worker is killed mid-step and the message reappears from SQS, `pipeline.py` checks `decision_result.status`:
- `COMPLETED`: log + skip (idempotent re-deliver).
- `RUNNING`: find last `COMPLETE` step; resume from `step_number + 1`.
- `PENDING`/`FAILED`: restart from Step 1.

### 13.3 Resume-from-last-successful-step

`pipeline.run_pipeline(case_id, decision_result_id)` at startup:
1. Load all `decision_steps` rows for this `decision_result_id`.
2. Find max `step_number` where `status = COMPLETE`.
3. If found: skip steps ≤ max; run from max + 1.
4. Policy block and heuristics are re-loaded (cache TTL may have expired between attempts).

### 13.4 DLQ

After 3 SQS delivery attempts: message moves to `pfl-decisioning-dlq`. Admin must inspect and manually re-trigger via `POST /cases/{id}/phase1` after fixing the underlying issue. DLQ messages are NOT auto-replayed.

---

## 14. Testing Strategy

### 14.1 Unit tests — per step

One test module per step (`tests/decisioning/test_step_01.py` … `test_step_11.py`):
- Step 1: policy gates with fixture extraction dicts; cover all 8 hard-fail conditions.
- Steps 2–9, 11: provide fixture extraction dicts + pre-built Anthropic response JSON (in `tests/fixtures/decisioning/step_N_response.json`). Mock `anthropic.AsyncAnthropic` via `unittest.mock.AsyncMock`. Assert parser output matches expected schema.
- Step 10: mock pgvector query; test empty-library path.

### 14.2 Parser unit tests

`tests/decisioning/test_parsers.py` — each parser tested against valid and malformed LLM output strings. Assert graceful degradation (warnings emitted, no exception raised).

### 14.3 Pipeline integration test

`tests/decisioning/test_pipeline_integration.py`:
- Use LocalStack SQS + real Postgres (test DB).
- Load fixture case (from M3 fixture case ZIP, fully ingested).
- Run `pipeline.run_pipeline(case_id, ...)` with all Anthropic calls mocked.
- Assert: all 11 `decision_steps` rows created; `decision_result.status = COMPLETED`; stage = `PHASE_1_COMPLETE`; audit entries correct.

### 14.4 E2E test

`tests/decisioning/test_e2e.py` (skipped if `ANTHROPIC_API_KEY` not set in environment):
- Runs full 11-step pipeline against the real Anthropic API on the Seema fixture case.
- Assert: `final_decision` is one of the valid `DecisionOutcome` values; `total_cost_usd < 1.50`; all steps COMPLETE; no uncited claim warnings in Step 11 output.

### 14.5 Coverage target

≥85% on `app/decisioning/` package.

---

## 15. Dependencies

New packages added to `backend/requirements.txt`:

- `anthropic >= 0.40` — Anthropic Python SDK (includes prompt-caching support via `cache_control` param)
- `pgvector >= 0.3` — pgvector SQLAlchemy integration for `vector` column type and `<=>` operator

No other new dependencies. `jinja2` (for prompt templates) is already in requirements from M3.

---

## 16. Configuration

New fields in `backend/app/config.py`:

```python
# Anthropic
anthropic_api_key: str               # required; no default
anthropic_default_timeout_s: int = 120
anthropic_max_retries: int = 3

# Decisioning
decisioning_enabled: bool = False
decisioning_shadow_only: bool = True
decisioning_step_flags: dict = {}    # overrides per-step; empty = all enabled
decisioning_cost_abort_usd: float = 2.00

# SQS
decisioning_queue_url: str           # required when decisioning_enabled=True
decisioning_dlq_url: str             # for monitoring only

# pgvector
pgvector_feature_dimensions: int = 8
case_library_retrieval_k: int = 10
case_library_similarity_threshold: float = 0.70

# MRP
mrp_fuzzy_match_threshold: float = 0.70
```

New environment variables (`.env.example`):
- `ANTHROPIC_API_KEY`
- `DECISIONING_QUEUE_URL`
- `DECISIONING_DLQ_URL`
- `DECISIONING_ENABLED=false`
- `DECISIONING_SHADOW_ONLY=true`

---

## 17. Definition of Done

- [ ] `pfl-decisioning-worker` container builds and boots cleanly
- [ ] `decision_results`, `decision_steps`, `mrp_entries` tables created by migration; all constraints and indexes in place
- [ ] `POST /cases/{id}/phase1` enqueues job and transitions stage in one transaction
- [ ] All 11 steps run end-to-end on the Seema fixture case (Anthropic mocked) with correct `decision_steps` rows written
- [ ] Step 1 hard-fail short-circuits the pipeline and produces `PHASE_1_REJECTED` stage
- [ ] Step 10 graceful degradation (empty library → `SKIPPED`, pipeline continues)
- [ ] Prompt caching applied to policy + heuristics blocks; `cache_read_tokens > 0` on second run in integration test
- [ ] `GET /cases/{id}/phase1/steps/{n}` returns citations with valid `artifact_id` references
- [ ] Shadow mode: with `decisioning_shadow_only=True`, no email notifications sent, no recommendation visible in API response
- [ ] ≥85% coverage on `app/decisioning/`; ruff + mypy clean; tag `m5-decisioning-engine` on merge commit

---

## 18. Out of M5

The following items are explicitly excluded from M5 and will be addressed in later milestones:

- **KYC vision** — Aadhaar/PAN/Voter OCR from JPEG/PNG images via Haiku vision. Step 4 uses text only.
- **Live bureau API** — CIBIL/Equifax/Experian direct pull. Still requires manual HTML upload from M3.
- **Signature matching** — Cross-document signature comparison.
- **Face match** — Aadhaar photo ↔ KYC video thumbnail ↔ visit photo.
- **Business premises vision** — Photo content analysis for Step 6 (structure quality, premises type, roof type).
- **Stock vision** — Photo-based item identification and quantity estimation for Step 7.
- **Full sentence embeddings** — Voyage-based semantic embeddings for the case library. M5 uses the 8-dim numerical vector.
- **Heuristic distillation** — Semi-automatic feedback → heuristic rule extraction (M7).
- **Phase 2 audit engine** (M6).

---

## 19. Cross-Reference to Parent Spec

| Parent spec section | Coverage in M5 |
|---|---|
| §5.1 — Phase 1 Purpose | §1 (Executive Summary) |
| §5.2 — Decision outputs | §4.2 (`decision_results` columns) |
| §5.3 — Decision logic flow (11 steps) | §6 (Steps 1–11) |
| §5.4 — Hard-rule reject policy | §6 Step 1; §5.6 stage machine |
| §5.5 — Auto-escalation policy | §6 Step 11 hard-fail conditions |
| §5.6 — Email notifications | §10 (shadow mode); §12 (worker) |
| §4.2 — Model cascade | §7.1 |
| §4.3 — Cost per case | §7.4 |
| §7.1 — Memory stores (policy, heuristics, case library, MRP) | §9 |
| §8 — Data model (phase_1_outputs, mrp_entries) | §4 |
| §9 — Workflow stages (PHASE_1_DECISIONING, PHASE_1_COMPLETE) | §5.6 |
| §14 — Model cascade detail | §7 |
| §18 — Cost targets | §7.4 |

---

*End of M5 spec. Next: spec review → plan → execute → merge.*
