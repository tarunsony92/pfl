# 🚦 PFL Credit AI — Resume Point

> **READ THIS FIRST when starting a new session.** All context needed to pick up exactly where we paused is in this file or referenced from it.

**Last updated:** 2026-04-22 (CAM discrepancy engine shipped; parallel work on 4-level verification gate continues on branch `4level-l1`)
**Current branch:** `main`
**HEAD commit:** `1371c36` — `feat(discrepancy): xlsx report exporter`
**Latest tag:** `m4-frontend-1.2` (pre-discrepancy-engine; consider a new tag after 4level-l1 merges and the combined branch is live-verified)
**Working tree:** clean on main. Sibling branch `4level-l1` has 13 additional commits ahead (L1–L5 verification gate) that haven't been merged — see "🔀 Pending branch merge" below.
**Backend tests:** 619 passing + 7 skipped (main). 4level-l1 has its own additions.
**Frontend tests:** 243 Vitest (main) + 3 Playwright

---

## 🆕 Latest work on main — CAM discrepancy engine (2026-04-22)

Five commits on top of `ab6544b`. Enforces the SystemCam (finpage-authoritative)
vs CM CAM IL (manual BCM / Credit HO) reconciliation rule per
`memory/project_autocam_sheet_authority.md`.

| SHA | Chunk |
|---|---|
| `c6daee2` | Detector + enums + 2 models + migration + schemas + service + 20 unit tests |
| `9fc9765` | HTTP router + Phase 1 trigger 409-gate + 11 integration tests + conftest MFA bypass hardening |
| `83ab04f` | Frontend DiscrepanciesPanel + tab wiring + 6 panel tests |
| `d22afb6` | Overview banner + Phase 1 "Start" button tooltip (gated until CRITICAL resolved) |
| `1371c36` | xlsx report exporter (two-sheet workbook, severity-coloured) + download link |

**What it does:**
- Detects 8 fields that appear in BOTH SystemCam and CM CAM IL (name, PAN, DOB,
  loan_amount, FOIR, CIBIL, monthly_income, tenure) with per-field tolerances.
- CRITICAL / WARNING severity: CRITICAL blocks `POST /cases/{id}/phase1` with a
  409 listing every pending flag.
- Resolution flow (ai_analyser / admin): `CORRECTED_CM_IL` self-serve,
  `SYSTEMCAM_EDIT_REQUESTED` spawns a CEO/admin approval request, `JUSTIFIED`
  records a narrative. Every resolution requires a ≥10-char comment.
- Markdown + .xlsx report exports include the full audit trail.

**Key endpoints:**
- `GET  /cases/{id}/cam-discrepancies`
- `POST /cases/{id}/cam-discrepancies/{field_key}/resolve`
- `GET  /cases/{id}/cam-discrepancies/report`
- `GET  /cases/{id}/cam-discrepancies/report.xlsx`
- `GET  /cases/{id}/system-cam-edit-requests`
- `POST /cases/{id}/system-cam-edit-requests/{request_id}/decide` (admin / ceo only)

**Dry-run on Ajay's real file (`10006079.xlsx`):** flags the WARNING FOIR gap
(SystemCam 25.35% vs CM CAM IL 18.1%) — exactly what the user called out.

## 🔀 Pending branch merge — 4level-l1 → main

A parallel session built a "4-Level Pre-Phase-1 Verification Gate" on branch
`4level-l1` (13 commits). That branch is ahead of the OLD main but behind the
CURRENT main which now has the discrepancy engine. Before running the combined
system, someone needs to:

1. **Reconcile Alembic heads.** `cam-discrepancy`'s migration is
   `c3d4e5f6a7b8` (down_revision = `b2c3d4e5f6a7`). `4level-l1`'s head is
   `c4d5e6f7a8b9` with the same parent. Two diverging heads on the same
   base — one of them needs to become a child of the other. Simplest:
   `git rebase main 4level-l1` then rename the duplicate-parent migration
   to point at `c3d4e5f6a7b8` as its down_revision.
2. **Resolve merge conflicts on shared files.** Expected hotspots:
   - `frontend/src/app/(app)/cases/[id]/page.tsx` — both branches add a
     TabsTrigger + TabsContent. Append the sibling's "Verification" tab
     next to "Discrepancies".
   - `frontend/src/lib/types.ts` / `frontend/src/lib/api.ts` — both
     branches append; line-by-line concat should suffice.
   - Everything else should be independent.
3. **Apply the combined migration to the live `pfl` DB.** The local
   stack's DB already has `c4d5e6f7a8b9` from when the sibling ran
   `alembic upgrade head`. After reconciliation, `alembic upgrade head`
   should pick up my new tables.
4. **Live-verify end-to-end on the Ajay case.** Expected flow:
   `Reingest → Discrepancies tab shows the FOIR WARNING + (after
   extractor tightening) potentially a PAN CRITICAL → resolve each →
   Phase 1 trigger now succeeds → per-step token/cost visible on
   Phase 1 tab`. All of this works in the unit + integration test
   matrix; the live-verify is the final assertion.

## ✅ Completed milestones

| # | Milestone | Tag | Tests (at merge) |
|---|---|---|---|
| **M1** | Backend Foundation + Auth | `m1-backend-foundation` | 69 |
| **M2** | Case Upload + Storage | `m2-case-upload-storage` | 126 + 1 skip |
| **M3** | Ingestion Workers + Extractors | `m3-ingestion-workers` | 391 + 7 skip |
| **M4** | Next.js Frontend | `m4-frontend` | 547 + 7 skip |
| **M5** | Phase 1 Decisioning Engine | `m5-decisioning-engine` | 557 + 7 skip |

M1–M5 are on main, each merged with `--no-ff` and tagged.

---

## 🟡 Where we actually paused — live E2E on Ajay Hisar ZIP

User uploaded `/Users/sakshamgupta/Downloads/10006079 Ajay Hisar.zip` (22 MB, 40 internal files) through the frontend wizard. Fixed every issue found live.

### ✅ Closed issue #A — "PARTIAL (Data Found)" label confusing

**Landed in:** `a728cd9` (backend) + `47fba01` (frontend) — tag `m4-frontend-1.1`

- **Backend:** Each extractor's status now derives from its *primary output*, not warning presence. `equifax` → SUCCESS when credit_score + ≥1 account. `auto_cam` → SUCCESS when applicant_name + PAN present across any sheet AND no missing sheets. Non-critical warnings (e.g. blank CIBIL) stay in `warnings[]` without flipping status.
- **Frontend** `ExtractionsPanel.tsx`: introduced `effectiveStatus()` that returns SUCCESS / PARTIAL / FAILED based on (fields, warnings, backend status). A single non-critical warning on a populated extract now reads SUCCESS (green). PARTIAL (amber) requires ≥3 warnings OR a critical warning (`missing_credit_score`, `no_accounts`, `no_account_header_detected`, `missing_applicant_name`, `no_known_fields_matched`). FAILED (red) when fields == 0.

### ✅ Closed issue #B — AutoCAM FAILED on Ajay's real xlsx

**Landed in:** `a728cd9` — tag `m4-frontend-1.1`

Dry-run on real files now extracts `applicant_name="AJAY SINGH"` + `pan="OWLPS6441C"` from both `10006079.xlsx` (SUCCESS, all 4 sheets) and `CAM_REPORT_10006079.xlsx` (PARTIAL, single sheet aliased to SystemCam). Three surgical fixes:

1. **A/_/C row layout** — `_parse_sheet` now falls back to col C when col A holds the label and col B is empty (SystemCam real layout).
2. **Header-row false positives** — `_looks_like_header()` guard skips rows whose value column ends with " details" / " particulars" or is a bare header word (e.g. "Co-Applicant Details" no longer lands in borrower_name).
3. **Over-broad fuzzy** — dropped bare `"loan"` fuzzy (picked up product codes like "IGL" as loan_amount). Kept `"loan amount"` / `"loan required"`.

### ✅ Closed issue #D (discovered during live-verify) — every non-fixture extractor was silently failing on real files

**Landed in:** `e47a962` (extractors) + `b76523d` (classifier + pipeline reingest)

Post-`m4-frontend-1.1` reingest surfaced that the other extractors were written to the synthetic fixture schema and silently produced PARTIAL on Ajay's actual files. Every extractor now handles the real-world format and the reingest flow picks up both classifier-rule changes and extractor-code changes without re-upload. DB after live reingest on `7bdea924-…`:

| extractor | file | status | primary output |
|---|---|---|---|
| auto_cam | 10006079.xlsx | SUCCESS | AJAY SINGH + PAN + loan |
| auto_cam | CAM_REPORT_10006079.xlsx | PARTIAL | single-sheet (3 genuinely missing) |
| bank_statement | 10006079_BANK_STMT_1.pdf | SUCCESS | 752 tx, A/C=44438612884 |
| checklist | Checklist.xlsx | SUCCESS | — |
| equifax | EQUIFAX_CREDIT_REPORT__2_.html | SUCCESS | AJAY SINGH score=834 |
| equifax | *_1_.html + *.html | PARTIAL | GORDHAN / PINKI (bureau not-found, accurate) |
| pd_sheet | PD_sheet.docx | SUCCESS | AJAY SINGH + business fields |

**bank_statement** — real SBI format: `Account Number : 44438612884` (space-colon-space), Indian `DD/MM/YYYY` transaction dates, Mr./Ms. name line (no "Account Holder:" header). Regex tightened to `[ \t]*` around the colon, transaction regex now accepts both date formats, Mr./Ms. fallback added.

**pd_sheet** — real PD docs have zero tables and 65 narrative `Label: Value` paragraphs. Added paragraph scan (`partition(":")`) plus a fuzzy-substring label pass. `_LABEL_MAP` extended to include "Customer Profile" / "Business Vintage" / "Monthly Income" variants.

**equifax** — real V2.0 bureau output uses `<h4 class="displayscore">` (not `.CreditScore`), `<table id="accountTable">` (lower-case a), and embeds identity in flat text (`Consumer Name: AJAY SINGH`, `PAN:OWLPS6441C`, `DOB:17-11-2001`). Added regex fallbacks for name/PAN/DOB, `_pick_display_score()` to select the max non-negative score across multiple `displayscore` tags, and `_parse_real_account_table()` that groups multi-row account blocks and pulls institution/type/balance/status/dates. Summary counts pull from `summaryTable` when fixture counts aren't available.

**classifier** — xlsx byte-level `"credit assessment" in body_lower` only ever matched the contrived test fixture; xlsx is a zip of XML so the literal bytes are never present. Rewrote `_classify_xlsx_by_content` to load the workbook via openpyxl (read-only) and inspect sheet names. Fallback: first-row cell content.

**pipeline** — (1) `_run_extractors` was called with `new_artifacts` only, so an admin reingest never re-extracted existing artifacts when extractor code changed — now receives `all_artifacts` on `trigger="reingest"`. (2) Added `_reclassify_existing_artifacts` that runs the (possibly-updated) classifier over each artifact's fresh zip bytes and updates `metadata_json.subtype` when it differs. Uses `flag_modified()` because SQLAlchemy tracks JSON columns by identity.

### Open issue #C — Loan amount / tenure show "—" on the OLD Ajay case

Case `7bdea924-225e-4b70-9c46-2d2387fc884c` was created BEFORE `5a3829a` added those columns, so the row's loan_amount / tenure / co_applicant_name are NULL. New cases populate correctly. Not a bug — either soft-delete and re-upload, or UPDATE the row manually. No code change needed.

---

## ✅ What shipped in this session (12 commits after M5 merge)

All on `main`, in order:

| SHA | Summary |
|---|---|
| `4d41ba4` | "+ New Case" button + dual S3 endpoint URL (internal vs public) for presigned URLs |
| `a12ca95` | Classifier fixes from live data (UID_*, CAM_REPORT, BANK_STMT, COAP_, bare BANK_ACCOUNT) + wizard loan_id trim |
| `d24dccf` | `api.cases.initiate` posts to `/cases/initiate` (was `/cases/` → 405) |
| `5c7f417` | `http.ts` renders Pydantic error list / object detail as readable string (was `[object Object]`) |
| `54169f2` | `StorageService.ensure_bucket_exists` applies permissive CORS on the bucket (fixed browser uploads) |
| `43607ba` | `Step3Finalize` uses `useRef` guard against React Strict Mode double-fire (fixed redirect not firing) |
| `d85b20a` | Dedupe tab: "no active snapshot" CTA (admin link) vs "no matches" (applicant unique) |
| `5a3829a` | `CaseInitiateRequest` accepts loan_amount, loan_tenure_months, co_applicant_name; Case table gained columns |
| `8c0df3b` | **`CaseFeedback` model + `POST/GET /cases/{id}/feedback` + `FeedbackWidget`** (AI-learning input, phase 1 of parent spec §7) |
| `94ef85d` | `CaseInsightsCard` on Overview tab — applicant, CIBIL, FOIR, surplus, counts |
| `3139a6b` | `ExtractionsPanel` header shows "N fields extracted" + PARTIAL-with-data styling |
| `97ca425` | AutoCam extractor fuzzy sheet-name + cell-label matching |

Test delta over M5 baseline: **+22 backend, +25 frontend. All green.**

### Permanent docker-compose.yml / dev config changes

- `AWS_S3_PUBLIC_ENDPOINT_URL=http://localhost:4566` — for presigned URLs served to browser
- `AWS_S3_ENDPOINT_URL=http://localstack:4566` — for backend→LocalStack calls
- S3 bucket CORS set to `*` on startup (localhost dev; tighten in M8)

### Dev-only live DB state

- User: `saksham@pflfinance.com` / `Saksham123!` — role=`admin`, mfa_enabled=`false` (spec §3.3 normally requires MFA for admin; we disable it to skip TOTP friction in dev)
- One case: `7bdea924-225e-4b70-9c46-2d2387fc884c` (loan_id=10006079, Ajay Singh, stage=INGESTED, 41 artifacts)

---

## ⏭️ What's next

### Immediate — M4 polish verification (~5 min)

1. **Live-verify #A + #B** — click admin "Re-ingest" on the Ajay case detail page. Expect AutoCAM row to flip FAILED→SUCCESS with applicant_name / pan populated. Equifax entries stay PARTIAL (primary genuinely missing) but show warning-count accurately. Any extractor that was flipping to "PARTIAL (Data Found)" on a non-critical warning should now show SUCCESS (green).
2. **Test FeedbackWidget end-to-end** — submit each verdict + notes, verify rows in `case_feedbacks` and audit entries for `case.feedback_submitted`.

### Current — M6 Phase 2 Audit Engine (starting now)

**Parent spec reference:** `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md` §6.

**Scope summary:**
- **Layer A:** 30-point credit audit, fully auto-filled (4 sections / 47 items, max 100 pts). Pass ≥90 · Concern 70–89 · Fail <70.
- **Layer B:** 150-point operational audit, schema + partial fill (17 sections A–Q). v1 fills ~60–80/150 from case kit; remainder "Pending API" until M8/Finpage.
- **Doc cross-verification:** CAM vs source docs → mismatch log (xlsx).
- **Exec summary:** 1–2 page Word doc synthesised by Claude Sonnet.
- **Outputs:** `{loan_id}_30pt_audit_filled.xlsx`, `{loan_id}_150pt_audit_partial.xlsx`, `{loan_id}_mismatch_log.xlsx`, `{loan_id}_audit_summary.docx`. Verdict: PASS / CONCERN / FAIL.

**M5 foundation available:** decision models + SQS worker pattern + pipeline in `app/decisioning/` — clone that shape for `app/auditing/`. No audit-specific tables/enums/workers exist yet (clean slate).

**Spec gaps that need closing before plan:**
- Per-item Pass/Fail/N/A rubric for the 30 items (extract from Saksham's current `30 Point Scoring Model Draft.xlsx` or AI-judge each?)
- 150-point schema field list + data-source mapping (data-driven vs AI-judged per item)
- Doc cross-verification prompts (which source pairs, tolerance bands, what lands in mismatch log vs deviation log)
- Exec summary .docx template structure

### Remaining milestones

| Milestone | Scope | Status |
|---|---|---|
| **M6** | Phase 2 Audit Engine — 30-point scoring fully auto-filled, 150-point template partial, mismatch log, exec summary | Needs spec + plan |
| **M7** | Memory subsystem — UI for `policy.yaml` + `heuristics.md` editing, approved-deviation workflow, NPA retrospective loop, Voyage embeddings replacing M5's 8-dim numeric vector. **Also closes:** the real "case feedback → heuristics proposals" loop (M4's `FeedbackWidget` is phase-1 capture only — M7 synthesises proposals). | Needs spec + plan |
| **M8** | AWS Mumbai deploy via CDK — ECS Fargate + RDS + S3 + SQS + SES + CloudFront + Route 53. Replace LocalStack. Redis for access-token cache (lifts the single-Next-instance constraint). | Needs spec + plan |
| **M9** | Shadow rollout (100 cases reviewed by user) + validation + go-live + monitoring | Needs spec + plan |

### User-granted orchestration authority (stable across sessions)

- *"no need to ask me further for other implementation milestones you become an orchestration expert and automatically go with your recommendations as my approvals"* (pre-M3)
- *"after m3 continue building m4 to m9 per the plan as well ... no chance of errors"* (M3)
- *"do as much as you can in this session then update the resume file accurately"* (M5)
- *"give me a resume session file so i can take this up right where you leave off in the next session"* (this session)

Working pattern:
1. Spec (with spec-reviewer subagent as quality gate, not approval gate)
2. Plan (with plan-reviewer subagent)
3. Execute via `superpowers:subagent-driven-development` in 2–3 chunks
4. Code review subagent per chunk
5. Commit per logical task (Co-Authored-By trailer)
6. Merge to `main` with `--no-ff`, tag `mN-<slug>`
7. Update this file + `FOLLOW_UPS.md` before ending

---

## 📍 How to resume (copy-paste)

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git checkout main
git status                                # should be clean
git log --oneline -1                      # should be 97ca425 or later

# Verify backend tests
export PATH="$HOME/.local/bin:$PATH"
cd backend && poetry run pytest -q | tail -3   # expect 579 passed, 7 skipped
cd ..

# Verify frontend tests
cd frontend && npx vitest run 2>&1 | tail -3   # expect 227 passed
cd ..

# Bring up full stack
docker compose up -d postgres localstack backend worker
cd frontend && npm run dev                 # http://localhost:3000
```

**Log in:** `saksham@pflfinance.com` / `Saksham123!` (admin, MFA off in dev).

**Test case URL:** [http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c](http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c)

---

## 🧩 Known deviations + gotchas (stable)

### §A1 — CLI uses `click`, not `typer`
### §A2 — `bcrypt` used directly, not `passlib[bcrypt]`
### §A3 — moto + aiobotocore compat patch in `backend/tests/integration/conftest.py` — DO NOT MODIFY
### §A4 — `Case.loan_id` partial unique index `WHERE is_deleted = false`
### §A5 — `add_artifact` accepts `queue: QueueService` kwarg
### §A6 — `CaseExtraction` uses two partial unique indexes (artifact_id NULL/NOT NULL)
### §A7 — `DedupeSnapshot.is_active` partial unique index
### §A8 — Worker uses system worker user for audit `actor_user_id`
### §A9 — `PgEnum(create_type=True, values_callable=..., name=...)` + `# noqa: N811`
### §A10 — Seema ZIP E2E tests skip if ZIP absent
### §A11 — `poetry` at `~/.local/bin/poetry` — always `export PATH="$HOME/.local/bin:$PATH"` before poetry
### §A12 — Follow-ups: `docs/superpowers/FOLLOW_UPS.md`
### §A13 — Frontend auth: HttpOnly refresh cookie, JS-readable CSRF cookie, server-side access-token cache
### §A14 — `frontend/src/lib/enums.ts` auto-generated — run `npm run sync-enums` after backend enum changes
### §A15 — `stages_svc.transition_stage()` does NOT accept `reason=` kwarg
### §A16 — `DecisionStatus.CANCELLED` (double-L British spelling)
### §A17 — `compute_feature_vector()` takes keyword float args
### §A18 (NEW) — Dev S3 endpoint split: `AWS_S3_ENDPOINT_URL` (docker-internal) vs `AWS_S3_PUBLIC_ENDPOINT_URL` (host-reachable)
### §A19 (NEW) — Dev bucket auto-CORS `AllowedOrigins=["*"]` on startup; tighten in M8
### §A20 (NEW) — Wizard Step3 uses `useRef` guard against React Strict Mode double-fire
### §A21 (NEW) — `http.ts` stringifies error `detail` when not a string (Pydantic list / object)
### §A22 (NEW) — `api.cases.initiate` posts to `/cases/initiate` (bare `/cases/` is list endpoint, GET only)
### §A23 (NEW) — `CaseInitiateRequest` accepts loan_amount / loan_tenure_months / co_applicant_name; Case has matching nullable columns
### §A24 (NEW) — Case feedback: `case_feedbacks` table + `FeedbackVerdict` enum (APPROVE/NEEDS_REVISION/REJECT) + `POST/GET /cases/{id}/feedback` + `FeedbackWidget` below tabs
### §A25 (NEW) — Next.js dev server on port 3000 can wedge after many hot reloads. Fix: `lsof -i :3000 -t | xargs kill; cd frontend && npm run dev`
### §A26 (NEW) — Incognito starts with no cookies; middleware redirects to `/login` — expected behavior
### §A27 (NEW) — Admin role requires MFA per spec §3.3; dev bypass `UPDATE users SET mfa_enabled=false WHERE email='…'`
### §A28 (NEW) — AutoCam extractor uses fuzzy sheet + cell-label matching; additive on top of original exact-match (existing fixture tests still pass)
### §A29 (NEW) — AutoCam `_parse_sheet` tries (A,B), (A,C fallback when B empty), and (B,C) column pairs. `_looks_like_header()` guard skips rows whose value cell ends with " details"/" particulars". Bare `loan` fuzzy removed — use `loan amount` / `loan required`.
### §A30 (NEW) — Extractor status semantics: SUCCESS = primary output populated (per-extractor); non-critical warnings stay in `warnings[]` without flipping status. Cross-sheet primary lookup in AutoCam via `_find_in_data(data, field_keys)`.
### §A31 (NEW) — `ExtractionsPanel.tsx::effectiveStatus(status, fieldCount, warnings)` re-maps backend PARTIAL → SUCCESS when data is present and warnings are low-severity. Critical warning prefixes live in `CRITICAL_WARNING_PREFIXES` constant; update when adding a new extractor warning that should force amber.
### §A32 (NEW) — Admin reingest now re-runs extractors on ALL artifacts and reclassifies them first. Code path: `pipeline.py::_run_pipeline` branches on `trigger == "reingest"` → calls `_reclassify_existing_artifacts` (updates `metadata_json.subtype` with `flag_modified`) then `_run_extractors(all_artifacts, ...)`. Safe because extractor writes are upserts keyed on `(case_id, extractor_name, artifact_id)` (see §A6).
### §A33 (NEW) — xlsx classifier uses `openpyxl.load_workbook(read_only=True)` to inspect sheet names (xlsx is a zip; raw byte `in` checks don't work on real files). AUTO_CAM markers: `systemcam` / `elegibilty` / `cm cam il` / `health sheet` / `cam_report`. Customer_Dedupe sheet still excludes.
### §A34 (NEW) — Real SBI bank statements use `"Account Number : 44438612884"` (space-colon-space) and `DD/MM/YYYY` transaction dates. Regexes use `[ \t]*` around the colon and accept both ISO + Indian date formats. Name fallback: first `Mr./Ms./Mrs.` line in the first 20 lines.
### §A35 (NEW) — Real PD sheets are narrative docx with 0 tables. `PDSheetExtractor` scans paragraphs with `partition(":")` in addition to tables. Fuzzy label map recognises "Customer Profile" / "Business Vintage" / "Monthly Income" variants.
### §A36 (NEW) — Real Equifax V2.0 HTML uses `<h4 class="displayscore">` (not `.CreditScore`) and `<table id="accountTable">` (lower-case a). `EquifaxHtmlExtractor` tries the fixture selectors first, falls back to `_pick_display_score()` + regex on flattened `get_text(" ")` for Consumer Name / PAN / DOB / summary counts. Real accountTable is a multi-row block per account — parsed by `_parse_real_account_table()`.
### §A37 (NEW) — Equifax "HIT CODE :00 / Consumer record not found" is a VALID complete bureau response (NTC applicants), not an extraction failure. `EquifaxHtmlExtractor` returns SUCCESS + single `bureau_no_record` warning + `data.bureau_hit=False`. **`data.credit_score` is preserved verbatim (e.g. `-1`) for NTC reports** — downstream decisioning MUST distinguish "bureau's explicit no-record sentinel (-1)" from "extractor found no score in the HTML (null)". `_pick_display_score()` prefers max positive; falls back to highest sentinel (typically -1); returns None only when no score tag parses. Only "real bureau report" files (hit=true) use the credit_score + ≥1 account primary-output check for PARTIAL.
### §A38 (NEW) — Single-sheet AutoCam variant (e.g. `CAM_REPORT_<loan>.xlsx`): if workbook has only 1 sheet, `AutoCamExtractor` omits `missing_sheet:*` warnings (the other 3 sheets aren't part of this variant by design) and sets `data.variant="single_sheet_cam"`. SUCCESS when primary extracted; FAILED when the sole sheet matches no alias.
### §A39 (NEW) — `bureau_no_record` is NOT emitted as a warning. The signal lives in `data.bureau_hit=False` and the preserved `data.credit_score=-1`; a warning chip on a clean bureau reply is reviewer noise. If you want to re-surface it, add a critical-prefix entry to `ExtractionsPanel.tsx::CRITICAL_WARNING_PREFIXES` AND re-emit from `equifax.py`.
### §A40 (NEW) — `ExtractionsPanel.tsx` derives a per-row subject via `extractionSubject(extraction)` so multiple rows from the same extractor are distinguishable (e.g. 3 Equifax reports → "Equifax — AJAY SINGH · score 834", "Equifax — GORDHAN · NTC / no bureau record", etc.). Subject candidates, in order: `customer_info.name` / `system_cam.applicant_name` / `eligibility.applicant_name` / `cm_cam_il.borrower_name` / `fields.applicant_name` / `account_holder`. Equifax-specific qualifier via `extractionQualifier()` annotates hit vs NTC.

---

## 🗂️ Key files touched in this session

### Backend
- `backend/app/config.py` — added `aws_s3_public_endpoint_url`
- `backend/app/services/storage.py` — split client/public_client + CORS on `ensure_bucket_exists`
- `backend/app/worker/classifier.py` — UID / CAM_REPORT / BANK_STMT / COAP_ patterns
- `backend/app/worker/extractors/auto_cam.py` — fuzzy sheet + label matching
- `backend/app/schemas/case.py` — `CaseInitiateRequest` extensions
- `backend/app/models/case.py` — loan_amount / tenure / co_applicant_name columns
- `backend/app/models/case_feedback.py` — NEW
- `backend/app/schemas/feedback.py` — NEW
- `backend/app/enums.py` — `FeedbackVerdict`
- `backend/app/api/routers/cases.py` — `POST/GET /cases/{id}/feedback`
- Two new Alembic migrations: wizard columns + `case_feedbacks`

### Frontend
- `frontend/src/lib/api.ts` — fixed `initiate` URL + added feedback + wizard fields
- `frontend/src/lib/http.ts` — error detail stringification
- `frontend/src/components/wizard/Step1Details.tsx` — trim transforms + passes all 5 fields
- `frontend/src/components/wizard/Step3Finalize.tsx` — `useRef` guard
- `frontend/src/components/cases/CaseInsightsCard.tsx` — NEW (Overview summary)
- `frontend/src/components/cases/ExtractionsPanel.tsx` — field-count header + PARTIAL-with-data badge
- `frontend/src/components/cases/DedupeMatchTable.tsx` — no-snapshot CTA (admin)
- `frontend/src/components/cases/FeedbackWidget.tsx` — NEW (below tabs)
- `frontend/src/app/(app)/cases/[id]/page.tsx` — insights + feedback wiring, loan_amount / tenure in header
- `frontend/src/app/(app)/cases/page.tsx` — `+ New Case` button

---

## ❗ First thing the next session should do

1. Read this file (top to "How to resume").
2. Verify: `git status` + backend `pytest -q` (expect 581) + frontend `vitest run` (expect 229).
3. `docker compose up -d postgres localstack backend worker` + `cd frontend && npm run dev`.
4. If the user hasn't already done live-verification of #A + #B, have them click "Re-ingest" on the Ajay case and sanity-check the Extractions tab.
5. Proceed with M6: draft spec at `docs/superpowers/specs/YYYY-MM-DD-m6-audit-engine-design.md`, dispatch spec-document-reviewer, iterate, then write the plan.

---

*End of resume document. Everything needed is in git or this file.*
