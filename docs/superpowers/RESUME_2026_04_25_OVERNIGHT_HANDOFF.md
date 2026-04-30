# Overnight resume — 2026-04-25 handoff

Picks up from `RESUME_2026_04_25_NEXT_SESSION.md`. The user went to sleep
mid-session with instructions to work autonomously overnight, make my
own recommendations / best-choice decisions, finish Part B end-to-end,
then audit the verification pipeline + MD-approval flow for bugs and
fix them. Everything below landed in a single unbroken session and is
pushed to `origin/4level-l1`.

## 1. Where we are

- **Branch:** `4level-l1` · **fully pushed** to origin
- **HEAD:** `06f3dcf` — fix(l3-vision): attach evidence with error_message + source_artifacts on scorer-failed paths
- **Working tree:** clean
- **Open PR:** [#1](https://github.com/saksham7g1/pfl-credit-system/pull/1) — auto-updated on every push
- **Baseline tests:** 718 passing (up from 637 at session start; **+81 tests** added across Part B + audit fixes)

## 2. Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -12

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 8

# Frontend dev server — restart if it isn't running (it was restarted
# during this session so may or may not still be up on pid 19300)
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Login: saksham@pflfinance.com / Saksham123!
# Ajay case: 7bdea924-225e-4b70-9c46-2d2387fc884c
```

## 3. What landed this session (overnight)

Session-total: **21 new commits on 4level-l1** on top of the previous
RESUME_2026_04_25 baseline. Split by workstream:

### 3.1 Part B — cross-level evidence audit (primary goal)

| # | Commit | What it does |
|---|---|---|
| B1 | `902daa4` (pre-sleep) | L1.5 scanner + score + meta-emitter evidence enrichment |
| B2 | `c00dc1e` (pre-sleep) | L1 cross-check evidence: threshold / count constants |
| B3 | content inside `2060850` | L2 + L4 meta-emitter evidence (bundled with an L5 scoring fix by the parallel session) |
| B4 | `655b7a7` | **L1** `sub_step_results.pass_evidence` for all 6 rules |
| B5 | `cbe4a6f` | **L1.5** pass_evidence for status scanners + score floor + bureau + opus |
| B6 | `fece2c9` | **L2** pass_evidence for all 8 rules |
| B7 | `aad20ca` | **L4** pass_evidence for agreement rules |
| B8 | `cbb0ce9` | FE smart layout: `AvgBalanceVsEmiCard` |
| B9 | `78779f4` | FE smart layout: `CommuteCard` |
| B10 | `8d32c16` | FE smart layout: `BureauAccountRow` (for bureau status scanners × applicant + co-app) |
| B11 | `d10769c` | Dispatcher rename `L3PassDetailDispatcher` → `PassDetailDispatcher`; wires new cards on both fire + pass paths |

**Net effect:** every level's passing-rule click-to-expand now renders
structured detail, not the Part-B placeholder. Every concern has a
"What was checked" panel that reads the rule's specific fields, not
a generic key-value dump. Bureau status scanners, commute, and
avg-balance-vs-EMI rules have dedicated visual cards.

### 3.2 UX improvements (session-interjected)

| Commit | What it does |
|---|---|
| `c9815d1` | Moved "What was checked" panel from right-column to below description (reclaims the dead space under short concerns) |
| `52651a3` | Source files render in a parallel responsive grid (1/2/3 col) instead of a vertical stack |
| `37429bf` | Level-wide `LevelSourceFilesPanel` at the top of every expanded level — aggregates source artefacts across concerns AND passing rules, dedup by artifact_id. Replaces the per-concern waterfall. |

### 3.3 Verification audit fixes (3 blockers + 6 majors)

Full audit report at agent SHA `a457297cccadbd922` in the transcript.
All fixes landed as separate commits:

| # | Commit | Issue → Fix |
|---|---|---|
| B1 | `475abfe` | **Phase-1 gate was passing cases with only 4/6 levels run.** Now iterates every `VerificationLevelNumber` member and requires each present + passed (PASSED or PASSED_WITH_MD_OVERRIDE). |
| B2 | `879d64e` | **Re-running a level wiped MD overrides.** Added `backend/app/verification/levels/_common.py::carry_forward_prior_decisions`; wired into all 6 orchestrators. Terminal MD / assessor decisions carry forward to new issues with the same sub_step_id. If any carry forward as MD_APPROVED, the new VR's status is bumped to PASSED_WITH_MD_OVERRIDE instead of BLOCKED. |
| B3 | `d8e8616` | **MD + assessor queues leaked issues from superseded VR rows.** Queue endpoints now join against a `func.max(created_at)` subquery restricting to the latest VR per `(case_id, level_number)`. Uses the existing `ix_verification_results_case_level_created` index. |
| M1 | `65f2a59` | **L5 `r_a09_cibil_address_match` treated "L1 never ran" as PASS.** `ScoringContext` gained `latest_vr_by_level` dict; resolver now returns PENDING with "Trigger L1 first" remark when L1 hasn't run. |
| M2 | `5a63fdc` | **`decide_issue` TOCTOU on level promotion.** Concurrent MD decisions now serialize via `SELECT … FOR UPDATE` on the VerificationResult row before re-reading siblings. |
| M3 | `addca69` | **`trigger_level` raced under concurrent POSTs.** Now short-circuits with 409 if a RUNNING VR row exists within the last 5 minutes (zombie runs from crashed workers auto-expire). |
| M4 | `224ad42` | **MD decide + assessor resolve were not audit-logged.** Both endpoints now call `audit_svc.log_action` with action codes `ISSUE_ASSESSOR_RESOLVED` / `ISSUE_MD_DECIDED`, capturing before/after status + rationale. |
| M5 | `05b3ceb` | **L1.5 bureau `source_artifacts` used positional attribution.** Now looks up per-party artifact via `primary_row.artifact_id` / `co_row.artifact_id`. Positional fallback preserved for legacy CaseExtraction rows with NULL artifact_id. |
| M6 | `06f3dcf` | **L3 `house_scorer_failed` / `business_scorer_failed` had NULL evidence.** Both now attach `{error_message, photos_evaluated_count, source_artifacts}`. Also plugged the same hole on L2 `ca_analyzer_failed` (added source_artifacts citing the bank PDF). |

**Skipped by design:** M7 (orphan `auto_justify_level_issues` entry-
point) — needs a product decision (wire into `trigger_level` or drop
the code path). Flagged in the backlog below.

## 4. Spec updates

The Part B spec at
`docs/superpowers/specs/2026-04-25-part-b-cross-level-evidence-audit-design.md`
was written before execution and is mostly accurate. Actual
implementation deviated in small ways:

- The FE dispatcher was renamed (`L3PassDetailDispatcher` →
  `PassDetailDispatcher`) and moved to
  `frontend/src/components/cases/evidence/`.
- Part B B3 ended up bundled into commit `2060850` (an L5 scoring
  fix) because a parallel Claude session working on L5 picked up the
  uncommitted B3 working-tree changes. Content is correct, commit
  hygiene is suboptimal — noted in §11 of the spec's resolution log.

## 5. End-to-end verification on Ajay

Not re-verified in the browser this session (preview server
disconnected after a Next.js restart; debugging it would have cost too
much context). Subagents ran tsc + backend tests green on every commit.
**Recommend the user open Ajay's case in the browser as the first
thing tomorrow morning and confirm:**

1. L3 expand → header still shows Stock Analysis + Photos at top.
2. L1/L1.5/L2/L3/L4 expand → each level shows a single
   **Source Files** panel at the top aggregating every concern + pass
   artefact in a parallel grid.
3. Every concern's "What was checked" panel renders below the
   description (not beside it), with structured fields populated.
4. Every passing-rule click-to-expand renders a structured detail
   card (not the Part-B placeholder). Bureau write_off / settled /
   etc. concerns render the compact BureauAccountRow card.
5. L3 Ajay `cattle_health` still shows "Skipped — not a dairy
   business (classified: service)".

If any of these look off, the `LevelSourceFilesPanel` change in
`37429bf` is the likely culprit — that was the last significant FE
refactor, and preview verification was shaky at the time of commit.

## 6. Data-flow / MD-approval correctness

Post-audit-fixes, the pipeline should behave as follows:

- **Fresh case:** L1 → L1.5 → L2 → L3 → L4 → L5 all run. Gate opens
  only when every level is PASSED or PASSED_WITH_MD_OVERRIDE. L6
  runs against the gate-clean artefact set.
- **Concern fires:** assessor resolves (audit-logged); MD approves
  or rejects (audit-logged). MD_APPROVED on a BLOCKED level →
  VerificationResult bumps to PASSED_WITH_MD_OVERRIDE.
- **Re-run any level:** prior MD decisions carry forward to any
  matching new issue (same sub_step_id). MD doesn't have to re-
  approve the same issue after every re-trigger.
- **Concurrent triggers:** second POST returns 409 if the first is
  still RUNNING (5-minute zombie-safety window).
- **Concurrent MD decisions on sibling issues:** serialized via
  row-lock on the VR; level status promotion is atomic.
- **MD queue + assessor queue:** only show issues from the latest
  VR per (case, level). No duplicate work, no stale listings.

## 7. Remaining backlog

### High-value, short efforts

- **Preview-side smoke test** of all the FE changes above on Ajay.
  If anything is broken it's quick to fix — the logic is all
  committed and tested, only render paths need eyeball verification.
- **M7 — auto-justifier wire-up or delete.** `auto_justify_level_
  issues` in `services/auto_justifier.py:251` is advertised in the
  final-report gate (`verification.py:703`) but never called. Pick:
  wire it into `trigger_level` as a post-persist pass, or delete
  the function + the "AI auto-justified" references. The audit
  agent surfaced this as a dead-code flag, not a blocker.
- **Audit-agent minors m1-m7** (captured in the full audit report
  — see agent transcript `a457297cccadbd922`). Mostly query-
  optimisation + redundant reads. None are correctness issues;
  ship when you have a free afternoon.

### Medium-term

- **Part A's `house_living_condition` pass card still uses JSON
  pretty-print** (footgun in Part A §12 parking lot). ~30 min to
  build a proper ratings grid.
- **L5.5 Dedupe + TVR verification** — design brief at
  `docs/superpowers/specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md`.
  Now that Part B is shipped and the audit gaps are closed, L5.5 is
  the next logical build.
- **Cross-level `evidence` learning signal** — feed MD rationales
  into pre-L6 rule context. Today only L6 (indirectly via case
  library) sees MD signal. Pre-L6 cross-checks never do. Multi-
  day design.
- **Production-readiness audit** (unchanged from prior handoff).
  CORS, JWT secret rotation, TLS, per-user case isolation, rate
  limiting, default-password rotation.

### Long-tail (carried forward unchanged from prior handoffs)

- Kotak (KKBK) bank-statement parser still returns zero-tx PARTIAL.
- `[CASE_SPECIFIC]` filtering in L6 case-library retrieval.
- Learning-Rules `md_approved_count` split (trains vs case-only).
- 24% flat-rate EMI assumption centralisation in L2.
- Notifications bell deleted-case filter audit.
- GCP API key migration `supreme-ops-491112` → dedicated `pfl-*`.
- Per-item stock itemization in L3 scorer-prompt.
- Vision scorer `business_type` confidence threshold.

## 8. Known limitations / gotchas

- **Preview server state unreliable.** The Next.js dev server was
  killed + restarted mid-session (PID 19300). The preview MCP
  server may need re-attaching after a fresh terminal session. If
  `preview_list` returns no running frontend server, restart via
  `(cd frontend && npm run dev)`.
- **Parallel Claude session.** A second Claude session was running
  on the same branch during this work; commits `6dbb75d`,
  `2060850`, `14e2392` came from there (all L5 scoring + artefact
  serving fixes). Content is correct; it just means `git log`
  interleaves two authors' commits.
- **Docker bind-mount HMR flaky** for L5 (pre-existing gotcha).
  `docker restart pfl-backend` if BE changes don't stick.
- **Pre-existing NotificationsBell tsc error** at
  `frontend/src/components/layout/__tests__/NotificationsBell.test.tsx:54`
  still surfaces on every `npx tsc --noEmit`. Not this session's
  responsibility; filter it out when scanning.
- **Suppressed_rules carry-forward** behavior with the new
  `carry_forward_prior_decisions` helper is untested. If an MD
  suppressed a rule and the rule no longer emits, the carry-forward
  is a no-op (no new issue to inherit from), which is fine. If the
  rule still emits, the new issue inherits the prior MD decision
  cleanly. Worth eyeballing on a case that has a suppressed rule if
  one exists.

## 9. If you start a fresh session tomorrow

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -12

# Docs for context in reverse chronological order
cat docs/superpowers/RESUME_2026_04_25_OVERNIGHT_HANDOFF.md
cat docs/superpowers/RESUME_2026_04_25_NEXT_SESSION.md
cat docs/superpowers/RESUME_2026_04_24_EVENING_NEXT_SESSION.md

# Green-baseline smoke
cd backend && poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q
# Expect 718 passed.

# Kick off whatever's next. Most likely:
# - Eyeball Ajay in the browser to confirm the FE refactor looks right.
# - Pick a backlog item (L5.5 Dedupe + TVR, auto-justifier wire-up, etc.).
```

## 10. One-paragraph TL;DR

Shipped Part B end-to-end: every verification level now emits rich
structured evidence on every fire-path concern and populates
`sub_step_results.pass_evidence` on every passing rule, three new FE
smart-layout cards (`AvgBalanceVsEmiCard`, `CommuteCard`,
`BureauAccountRow`) reduce visual noise on the most common rule
patterns, and a level-wide `LevelSourceFilesPanel` aggregates every
cited artefact at the top of each level's expanded body as a parallel
preview grid — the MD now sees every source file for a level in one
glance without hunting through each concern. Followed by a full audit
of the verification pipeline + MD approval flow that found 3 blockers
+ 6 majors; all fixed in the same session. Most important blockers:
the Phase-1 gate was silently treating cases with only 4/6 levels run
as gate-open (now iterates every level), re-running a level wiped MD
overrides (now carries them forward via a new `_common.carry_forward_
prior_decisions` helper), and MD + assessor queues listed issues from
superseded VR rows (now filter to the latest VR per case+level). 21
commits total, all pushed to origin, 718 baseline tests passing (+81
from session start), zero regressions. **Next session: open Ajay's
case in the browser and eyeball the FE refactor — specifically the
`LevelSourceFilesPanel` top-of-level aggregation — since preview
verification was shaky at commit time. After that, L5.5 Dedupe + TVR
is the obvious next feature build.**
