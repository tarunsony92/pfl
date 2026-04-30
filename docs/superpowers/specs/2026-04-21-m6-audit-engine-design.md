# Milestone 6: Phase 2 Audit Engine — Design Spec

**Project:** PFL Finance Credit AI Platform
**Milestone:** M6
**Version:** 1.0
**Spec date:** 2026-04-21
**Author:** Saksham Gupta (with Claude)
**Status:** Draft — pending spec review
**Builds on:** M3 (tag `m3-ingestion-workers`), M4 (frontend shell), M5 (tag `m5-decisioning-engine`)
**Parent design:** `/Users/sakshamgupta/Desktop/PFL credit system/docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md` §6

---

## 1. Executive Summary

M6 implements the Phase 2 Audit Engine — an independent, arm's-length auditor that re-reads a decisioned case kit and produces audit-grade outputs. It runs after M5's Phase 1 decisioning completes and consists of three sub-jobs dispatched in parallel by a new worker container (`pfl-audit-worker`) consuming a dedicated SQS queue:

1. **Layer A fill** — auto-populates the 30-point credit audit rubric (sections A–D, max 100 pts) using a cascade of deterministic rules and Haiku-judged items governed by a declarative YAML rubric.
2. **Layer B partial fill** — auto-populates ~60–80 of the 150 operational audit items across 17 sections; remaining items are stamped `Pending API` awaiting Finpage integration (v2).
3. **Doc cross-verification + exec summary** — runs a suite of mismatch rules across CAM ↔ Equifax ↔ Bank ↔ Case metadata and then generates a 1–2 page Word exec summary via Sonnet.

Outputs: `{loan_id}_30pt_audit_filled.xlsx`, `{loan_id}_150pt_audit_partial.xlsx`, `{loan_id}_mismatch_log.xlsx`, `{loan_id}_audit_summary.docx`. Verdict is bucketed from Layer A score: **PASS ≥ 90 · CONCERN 70–89 · FAIL < 70**. Target cost is **under $0.35 per case average, under $0.80 p99**. M6 is spec-only for Layer B deep-fill (Finpage API), live bureau APIs, and vision-based 30-point items — those ship in later milestones.

---

## 2. Scope

### 2.1 In scope for M6

- New `app/auditing/` package (worker, sub-jobs, rubric loader, mismatch engine, docx generator)
- New SQS queue `pfl-audit-jobs` + DLQ `pfl-audit-dlq`
- New ORM models: `audit_results`, `audit_steps`; new enums: `AuditStatus`, `AuditVerdict`, `AuditStepName`
- Alembic migration for the above (case_stage additions already in place per M2)
- Declarative YAML files under `backend/app/memory/`: `audit_rubric_30pt.yaml` (30 items, weights, evaluators), `audit_schema_150pt.yaml` (17 sections, ~150 items, source mapping, v1 fillable flag), `audit_mismatch_rules.yaml` (6–8 cross-document rules)
- Three sub-jobs dispatched as `asyncio.gather` tasks (§6); XLSX output via `openpyxl`; DOCX output via `python-docx`
- Upload of 4 output files to S3 under `cases/{case_id}/phase2/{loan_id}_*.{xlsx,docx}`
- Prompt caching on rubric text + policy.yaml for Haiku/Sonnet calls
- Shadow mode + feature flags (§13); stage machine `PHASE_1_COMPLETE → PHASE_2_AUDITING → PHASE_2_COMPLETE` (parent spec §9). Frontend displays aliases `Auditing` / `Audited`; DB stages keep M2 names for backward compatibility.
- API endpoints (§5); new worker container `pfl-audit-worker` in docker-compose
- Frontend "Phase 2" tab with verdict badge, section score table, mismatch/deviation log tables, 4 download buttons (§20)
- ≥85% coverage on new code

### 2.2 Out of scope (deferred)

- Layer B deep-fill (~70–90 items pending Finpage API; v2)
- Vision-based audit items (premises roof-type, stock quantification) — Layer A uses `v1_textonly_proxy: true` flag where vision would be ideal
- Live bureau API cross-verification (still uses M3 HTML extractions)
- Feedback-driven rubric tuning (static YAML in v1; live editor in M7)
- Signature cross-checking, face match (Aadhaar ↔ KYC video)
- PDF output generation (xlsx + docx only in v1; PDF bundle is M7)
- Layer C/D/E expansion of the 30-point rubric (parent spec lists A–D only)

### 2.3 Non-goals

- Does not override the Phase 1 decision — audit verdict is independent (Phase 1 APPROVE + Phase 2 CONCERN is valid).
- Does not call external APIs (Finpage, bureau, MCA); reads only existing `case_extractions`, `case_artifacts`, and the latest COMPLETED `decision_result`.
- Does not send email notifications in v1 (CEO dispatch is M7).
- Does not fine-tune any LLM.

---

## 3. High-Level Architecture

```
FastAPI → POST /cases/{id}/phase2 → SQS pfl-audit-jobs (DLQ pfl-audit-dlq)
       (precondition: decision_result.status = COMPLETED for latest run)
                                 │
                                 ▼
               ECS: pfl-audit-worker (app/auditing/__main__.py)
                  engine.run_phase2() dispatches via asyncio.gather:

               ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
               │ LAYER_A_FILL │ │ LAYER_B_FILL │ │  DOC_XREF    │
               │ rubric eval  │ │ schema fill  │ │ rule engine  │
               └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
                      └───────── gather ───────────────┘
                                 │
                                 ▼
                     EXEC_SUMMARY (Sonnet + docx)
                                 │
                                 ▼
              write 4 outputs to S3 + finalize audit_result/audit_steps

reads: case_extractions, case_artifacts, decision_results (latest),
       audit_rubric_30pt.yaml, audit_schema_150pt.yaml, audit_mismatch_rules.yaml
writes: audit_results, audit_steps, audit_log, S3 (3× xlsx + 1× docx)
```

### 3.1 Package layout

New package `backend/app/auditing/`:

```
auditing/
  __main__.py               # SQS consumer loop
  engine.py                 # run_phase2(session, audit_result_id, actor_user_id)
  context.py                # AuditContext dataclass (assembled from DB reads)
  subjobs/{layer_a,layer_b,doc_xref,exec_summary}.py
  rubric.py / schema.py / mismatch_rules.py    # YAML loaders + Pydantic validators
  evaluators/{rule_evaluator,ai_evaluator}.py
  outputs/{xlsx_writer_30pt,xlsx_writer_150pt,xlsx_writer_mismatch,docx_writer}.py
  cost.py                   # reuse M5 pattern; token → usd
```

---

## 4. Data Model

### 4.1 New enums (append to `backend/app/enums.py`)

```python
class AuditStatus(StrEnum):
    """Lifecycle state of an audit_result run. M6."""

    PENDING   = "PENDING"     # enqueued, not started
    RUNNING   = "RUNNING"     # engine in progress (any sub-job active)
    COMPLETED = "COMPLETED"   # all sub-jobs done; verdict set
    FAILED    = "FAILED"      # unrecoverable error
    CANCELLED = "CANCELLED"   # admin cancelled mid-run


class AuditVerdict(StrEnum):
    """Bucketed verdict derived from layer_a_score. M6."""

    PASS    = "PASS"      # layer_a_score >= 90
    CONCERN = "CONCERN"   # 70 <= layer_a_score < 90
    FAIL    = "FAIL"      # layer_a_score < 70


class AuditStepName(StrEnum):
    """The four sub-job step identities. M6."""

    LAYER_A_FILL = "LAYER_A_FILL"
    LAYER_B_FILL = "LAYER_B_FILL"
    DOC_XREF     = "DOC_XREF"
    EXEC_SUMMARY = "EXEC_SUMMARY"
```

`StepStatus` (defined in M5) is re-used for audit steps. No new StepStatus values are added.

### 4.2 `audit_results` table

One row per Phase 2 run per case. Re-runs insert new rows; latest by `created_at DESC` is canonical.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `case_id` | UUID FK → cases(id) ON DELETE CASCADE, indexed | |
| `decision_result_id` | UUID FK → decision_results(id) NULL | Phase 1 run being verified |
| `status` | `AuditStatus` enum NOT NULL DEFAULT `PENDING` | |
| `verdict` | `AuditVerdict` enum NULL | set when status=COMPLETED |
| `layer_a_score` | numeric(5,2) NULL | 0.00–100.00 |
| `layer_a_section_scores` | JSONB NULL | `{A: 42.0, B: 28.0, C: 13.0, D: 7.0}` |
| `layer_b_fill_count` | smallint NULL | filled items (not Pending API) |
| `layer_b_pending_count` | smallint NULL | = 150 − layer_b_fill_count |
| `mismatch_count` | smallint NULL | rows in mismatch_log |
| `deviation_count` | smallint NULL | rows in Layer A deviation log |
| `critical_issue_count` | smallint NULL | CRITICAL mismatches + hard rubric fails |
| `output_s3_keys` | JSONB NOT NULL DEFAULT `'{}'::jsonb` | `{"30pt","150pt","mismatch","summary"}` → s3 keys |
| `token_usage` | JSONB NULL | aggregate across sub-jobs |
| `total_cost_usd` | numeric(10,6) NULL | |
| `error_message` | text NULL | on status=FAILED |
| `triggered_by` | UUID FK → users(id) NULL | |
| `started_at` / `completed_at` / `created_at` / `updated_at` | timestamptz | |

Index: `(case_id, created_at DESC)`.

### 4.3 `audit_steps` table

Exactly 4 rows per `audit_result` (one per `AuditStepName`).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `audit_result_id` | UUID FK → audit_results(id) ON DELETE CASCADE, indexed | |
| `step_name` | `AuditStepName` enum NOT NULL | LAYER_A_FILL / LAYER_B_FILL / DOC_XREF / EXEC_SUMMARY |
| `model_used` | varchar(64) NULL | `"claude-haiku-4-7"` / `"claude-sonnet-4-7"` / `"none"` |
| `status` | `StepStatus` enum NOT NULL DEFAULT `PENDING` | (reused from M5) |
| `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_creation_tokens` | integer NULL | |
| `cost_usd` | numeric(10,6) NULL | |
| `output_data` | JSONB NULL | step-specific output (per §6 schemas) |
| `error_message` | text NULL | |
| `started_at` / `completed_at` / `created_at` / `updated_at` | timestamptz | |

Unique index: `(audit_result_id, step_name)` — upsert on conflict.

### 4.4 Alembic migration

New revision after M5's latest (chain: `m5_decisioning → m6_auditing`):

- Create Postgres enums: `audit_status`, `audit_verdict`, `audit_step_name`
- `CREATE TABLE audit_results (...)`
- `CREATE TABLE audit_steps (...)`
- `CREATE INDEX ix_audit_results_case_id_created ON audit_results (case_id, created_at DESC)`
- `CREATE UNIQUE INDEX uq_audit_steps_result_stepname ON audit_steps (audit_result_id, step_name)`
- No `case_stage` enum alterations (PHASE_2_AUDITING / PHASE_2_COMPLETE already present per M2)

---

## 5. API Endpoints

All endpoints under `backend/app/api/routers/auditing.py`, mounted at `/cases/{case_id}`. Mirror the symmetry of M5's `decisioning.py` router.

### 5.1 `POST /cases/{id}/phase2`

Auth: `admin`, `ai_analyser`. Returns `202 Accepted`.

Pre-conditions (synchronous, all else → 409 / 503):
1. Case exists + not soft-deleted.
2. `current_stage == PHASE_1_COMPLETE` (`PHASE_1_REJECTED` NOT eligible — rejected cases skip audit).
3. `auditing_enabled` feature flag true (else 503).
4. Latest `decision_result` has `status = COMPLETED`.
5. No existing `audit_result` with `status ∈ {PENDING, RUNNING}`.

On success: create `audit_result` row (`status=PENDING`, `triggered_by=current_user.id`, `decision_result_id=<latest completed>`); transition stage `PHASE_1_COMPLETE → PHASE_2_AUDITING` (audited); publish SQS `{"case_id", "audit_result_id", "actor_user_id"}`; return `{audit_result_id, status: "PENDING"}`.

### 5.2 `GET /cases/{id}/phase2`

Auth: any authenticated user. Returns latest `AuditResultRead` schema (most recent `created_at`). 404 if no runs exist.

Response schema (Pydantic `AuditResultRead`): `id, case_id, decision_result_id, status, verdict, layer_a_score, layer_a_section_scores, layer_b_fill_count, layer_b_pending_count, mismatch_count, deviation_count, critical_issue_count, output_s3_keys, total_cost_usd, error_message, started_at, completed_at, created_at` — types match the table columns in §4.2.

### 5.3 `GET /cases/{id}/phase2/steps`

Auth: any authenticated user. Returns `list[AuditStepRead]` — always 4 rows (one per AuditStepName), ordered by the canonical enum order (LAYER_A_FILL, LAYER_B_FILL, DOC_XREF, EXEC_SUMMARY). Includes `output_data` for frontend table rendering.

### 5.4 `GET /cases/{id}/phase2/outputs/{output_key}`

Auth: any authenticated user with case visibility. `output_key ∈ {"30pt", "150pt", "mismatch", "summary"}`.

Returns a **presigned S3 GET URL** (15-minute TTL) in the response body:
```json
{"download_url": "https://…s3…?X-Amz-Signature=…", "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "filename": "10006484_30pt_audit_filled.xlsx"}
```

Frontend download buttons fetch this, then follow the URL. 404 if `output_s3_keys[output_key]` is absent (e.g., the sub-job failed). 410 if the S3 object no longer exists (archived).

### 5.5 `POST /cases/{id}/phase2/cancel`

Auth: `admin` only. Returns `200` if cancelled, `409` if run is already COMPLETED or FAILED.

Sets `audit_result.status = CANCELLED`. Worker checks cancellation flag between sub-job completions (sub-jobs do not interrupt mid-call — the `asyncio.gather` awaits outstanding sub-jobs before honouring cancellation, to avoid leaked Anthropic tokens charged-but-discarded). Stage reverts to `PHASE_1_COMPLETE`.

### 5.6 Stage machine additions

- `PHASE_1_COMPLETE → PHASE_2_AUDITING` — POST /phase2 (sync, in endpoint)
- `PHASE_2_AUDITING → PHASE_2_COMPLETE` — worker: all sub-jobs done, verdict set
- `PHASE_2_AUDITING → PHASE_1_COMPLETE` — worker: cancel or unrecoverable failure

`PHASE_2_FAILED` is NOT a separate stage — failure is tracked on `audit_result.status`; stage reverts to `PHASE_1_COMPLETE` so a re-run can be triggered after fix. Frontend aliases: `PHASE_2_AUDITING` → "Auditing", `PHASE_2_COMPLETE` → "Audited".

---

## 6. The 3 Sub-Jobs

The audit worker dispatches sub-jobs concurrently via `asyncio.gather` inside `app/auditing/engine.py`. LAYER_A_FILL, LAYER_B_FILL, and DOC_XREF run fully in parallel; EXEC_SUMMARY awaits the first three, then runs sequentially.

```python
async def run_phase2(session, audit_result_id, actor_user_id):
    ctx = await build_context(session, audit_result_id)
    layer_a, layer_b, xref = await asyncio.gather(
        run_layer_a(ctx), run_layer_b(ctx), run_doc_xref(ctx)
    )
    summary = await run_exec_summary(ctx, layer_a, layer_b, xref)
    await write_outputs_and_finalize(ctx, layer_a, layer_b, xref, summary)
```

### 6.1 Sub-job LAYER_A_FILL (30-point rubric fill)

**Model:** Per-item cascade: `none` (Python rules, 20 items) or `claude-haiku-4-7` (AI items, 10 items, batched 5/call). No Sonnet/Opus at item level.

**Input context:** full `case_extractions` (CAM, Equifax, Bank, PD Sheet, KYC, Checklist); latest completed `decision_result` (used as one evidence source — audit verifies Phase 1, does not defer); `audit_rubric_30pt.yaml`; `policy.yaml` (shared with M5).

**Process:**
1. Load rubric via `rubric.load_rubric()` → `Rubric` dataclass (30 items grouped A/B/C/D).
2. Dispatch each item to `rule_evaluator` or `ai_evaluator` based on `evaluator: {rule|ai}`.
3. Rule evaluator runs the YAML `expression` (sandboxed via `simpleeval`) against the `AuditContext` namespace → `{status, score, evidence, notes}`.
4. AI evaluator builds a Haiku prompt from `ai_prompt_template` (+ cached rubric + cached policy blocks), calls Anthropic, parses `{status, score, evidence_citation, notes}` JSON.
5. Batches AI items 5/call to reduce per-item overhead.
6. Aggregates into section scores (A/B/C/D) and `layer_a_score`, derives verdict bucket (PASS ≥ 90, CONCERN 70–89, FAIL < 70).
7. Builds the "Deviation & Error Log" block (max 10 rows) from items with `status == "Fail"` and severity ≠ `info`.

**Output schema** (`audit_steps.output_data` for LAYER_A_FILL):
```json
{
  "layer_a_score": 87.0,
  "section_scores": {"A": 41.0, "B": 26.0, "C": 13.0, "D": 7.0},
  "items": [
    {
      "item_id": "A1", "title": "CIBIL score >= 750", "weight": 5,
      "status": "PARTIAL", "score": 3.0, "evaluator": "rule",
      "evidence": {"artifact_id": "uuid", "locator": "equifax.credit_score", "quoted_text": "720"},
      "notes": "Score 720 — above Saksham floor, below policy ideal", "risk_flag": "WARN"
    }
  ],
  "deviation_log": [
    {"s_no": 1, "category": "Bureau", "description": "...", "role": "Credit",
     "step_violated": "CIBIL min", "impact": "MEDIUM", "default_risk": "MEDIUM",
     "action": "CEO deviation approval", "status": "OPEN", "notes": "..."}
  ],
  "computed_blocks": {
    "declared_income_inr": 420000, "bank_6m_avg_credits_inr": 398000,
    "abb_inr": 18500, "proposed_emi_inr": 8542, "abb_to_emi_ratio": 2.16,
    "foir_pct": 38.0, "income_variance_pct": 5.2,
    "eligibility_calc_amount_inr": 120000, "sanctioned_amount_inr": 100000,
    "living_standard_rating": "MODERATE", "eb_verdict": "CONSISTENT"
  }
}
```

**Latency:** 45–90 s. **Sub-job hard-fail:** none — individual item failures only affect score. Haiku parse failure after 3 retries → item marked PARTIAL, score 0, `parser_failure` flag; sub-job continues.

### 6.2 Sub-job LAYER_B_FILL (150-point schema partial fill)

**Model:** Mostly `none` (schema-driven lookup). Small narrative subset uses `claude-haiku-4-7` (target ≤ 15 items, batched).

**Input context:** full `case_extractions`, `case_artifacts`, latest completed `decision_result` (feeds J-QR + Q-Site-Visit verdicts), `audit_schema_150pt.yaml`.

**Process:** Load 17-section schema; each item has `field_name`, `source` (dotted path like `case_extractions.auto_cam.applicant_name`), `v1_fillable: {true|false|"ai"}`. For `true` items: fetch via dotted-path lookup → `status = FILLED`. For `false`: `status = PENDING_API`. For `"ai"`: batch into Haiku calls → parse `{value, status, notes}`. Track `layer_b_fill_count` + `layer_b_pending_count`.

**Output schema** (`audit_steps.output_data` for LAYER_B_FILL):
```json
{
  "fill_count": 72, "pending_count": 78,
  "sections": [
    {"section_id": "A", "section_name": "KYC", "items": [
      {"field_name": "applicant_aadhaar_number", "value": "XXXX-XXXX-1234",
       "status": "FILLED", "source": "case_extractions.kyc.aadhaar_number", "notes": ""},
      {"field_name": "disbursement_utr", "value": null, "status": "PENDING_API",
       "source": "finpage.disbursement.utr", "notes": "Requires Finpage API (v2)"}
    ]}
  ]
}
```

**Latency:** 20–40 s (bounded by the few AI narrative items). **Sub-job hard-fail:** none — missing source → `status = FILLED, value = null, notes = "Source missing"`.

### 6.3 Sub-job DOC_XREF (doc cross-verification)

**Model:** `none` — pure Python rule engine. Rules in `audit_mismatch_rules.yaml` (§9).

**Input context:** `case_extractions` (CAM, Equifax, Bank, KYC, Checklist, PD Sheet); `cases.loan_amount` + `loan_id`; Phase 1 computed FOIR and bank-6M avg from `decision_result.output_data` (Steps 2 + 8).

**Process:** Load 6–8 rules. For each, resolve `left_value` / `right_value` via dotted-path lookup, apply the declared comparator (`exact`, `tolerance_absolute`, `tolerance_pct`, `fuzzy_name`). Mismatches append a row `{rule_id, left_source, right_source, left_value, right_value, severity, notes}`. Count critical/warning/info separately.

**Output schema** (`audit_steps.output_data` for DOC_XREF):
```json
{
  "mismatch_count": 3, "critical_count": 1, "warning_count": 2, "info_count": 0,
  "rows": [
    {"rule_id": "R1_APPLICANT_NAME",
     "left_source": "case_extractions.auto_cam.applicant.name",
     "right_source": "case_extractions.equifax.customer_info.name",
     "left_value": "RAKESH KUMAR", "right_value": "RAKESH KR",
     "comparator": "fuzzy_name", "matched": false, "severity": "WARNING",
     "notes": "Token overlap 0.80 — likely abbreviation; review."}
  ]
}
```

**Latency:** < 500 ms. **Sub-job hard-fail:** none — missing-input rule is skipped (`status = SKIPPED_MISSING_INPUT`, logged), not counted as mismatch.

### 6.4 Sub-job EXEC_SUMMARY (docx generation)

**Model:** `claude-sonnet-4-7` narrative; `python-docx` assembly.

**Input context:** `LAYER_A_FILL.output_data` (score + section breakdown + deviation log); `LAYER_B_FILL.output_data` (fill counts); `DOC_XREF.output_data` (mismatch log); latest completed `decision_result` (final_decision, recommended_amount, conditions); `cases` row (loan_id, applicant, amount, tenure); template skeleton (§10).

**Process:** Build Sonnet prompt with structured JSON inputs + template skeleton. Sonnet returns JSON `{case_overview_md, layer_a_verdict_md, layer_b_summary_md, top_mismatches_md, top_deviations_md, final_recommendation_md}`. `docx_writer.py` renders each section into the Word template (PFL letterhead, section headings, bullets, 1–2 inline tables for section scores + top mismatches via `python-docx.add_table`). Save to temp path, upload to S3 at `cases/{case_id}/phase2/{loan_id}_audit_summary.docx`.

**Output schema** (`audit_steps.output_data` for EXEC_SUMMARY):
```json
{
  "docx_s3_key": "cases/{case_id}/phase2/10006484_audit_summary.docx",
  "docx_size_bytes": 58320,
  "section_word_counts": {"case_overview": 89, "layer_a_verdict": 120, "layer_b_summary": 60, "top_mismatches": 75, "top_deviations": 70, "final_recommendation": 95},
  "total_word_count": 509
}
```

**Latency:** 20–40 s (Sonnet + ~2 s docx assembly). **Sub-job hard-fail:** Sonnet error after 3 retries → step FAILED, but `run_phase2` still marks `audit_result.status = COMPLETED` if LAYER_A/B/XREF succeeded (docx is non-blocking — xlsx outputs sufficient for verdict dispatch). Frontend hides the summary download when FAILED.

---

## 7. 30-Point Rubric — Declarative File Layout

Rubric lives at `/Users/sakshamgupta/Desktop/PFL credit system/backend/app/memory/audit_rubric_30pt.yaml` and is loaded by `app/auditing/rubric.py` on worker startup, validated against a Pydantic schema, then cached in-process.

### 7.1 YAML schema

```yaml
version: "2026-04-21-v1"
total_items: 30
max_score: 100
verdict_buckets: {pass_min: 90, concern_min: 70}
sections:
  - id: "A"
    name: "Credit Assessment & Eligibility"
    max_score: 47
    items:
      - item_id: "A1"
        title: "CIBIL score ≥ 750 (policy ideal)"
        weight: 5
        evaluator: "rule"
        rule:
          expression: "equifax.credit_score >= 750"
          partial_expression: "equifax.credit_score >= 700"
          partial_score_pct: 60                # partial gets 60% of weight
        evidence_locator: "equifax.customer_info.credit_score"
      - item_id: "A7"
        title: "Business premises match declared activity (narrative)"
        weight: 4
        evaluator: "ai"
        model: "claude-haiku-4-7"
        ai_prompt_template: |
          Given the PD Sheet business section and CAM business-type,
          assess whether the premises description matches declared activity.
          Return JSON: {status, score, notes, evidence_citation}.
        v1_textonly_proxy: true                # ideal evaluator is vision; v1 text
      # … items A2–A13 (all rule-type except A7, A8)
  - id: "B"
    name: "QR and Banking Check"
    max_score: 30
    items: [ … 9 items totalling 30 pts ]
  - id: "C"
    name: "Assets & Living Standard"
    max_score: 15
    items: [ … 5 items totalling 15 pts ]
  - id: "D"
    name: "Reference Checks & TVR"
    max_score: 8
    items: [ … 3 items totalling 8 pts ]
```

### 7.2 Item catalogue (all 30 items)

Distribution: **A = 13 items (47 pts) · B = 9 (30) · C = 5 (15) · D = 3 (8) = 30 items / 100 pts**. Eval column: `R` = deterministic rule, `A` = Haiku AI judge.

| Item | Title | Wt | Eval |
|---|---|---|---|
| **A — Credit Assessment & Eligibility (47 pts)** | | | |
| A1 | CIBIL score ≥ 750 (policy ideal) | 5 | R |
| A2 | No DPD last 24 months | 5 | R |
| A3 | No written-off / suit-filed / LSS | 4 | R |
| A4 | Total indebtedness < ₹5L incl. proposed | 4 | R |
| A5 | Applicant age ∈ [21, 60] | 3 | R |
| A6 | Co-applicant age ∈ [21, 65] | 3 | R |
| A7 | Business vintage ≥ 3y same line + location | 4 | A |
| A8 | Residence stability ≥ 3y same premises | 3 | A |
| A9 | Annual household income > ₹3.5L | 3 | R |
| A10 | Annual sales > ₹10L (services > ₹50k) | 3 | R |
| A11 | Not in negative business list | 4 | R |
| A12 | NTC: loan ≤ 50k OR guarantor + owned-house | 3 | R |
| A13 | FOIR ≤ 50% (alert at 40%) | 3 | R |
| **B — QR and Banking Check (30 pts)** | | | |
| B14 | Bank statement ≥ 6 months coverage | 3 | R |
| B15 | ABB ≥ proposed monthly EMI | 4 | R |
| B16 | Zero bounces / NACH returns | 4 | R |
| B17 | Bank credits match declared sales (±15%) | 4 | R |
| B18 | Distinct income sources ≥ 1 | 3 | R |
| B19 | Earning family members ≥ 1 | 2 | R |
| B20 | No suspicious round-number deposits | 3 | A |
| B21 | No unexplained gap > 20 days before disbursement | 3 | R |
| B22 | Bureau report freshness ≤ 30 days | 4 | R |
| **C — Assets & Living Standard (15 pts)** | | | |
| C23 | Residence OR business premises owned | 4 | R |
| C24 | Permanent structure (RCC/stone-slab roof) | 3 | A |
| C25 | Stock value ≥ loan amount | 4 | R |
| C26 | Living-standard narrative consistent w/ income | 2 | A |
| C27 | Electricity bill aligns w/ declared lifestyle | 2 | A |
| **D — Reference Checks & TVR (8 pts)** | | | |
| D28 | PD Sheet interview completeness | 3 | A |
| D29 | No red flags in PD narrative | 3 | A |
| D30 | ≥ 2 reference contacts, ≥ 1 non-relative | 2 | R |

**Evaluator tally:** 20 R + 10 A items → 2 Haiku batch calls.

### 7.3 Why declarative?

- Rule text, weights, thresholds, and evaluator type live in YAML → tuneable without code deploy.
- Saksham can add/remove items and reweight sections in M7's Settings → Rubric tab (not in M6 scope; M6 ships the YAML file only).
- Schema version (`version:` key) is logged in every `audit_result.output_data` for retrospective auditability.

---

## 8. 150-Point Schema — 17 Sections

Schema lives at `/Users/sakshamgupta/Desktop/PFL credit system/backend/app/memory/audit_schema_150pt.yaml`. Every item has `section_id`, `field_name`, `source` (dotted path), `v1_fillable`, and `notes`. Items with `v1_fillable: false` render `Pending API` in the output xlsx.

### 8.1 Section item distribution (totalling 150)

| § | Section | Items | Primary source | v1 fill |
|---|---|---|---|---|
| A | KYC | 10 | `case_extractions.kyc.*`, `case_artifacts` | 8/10 |
| B | Basic Info | 8 | `case_extractions.auto_cam.personal.*` | 7/8 |
| C | Product | 6 | `cases.loan_amount`, `policy.yaml.ticket_grid` | 6/6 |
| D | Financials — Applicant | 12 | `auto_cam.financials.*`, `bank_stmt` | 10/12 |
| E | Financials — Co-applicant | 10 | `auto_cam.coapp.*` | 8/10 |
| F | Vintage | 6 | `pd_sheet.business.vintage`, `cam.vintage` | 5/6 |
| G | Assets | 8 | `auto_cam.assets.*`, `house_visit_photo metadata` | 6/8 |
| H | CIBIL | 14 | `case_extractions.equifax.*` | 14/14 |
| I | Dedupe / Fraud | 8 | `dedupe_matches`, `auto_cam.*` | 6/8 |
| J | QR | 10 | `decision_result.output_data` (Phase 1 Step 11) | 7/10 |
| K | TVR | 6 | Finpage (v2) | 0/6 |
| L | Credit Assessment | 12 | `decision_result.output_data`, `LAYER_A_FILL` | 10/12 |
| M | Documents | 10 | `case_artifacts`, `checklist_validation_result` | 10/10 |
| N | Ops (Disbursement) | 12 | Finpage (v2) | 0/12 |
| O | Accounts (Post-Disb) | 8 | Finpage (v2) | 0/8 |
| P | Role Comments | 6 | `case_feedback` + manual notes | 3/6 |
| Q | Site Visit | 4 | `pd_sheet.site_visit`, `house_visit_photo` | 3/4 |
| **Total** | | **150** | | **≈ 103/150** |

v1 realistic fill: **95–105** items without Finpage. Parent spec's ~60–80 floor is conservative; > 80 is a win. Sections K/N/O are fully Finpage-dependent (0/26 v1).

### 8.2 Representative items per section

Example entries for the three largest sections:

**Section H — CIBIL (14/14 filled in v1):** H1–H14 sourced from `case_extractions.equifax.*` — applicant + coapp cibil score, open loan count, outstanding sum, dpd-24m count + max bucket, written-off / suit-filed / LSS counts, unsecured + secured exposure counts, 12-month enquiry count, report date, freshness days.

**Section M — Documents (10/10 filled):** M1–M10 each a boolean presence flag driven by `checklist_validation_result.items[*]` — Aadhaar, PAN, Voter/DL, bank statement 6M, KYC video, residence photo, business photo, electricity bill, Equifax report, PD Sheet.

**Section N — Ops (0/12 in v1, all `Pending API`):** N1–N12 all require Finpage — disbursement UTR, disbursement date, NACH reg ref, e-sign timestamp, ₹1 test date, LAGR/DPN/KFS e-sign status, disbursement mode, PF deducted, net disbursed.

---

## 9. Doc Cross-Verification Rules

Rules live at `/Users/sakshamgupta/Desktop/PFL credit system/backend/app/memory/audit_mismatch_rules.yaml`. Loaded by `app/auditing/mismatch_rules.py` on worker startup.

### 9.1 YAML schema + rule catalogue

```yaml
version: "2026-04-21-v1"
rules:
  - rule_id: "R1_APPLICANT_NAME"
    left:  "case_extractions.auto_cam.applicant.name"
    right: "case_extractions.equifax.customer_info.name"
    comparator: "fuzzy_name"
    fuzzy_threshold: 0.90
    severity_on_mismatch: "WARNING"
    notes_template: "CAM name '{left}' vs Equifax name '{right}'"
```

All 8 rules:

| # | rule_id | left | right | comparator | tolerance | severity |
|---|---|---|---|---|---|---|
| 1 | R1_APPLICANT_NAME | `cam.applicant.name` | `equifax.customer_info.name` | fuzzy_name | 0.90 | WARNING |
| 2 | R2_CIBIL_SCORE_EXACT | `cam.bureau.cibil_score` | `equifax.customer_info.credit_score` | exact | — | CRITICAL |
| 3 | R3_FOIR_TOLERANCE | `cam.eligibility.foir_pct` | `computed.foir_pct` | tolerance_absolute | ±5 pp | WARNING |
| 4 | R4_INCOME_BANK_TOLERANCE | `cam.financials.total_monthly_income_inr` | `computed.bank_6m_avg_credits_per_month` | tolerance_pct | ±15% | CRITICAL |
| 5 | R5_LOAN_AMOUNT_EXACT | `cam.product.loan_amount_inr` | `cases.loan_amount` | exact | — | CRITICAL |
| 6 | R6_APPLICANT_DOB_EXACT | `kyc.aadhaar.dob` | `cam.applicant.dob` | exact | — | CRITICAL |
| 7 | R7_ADDRESS_PINCODE | `kyc.aadhaar.address.pincode` | `equifax.customer_info.address.pincode` | exact | — | WARNING |
| 8 | R8_TENURE_FROM_GRID | `cam.product.tenure_months` | `policy.ticket_grid[@amount].tenure` | exact | — | INFO |

### 9.2 Comparators

- `exact` → `str(left).strip().lower() == str(right).strip().lower()` (None → "")
- `tolerance_absolute` → `abs(float(left) - float(right)) <= tolerance`
- `tolerance_pct` → `abs(left-right) / max(abs(left),abs(right)) <= tolerance_pct/100` (denom = 1 if both 0)
- `fuzzy_name` → `rapidfuzz.fuzz.token_set_ratio(left, right) / 100 >= fuzzy_threshold`

### 9.3 Mismatch log xlsx columns

`{loan_id}_mismatch_log.xlsx` → single sheet `Mismatches` with frozen header row. Columns: A S.No. · B Rule ID · C Left Source · D Right Source · E Left Value · F Right Value · G Comparator · H Matched? · I Severity · J Notes. Rows with `Matched=No` get row-fill by severity: `#FFE5E5` CRITICAL, `#FFF4D6` WARNING, `#EAF4FF` INFO (matches UI colour map).

### 9.4 Missing-input handling

If either `left` or `right` lookup returns `None`, the rule is **skipped** (not counted as a mismatch) and logged to `audit_log` with action `audit.mismatch_rule_skipped`, `after_json: {rule_id, missing_side}`.

---

## 10. Exec Summary Word Template

Template skeleton assembled by `app/auditing/outputs/docx_writer.py`. Target: **1–2 pages**, single-column, PFL letterhead. Generated by Sonnet as structured markdown per-section, then rendered via `python-docx`.

### 10.1 Section structure

1. **Header** — PFL logo (PNG embedded), "Credit Audit Summary", Loan ID, Applicant, Date, Audit Run ID.
2. **Case Overview** — 3–4 sentences: applicant, loan amount, tenure, business type, CIBIL snapshot. Model-generated.
3. **Layer A Verdict + Section Breakdown** — single sentence (verdict + overall score) followed by a 4-row table with columns: Section (A/B/C/D), Max, Scored, % (e.g., `A — Credit Assessment & Eligibility · 47 · 41 · 87%`).
4. **Layer B Partial Fill Summary** — 2 sentences: "X of 150 items filled. Y items marked Pending API. Notable filled sections: …"
5. **Top Mismatches** — max 5 bullet rows: `[Rule ID] left vs right — severity`, from DOC_XREF sorted CRITICAL → WARNING → INFO.
6. **Top Deviations** — max 5 bullet rows from LAYER_A deviation_log, sorted by impact.
7. **Final Recommendation** — 3–5 sentences, model-generated. Must cite Layer A verdict, top-2 mismatches (or "None found"), top-1 deviation.
8. **Footer** — "Generated by PFL Credit AI · Audit Run {audit_result_id} · {ISO timestamp}".

### 10.2 Sonnet prompt structure

```jinja
SYSTEM: You are PFL Credit's audit summary writer. Concise, evidence-cited
prose for a CEO-facing 1-page brief. Never invent; if input is null, say so.

USER: Loan {{loan_id}} | {{applicant_name}} | ₹{{amount}}.
LAYER A: verdict={{verdict}} score={{score}}/100
         section_scores={{section_scores|json}} deviations={{deviation_log|json}}
LAYER B: fill_count={{fill_count}}/150 zero_fill_sections={{zero_fill|json}}
MISMATCHES: {{mismatches|json}}
PHASE 1: {{phase_1_decision}} @ conf={{phase_1_confidence}}

Return JSON: {case_overview_md, layer_a_verdict_md, layer_b_summary_md,
top_mismatches_md, top_deviations_md, final_recommendation_md}. Each field is
markdown (1–5 sentences). Total word count < 600.
```

### 10.3 Cache control

Template skeleton + system prompt (~600 tok) cached via `cache_control: {"type": "ephemeral"}` across runs. Per-run incremental cost: ~500 input + ~600 output tokens on Sonnet ≈ **$0.009 / case**.

---

## 11. Model Cascade + Prompt Caching

### 11.1 Model assignment summary

| Sub-job / item | Model | Rationale |
|---|---|---|
| LAYER_A_FILL rule items (×20) | Python only | Deterministic |
| LAYER_A_FILL AI items (×10) | claude-haiku-4-7 | Bounded narrative; batch 5/call |
| LAYER_B_FILL filled items (~95) | Python only | Dotted-path lookup |
| LAYER_B_FILL AI items (~8) | claude-haiku-4-7 | Narrative micro-judgment |
| DOC_XREF | Python only | Deterministic comparators |
| EXEC_SUMMARY | claude-sonnet-4-7 | Multi-source synthesis + prose |

### 11.2 Prompt caching targets

Cache blocks (`cache_control: {"type": "ephemeral"}`, 5-minute TTL):
1. `audit_rubric_30pt.yaml` block (~2,000 tok) — prepended to all LAYER_A Haiku calls; creation charged once per run.
2. `policy.yaml` block (~1,500 tok) — prepended to LAYER_A + LAYER_B AI calls; reuses M5's cached block (same file, same version).
3. Exec-summary template + system prompt (~600 tok) — prepended to EXEC_SUMMARY Sonnet call. Cache benefits across runs within the 5-min TTL window (batches).

### 11.3 Per-sub-job token caps

| Sub-job | Max input | Max output |
|---|---|---|
| LAYER_A AI batch (5 items) | 12,000 | 2,048 |
| LAYER_B AI batch (5 items) | 10,000 | 1,024 |
| EXEC_SUMMARY | 16,000 | 4,096 |

Exceeding a cap → `engine.py` truncates lower-priority context (bank-stmt raw text first, then PD paragraphs, then CAM narrative — same prioritisation as M5) and logs `context.truncated`.

### 11.4 Cost budget

Target average **< $0.35/case**; p99 ceiling **< $0.80/case**; hard abort at `total_cost_usd > 1.50` (logs `audit.cost_exceeded`).

Per-sub-job cost breakdown (cache-warm steady state): LAYER_A $0.03–0.08 (2 Haiku batches) · LAYER_B $0.02–0.05 (2 Haiku batches) · DOC_XREF $0 · EXEC_SUMMARY $0.08–0.20 (Sonnet) · **total $0.13–0.33**.

---

## 12. Citations / Evidence Tracking

Every Layer A item output row includes an `evidence` object matching the M5 `Citation` dataclass: `{artifact_id, locator, quoted_text}`. `locator` formats inherit from M5 §8 (xlsx `sheet:{name}:row:{n}:col:{letter}`, docx `para:{n}` / `table:{n}:row:{r}:col:{c}`, html `css:{selector}`, pdf `page:{n}:line:{l}`, metadata `artifact_metadata:{field}`, plus a new `computed:{expression_id}` for LAYER_A computed values like `computed:layer_a.foir_pct`).

**Rule-evaluator citations** are populated automatically from the item's `evidence_locator` YAML field combined with the resolved source artifact ID — the framework guarantees a citation on every rule item.

**AI-evaluator citations** are emitted by Haiku (prompted to include `evidence_citation`); the parser verifies `artifact_id` exists in the case's `CaseArtifact` rows. Missing/invalid citation → item marked PARTIAL, score reduced 30%, `warnings.citation_missing` flag set.

**Mismatch log rows** use the `left` / `right` source paths as evidence pointers (no artifact_id required since comparisons are at extraction-field level).

---

## 13. Shadow Mode + Feature Flags

Three config flags in `backend/app/config.py`:

```python
auditing_enabled: bool = False           # master on/off; False → POST /phase2 returns 503
auditing_shadow_only: bool = True        # run fully but hide verdict in UI
auditing_subjob_flags: dict[str, bool] = {
    "layer_a_fill": True, "layer_b_fill": True, "doc_xref": True, "exec_summary": True,
}
```

**Shadow mode:** with `auditing_shadow_only=True`, engine runs fully (DB + S3 writes persist) but verdict badge is hidden behind an "Audit Running in Shadow Mode" banner; download buttons visible to Admin only. No email notifications (v1 has none). After 50 shadow audits reviewed, Saksham flips to `false`.

**Per-sub-job flags:** e.g. `auditing_subjob_flags["exec_summary"]=False` causes `engine.py` to skip EXEC_SUMMARY; row stamped SKIPPED, `output_s3_keys.summary` omitted. Verdict still set from LAYER_A_FILL score.

---

## 14. Audit Actions

Audit actions recorded to `audit_log` with `entity_type = "audit_result" | "audit_step"` and the relevant entity ID.

| Action | When / after_json |
|---|---|
| `audit.started` | Worker picks up job |
| `audit.completed` | All sub-jobs finalized; `{verdict, layer_a_score, mismatch_count, total_cost_usd}` |
| `audit.failed` | Unrecoverable error; `{error_message, last_completed_subjob}` |
| `audit.cancelled` | Admin cancels |
| `audit.subjob_started` / `audit.subjob_completed` / `audit.subjob_failed` / `audit.subjob_skipped` | Per sub-job lifecycle; `{step_name, status, cost_usd}` |
| `audit.mismatch_rule_skipped` | DOC_XREF rule skipped; `{rule_id, missing_side}` |
| `audit.verdict_set` | Verdict bucket derived; `{verdict, score, bucket_boundary_distance}` |
| `audit.cost_exceeded` | `total_cost_usd > 1.50` safety abort |
| `audit.output_uploaded` | Each xlsx/docx uploaded; `{output_key, s3_key, bytes}` |

Actor for all worker-originated events: `SYSTEM_WORKER_USER_ID` (same seed user as M3's `worker@system.pflfinance.internal`).

---

## 15. Worker Integration + Docker Compose

### 15.1 Separate worker container (Option B, same as M5)

**Decision: new `pfl-audit-worker` container.** Rationale mirrors M5 §12 Option B — different scaling profile (audit is LLM-I/O-bound), fault isolation from ingestion/decisioning, clean Anthropic credential separation, independent scale-out.

Concurrency: 1 message per worker instance. LAYER_A/B/XREF run in parallel inside the job via `asyncio.gather`, so a single worker processes a case in < 2 minutes wall-clock. Horizontal scale via ECS desired-count.

### 15.2 Worker process

`backend/app/auditing/__main__.py` mirrors `backend/app/worker_decisioning/__main__.py`. Job payload: `{"case_id": "uuid", "audit_result_id": "uuid", "actor_user_id": "uuid"}`. On pickup: set `audit_result.status = RUNNING`, record `started_at`, call `run_phase2(session, audit_result_id, actor_user_id=...)`, commit. Queue construction uses `QueueService(queue_name=settings.sqs_audit_queue, dlq_name=settings.sqs_audit_dlq, ...)` — same parameters pattern as M5's decisioning worker.

### 15.3 docker-compose service

```yaml
  audit-worker:
    build: ./backend
    container_name: pfl-audit-worker
    environment:
      # reuses DATABASE_URL, AWS_*, ANTHROPIC_API_KEY from .env
      - SQS_AUDIT_QUEUE=${SQS_AUDIT_QUEUE}
      - SQS_AUDIT_DLQ=${SQS_AUDIT_DLQ}
      - AUDITING_ENABLED=${AUDITING_ENABLED}
      - AUDITING_SHADOW_ONLY=${AUDITING_SHADOW_ONLY}
    depends_on:
      postgres: { condition: service_healthy }
      localstack: { condition: service_healthy }
    command: python -m app.auditing
```

### 15.4 New configuration

Append to `backend/app/config.py`: `auditing_enabled: bool = False`, `auditing_shadow_only: bool = True`, `auditing_subjob_flags: dict = {}`, `auditing_cost_abort_usd: float = 1.50`, `sqs_audit_queue: str = "pfl-audit-jobs"`, `sqs_audit_dlq: str = "pfl-audit-dlq"`, `audit_output_s3_prefix: str = "cases/{case_id}/phase2"`. New env vars in `.env.example`: `AUDITING_ENABLED`, `AUDITING_SHADOW_ONLY`, `SQS_AUDIT_QUEUE`, `SQS_AUDIT_DLQ`.

---

## 16. Error Handling + Retries

### 16.1 Anthropic API errors

Same pattern as M5 §13.1: `RateLimitError` / `OverloadedError` / `APIStatusError` 5xx → exponential backoff (5 s / 20 s / 60 s), 3 attempts; on 3rd failure step → FAILED. `AuthenticationError` → immediate fail, no retry.

### 16.2 Sub-job-level idempotency

Each sub-job upserts on `(audit_result_id, step_name)`. On SQS redeliver, `engine.py` at startup loads existing `audit_steps` rows: SUCCEEDED → skip; RUNNING (crash-orphan) → re-run; FAILED with retry-budget → re-run; `audit_result.status = COMPLETED` → log `audit.already_completed` and ack the message.

### 16.3 Partial success

The orchestrator **does not fail the whole run** if one sub-job fails, as long as LAYER_A_FILL succeeded (it's the only source of the verdict and score):

| LAYER_A | LAYER_B | DOC_XREF | EXEC_SUMMARY | `audit_result.status` |
|---|---|---|---|---|
| ✓ | ✓ | ✓ | ✓ | COMPLETED (happy path) |
| ✓ | ✓ | ✓ | ✗ | COMPLETED (docx missing; frontend hides summary) |
| ✓ | ✗ | ✓ | ✓ | COMPLETED (layer_b counts null) |
| ✓ | any | ✗ | any | COMPLETED (mismatch_count null) |
| ✗ | any | any | any | FAILED (no verdict possible) |

### 16.4 DLQ

After 3 SQS delivery attempts: message moves to `pfl-audit-dlq`. Admin must inspect and manually re-trigger via `POST /cases/{id}/phase2` after fixing the underlying issue.

---

## 17. Testing Strategy

### 17.1 Unit tests per sub-job

- `tests/auditing/test_layer_a_fill.py` — rubric loader, rule evaluator (all comparators + edge cases), AI evaluator parser (valid + malformed Haiku JSON via `AsyncMock`), section-score aggregation, verdict bucket boundaries.
- `tests/auditing/test_layer_b_fill.py` — schema loader, dotted-path lookup on fixture extractions, `Pending API` stamping, fill-count math.
- `tests/auditing/test_doc_xref.py` — each comparator with boundary + missing-input cases; severity aggregation; notes interpolation.
- `tests/auditing/test_exec_summary.py` — prompt assembly, Sonnet response parsing, docx rendering, S3 upload (LocalStack).

### 17.2 YAML validation tests

- `test_rubric_yaml.py` — assert: total items = 30, total weight = 100, per-section sums = declared `max_score`, every `ai` item has non-empty `ai_prompt_template`.
- `test_schema_yaml.py` — assert: 150 items across 17 sections, every item has a `source` path, `v1_fillable ∈ {true, false, "ai"}`.
- `test_mismatch_rules_yaml.py` — assert: ≥ 6 rules, `comparator` ∈ allowed set, `severity_on_mismatch ∈ {CRITICAL, WARNING, INFO}`.

### 17.3 Pipeline integration test

`test_engine_integration.py` — LocalStack SQS + S3, real Postgres test DB, Seema fixture case (fully ingested + Phase 1 complete via M5 fixture). Run `engine.run_phase2(...)` with Anthropic mocked. Assert: 4 `audit_steps` rows created, `audit_result.status = COMPLETED`, stage → `PHASE_2_COMPLETE`, 4 S3 objects exist, xlsx parses via `openpyxl`, docx opens via `python-docx`, audit log entries correct.

### 17.4 Output format tests

- `test_xlsx_30pt.py` — sheet structure matches PFL template (A/B/C/D sections, scoring column, deviation log block).
- `test_xlsx_mismatch.py` — colour fills match severity map; row counts correct.
- `test_docx_summary.py` — section headings present, table row counts correct, total word count < 700.

### 17.5 E2E test

`test_e2e.py` (skipped without `ANTHROPIC_API_KEY`) — runs full Phase 2 on Seema fixture against real Anthropic. Assert: verdict ∈ `{PASS, CONCERN, FAIL}`, `total_cost_usd < 0.80`, all sub-jobs SUCCEEDED (or EXEC_SUMMARY SKIPPED if flag off), docx opens.

### 17.6 Coverage target

≥85% on `app/auditing/`. Same coverage-gate as M5.

---

## 18. Dependencies

New in `backend/requirements.txt`: `python-docx >= 1.1` (exec summary), `rapidfuzz >= 3.9` (fuzzy_name comparator), `simpleeval >= 1.0` (sandboxed rubric-rule expressions — avoids `eval()` on YAML). Re-uses: `anthropic` (M5), `openpyxl` (M3), `jinja2` (M3), `pydantic`.

---

## 19. Configuration (`.env.example` additions)

```dotenv
AUDITING_ENABLED=false
AUDITING_SHADOW_ONLY=true
AUDITING_COST_ABORT_USD=1.50
SQS_AUDIT_QUEUE=pfl-audit-jobs
SQS_AUDIT_DLQ=pfl-audit-dlq
# Reuses from M5: ANTHROPIC_API_KEY, AWS_*, DATABASE_URL
```

---

## 20. Frontend Changes

Reference: M4 frontend shell design, `docs/superpowers/specs/2026-04-18-m4-frontend-design.md`.

### 20.1 New "Phase 2" tab on Case Detail page

Tab order becomes: Overview | Extractions | Phase 1 | **Phase 2** | Feedback.

Contents (top-down):

1. **Verdict banner** — pill: green `PASS`, amber `CONCERN`, red `FAIL` (or grey `RUNNING` / `PENDING` / `SHADOW`). Shows `layer_a_score / 100` prominently.
2. **Run controls** — "Run Phase 2" button (disabled unless Phase 1 complete and no run in flight); "Cancel" button (Admin only, visible during RUNNING).
3. **Section score breakdown table** — 4 rows (A/B/C/D): Section, Max, Scored, %, progress bar.
4. **Layer A item detail accordion** — expandable section list with items (Status chip, Score, Evidence popover, Notes).
5. **Deviation & Error Log table** — up to 10 rows from LAYER_A_FILL.
6. **Mismatch Log table** — DOC_XREF rows; colour-coded severity.
7. **Layer B Partial Fill summary** — donut chart of `fill_count / 150`; 17-section list showing per-section fill ratio.
8. **Downloads panel** — 4 buttons (one per output file); each fetches `/phase2/outputs/{key}` and follows the presigned URL. Disabled for SKIPPED/FAILED sub-jobs.
9. **Steps sidebar** — 4 sub-jobs with status chips + cost per sub-job.

### 20.2 Case list + polling + Next.js routes

- Case list gains a sortable **"Audit"** column showing latest `AuditVerdict` pill.
- Tab polls `GET /cases/{id}/phase2` every 5 s while `status == RUNNING`; stops on COMPLETED/FAILED (aligns with M4 patterns).
- New route handlers under `apps/web/app/api/cases/[id]/phase2/`: `route.ts` (POST + GET), `steps/route.ts`, `outputs/[key]/route.ts`, `cancel/route.ts`. All proxy to the FastAPI backend.

---

## 21. Definition of Done

- [ ] `pfl-audit-worker` container builds and boots cleanly against LocalStack
- [ ] `audit_results`, `audit_steps` tables + constraints + indexes created by migration
- [ ] `POST /cases/{id}/phase2` enqueues job and transitions stage in one transaction
- [ ] All 3 YAMLs validate: rubric (30 items, weights sum to 100, per-section sums match), schema (17 sections, 150 items, every item has source path), mismatch rules (≥ 6, comparators + severities in allowed sets)
- [ ] All 4 sub-jobs run E2E on Seema fixture (Anthropic mocked) with correct `audit_steps` rows
- [ ] `LAYER_A_FILL` produces `layer_a_score ∈ [0, 100]` and matching verdict bucket
- [ ] `DOC_XREF` emits ≥ 1 mismatch row on a deliberately-corrupted fixture
- [ ] 4 S3 outputs at declared keys after a successful run; all 4 files open cleanly in `openpyxl` / `python-docx`
- [ ] `GET /cases/{id}/phase2/outputs/{key}` returns presigned URL with 15-min TTL
- [ ] Shadow mode: with `auditing_shadow_only=True`, verdict hidden in API response; DB + S3 writes persist
- [ ] Frontend "Phase 2" tab renders verdict + all tables + downloads; disabled states correct for RUNNING / SKIPPED / FAILED
- [ ] ≥85% coverage on `app/auditing/`; ruff + mypy clean; tag `m6-audit-engine` on merge commit
- [ ] Target cost: average `total_cost_usd` across 5 E2E runs ≤ $0.35

---

## 22. Open Questions / Deferred

1. **Layer A vs Layer B overlap** — items like CIBIL score appear in both. v1 treats them as independent; shared-field canonicalization in M7 if inconsistencies surface.
2. **Deviation Log max-10 cap** — if > 10 deviations we truncate with "10 of N" footer; severity-prioritized re-ordering deferred to first-20-case review.
3. **Mismatch → verdict coupling** — v1: Layer A and mismatches are independent (rubric-driven vs data-quality). Override "CRITICAL mismatch forces CONCERN verdict" deferred to M7.
4. **Re-run semantics** — v1 keeps all `audit_result` rows; UI shows latest; full history in audit log. 7-year retention per parent §12.1.
5. **Phase 1 ↔ Phase 2 verdict divergence** — v1: no auto-escalation; UI surfaces both verdicts side-by-side on Overview tab; human decides.
6. **Docx template customisation** — v1 uses hard-coded template in `docx_writer.py`; user-uploadable Jinja `.docx` template in M7.
7. **Bulk audit endpoint** — `POST /cases/phase2/batch` deferred; v1 uses ECS desired-count for parallelism.
8. **Email dispatch on FAIL** — parent spec implies CEO notification; v1 has none; M7 adds `auditing.notify_ceo_on_fail` + SES template.

---

## 23. Cross-Reference to Parent Spec

| Parent § | M6 coverage |
|---|---|
| §6.1 Phase 2 Purpose | §1 |
| §6.2 Layer A 30-point audit | §6.1, §7 |
| §6.3 Layer B 150-point audit | §6.2, §8 |
| §6.4 Audit runs in parallel | §3, §6 (asyncio.gather) |
| §6.5 Phase 2 outputs | §6.4, §9.3, §20 |
| §4.2 Model cascade / §4.3 cost per case | §11.1 / §11.4 |
| §7.1 Memory stores | §11.2 (reads policy.yaml); §22 (rubric editor = M7) |
| §8 Data model (phase_2_outputs) | §4 |
| §9 Workflow stages | §5.6 |
| §12 Security & PII masking | §5.4 (presigned URLs), §20 (verdict hidden in shadow) |
| §13.1 Validation dataset | §17.5 (E2E) |
| §13.2 Shadow mode rollout | §13 |

---

*End of M6 spec. Next: spec review → plan → execute → merge.*
