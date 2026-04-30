# Resume — 7-Level One-Pager · MD Approvals Rebuild · Assessor Queue · Auto-Run Orchestration

> **Open a new Claude Code session in this repo and paste this file's path
> (`docs/superpowers/RESUME_2026_04_22_PIPELINE_ONEPAGER.md`) to pick up
> exactly where this session left off.**

**Spawned:** 2026-04-22 (late evening)
**Parent:** `docs/superpowers/RESUME_2026_04_22_L5_SCORING.md`
**Branch:** `4level-l1` (tip at session start: `6044b07`)
**Status:** 7-level credit pipeline is a single Verification tab (L1 → L6).
MD Approvals rebuilt in the standard app aesthetic with an amber "case-only"
third decision path. Assessor Queue shipped as Phase 1 of the gap-fix
workflow. ZIP download + artifact re-bundle endpoint live. Client-side
auto-run orchestrator fires L1 → L6 sequentially from a single CTA, with a
modal, a minimised dock, and per-case progress rings on the cases list.

---

## 1. What shipped this session

No commits yet — see §2 for the uncommitted working tree. A single commit
or a stack of focused commits is appropriate here depending on how you
want the PR to read.

### Functional summary

**Scoring drag context (MD-readable)**
- `level_5_scoring.py` now enriches `scoring_grade` and `scoring_section_{a,b,c,d}`
  issue descriptions with a `\n\n`-separated block summarizing *why* the
  score dropped:
  - **Weakest sections:** bullet list of the worst 3 sections with their
    titles and scores (e.g. `Section B (QR and Banking Check) — 13 / 35 (37%)`).
  - **Top misses:** bullet list of the worst 3 failing or pending rows —
    parameter name + plain-English status (`failing` / `data pending`) + a
    one-line evidence snippet. Weights stripped from user-visible text.
- Helpers `_row_bullet`, `_section_drag_context`, `_grade_drag_context`
  live at the top of the orchestrator. FAILs ordered before PENDINGs,
  each by weight desc.

**MD Approvals rewrite (standard-app aesthetic)**
- `frontend/src/app/(app)/admin/approvals/page.tsx` fully rewritten —
  removed the editorial/serif/rotated-stamp look. Now uses `Card`, `Badge`,
  `Button`, standard sans-serif type, same header band as the Cases page.
- **Three decision paths** per issue:
  - Green **Approve · override the block** → `[MITIGATION]` tag → trains
    the auto-justifier.
  - Amber **Approve for this case only** → `[CASE_SPECIFIC]` tag →
    recorded on the case + audit log, **not** surfaced as precedent (the
    auto-justifier and the precedents endpoint both filter on this marker).
  - Red **Reject · uphold the block** → `[REJECTION]` tag → trains the
    auto-justifier.
- Backend changes to support the new tag:
  - `backend/app/verification/services/auto_justifier.py` adds a
    `CASE_SPECIFIC_MARKER` constant; `_fetch_precedents` skips any row
    whose `md_rationale` starts with it.
  - `backend/app/api/routers/verification.py::get_precedents` does the
    same filter so the UI precedents panel never shows case-specific
    approvals as "past rulings".
- Intent UI structured as three equal-width cards; the textarea, submit
  button, and character counter all swap colour / copy based on the
  chosen intent.

**Assessor Queue (Phase 1 of the gap-fix workflow)**
- New route `/assessor/queue` ([page.tsx](frontend/src/app/(app)/assessor/queue/page.tsx))
  — grouped-by-case docket with collapsible dossiers + per-issue 3-step
  triage panel:
  1. **Upload a missing document** → `POST /cases/{id}/artifacts` (existing
     endpoint reused).
  2. **Re-run the owning level** → `POST /cases/{id}/verification/{level}`.
  3. **Promote to MD** → `POST /cases/verification/issues/{id}/resolve`
     with an assessor note; flips status to `ASSESSOR_RESOLVED` so it
     surfaces in MD Approvals.
- Per-dossier **"regenerate ZIP ↓"** link — streams a fresh bundle of all
  current artifacts (see below).
- Sidebar entry gated to `ai_analyser / underwriter / credit_ho / admin`
  with an amber pending-count badge.
- Backend: new `GET /verification/assessor-queue` endpoint reuses
  `MDQueueResponse` but returns only OPEN issues (not `ASSESSOR_RESOLVED`
  which are MD-bound). Accessible to the same four roles.

**Artifact bundle ZIP endpoint**
- `GET /cases/{id}/artifacts/zip` streams a DEFLATE-compressed archive of
  every non-deleted artifact on a case. Skips rows pointing at missing S3
  keys (logs a warning) rather than 500'ing the whole zip. Filename format
  `{loan_id}_artifacts.zip`. Audit-logged as `ARTIFACTS_ZIP_DOWNLOADED`.
- Gated to `ai_analyser / underwriter / credit_ho / admin / ceo`.
- Frontend: `casesApi.downloadArtifactsZip(caseId)` in `lib/api.ts`
  returns `{ ok, blob, filename }`; the assessor queue dossier header
  triggers it and streams the download.

**L6 Decisioning merged into the Verification tab**
- `VerificationPanel.tsx` now accepts `currentStage` and renders a 7th
  synthetic level: **L6 · Decisioning** — reads from `useDecisionResult`
  (the existing Phase 1 data path). No backend migration needed; L6 data
  still lives in `DecisionResult` / `DecisionStep` tables.
- The summary table now has 7 rows. L6 row shows status (PENDING /
  RUNNING / COMPLETED / FAILED / CANCELLED), total cost, last run
  timestamp, and an "Open" button that scrolls to / expands the L6 card.
- Below the 6 existing LevelCards, a new L6 card wraps the existing
  `<DecisioningPanel>` — so the entire credit pipeline reads top-to-bottom
  on one tab.
- The **"Verification 2" tab is removed** from the case detail page.
  `DecisioningPanel` import moved from the page to the verification panel.
- Gate banner wording updated: "Gate opens when L1–L5 all resolve to
  PASSED or PASSED_WITH_MD_OVERRIDE. L6 · Decisioning runs against the
  gate-clean artifact set."

**Client-side auto-run orchestration**
- `components/autorun/AutoRunProvider.tsx` — a React context + reducer
  that owns per-case run state. Walks `L1 → L1.5 → L2 → L3 → L4 → L5 → L6`
  sequentially, calling `casesApi.verificationTrigger(level)` then
  `casesApi.phase1Start()` for L6. Failures are captured per-step but
  don't stop the walk — a broken level doesn't strand the rest.
- State mirrored to `localStorage` key `pfl:autorun:v1`. On mount, any
  step left in `running` (interrupted by refresh or nav) is re-flagged
  `failed` with "Interrupted by navigation" so the UI doesn't show a
  zombie spinner. A **Resume** button in the modal re-walks from the next
  non-done step.
- `AutoRunModal` — centre-screen dialog with overall % bar + 7 rows
  (pending circle → spinner → green tick / red X). Header swaps to
  amber on finished-with-errors, emerald on clean. Footer buttons:
  **Minimize — keep running** (hides modal, state continues) or
  **Dismiss** / **Keep in dock** when complete.
- `AutoRunDock` — fixed bottom-right card stack listing every minimised
  run. Each card shows the per-case circular % ring (or a green tick
  once done), the applicant name, status, and links back to the modal
  and to the case detail page.
- `AutoRunCaseBadge` — tiny per-case indicator that sits beside the
  "View" button on the Cases table. A live progress ring while running,
  a green `✓ ready` pill when complete; click to re-open the modal.
- `AutoRunTrigger` — header button on the case detail page. Swaps
  between "Auto-run all levels" (idle) → "Auto-run running — open" →
  "Pipeline complete".
- **Integration**:
  - `wizard/Step3Finalize.tsx` calls `startAutoRun(...)` as soon as
    `api.cases.finalize` resolves — so the modal is visible before the
    2s redirect to the case detail page.
  - `actions/ReingestDialog.tsx` fires `startAutoRun(...)` after a
    successful `casesApi.reingest`.
  - The provider is mounted at `app/(app)/layout.tsx` so it survives
    navigation between routes; the modal + dock are rendered there too.

**Bug fixes landed this session**
- **Case detail page crashed on the "Verification 2" tab**
  (`Objects are not valid as a React child (found: object with keys
  {text, citations})`). Anthropic responses with citations enabled
  return text blocks as `{text, citations}` objects; `DecisioningPanel`
  rendered them directly. Added an `asText()` helper that unwraps
  `{text}` (or an array of blocks) into a plain string. Applied to
  `conditions`, `pros_cons.pros/cons`, `deviations`,
  `reasoning_markdown`, `risk_summary`.
- **Invalid HTML nesting** (hydration error) — both the MD Approvals
  dossier header and the Assessor Queue dossier header wrapped a
  `<Link>` / inline `<button>` / `<Badge>` (renders `<div>`) inside a
  `<button>`. Converted the outer headers and each issue row's toggler
  to `<div role="button" tabIndex={0}>` with `onKeyDown={Enter/Space}`.
- **L4 Agreement level re-run blew up with
  `uq_case_extractions_per_artifact` UniqueViolationError.**
  `_load_or_scan_lagr_parties` (in `level_1_address.py`) gated its cache
  hit on `status == SUCCESS` but fell through to a raw INSERT on every
  non-SUCCESS row. If a prior PARTIAL extraction existed, the next re-run
  violated the `(case_id, extractor_name, artifact_id)` unique key.
  Fix: when `existing is not None`, UPDATE its fields in place (schema
  version, status, data, warnings, error_message, extracted_at).
- **Skipped decisioning steps polluted the pipeline table and tier
  breakdown.** `DecisioningPanel` now filters SKIPPED rows out of the
  steps table and the tier grouping; the caption shows `(N skipped —
  covered by the 6-level verification gate)` so the info isn't lost.

---

## 2. Uncommitted working tree

Everything from this session is uncommitted. Also carrying over the
Notifications scaffolding from the parent session.

```
 M backend/app/api/routers/cases.py                       ← NEW zip endpoint + _log import
 M backend/app/api/routers/notifications.py               (user-added, carried over)
 M backend/app/api/routers/verification.py                ← new /verification/assessor-queue + precedent filter
 M backend/app/main.py                                    (user-added, carried over)
 M backend/app/services/notifications.py                  (user-added, carried over)
 M backend/app/verification/levels/level_1_address.py     ← LAGR cache upsert fix
 M backend/app/verification/levels/level_5_scoring.py     ← drag-context helpers + richer issue descriptions
 M backend/app/verification/services/auto_justifier.py    ← CASE_SPECIFIC_MARKER filter
?? backend/app/api/routers/notifications.py               (was staged)
?? backend/app/services/notifications.py                  (was staged)
?? FOLLOW_UPS.md
?? docs/superpowers/RESUME_2026_04_22_L5_SCORING.md       (parent resume doc)
?? docs/superpowers/RESUME_2026_04_22_PIPELINE_ONEPAGER.md (this file)

 M frontend/src/app/(app)/admin/approvals/page.tsx        ← full rewrite
 M frontend/src/app/(app)/cases/[id]/page.tsx             ← Verification 2 tab removed, AutoRunTrigger added
 M frontend/src/app/(app)/layout.tsx                      ← AutoRunProvider + Modal + Dock mounted
 M frontend/src/components/cases/CaseTable.tsx            ← AutoRunCaseBadge next to View
 M frontend/src/components/cases/DecisioningPanel.tsx     ← asText() coercer + SKIPPED filter
 M frontend/src/components/cases/VerificationPanel.tsx    ← L6 row + card + dedupe-badge hydration fix
 M frontend/src/components/cases/actions/ReingestDialog.tsx ← auto-run kickoff after reingest
 M frontend/src/components/layout/Sidebar.tsx             ← Assessor Queue entry + dual badges
 M frontend/src/components/layout/Topbar.tsx              (notifications bell, carried over)
 M frontend/src/components/wizard/Step3Finalize.tsx       ← auto-run kickoff after finalize
 M frontend/src/lib/api.ts                                ← downloadArtifactsZip + assessorQueue
 M frontend/src/lib/useVerification.ts                    ← useAssessorQueue hook
?? frontend/src/app/(app)/assessor/queue/page.tsx         ← Assessor Queue page
?? frontend/src/components/autorun/AutoRunProvider.tsx
?? frontend/src/components/autorun/AutoRunModal.tsx
?? frontend/src/components/autorun/AutoRunDock.tsx
?? frontend/src/components/autorun/AutoRunCaseBadge.tsx
?? frontend/src/components/autorun/AutoRunTrigger.tsx
?? frontend/src/components/layout/NotificationsBell.tsx   (user-added, carried over)
?? frontend/src/components/layout/__tests__/NotificationsBell.test.tsx (user-added, carried over)

?? .claude/                                               ← local agent config (gitignore candidate)
?? "backend/.coverage 2"                                  ← pytest scratch (gitignore candidate)
```

**Suggested commit boundaries** (focused `feat(...)` / `fix(...)`):
1. `fix(l5): readable drag context + L1 LAGR cache upsert`
2. `fix(decisioning): unwrap citation-style {text, citations} blocks + filter SKIPPED steps`
3. `feat(md-approvals): rewrite in standard app aesthetic + case-specific (non-learning) third decision path`
4. `feat(assessor): queue page + backend /assessor-queue + artifact ZIP endpoint`
5. `feat(verification): merge L6 Decisioning into the 7-level one-pager`
6. `feat(autorun): client-side pipeline orchestrator + modal + dock + cases-list badge`

---

## 3. Key code landmarks

### Backend

- `backend/app/api/routers/verification.py::assessor_queue` — new
  `GET /verification/assessor-queue` endpoint.
- `backend/app/api/routers/verification.py::get_precedents` — now filters
  `[CASE_SPECIFIC]` rows.
- `backend/app/api/routers/cases.py::download_artifacts_zip` — the ZIP
  endpoint, streams with `StreamingResponse`, skips missing S3 keys.
- `backend/app/verification/services/auto_justifier.py::CASE_SPECIFIC_MARKER`
  + `_fetch_precedents` filter.
- `backend/app/verification/levels/level_5_scoring.py::_row_bullet` /
  `_section_drag_context` / `_grade_drag_context` — drag-context helpers.
- `backend/app/verification/levels/level_1_address.py::_load_or_scan_lagr_parties`
  — UPSERT fix.

### Frontend

- `frontend/src/components/autorun/` — new directory
  (`AutoRunProvider`, `AutoRunModal`, `AutoRunDock`, `AutoRunCaseBadge`,
  `AutoRunTrigger`). Everything in-memory + `localStorage` — no worker.
- `frontend/src/app/(app)/layout.tsx` — `<AutoRunProvider>` wraps the
  whole `(app)` group; `<AutoRunModal />` + `<AutoRunDock />` rendered at
  the root so they survive navigation.
- `frontend/src/app/(app)/assessor/queue/page.tsx` — Assessor Queue.
- `frontend/src/components/cases/VerificationPanel.tsx` — 7-level
  one-pager; look at the `(() => { const dStatus = ... })()` IIFE in the
  summary table for the L6 row and the matching card right below the
  per-level map.
- `frontend/src/components/cases/DecisioningPanel.tsx::asText()` — the
  citation-block unwrapper. `activeSteps = (steps ?? []).filter(s => s.status !== 'SKIPPED')`
  is the one-liner that also cleanses the tier table.
- `frontend/src/app/(app)/admin/approvals/page.tsx` — rewritten.
  `INTENT_META` at the top has the three-intent config (tag, colour,
  placeholder text, button label).

---

## 4. Ajay reference case (`7bdea924-225e-4b70-9c46-2d2387fc884c`)

Current state at end of session, after an auto-run:

| Level | Status | Cost | Notes |
|---|---|---|---|
| L1 Address | BLOCKED · ~60% match | $0.019 | ration_owner_rule CRITICAL · gps_vs_aadhaar WARN |
| L1.5 Credit | PASS · 88% · 1 issue | $0.101 | Opus caution — Gordhan NTC |
| L2 Banking | BLOCKED · ~71% · 2 issues | $0.016 | chronic_low_balance CRITICAL · ca_narrative_concerns WARN |
| L3 Vision | BLOCKED · ~75% · 1 issue | $0.166 | house_living_condition CRITICAL · barbershop classification |
| L4 Agreement | BLOCKED · ~67% · 1 issue | $0.060 | asset_annexure_empty CRITICAL |
| L5 Scoring | BLOCKED · 48/100 · 9 issues | $0.000 | drag-context block now renders on scoring_grade / scoring_section_* |
| L6 Decisioning | COMPLETED · ESCALATE_TO_CEO | $0.427 | renders inline under L5 on the Verification tab |

Overall docket count: **61 issues** (re-running creates fresh VerificationResults
each time — see §5 P1). Final-report endpoint returns 409 with the blocker list.

---

## 5. Next-up work queue (priority order)

### P0 — De-duplicate verification result history

Every re-run of a level creates a brand-new `VerificationResult` + a fresh
set of `LevelIssue` rows. Re-running L5 once on Ajay pushed the pending
docket from 42 → 51 → 61 across this session. The MD and assessor queues
don't collapse by `(case_id, level_number, sub_step_id)`, so stale issues
linger forever.

Options:
1. Keep appending, but add a `superseded_by_id` column on `LevelIssue` and
   have the run orchestrator mark previous results' issues as superseded
   when a new result completes for the same level.
2. Collapse in the queue query: select only issues whose
   `verification_result_id` is the latest per `(case_id, level_number)`.
3. A nightly/weekly janitor that closes issues on non-latest results.

Option (2) is the least invasive — a SQL change in `md_queue` and
`assessor_queue`. Recommend starting there.

### P1 — Wait-for-INGESTED before auto-run

Right now `startAutoRun` fires immediately from `Step3Finalize` and
`ReingestDialog`. If extractions haven't finished, the first few level
calls get incomplete data and mark the step "failed". The user then has
to click Resume.

Cleaner: poll the case's `current_stage` until it's `INGESTED` (or a
terminal error stage) before the provider starts the L1 trigger. Put a
"Waiting for ingestion…" state in the modal's overall bar.

### P2 — Tab-close survival (backend-orchestrated auto-run)

The current orchestrator lives 100% on the client, so a full tab close
stops it. Move the loop to a FastAPI background task or a dedicated
worker: new endpoint `POST /cases/{id}/autorun` enqueues a job that
walks L1 → L6 server-side. Status polled by the UI. The modal +
`localStorage` mirror becomes a status viewer.

### P3 — AutoJustifier wiring into level engines

Still not done (carried from parent resume doc). Add an
`auto_justify_level_issues` post-pass call at the end of each
`run_level_*` function. Expected effect on Ajay: 2–3 of the ~30 open
issues auto-resolve on re-run once a couple of `[MITIGATION]` precedents
exist.

### P4 — Scoring-model PENDING resolvers

Unchanged from parent doc. Parameters #2, #11, #13, #14, #15, #17, #25,
#28, #30, #31, #32 still always PENDING.

### P5 — Unit tests

- `tests/unit/test_autorun_provider.test.tsx` — reducer transitions + localStorage roundtrip.
- `tests/unit/test_assessor_queue_endpoint.py` — RBAC + filter correctness.
- `tests/unit/test_artifacts_zip.py` — skip-missing-keys path + filename + audit log.
- `tests/unit/test_md_queue_case_specific.py` — verify
  `[CASE_SPECIFIC]` rows don't surface in `/precedents/{sub_step_id}`.
- `tests/unit/test_level_1_address_lagr_upsert.py` — prior PARTIAL row +
  fresh scan should UPDATE, not INSERT.

### P6 — Notifications feature (still uncommitted)

User-scaffolded module carried from the parent session. Check with the
user whether they want Slack, in-app bell only, or email.

### P7 — Carried forward from parent doc

Equifax per-account `emi_amount` + enquiries with dates · Punjab / Delhi
/ UP pincode masters · address capture on equifax + bank_statement
extractors.

---

## 6. How to resume

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -5

# Stack
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 6       # bounce after any python edit

# Frontend
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Auth (same creds, MFA off locally)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Probe the new assessor queue endpoint
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/verification/assessor-queue | python3 -m json.tool | head -40

# Probe the ZIP endpoint on Ajay (expect ~22 MB archive)
curl -s -o /tmp/ajay.zip -w "HTTP %{http_code}  bytes: %{size_download}\n" \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/artifacts/zip
unzip -l /tmp/ajay.zip | head

# Re-run the drag-context for Ajay and print it
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L5_SCORING >/dev/null
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L5_SCORING \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
for i in d.get('issues',[]):
    if i['sub_step_id']=='scoring_grade':
        print(i['description']); break
"

# Browser
open "http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c"
open "http://localhost:3000/admin/approvals"
open "http://localhost:3000/assessor/queue"
```

You should see:
- Verification tab: **7** rows in the summary table (L1 → L6), all green
  ticks / red Xs, followed by per-level cards including a collapsible
  **L6 · Decisioning** card at the bottom wrapping the old
  DecisioningPanel.
- Case detail header: an extra blue **"Auto-run all levels"** button
  next to Re-upload / Re-ingest. Click it → modal appears → watch L1 → L6
  advance.
- MD Approvals: clean sans-serif page, **three** coloured decision cards
  (green / amber / red) per issue.
- Assessor Queue: per-case dossiers with 3-step triage panels and a
  `regenerate ZIP ↓` link on every dossier header.
- Cases list: a green `✓ ready` pill or spinning ring next to **View** on
  any case with an auto-run in state.

Login creds: `saksham@pflfinance.com` / `Saksham123!`.

---

## 7. Quirks observed this session

| Symptom | Cause / Fix |
|---|---|
| `<button>` with nested `<Link>` / `<Badge>` (renders `<div>`) triggers React hydration errors and trips the `(app)/error.tsx` error boundary. | Converted outer containers to `<div role="button" tabIndex={0}>` with `onKeyDown` for Enter/Space. |
| Anthropic tool-use / citation responses return text as `[{ text, citations }]` blocks, not strings — rendering directly throws `"Objects are not valid as a React child"`. | `asText()` helper in DecisioningPanel; should be lifted into a shared util if this pattern recurs elsewhere. |
| `POST /cases/{id}/verification/L4_AGREEMENT` blew up with `UniqueViolationError` on `uq_case_extractions_per_artifact` after an L1 re-run had persisted a PARTIAL row. | L1's LAGR cache gated on SUCCESS-only; fresh scans then INSERTed a duplicate. Fix is an UPSERT. Look for the same pattern in any future per-artifact caches. |
| `localStorage.getItem('pfl:autorun:v1')` read inside `runAll` uses a synchronous snapshot, not the reducer state — chosen deliberately because the reducer is closed over the initial value at closure time. | Fine for resume behaviour (walk skips `done` steps) but any future "cancel" feature needs a cross-tick cancellation check that reads the live snapshot. |
| Next.js link navigation via `window.location.href = ...` in preview eval sometimes no-ops in Radix-rooted pages; dispatch `new MouseEvent('click', { bubbles: true })` on the anchor instead. | Preview-only quirk, not a product bug. |
| `startAutoRun` fires before ingestion finishes when called straight after `finalize` / `reingest`. First 1–2 level calls may 500 / return empty. | See §5 P1 — add a wait-for-INGESTED poll before firing L1. |

---

## 8. When you finish the next chunk

1. Commit with focused `feat(...)` / `fix(...)` messages (see §2 for
   suggested boundaries).
2. Update §1 status, §2 uncommitted tree, §4 Ajay snapshot, and §5
   priority queue in a **new** `RESUME_*.md` — don't overwrite this one.
3. If you land P0 (dedupe result history), the Ajay docket count should
   drop substantially; record the before/after in the new resume doc.
4. If you land P1 (wait-for-INGESTED), add an integration test that
   uploads a ZIP, waits for the modal to reach 100%, and verifies
   `VerificationLevelDetail` has a result per level.
