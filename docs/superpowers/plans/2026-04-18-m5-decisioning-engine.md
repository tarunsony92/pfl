# Milestone 5: Phase 1 Decisioning Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 1 Decisioning Engine — an 11-step LLM pipeline that reads a fully-ingested case kit and produces an APPROVE / APPROVE_WITH_CONDITIONS / REJECT / ESCALATE_TO_CEO recommendation backed by evidence-cited reasoning. Runs as an independent worker container (`pfl-decisioning-worker`) consuming SQS. Model cascade: pure-Python gates → Haiku → Sonnet → Opus synthesis.

**Architecture:** Separate `pfl-decisioning-worker` container (ECS/docker-compose). 11 steps run serially with resume-from-last-successful. Prompt caching on policy + heuristics blocks. Cost tracked per step; hard abort at $2.00/run. pgvector 8-dim numeric feature vector for case library retrieval. Shadow mode suppresses UI/email until approved.

**Tech Stack:** Python 3.12 + existing M3 stack + new deps: `anthropic >= 0.40`, `pgvector >= 0.3`. `jinja2` already present from M3. New SQS queues: `pfl-decisioning-jobs` + `pfl-decisioning-dlq`.

**Builds on:** M3 (tagged `m3-ingestion-workers`), M4 (frontend shell).

**Spec reference:** `docs/superpowers/specs/2026-04-18-m5-decisioning-engine-design.md` — implementers should read the relevant section when prompted.

**Definition of done:** Spec §17. All existing tests still pass; new tests bring coverage ≥ 85% on `app/decisioning/`; ruff + mypy clean; 11-step pipeline runs end-to-end on Seema fixture (Anthropic mocked); tag `m5-decisioning-engine`.

---

## File structure for M5

```
backend/
├── app/
│   ├── enums.py                              # MODIFY — add DecisionStatus, DecisionOutcome, StepStatus, MrpSource
│   ├── config.py                             # MODIFY — add Anthropic + decisioning + pgvector + MRP settings
│   ├── memory/
│   │   ├── policy.yaml                       # NEW — stub hard-rule policy for M5
│   │   └── heuristics.md                     # NEW — stub NPA patterns + soft signals
│   ├── models/
│   │   ├── decision_result.py                # NEW
│   │   ├── decision_step.py                  # NEW
│   │   └── mrp_entry.py                      # NEW
│   ├── schemas/
│   │   └── decisioning.py                    # NEW — DecisionResultRead, DecisionStepRead, MrpEntryRead
│   ├── services/
│   │   └── claude.py                         # NEW — async Claude wrapper (caching, cascade, retry, cost)
│   ├── decisioning/
│   │   ├── __init__.py                       # NEW
│   │   ├── __main__.py                       # NEW — SQS consumer loop
│   │   ├── pipeline.py                       # NEW — run_phase1(decision_result_id); resume logic
│   │   ├── context.py                        # NEW — DecisionContext dataclass (assembled from DB reads)
│   │   ├── citations.py                      # NEW — Citation dataclass + locator helpers
│   │   ├── cost.py                           # NEW — token → cost_usd calculator per model
│   │   ├── memory.py                         # NEW — load_policy(), load_heuristics(), retrieve_similar_cases()
│   │   ├── case_library.py                   # NEW — similarity_search(vector, k) via pgvector
│   │   ├── steps/
│   │   │   ├── __init__.py                   # NEW
│   │   │   ├── step_01_policy_gates.py       # NEW — pure Python hard gates
│   │   │   ├── step_02_banking.py            # NEW — Haiku
│   │   │   ├── step_03_income.py             # NEW — Haiku
│   │   │   ├── step_04_kyc.py                # NEW — Haiku (text-only)
│   │   │   ├── step_05_address.py            # NEW — Sonnet
│   │   │   ├── step_06_business.py           # NEW — Sonnet
│   │   │   ├── step_07_stock.py              # NEW — Opus + MRP lookups + stub flag
│   │   │   ├── step_08_reconciliation.py     # NEW — Sonnet
│   │   │   ├── step_09_pd_sheet.py           # NEW — Sonnet
│   │   │   ├── step_10_retrieval.py          # NEW — pgvector, no LLM
│   │   │   └── step_11_synthesis.py          # NEW — Opus, final judgment
│   │   ├── prompts/                          # NEW — Jinja2 .txt templates (one per LLM step)
│   │   │   ├── step_02_banking.txt
│   │   │   ├── step_03_income.txt
│   │   │   ├── step_04_kyc.txt
│   │   │   ├── step_05_address.txt
│   │   │   ├── step_06_business.txt
│   │   │   ├── step_07_stock.txt
│   │   │   ├── step_08_reconciliation.txt
│   │   │   ├── step_09_pd_sheet.txt
│   │   │   └── step_11_synthesis.txt
│   │   └── parsers/                          # NEW — parse_step_N_output(raw: str) → dict
│   │       ├── __init__.py
│   │       ├── step_02.py
│   │       ├── step_03.py
│   │       ├── step_04.py
│   │       ├── step_05.py
│   │       ├── step_06.py
│   │       ├── step_07.py
│   │       ├── step_08.py
│   │       ├── step_09.py
│   │       └── step_11.py
│   └── api/routers/
│       └── decisioning.py                    # NEW — /cases/{id}/phase1 + steps + cancel
├── alembic/versions/
│   └── <hash>_m5_decisioning_tables.py       # NEW
├── frontend/app/cases/[id]/
│   └── phase1/                               # NEW — Phase 1 tab components
└── tests/
    ├── fixtures/
    │   └── decisioning/                      # NEW — mock LLM response JSON per step
    │       ├── step_02_response.json
    │       ├── step_03_response.json
    │       ├── step_04_response.json
    │       ├── step_05_response.json
    │       ├── step_06_response.json
    │       ├── step_07_response.json
    │       ├── step_08_response.json
    │       ├── step_09_response.json
    │       └── step_11_response.json
    └── decisioning/
        ├── test_step_01.py                   # NEW — all 8 hard-fail conditions
        ├── test_step_02.py through test_step_11.py  # NEW — one module per step
        ├── test_parsers.py                   # NEW — valid + malformed LLM output
        ├── test_pipeline_integration.py      # NEW — full 11-step run, Anthropic mocked
        └── test_e2e.py                       # NEW — skipped unless ANTHROPIC_API_KEY set

docker-compose.yml                            # MODIFY — add decisioning-worker service, new SQS queues
.env.example                                  # MODIFY — add ANTHROPIC_API_KEY + decisioning vars
```

---

## Task 1: Deps + config + worker container

> **Suggested model:** Haiku (mechanical: add deps, edit config + docker-compose)

**Files:** `backend/pyproject.toml`, `backend/app/config.py`, `.env.example`, `docker-compose.yml`

**Reference:** spec §15, §16, §12.2

- [ ] Add runtime deps: `poetry add anthropic pgvector` (non-dev group)
- [ ] Append to `Settings` in `backend/app/config.py`:

```python
    # Anthropic
    anthropic_api_key: str = ""              # required when decisioning_enabled=True
    anthropic_default_timeout_s: int = 120
    anthropic_max_retries: int = 3

    # Decisioning
    decisioning_enabled: bool = False
    decisioning_shadow_only: bool = True
    decisioning_step_flags: dict = {}        # empty = all enabled
    decisioning_cost_abort_usd: float = 2.00

    # Decisioning SQS
    decisioning_queue_url: str = ""          # required when decisioning_enabled=True
    decisioning_dlq_url: str = ""

    # pgvector
    pgvector_feature_dimensions: int = 8
    case_library_retrieval_k: int = 10
    case_library_similarity_threshold: float = 0.70

    # MRP
    mrp_fuzzy_match_threshold: float = 0.70
```

- [ ] `.env.example`: add `ANTHROPIC_API_KEY`, `DECISIONING_QUEUE_URL`, `DECISIONING_DLQ_URL`, `DECISIONING_ENABLED=false`, `DECISIONING_SHADOW_ONLY=true`
- [ ] `docker-compose.yml`:
  - LocalStack env: extend `SERVICES=s3,sqs,ses` → `SERVICES=s3,sqs,ses` (SQS already handles multiple queues; add `pfl-decisioning-jobs` + `pfl-decisioning-dlq` to the LocalStack init script or startup)
  - New service `decisioning-worker`: same build as backend, `command: python -m app.decisioning`, same env + `ANTHROPIC_API_KEY`, depends_on postgres + localstack
- [ ] Verify: `docker compose config >/dev/null && echo OK`; `poetry run pytest -q` → existing tests all pass
- [ ] Commit: `feat(m5): deps (anthropic, pgvector), decisioning config fields, worker container`

---

## Task 2: Enums + stage machine transitions

> **Suggested model:** Sonnet

**Files:** `backend/app/enums.py`, `backend/app/services/stages.py`, `backend/tests/unit/test_enums.py`, `backend/tests/unit/test_stages.py`

**Reference:** spec §4.1, §5.6

- [ ] Append to `backend/app/enums.py`:

```python
class DecisionStatus(StrEnum):
    """Lifecycle state of a decision_result run."""
    PENDING    = "PENDING"
    RUNNING    = "RUNNING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"
    CANCELLED  = "CANCELLED"

class DecisionOutcome(StrEnum):
    """The recommendation produced by Step 11."""
    APPROVE                  = "APPROVE"
    APPROVE_WITH_CONDITIONS  = "APPROVE_WITH_CONDITIONS"
    REJECT                   = "REJECT"
    ESCALATE_TO_CEO          = "ESCALATE_TO_CEO"

class StepStatus(StrEnum):
    PENDING  = "PENDING"
    RUNNING  = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED   = "FAILED"
    SKIPPED  = "SKIPPED"

class MrpSource(StrEnum):
    CASE_PHOTO   = "CASE_PHOTO"
    LLM_ESTIMATE = "LLM_ESTIMATE"
    MANUAL_ENTRY = "MANUAL_ENTRY"
```

- [ ] In `stages.py` `ALLOWED_TRANSITIONS` dict, extend or add entries:

```python
    CaseStage.INGESTED:            {CaseStage.PHASE_1_DECISIONING, ...},  # add PHASE_1_DECISIONING
    CaseStage.PHASE_1_DECISIONING: {CaseStage.PHASE_1_COMPLETE, CaseStage.PHASE_1_REJECTED, CaseStage.INGESTED},
```

- [ ] Append tests to `test_enums.py`:

```python
def test_decision_status_five_values():
    assert len(list(DecisionStatus)) == 5

def test_decision_outcome_four_values():
    assert len(list(DecisionOutcome)) == 4

def test_step_status_five_values():
    assert len(list(StepStatus)) == 5

def test_mrp_source_three_values():
    assert len(list(MrpSource)) == 3
```

- [ ] Append tests to `test_stages.py`:

```python
def test_ingested_to_phase1_decisioning():
    validate_transition(CaseStage.INGESTED, CaseStage.PHASE_1_DECISIONING)

def test_phase1_decisioning_to_complete():
    validate_transition(CaseStage.PHASE_1_DECISIONING, CaseStage.PHASE_1_COMPLETE)

def test_phase1_decisioning_to_rejected():
    validate_transition(CaseStage.PHASE_1_DECISIONING, CaseStage.PHASE_1_REJECTED)

def test_phase1_decisioning_reverts_to_ingested_on_cancel():
    validate_transition(CaseStage.PHASE_1_DECISIONING, CaseStage.INGESTED)
```

- [ ] Run tests: full suite passes + new tests green
- [ ] Commit: `feat(m5): DecisionStatus/Outcome/StepStatus/MrpSource enums; stage transitions for PHASE_1_DECISIONING`

---

## Task 3: Models + migration

> **Suggested model:** Sonnet

**Files:** `backend/app/models/{decision_result,decision_step,mrp_entry}.py`, `backend/app/models/__init__.py`, new Alembic migration

**Reference:** spec §4.2, §4.3, §4.4, §4.5

- [ ] `decision_result.py`: ORM model with all columns from spec §4.2, including `pgvector` `vector(8)` embedding column on the model (for case library). Use `PgEnum(create_type=True)` with `values_callable` for `DecisionStatus` and `DecisionOutcome` columns following M3 pattern exactly.
- [ ] `decision_step.py`: ORM model with all columns from spec §4.3. Add the unique constraint `UniqueConstraint("decision_result_id", "step_number", name="uq_decision_steps_result_step")`.
- [ ] `mrp_entry.py`: ORM model with all columns from spec §4.4. Add `UniqueConstraint("item_normalized_name", name="uq_mrp_entries_name")`.
- [ ] Update `models/__init__.py` to re-export all three new models.
- [ ] Generate migration: `poetry run alembic revision --autogenerate -m "m5 decisioning tables"`
- [ ] Review migration; manually add:
  - `CREATE EXTENSION IF NOT EXISTS vector` (pgvector) at top of `upgrade()`
  - `CREATE INDEX ix_decision_results_case_id_created ON decision_results (case_id, created_at DESC)` — autogenerate may miss composite index ordering
  - Verify `uq_decision_steps_result_step` unique index is present
  - Verify `uq_mrp_entries_name` unique index is present
- [ ] Apply: `poetry run alembic upgrade head`; verify with `\d decision_results` (should show vector column + index)
- [ ] Verify all tests pass
- [ ] Commit: `feat(m5): decision_results, decision_steps, mrp_entries models + migration with pgvector`

---

## Task 4: Claude API wrapper service

> **Suggested model:** Opus (architectural subtlety around caching + cost + retry)

**Files:** `backend/app/services/claude.py`, `backend/tests/unit/test_claude_service.py`

**Reference:** spec §7.1, §7.2, §7.3, §7.4, §13.1

- [ ] `ClaudeService` class with async `complete(model, messages, max_tokens, cache_blocks)` method:
  - Accepts `cache_blocks: list[str]` — each entry becomes a `cache_control: {"type": "ephemeral"}` content block prepended to the request
  - Maps model names via constants: `HAIKU = "claude-haiku-4-5"`, `SONNET = "claude-sonnet-4-6"`, `OPUS = "claude-opus-4-7"`
  - Returns `ClaudeResponse(content: str, input_tokens: int, output_tokens: int, cache_read_tokens: int, cache_creation_tokens: int, cost_usd: float)`
- [ ] Retry logic: `RateLimitError` / `APIStatusError(5xx)` → exponential backoff with delays `[5, 20, 60]` seconds; 3 attempts total. `AuthenticationError` → immediate raise (no retry). After 3rd failure: re-raise the last exception.
- [ ] `calculate_cost(model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) -> float`: hardcoded pricing per model per spec §7.4 cost table. Haiku cheapest, Opus most expensive.
- [ ] `count_tokens(model, text) -> int`: rough token estimate (character-count / 4 fallback if SDK doesn't expose tokenizer directly).
- [ ] Module-level singleton `get_claude_service() -> ClaudeService` following storage/queue pattern; `reset_claude_service()` for tests.
- [ ] Unit tests: mock `anthropic.AsyncAnthropic`; verify retry fires on rate-limit; verify cost calculation for each model tier; verify cache block injection produces correct message structure.
- [ ] Commit: `feat(m5): Claude API wrapper with prompt caching, model cascade, retry/backoff, cost tracking`

---

## Task 5: Memory files + policy/heuristics loader

> **Suggested model:** Haiku (file creation + simple loader)

**Files:** `backend/app/memory/policy.yaml`, `backend/app/memory/heuristics.md`, `backend/app/decisioning/memory.py`, `backend/tests/unit/test_memory_loader.py`

**Reference:** spec §9.1, §9.2

- [ ] `backend/app/memory/policy.yaml` — stub with the hard-rule thresholds referenced in Step 1:

```yaml
# PFL Finance — Phase 1 Credit Policy (M5 stub, static)
# Managed by: Credit Head. Edit via M7 heuristic distillation.
version: "1.0"

hard_rules:
  cibil_min: 700
  coapplicant_cibil_min: 700
  max_total_indebtedness_inr: 500000
  applicant_age_min: 21
  applicant_age_max: 60
  coapplicant_age_min: 21
  coapplicant_age_max: 65
  max_business_distance_km: 25
  foir_cap_pct: 50
  idir_cap_pct: 50
  bank_declared_variance_pct_max: 15
  stock_to_loan_ratio_min: 1.0
  address_match_min: 4
  bounce_count_escalate: 3

loan_grid:
  min_inr: 50000
  max_inr: 300000
  ticket_sizes_inr: [50000, 75000, 100000, 150000, 200000, 300000]
  tenures_months: [12, 18, 24, 36]
```

- [ ] `backend/app/memory/heuristics.md` — stub markdown with `## Hard Rules` and `## NPA Patterns` sections; 5–10 placeholder rules drawn from spec §9.2 description.
- [ ] `backend/app/decisioning/memory.py`:
  - `load_policy() -> dict`: reads + parses `policy.yaml` via PyYAML; validates required keys with Pydantic model; caches in module-level dict; re-loads if TTL expired (configurable, default 300s).
  - `load_heuristics() -> str`: reads `heuristics.md`; caches in-process; returns raw markdown string.
  - `retrieve_similar_cases(session, feature_vector: list[float], k: int) -> list[dict]`: wraps `case_library.similarity_search`; returns empty list if pgvector not available or no qualifying rows.
  - `lookup_mrp(session, item_name: str) -> dict | None`: exact match then trigram fuzzy match on `mrp_entries.item_normalized_name`.
  - `upsert_mrp(session, item_name, category, unit_price_inr, source, case_id=None)`: insert or update MRP entry.
- [ ] Unit tests: load_policy returns dict with `hard_rules.cibil_min = 700`; load_heuristics returns non-empty string; policy cache TTL expiry triggers re-read.
- [ ] Commit: `feat(m5): policy.yaml + heuristics.md stubs; memory loader with caching`

---

## Task 6: Case library embeddings infrastructure

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/case_library.py`, `backend/tests/unit/test_case_library.py`

**Reference:** spec §9.3

- [ ] `build_feature_vector(case_context: DecisionContext) -> list[float]`: constructs the 8-dim vector `[loan_amount_normalized, cibil_score_normalized, foir_pct, business_type_hash, district_hash, income_inr_normalized, abb_inr_normalized, tenure_months_normalized]`. Normalization ranges hardcoded as constants (loan 0–500k, CIBIL 300–900, etc.). `business_type_hash` and `district_hash` use a small lookup dict → int normalized 0–1.
- [ ] `similarity_search(session: AsyncSession, vector: list[float], k: int = 10, threshold: float = 0.70) -> list[dict]`: executes `SELECT id, case_id, final_decision, confidence_score, reasoning_markdown FROM decision_results WHERE status = 'COMPLETED' AND embedding IS NOT NULL ORDER BY embedding <=> :vec LIMIT :k` via SQLAlchemy text + pgvector cast. Truncates `reasoning_markdown` to first 500 chars. Returns empty list if pgvector extension missing (catch `ProgrammingError`).
- [ ] Unit tests: mock DB session; verify empty list returned when no rows; verify result dict has expected keys; verify graceful degradation on missing pgvector extension.
- [ ] Commit: `feat(m5): case library embeddings — feature vector builder + pgvector similarity search`

---

## Task 7: MRP database seed + CRUD helpers

> **Suggested model:** Haiku (mechanical CRUD + seed data)

**Files:** `backend/app/decisioning/mrp.py`, `backend/tests/unit/test_mrp.py`, optional seed script `backend/app/cli_mrp_seed.py`

**Reference:** spec §9.4

- [ ] `backend/app/decisioning/mrp.py`:
  - `get_mrp(session, item_name: str) -> MrpEntry | None`: normalizes name (lowercase, strip); exact match; if not found, trigram fuzzy match via `SELECT ... WHERE similarity(item_normalized_name, :name) > :threshold ORDER BY similarity(...) DESC LIMIT 1`.
  - `upsert_mrp(session, item_name, category, unit_price_min, unit_price_median, unit_price_max, source, source_case_id=None)`: insert on conflict update price range (recalculate if observation_count increases) + increment `observation_count`.
  - `list_mrp(session, category: str | None = None, limit=100) -> list[MrpEntry]`: simple listing with optional category filter.
- [ ] Seed data — 50 common Kirana/retail items as a Python list of dicts at the top of `mrp.py`. Run via `async def seed_mrp_entries(session)` — idempotent upserts. Items should cover categories: grocery, cosmetics, hardware, stationery, household.
- [ ] Unit tests: upsert new item; upsert existing (observation_count increments, median updated); fuzzy match on normalized name; get returns None for unknown item.
- [ ] Commit: `feat(m5): MRP CRUD helpers + 50-item Kirana seed data`

---

## Task 8: Step 1 — Hard policy gates (pure Python)

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/steps/step_01_policy_gates.py`, `backend/tests/decisioning/test_step_01.py`

**Reference:** spec §6 Step 1

- [ ] `run(context: DecisionContext, policy: dict) -> dict` — returns the Step 1 output JSON:

```json
{
  "passed": true,
  "failures": [{"rule": "cibil_min", "value": 650, "threshold": 700, "severity": "HARD_REJECT"}],
  "warnings": []
}
```

- [ ] Implement all 8 hard-fail conditions as individual checks in order:
  1. CIBIL score applicant < `policy.hard_rules.cibil_min`
  2. Co-applicant CIBIL < `policy.hard_rules.coapplicant_cibil_min`
  3. Written-off / suit-filed / LSS status present in Equifax extraction
  4. Negative business list match (dedupe match type present in context)
  5. Total indebtedness ≥ `policy.hard_rules.max_total_indebtedness_inr` including proposed loan
  6. Applicant age outside `[policy.hard_rules.applicant_age_min, policy.hard_rules.applicant_age_max]`
  7. Co-applicant age outside `[policy.hard_rules.coapplicant_age_min, policy.hard_rules.coapplicant_age_max]`
  8. Required docs checklist incomplete (`checklist_validation.is_complete == False`)
- [ ] If `failures` non-empty and any failure has `severity == "HARD_REJECT"`: return `passed = False`. Negative business match → `severity = "ESCALATE_TO_CEO"`.
- [ ] No LLM call. Expected latency < 200 ms.
- [ ] Tests: cover all 8 individual hard-fail conditions; CIBIL below threshold; CIBIL exactly at threshold (pass); age boundary; checklist incomplete; all-pass happy path; negative business match → ESCALATE_TO_CEO severity.
- [ ] Commit: `feat(m5): Step 1 hard policy gates (pure Python, no LLM)`

---

## Task 9: Steps 2–3 — Banking + income classification (Haiku)

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/steps/step_02_banking.py`, `backend/app/decisioning/steps/step_03_income.py`, `backend/app/decisioning/prompts/step_02_banking.txt`, `backend/app/decisioning/prompts/step_03_income.txt`, `backend/app/decisioning/parsers/step_02.py`, `backend/app/decisioning/parsers/step_03.py`, `backend/tests/fixtures/decisioning/step_02_response.json`, `backend/tests/fixtures/decisioning/step_03_response.json`, `backend/tests/decisioning/test_step_02.py`, `backend/tests/decisioning/test_step_03.py`

**Reference:** spec §6 Steps 2–3, §7.2, §7.3

- [ ] Each step module exposes `async def run(context: DecisionContext, claude: ClaudeService, policy_block: str) -> dict`. The `policy_block` is the pre-loaded policy.yaml text passed as a cache block.
- [ ] **Step 2** prompt template (`step_02_banking.txt`): inject bank statement raw text (truncated to 8,000 tokens); instruct Haiku to compute ABB, bounce count, FOIR feasibility, and any suspicious flags. Return JSON matching spec §6 Step 2 schema.
- [ ] **Step 3** prompt template (`step_03_income.txt`): inject bank transactions + Auto CAM income fields + PD Sheet income section (truncated to 10,000 tokens combined). Instruct Haiku to classify income sources, count earning members, estimate business income share. Return JSON matching spec §6 Step 3 schema.
- [ ] Parsers `step_02.py` / `step_03.py`: `parse(raw: str) -> dict` — JSON extract with fallback warning; validate required keys present; emit `citation_missing` warnings where factual claims lack `artifact_id`.
- [ ] Fixture responses: valid JSON matching each step's output schema.
- [ ] Tests: mock `ClaudeService.complete` returning fixture JSON; assert parser output has all required keys; test parser on malformed input (missing key → graceful warning, no exception).
- [ ] Commit: `feat(m5): Steps 2-3 (banking + income classification) with Haiku prompts + parsers`

---

## Task 10: Step 4 — KYC & demographic match (Haiku)

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/steps/step_04_kyc.py`, `backend/app/decisioning/prompts/step_04_kyc.txt`, `backend/app/decisioning/parsers/step_04.py`, `backend/tests/fixtures/decisioning/step_04_response.json`, `backend/tests/decisioning/test_step_04.py`

**Reference:** spec §6 Step 4

- [ ] `async def run(context: DecisionContext, claude: ClaudeService, policy_block: str) -> dict`
- [ ] Input context: M3 OCR text from Aadhaar, PAN, Voter ID, DL artifacts; Auto CAM personal details (applicant name, DOB, address). Text-only — vision deferred.
- [ ] Prompt instructs Haiku to compare name + DOB across all available text-based KYC sources; flag mismatches.
- [ ] Output JSON per spec §6 Step 4 schema: `{name_consistent, dob_consistent, mismatches, kyc_confidence}`.
- [ ] If M3 produced no OCR text for a KYC artifact: step marks `kyc_confidence = "LOW"` and adds flag rather than failing.
- [ ] Hard-fail: DOB mismatch across 2+ IDs with text coverage → `kyc_confidence = "LOW"` + failure flag.
- [ ] Parser: validates required keys; emits `citation_missing` warning for uncited claims.
- [ ] Tests: name-consistent happy path; DOB mismatch triggers flag; no OCR text → kyc_confidence=LOW without exception; malformed parser input graceful.
- [ ] Commit: `feat(m5): Step 4 KYC demographic match (Haiku, text-only for M5)`

---

## Task 11: Steps 5–6 — Address verification + business premises (Sonnet)

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/steps/step_05_address.py`, `backend/app/decisioning/steps/step_06_business.py`, `backend/app/decisioning/prompts/step_05_address.txt`, `backend/app/decisioning/prompts/step_06_business.txt`, `backend/app/decisioning/parsers/step_05.py`, `backend/app/decisioning/parsers/step_06.py`, `backend/tests/fixtures/decisioning/step_05_response.json`, `backend/tests/fixtures/decisioning/step_06_response.json`, `backend/tests/decisioning/test_step_05.py`, `backend/tests/decisioning/test_step_06.py`

**Reference:** spec §6 Steps 5–6

- [ ] **Step 5** (six-way address verification): prompt injects addresses from (a) Aadhaar, (b) PAN, (c) Equifax/CIBIL, (d) electricity bill, (e) bank statement header, (f) GPS metadata from house-visit photo. Policy: ≥4 of 6 must match. Input capped at 8,000 tokens.
- [ ] Step 5 output schema: `{match_count, sources_matched, sources_mismatched, mismatch_details, verdict}`. Hard-fail: `match_count < 4`.
- [ ] **Step 6** (business premises check): prompt injects PD Sheet business section + Auto CAM premises fields + GPS metadata from `BUSINESS_PREMISES_PHOTO`. M5 uses metadata only — no image content analysis. Input capped at 6,000 tokens.
- [ ] Step 6 output schema: `{business_distance_km, premises_owned, structure_type, verdict, flags}`. Hard-fail: distance > 25 km; structure = THELA/REHDI/TEMPORARY; both residence + business rented.
- [ ] Parsers for both steps: standard JSON extract + citation-missing warnings.
- [ ] Tests: Step 5 — match_count=5 → PASS; match_count=3 → FAIL; missing GPS source skipped gracefully. Step 6 — distance OK → PASS; distance > 25 km → FAIL; THELA structure type → FAIL.
- [ ] Commit: `feat(m5): Steps 5-6 (six-way address + business premises) with Sonnet prompts`

---

## Task 12: Step 7 — Stock quantification (Opus + MRP stub)

> **Suggested model:** Opus (stock estimation is high-value; plan the prompt + output carefully)

**Files:** `backend/app/decisioning/steps/step_07_stock.py`, `backend/app/decisioning/prompts/step_07_stock.txt`, `backend/app/decisioning/parsers/step_07.py`, `backend/tests/fixtures/decisioning/step_07_response.json`, `backend/tests/decisioning/test_step_07.py`

**Reference:** spec §6 Step 7, §9.4

- [ ] `async def run(context: DecisionContext, claude: ClaudeService, policy_block: str, mrp_lookup) -> dict`
- [ ] Pre-LLM step: extract item names mentioned in PD Sheet business section text → call `mrp_lookup(item_name)` for each → build `mrp_results` dict (matched items with price ranges).
- [ ] Prompt injects: PD Sheet business section (stock description, items), Auto CAM business details (annual turnover, type), MRP lookup results. Instructs Opus to estimate stock value item-by-item, use MRP prices where available, estimate for unmatched items. Total capped at 12,000 tokens.
- [ ] Output must include `stub_mode: true` (vision deferred), `total_stock_value_inr`, `items` array with `mrp_source` per item, `stock_to_loan_ratio`, `verdict`.
- [ ] Hard-fail: `stock_to_loan_ratio < 1.0`.
- [ ] After successful run: call `upsert_mrp` for any item with LLM-estimated price (source = `LLM_ESTIMATE`).
- [ ] Tests: happy path stub_mode + ratio ≥ 1.0 → PASS; ratio < 1.0 → FAIL; MRP lookup hit uses mrp_entries price; unmatched item uses LLM estimate and triggers upsert.
- [ ] Commit: `feat(m5): Step 7 stock quantification (Opus) with MRP lookup and stub flag`

---

## Task 13: Steps 8–9 — Reconciliation + PD Sheet analysis (Sonnet)

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/steps/step_08_reconciliation.py`, `backend/app/decisioning/steps/step_09_pd_sheet.py`, `backend/app/decisioning/prompts/step_08_reconciliation.txt`, `backend/app/decisioning/prompts/step_09_pd_sheet.txt`, `backend/app/decisioning/parsers/step_08.py`, `backend/app/decisioning/parsers/step_09.py`, `backend/tests/fixtures/decisioning/step_08_response.json`, `backend/tests/fixtures/decisioning/step_09_response.json`, `backend/tests/decisioning/test_step_08.py`, `backend/tests/decisioning/test_step_09.py`

**Reference:** spec §6 Steps 8–9

- [ ] **Step 8** (income/stock/bank reconciliation): prompt injects Step 2 output (ABB, FOIR), Step 3 output (income classification), Step 7 output (stock value), Auto CAM income fields, Equifax account list. Prior-step outputs come from `context.step_outputs[2]`, etc. Input capped at 8,000 tokens.
- [ ] Step 8 output schema: `{bank_vs_declared_variance_pct, foir_pct, idir_pct, income_stock_aligned, verdict, flags}`. Hard-fail: variance_pct > 15; foir_pct > 50; idir_pct > 50.
- [ ] **Step 9** (PD Sheet deep analysis): prompt injects full PD Sheet extracted content (fields, tables, paragraphs — M3 PDSheetExtractor output). Input capped at 10,000 tokens.
- [ ] Step 9 output schema: `{consistency_with_cam, red_flags, notable_observations, interview_quality}`. No hard-fail; advisory only; feeds Step 11.
- [ ] Tests: Step 8 — variance 8% → PASS; variance 20% → FAIL; FOIR 55% → FAIL. Step 9 — consistent PD → advisory pass; multiple red flags in output without exception.
- [ ] Commit: `feat(m5): Steps 8-9 (reconciliation + PD Sheet analysis) with Sonnet prompts`

---

## Task 14: Step 10 — Case library retrieval (pgvector)

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/steps/step_10_retrieval.py`, `backend/tests/decisioning/test_step_10.py`

**Reference:** spec §6 Step 10, §9.3

- [ ] `async def run(context: DecisionContext, session: AsyncSession) -> dict`
- [ ] Build feature vector from context using `case_library.build_feature_vector(context)`.
- [ ] Call `case_library.similarity_search(session, vector, k=settings.case_library_retrieval_k, threshold=settings.case_library_similarity_threshold)`.
- [ ] If empty result (library empty or below threshold): set `library_empty = True`, return with `retrieved_count = 0`; step `status = SKIPPED`.
- [ ] Output schema per spec §6 Step 10: `{retrieved_count, cases: [{case_id, similarity, final_decision, key_factors}], library_empty}`.
- [ ] No LLM call. Expected latency < 500 ms.
- [ ] Tests: mock pgvector query returning 3 rows → `retrieved_count=3`; mock empty query → `library_empty=True`; verify step is marked SKIPPED when empty.
- [ ] Commit: `feat(m5): Step 10 case library retrieval via pgvector (graceful skip when empty)`

---

## Task 15: Step 11 — Judgment synthesis (Opus)

> **Suggested model:** Opus (final judgment; most critical step)

**Files:** `backend/app/decisioning/steps/step_11_synthesis.py`, `backend/app/decisioning/prompts/step_11_synthesis.txt`, `backend/app/decisioning/parsers/step_11.py`, `backend/tests/fixtures/decisioning/step_11_response.json`, `backend/tests/decisioning/test_step_11.py`

**Reference:** spec §6 Step 11, §7.2, §8

- [ ] `async def run(context: DecisionContext, claude: ClaudeService, policy_block: str, heuristics_block: str) -> dict`
- [ ] Prompt assembles all prior step outputs (1–10) + policy.yaml (cache block) + heuristics.md (cache block) + case library results (if any). Both policy + heuristics injected as `cache_control: {"type": "ephemeral"}` blocks. Input capped at 32,000 tokens (per spec §7.3 token cap table).
- [ ] If any prior step has `FAILED` or mandatory hard-fail: instruct Opus to note the constraint; still synthesize a recommendation.
- [ ] Output schema per spec §6 Step 11. Key logic: if any deviation present OR confidence < 60 → `final_decision = ESCALATE_TO_CEO`.
- [ ] Parser `step_11.py`: full validation of all required fields; citation presence check for `reasoning_markdown`; emit `citation_missing` warnings per uncited factual claim.
- [ ] After step completes: write `decision_result.embedding = build_feature_vector(context)` for future case library use.
- [ ] Tests: happy path → APPROVE with confidence ≥ 60; deviation present → ESCALATE_TO_CEO; confidence < 60 → ESCALATE_TO_CEO; malformed parser output → graceful warnings, no exception.
- [ ] Commit: `feat(m5): Step 11 judgment synthesis (Opus) with dual cache blocks + citation validation`

---

## Task 16: Pipeline orchestrator

> **Suggested model:** Opus (transactional correctness; resume-from-last logic)

**Files:** `backend/app/decisioning/pipeline.py`, `backend/app/decisioning/context.py`, `backend/app/decisioning/citations.py`, `backend/app/decisioning/cost.py`, `backend/tests/decisioning/test_pipeline_integration.py`

**Reference:** spec §13.2, §13.3, §11

- [ ] `context.py`: `DecisionContext` dataclass — assembled from DB reads at pipeline startup. Includes: case ORM, all `CaseArtifact` rows, extraction JSONB outputs keyed by extractor name, checklist validation result, dedupe matches, step_outputs dict (populated as steps complete), loan amount + tenor from Auto CAM, feature vector (computed after steps 2–3).
- [ ] `citations.py`: `Citation(artifact_id: UUID, locator: str, quoted_text: str)` dataclass. `validate_citations(citations: list[dict], valid_artifact_ids: set[UUID]) -> list[str]`: returns list of warning strings for any cited `artifact_id` not in the case's artifacts.
- [ ] `cost.py`: `CostTracker` class accumulating `total_cost_usd` across steps; `check_abort(limit: float)` raises `CostAbortError` if exceeded; `add_step(model, input_tokens, output_tokens, cache_read, cache_creation)`.
- [ ] `pipeline.py::run_phase1(case_id: UUID, decision_result_id: UUID, session: AsyncSession)`:
  1. Load `DecisionResult`; if already `COMPLETED`, log + return (idempotent).
  2. If `RUNNING`: find last `COMPLETE` step; resume from `step_number + 1`.
  3. Else start from Step 1.
  4. At start of each step: check `decision_result.status == CANCELLED` → exit cleanly.
  5. Check per-step feature flag `settings.decisioning_step_flags.get(f"step_{n:02d}", True)` → write SKIPPED row if disabled.
  6. Run step; on success: upsert `DecisionStep` with status=COMPLETE + output_data + citations + cost.
  7. After each upsert: check `CostTracker.check_abort(settings.decisioning_cost_abort_usd)` → log `decision.cost_exceeded` audit entry if triggered.
  8. Emit audit log actions per spec §11 at each lifecycle event.
  9. On Step 1 hard-fail: skip steps 2–10; run Step 11 with short-circuit flag OR write final_decision=REJECT directly; transition case stage to `PHASE_1_REJECTED`.
  10. On all steps complete: update `decision_result.status=COMPLETED`, `completed_at`, aggregate token usage + total_cost_usd, write `decision_result.embedding`; transition stage to `PHASE_1_COMPLETE`.
  11. On unrecoverable error: set status=FAILED, error_message; revert case stage to `INGESTED`.
- [ ] Integration test: real Postgres test DB; all Anthropic calls mocked via `AsyncMock`; run `run_phase1` on fixture case; assert all 11 `decision_steps` rows created with status=COMPLETE; `decision_result.status=COMPLETED`; case stage = `PHASE_1_COMPLETE`; audit entries present for all lifecycle events.
- [ ] Commit: `feat(m5): pipeline orchestrator with resume-from-step, cost abort, cancellation, audit`

---

## Task 17: Decisioning worker main entrypoint

> **Suggested model:** Sonnet

**Files:** `backend/app/decisioning/__init__.py`, `backend/app/decisioning/__main__.py`

**Reference:** spec §12.1

- [ ] `__init__.py`: empty package marker.
- [ ] `__main__.py`:

```python
import asyncio
import logging
from app.config import get_settings
from app.db import AsyncSessionLocal
from app.decisioning.pipeline import run_phase1
from app.worker.system_user import get_or_create_worker_user

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)


async def process_decisioning_job(payload: dict) -> None:
    case_id = payload["case_id"]
    decision_result_id = payload["decision_result_id"]
    async with AsyncSessionLocal() as session:
        await run_phase1(case_id, decision_result_id, session)
        await session.commit()


async def main():
    _log.info("PFL decisioning worker starting")
    async with AsyncSessionLocal() as session:
        user = await get_or_create_worker_user(session)
        await session.commit()
    _log.info("System worker user: %s", user.id)

    settings = get_settings()
    if not settings.decisioning_enabled:
        _log.warning("decisioning_enabled=False — worker idle (shadow mode)")

    from app.services.queue import get_queue
    # Use a separate queue client pointed at decisioning_queue_url
    while True:
        try:
            # consume from pfl-decisioning-jobs
            pass  # implement queue.consume_jobs(handler=process_decisioning_job, ...)
        except Exception:
            _log.exception("Decisioning worker loop iteration failed")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] Fill in the `consume_jobs` call using the same `QueueService` pattern as M3 but pointed at `settings.decisioning_queue_url`. Reuse `get_queue` if it accepts a URL parameter; otherwise create a `DecisioningQueueService` subclass.
- [ ] Verify container boots: `docker compose run --rm decisioning-worker python -m app.decisioning --help` (should start without error; exit on no messages).
- [ ] Commit: `feat(m5): decisioning worker __main__ entrypoint consuming pfl-decisioning-jobs`

---

## Task 18: API endpoints

> **Suggested model:** Sonnet

**Files:** `backend/app/api/routers/decisioning.py`, `backend/app/schemas/decisioning.py`, `backend/app/main.py` (wire), `backend/tests/integration/test_decisioning_router.py`

**Reference:** spec §5.1–§5.5

- [ ] `schemas/decisioning.py`: Pydantic schemas with `from_attributes=True`:
  - `DecisionResultRead`: all columns from spec §4.2 table; hide recommendation fields when `settings.decisioning_shadow_only=True` (use `@computed_field` or a custom serializer).
  - `DecisionStepRead`: all columns from spec §4.3; include `output_data` and `citations`.
  - `TriggerPhase1Response`: `{decision_result_id: UUID, status: DecisionStatus}`.
- [ ] `routers/decisioning.py` — 5 endpoints:
  - `POST /cases/{case_id}/phase1`: pre-condition checks from spec §5.1 (case exists, stage==INGESTED, flag enabled, no in-flight run); create `DecisionResult(status=PENDING)`; transition stage; publish SQS; return 202 + `TriggerPhase1Response`.
  - `GET /cases/{case_id}/phase1`: latest `DecisionResult` by `created_at DESC`; 404 if none.
  - `GET /cases/{case_id}/phase1/steps`: all `DecisionStep` rows ordered by `step_number`.
  - `GET /cases/{case_id}/phase1/steps/{n}`: single step by number; 404 if not yet started.
  - `POST /cases/{case_id}/phase1/cancel`: admin only; set status=CANCELLED; revert stage to INGESTED; 409 if already COMPLETED or FAILED.
- [ ] Wire router into `main.py`.
- [ ] Tests cover:
  - POST phase1 — happy path returns 202; duplicate in-flight returns 409; wrong stage returns 409; flag disabled returns 503.
  - GET phase1 — returns latest result; 404 when none.
  - GET steps — ordered list; returns empty list when not started.
  - GET steps/{n} — correct step returned; 404 for non-existent step.
  - Cancel — admin cancels RUNNING run; non-admin rejected 403; cancelling COMPLETED returns 409.
- [ ] Commit: `feat(m5): decisioning API endpoints (trigger, read, steps, cancel)`

---

## Task 19: Frontend Phase 1 tab

> **Suggested model:** Sonnet

**Files:** `frontend/app/cases/[id]/phase1/page.tsx` (or equivalent component path), supporting component files

**Reference:** spec §5.2, §5.3, §10 (shadow mode)

- [ ] Locate the existing case detail route under `frontend/` (check `frontend/app/cases/[id]/` or equivalent Next.js/React structure from M4 implementation).
- [ ] Add a "Phase 1" tab to the case detail page:
  - If no `decision_result` exists: show "Run Phase 1 Analysis" button (calls `POST /cases/{id}/phase1`).
  - If `status == PENDING` or `RUNNING`: show progress indicator + per-step status list (polling `GET /cases/{id}/phase1/steps` every 10 s).
  - If `status == COMPLETED` and `decisioning_shadow_only == false`: show final decision badge (APPROVE / APPROVE_WITH_CONDITIONS / REJECT / ESCALATE_TO_CEO), confidence score, reasoning markdown, pros/cons, deviations.
  - If `decisioning_shadow_only == true`: show "Analysis complete (shadow mode)" without recommendation details.
  - If `status == FAILED`: show error message + "Retry" button.
  - Admin users see "Cancel" button when RUNNING.
- [ ] Per-step progress table: step number, step name, status badge (color-coded), model used, cost_usd, completed_at. Expand row to show `output_data` as formatted JSON.
- [ ] Commit: `feat(m5): frontend Phase 1 tab with step progress + decision display`

---

## Task 20: Parsers unit tests + coverage + lint + README + tag

> **Suggested model:** Haiku (mechanical close-out)

**Files:** `backend/tests/decisioning/test_parsers.py`, various test gaps, README

**Reference:** spec §14.2, §14.5, §17

- [ ] `test_parsers.py`: test each of `parsers/step_02.py` through `step_11.py` against:
  - Valid fixture JSON → correct dict returned, no warnings for complete citations.
  - Missing required key → `KeyError` caught, warning emitted, partial dict returned.
  - Completely malformed string → empty dict + warning, no exception raised.
- [ ] Run `poetry run pytest --cov=app/decisioning --cov-report=term-missing` — identify gaps.
- [ ] Fill coverage gaps targeting ≥ 85% on `app/decisioning/`.
- [ ] `poetry run ruff format app tests && poetry run ruff check app tests` — fix any issues.
- [ ] `poetry run mypy app` — fix any type errors (ensure `vector` column typing is correct for pgvector).
- [ ] Update `backend/README.md` (or project root README): add "M5 ✅ Phase 1 Decisioning Engine" section with brief summary + updated roadmap.
- [ ] Commit: `test(m5): parsers unit tests, coverage ≥85%, ruff + mypy clean`
- [ ] Commit: `docs(m5): README update`
- [ ] Tag: `git tag -a m5-decisioning-engine -m "M5 complete: Phase 1 Decisioning Engine, 11-step pipeline, Haiku/Sonnet/Opus cascade"`

---

## M5 Exit Criteria

- [ ] `docker compose up -d` boots Postgres + backend + ingestion-worker + decisioning-worker + LocalStack cleanly
- [ ] Decisioning worker logs show "PFL decisioning worker starting" + "System worker user: <uuid>"
- [ ] `POST /cases/{id}/phase1` returns 202 and transitions case stage to `PHASE_1_DECISIONING` in one transaction
- [ ] All 11 `decision_steps` rows created for a full run on the Seema fixture case (Anthropic mocked)
- [ ] `decision_result.status = COMPLETED` and case stage = `PHASE_1_COMPLETE` at end of happy-path run
- [ ] Step 1 hard-fail short-circuits: case stage = `PHASE_1_REJECTED`, steps 2–10 have status = SKIPPED
- [ ] Step 10 graceful degradation: empty pgvector library → step status = SKIPPED, pipeline continues to Step 11
- [ ] `cache_read_tokens > 0` on second pipeline run in integration test (policy block cache hit)
- [ ] `GET /cases/{id}/phase1/steps/{n}` returns citations with valid `artifact_id` references
- [ ] Shadow mode: `decisioning_shadow_only=True` suppresses email notifications and hides recommendation in API response
- [ ] Cost abort: pipeline terminates if `total_cost_usd > 2.00`, writes `decision.cost_exceeded` audit entry
- [ ] Cancel: `POST /cases/{id}/phase1/cancel` stops the worker at next step boundary, reverts stage to INGESTED
- [ ] ≥ 85% coverage on `app/decisioning/`
- [ ] Ruff + mypy clean
- [ ] Tag `m5-decisioning-engine` created, merged to main with `--no-ff`

---

## Cross-reference to spec

| Task | Spec section |
|---|---|
| T1 | §15, §16, §12.2 |
| T2 | §4.1, §5.6 |
| T3 | §4.2–§4.5 |
| T4 | §7.1–§7.3, §13.1 |
| T5 | §9.1, §9.2 |
| T6 | §9.3 |
| T7 | §9.4 |
| T8 | §6 Step 1 |
| T9 | §6 Steps 2–3, §7.2–§7.3 |
| T10 | §6 Step 4 |
| T11 | §6 Steps 5–6 |
| T12 | §6 Step 7, §9.4 |
| T13 | §6 Steps 8–9 |
| T14 | §6 Step 10, §9.3 |
| T15 | §6 Step 11, §7.2, §8 |
| T16 | §13.2–§13.3, §11 |
| T17 | §12.1 |
| T18 | §5.1–§5.5 |
| T19 | §5.2–§5.3, §10 |
| T20 | §14.2, §14.5, §17 |

---

*End of M5 plan.*
