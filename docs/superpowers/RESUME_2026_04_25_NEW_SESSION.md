# Resume — 2026-04-25 (new session, post-overnight)

Pick up here for a fresh session. Continues from
`docs/superpowers/RESUME_2026_04_25_OVERNIGHT_HANDOFF.md`, plus one
fix-up morning commit (`4c00f67`) for the source-file panel that
Saksham caught after waking.

## 1. Where we are

- **Branch:** `4level-l1` · fully pushed
- **HEAD:** `4c00f67` · `fix(case-view): compact source-file cards — kill auto-download on render + restore parallel grid`
- **Open PR:** [#1](https://github.com/saksham7g1/pfl-credit-system/pull/1)
- **Working tree:** clean
- **Backend baseline:** **718 passing** (`poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q`)
- **Frontend tsc:** clean except a pre-existing `NotificationsBell.test.tsx:54` error you can ignore
- **Live case:** Ajay singh · loan `10006079` · `7bdea924-225e-4b70-9c46-2d2387fc884c`
- **Login:** `saksham@pflfinance.com` / `Saksham123!`

## 2. Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -8

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 8        # picks up any uncommitted BE work

# Frontend dev server — start if not running. NB the Next process
# may have been killed during the overnight session; check first.
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Sanity — backend health
curl -s -o /dev/null -w "health: %{http_code}\n" http://localhost:8000/health

# Sanity — Ajay's L3 still has visual_evidence + stock_analysis + pass_evidence
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L3_VISION" \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
ssr=(d.get('result') or {}).get('sub_step_results',{})
for k in ('visual_evidence','stock_analysis','pass_evidence'):
    print(f'{k}:', sorted(list((ssr.get(k) or {}).keys()))[:6])
"
```

## 3. What just shipped (overnight + this morning)

23 commits on `4level-l1` since the previous (4-night-prior) handoff.
Grouped:

### 3.1 Part A (recap — already shipped)

L3 always-visible Visual Evidence panel + click-to-expand pass detail
+ `cattle_health` business-type guard. See the prior overnight
handoff for the full story.

### 3.2 Part B — cross-level evidence audit (11 commits)

- **B1-B3** — fire-path evidence enrichment on L1, L1.5, L2, L4
  (every `cross_check_*` now attaches structured evidence not just
  `{party, accounts_matched}`).
- **B4-B7** — `sub_step_results.pass_evidence` populated for L1,
  L1.5, L2, L4. Click-to-expand on a passing rule now shows
  structured detail across every level, not just L3. Each entry
  carries `source_artifacts` matching the orchestrator's fire-path
  pattern.
- **B8-B10** — three new FE smart-layout cards:
  - `AvgBalanceVsEmiCard` — emerald/amber/red bar comparing avg
    balance vs `EMI × 1.5`.
  - `CommuteCard` — travel time + distance + dm_status pill +
    judge verdict row.
  - `BureauAccountRow` — party pill + worst-account one-liner +
    "+N more" chip; used by every bureau status scanner across
    applicant + co-app.
- **B11** — dispatcher rename `L3PassDetailDispatcher` →
  `PassDetailDispatcher` (moved to
  `frontend/src/components/cases/evidence/`); wires the new cards
  on both fire and pass paths.

### 3.3 UX pass (4 commits, including this morning's fix)

- `c9815d1` — "What was checked" panel moved under the description
  instead of beside it. Better at narrow widths, reclaims dead
  space under short concerns.
- `52651a3` — source files render in a parallel responsive grid
  instead of a vertical stack.
- `37429bf` — level-wide `LevelSourceFilesPanel` at the top of every
  expanded level, aggregating source artefacts from BOTH concerns
  AND passing rules; replaces the per-concern waterfall.
- **`4c00f67` (this morning)** — compact source-file cards. The
  level-wide panel previously embedded a full-size image / PDF /
  HTML preview in every card, which (a) auto-fired a GET on every
  level expand (the localstack PDF disposition was triggering Save
  dialogs), and (b) made each card ~600 px tall so the responsive
  grid stacked. Cards are now a single dense row — icon, label,
  filename / size / page, Open + Download buttons. Grid breakpoints
  tightened to `1 / sm:2 / lg:3 / xl:4` now that height is bounded.
  Click Open to preview in a new tab.

### 3.4 Verification audit + fixes (9 commits)

A full audit of the L1-L5 pipeline + MD-approval flow surfaced 3
blockers + 7 majors + 7 minors. Every blocker and 6 of 7 majors are
fixed:

- **B1 `475abfe`** — Phase-1 gate now requires every
  `VerificationLevelNumber` member present + passed (was silently
  passing 4/6). Cases that were previously auto-gated through with
  L1.5 or L5 missing will now correctly block.
- **B2 `879d64e`** — MD + assessor decisions carry forward across
  re-runs (new shared helper at
  `backend/app/verification/levels/_common.py::carry_forward_prior_decisions`,
  wired into all 6 orchestrators). MD doesn't have to re-approve
  the same issue after every re-trigger.
- **B3 `d8e8616`** — MD + assessor queues filter to the latest VR
  per `(case_id, level_number)` via a `func.max(created_at)`
  subquery. Stale issues from superseded VRs no longer leak into
  queues.
- **M1 `65f2a59`** — L5 `r_a09_cibil_address_match` distinguishes
  "L1 never ran" from "L1 passed". `ScoringContext` gained
  `latest_vr_by_level`; resolver returns PENDING when L1 hasn't run.
- **M2 `5a63fdc`** — `decide_issue` serialises via `SELECT … FOR
  UPDATE` on the VerificationResult row before re-reading siblings.
  Closes a TOCTOU on level promotion under concurrent MD decisions.
- **M3 `addca69`** — `trigger_level` returns 409 when a RUNNING VR
  exists for the same level within the last 5 minutes. Zombie
  RUNNING rows from crashed workers auto-expire.
- **M4 `224ad42`** — MD decide + assessor resolve endpoints now
  call `audit_svc.log_action`. Compliance trail is complete.
- **M5 `05b3ceb`** — L1.5 bureau `source_artifacts` attribution by
  party (`primary_row.artifact_id` / `co_row.artifact_id`) instead
  of positional. Legacy CaseExtraction rows with NULL artifact_id
  fall back to positional.
- **M6 `06f3dcf`** — L3 `house_scorer_failed` /
  `business_scorer_failed` now attach
  `{error_message, photos_evaluated_count, source_artifacts}`.
  Same hole on L2 `ca_analyzer_failed` plugged.

**Skipped: M7** — orphan `auto_justify_level_issues` in
`services/auto_justifier.py:251` is advertised in the final-report
gate but never called. Pick: wire it into `trigger_level` as a
post-persist pass, or delete the function. Needs a product call.

## 4. Quick verification on Ajay (do this first)

Open `http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c?tab=verification`
and click through each level. Expected behavior post-`4c00f67`:

- **Top of every level expand**: a single **Source Files (N)** panel
  with cards in a parallel grid (1 / 2 / 3 / 4 cols by viewport).
  Each card is one row tall — title + filename + Open + Download.
  Opening a case should NOT trigger any download dialogs.
- **L3 Vision specifically**: still shows the Stock Analysis +
  Photos gallery header above the Source Files panel.
- **Concerns**: each "What was checked" panel is below the
  description (not to the right) and renders structured fields per
  rule. Bureau write_off / settled / etc. concerns get the compact
  `BureauAccountRow` card. `avg_balance_vs_emi` gets the bar.
  `house_business_commute` gets the time/distance card.
- **Passing rules → click any row**: structured pass-detail card,
  not the Part-B placeholder. `cattle_health` on Ajay still shows
  "Skipped — not a dairy business (classified: service)".

If anything looks off, the most likely culprit is an HMR miss —
hard refresh (`Cmd+Shift+R`).

## 5. Next-session candidates (ordered by ROI)

| Item | Why | Rough effort |
|---|---|---|
| **L5.5 · Dedupe + TVR verification** | Design brief is ready at `docs/superpowers/specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md`. Phase 1 (dedupe parse + TVR presence) is ~1.5–2 days, fully deterministic, no extra AI cost. Phase 2 (Whisper + Opus cross-check) ~$0.10/case, ship later. | 1.5–2 days for Phase 1 |
| **M7 — auto-justifier wire-up or delete** | Currently advertised in the gate but never called. Either wire into `trigger_level` post-persist, or delete the dead path. Product call required. | 2 hrs once decided |
| **`house_living_condition` pass card ratings grid** | Today still uses a JSON pretty-print fallback (footgun in Part A §12). 5 labeled rows + 2 bullet lists. | 30 min |
| **`[CASE_SPECIFIC]` filter in L6 case-library retrieval** | One-off MD approvals leak into future prompts. | ½ day |
| **Learning Rules `md_approved_count` split — trains vs case-only** | Same integrity reason. Inflates training signal with one-offs. | 1–2 hrs |
| **Audit minors m1-m7** | Captured in `RESUME_2026_04_25_OVERNIGHT_HANDOFF.md` §3.3 (full list in agent transcript). All query-optimisation / hygiene; no correctness issues. | Half-day total |
| **Production-readiness audit** | CORS, JWT secret rotation, TLS, per-user case isolation, rate limiting, default-password rotation. Carried forward from prior handoff. | Half-day |
| **Editable numeric thresholds on Learning Rules** | Admin can suppress / annotate but can't tune values (`avg_balance_vs_emi` 1.5×, etc.). Needs `RuleOverride.parameters JSONB`. | Full day |
| **Auto-suggest "Suppress?" on high-confidence rules** | Surfaces candidates (≥10 fires, ≥90% MD-approve). | 2-3 hrs |
| **Phase 2 source-viewer bounding boxes** | `bbox` is in the contract; coord extractor pass needed. | 1-2 days |
| **Kotak (KKBK) bank-statement parser** | Still returns zero-tx PARTIAL. | 1 day |
| **Centralise 24% flat-rate EMI assumption** in L2 | Magic number; no config hook. | 1 hr |
| **Notifications bell deleted-case filter** | Bell endpoint may include deleted cases. | 20 min |
| **Migrate GCP API key** `supreme-ops-491112` → `pfl-*` | Env-var swap + enable Routes/Geocoding on new project. | 30 min |

## 6. Known limitations / gotchas

- **Docker bind-mount HMR is flaky for L5** — `docker restart
  pfl-backend` if BE changes don't stick.
- **Pre-existing FE tsc error** at
  `frontend/src/components/layout/__tests__/NotificationsBell.test.tsx:54`.
  Not yours; filter it out.
- **Carry-forward + suppressed_rules** combination is untested. If
  a case has both an MD-approved decision and a suppressed rule on
  the same level, eyeball the next re-run to confirm both invariants
  hold. (Suppressed rules don't emit new issues, so the
  carry-forward should silently no-op for those.)
- **The Next.js dev server was restarted** during the overnight
  session. PID may be stale; check `pgrep -f "next dev"` and
  re-start if needed.
- **A parallel Claude session was running** alongside the overnight
  work. Commits `6dbb75d`, `2060850`, `14e2392` came from there
  (L5 scoring + artefact-serving fixes). Fine, just means `git log`
  interleaves authors.
- **No new evidence is visible on historical L1-L5 runs** until
  they're re-triggered. The new `pass_evidence` / smart layouts
  only render once an orchestrator runs against the new code. For
  Ajay this happened in the overnight session; for any other case
  you'll need to trigger a re-run.

## 7. Spec / brief / plan inventory

Live design docs in `docs/superpowers/specs/` and plans in
`docs/superpowers/plans/`. Most recent first:

- `specs/2026-04-25-part-b-cross-level-evidence-audit-design.md` —
  Part B (cross-level evidence audit). **Shipped.**
- `specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md` — L5.5 stub
  brief. Not yet shipped; promote to a full spec when ready.
- `specs/2026-04-24-l3-visual-evidence-and-cross-level-evidence-audit-design.md` —
  Part A. **Shipped.**
- `plans/2026-04-24-l3-visual-evidence-part-a.md` — Part A's
  16-task execution plan. **Done.**
- Older specs at
  `specs/2026-04-22-l1-house-business-commute-design.md`.

## 8. Recent commit log (for orientation)

```text
4c00f67 fix(case-view): compact source-file cards — kill auto-download on render + restore parallel grid
b9fe42e docs: overnight handoff — Part B shipped end-to-end + audit-fix pass
06f3dcf fix(l3-vision): attach evidence with error_message + source_artifacts on scorer-failed paths
05b3ceb fix(l1.5-credit): attribute bureau source_artifacts by party, not by artifact-list position
224ad42 feat(audit): log MD decide + assessor resolve actions for compliance trail
addca69 fix(verification): trigger_level returns 409 if a RUNNING row exists for the same level
5a63fdc fix(verification): serialize decide_issue via SELECT FOR UPDATE to close TOCTOU on level promotion
65f2a59 fix(l5): r_a09 distinguishes "L1 never ran" from "L1 passed" — avoids silent pass
d8e8616 fix(queues): MD + assessor queues drop stale issues from superseded verification runs
879d64e fix(verification): carry forward MD + assessor decisions across re-runs
475abfe fix(gate): require every verification level present + passed, not just 4/6
aad20ca feat(l4-agreement): populate sub_step_results.pass_evidence for agreement rules
fece2c9 feat(l2-banking): populate sub_step_results.pass_evidence for all 8 L2 rules
cbe4a6f feat(l1.5-credit): populate sub_step_results.pass_evidence for status scanners + score floor + bureau + opus
655b7a7 feat(l1-address): populate sub_step_results.pass_evidence for all 6 L1 rules
d10769c feat(evidence-fe): unify dispatcher + wire new smart-layout cards on fire + pass paths
8d32c16 feat(evidence-fe): BureauAccountRow smart layout for L1.5 bureau status scanners
78779f4 feat(evidence-fe): CommuteCard smart layout for L1 rule
cbb0ce9 feat(evidence-fe): AvgBalanceVsEmiCard smart layout for L2 rule
37429bf feat(case-view): level-wide Source Files panel covers concerns + passing rules
14e2392 fix(l5): retune every rubric resolver — tighten facts check against L1-L4 outputs
2060850 fix(l5): CIBIL Address Match reconciles with L1 bureau-match outcome
6dbb75d fix(artifacts): stop auto-download on View source — inline preview by default
```

## 9. One-paragraph TL;DR

Part B (cross-level evidence audit) shipped end-to-end overnight: every
verification level now emits structured fire-path evidence and a
`sub_step_results.pass_evidence` block for every passing rule, three
new FE smart-layout cards reduce noise on the most common rule
patterns, and a level-wide `LevelSourceFilesPanel` aggregates source
artefacts from BOTH concerns and passes at the top of every level
expand. A full verification-pipeline + MD-approval audit found and
fixed 3 blockers (Phase-1 gate ignored 2/6 levels, MD overrides got
wiped on re-run, MD queues leaked stale issues) and 6 majors. Plus
this morning a follow-up fix (`4c00f67`) compacted the level-wide
source-file cards to a single dense row — eliminating both the
auto-download triggered by inline previews and the "stacked, not
parallel" layout the inline previews caused. **23 commits on
`4level-l1`, all pushed, 718 baseline tests passing, working tree
clean. Highest-ROI next move: open Ajay in the browser to confirm
`4c00f67` looks right, then start L5.5 from the design brief.**
