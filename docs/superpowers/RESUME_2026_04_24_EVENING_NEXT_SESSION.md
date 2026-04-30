# Resume notes — 2026-04-24 evening handoff

Pick up here in a fresh session. Continues from
`docs/superpowers/RESUME_2026_04_24_NEXT_SESSION.md` — that one has
the broader background (source-file viewer, level-card restructure,
admin Learning-Rules surface). This file covers just what shipped in
the afternoon / evening stretch.

## 1. Where we are

- **Branch:** `4level-l1`
- **Remote:** `https://github.com/saksham7g1/pfl-credit-system`
- **Open PR:** [#1](https://github.com/saksham7g1/pfl-credit-system/pull/1)
- **Last commit:** `a4176d5` · feat(l5-smart-layout): structured score cards for section / grade / row issues
- **Working tree:** clean, all commits pushed.

This session added 8 commits on top of the last handoff
(`0d26e27`):

```bash
git log --oneline 0d26e27..HEAD
```

## 2. Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -8

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 8

# Frontend — reuse if running
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Login: saksham@pflfinance.com / Saksham123!
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Quick sanity — L5 section issue should have the new evidence shape
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L5_SCORING" \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
for i in d['issues']:
    if i['sub_step_id'] == 'scoring_section_b':
        ev = i['evidence'] or {}
        print('keys:', sorted(ev.keys()))
"
# → should include failing_rows, section_title, source_artifacts
```

**Reference case:** Ajay singh · loan `10006079` · id
`7bdea924-225e-4b70-9c46-2d2387fc884c`. Still the only active
case. A recent L5 re-run populated the new BE evidence shape, so the
L5 smart-layout renders correctly on first open.

## 3. What landed this stretch (8 commits)

Grouped by feature.

| Area | Commits | Summary |
|---|---|---|
| **Pill copy** | `f1c322c` | "ASSESSOR RESOLVED" → "Justified · awaiting MD" on every issue-status pill. Adds a tooltip on every state explaining what it means and what moves it forward. Eliminates the "looks done but isn't" bug flagged in the earlier chat. |
| **Rule-catalog audit** | `56da11a` · `d41a26d` | Every backend-emitted `sub_step_id` now has a matching `RULE_CATALOG` entry with a friendly title + description. Newly registered: `business_visit_gps`, `house_business_commute` (L1); `bureau_report_missing` + 6× `coapp_credit_*` (L1.5); `bank_statement_missing` (L2); `loan_agreement_missing` (L4). Co-app rules carry `skipIf` on an empty `co_applicant` block so credit-invisible co-apps don't falsely count as 6 passes. |
| **Extraction-details audit** | `639daa8` · `a46fc79` | Three L1 `sub_step_results` fields and one L2 field were being persisted by the BE but never rendered as Param rows, so the MD could only see them through failing-issue descriptions. Now standalone Extraction-Details rows: `ration_bill_owner`, `ration_bill_address`, `business_derived_address` (L1), `declared_foir_pct` (L2). The L2 FOIR row is colour-graded (>60% fail · >50% warn). |
| **Case-view UX** | `b1538c1` | 7-Level Credit Pipeline summary card is now collapsible — the header chevron toggles between the full table and a one-line `✗ L1 · ✓ L1.5 · ✗ L2 · ✗ L3 · ✗ L4 · ✗ L5` glance strip. Plus: every mutation site (assessor resolve on case view · MD adjudicate on approvals · assessor resolve on queue page) now broadcasts to MD-queue + assessor-queue + every open overview / level-detail SWR key using key predicates, so badge counts and pages cross-invalidate instantly. |
| **L5 Scoring restructure** | `443eadc` (BE) · `a4176d5` (FE) | Turns L5 section / grade / per-row issues from wall-of-text prose into structured score cards. BE adds `failing_rows`, `weakest_sections`, `top_misses`, `section_title` on the issue evidence. FE renders: hero `ScoreBar` (earned / max + progress bar colour-graded by pct), "Causing the drop" (section) or "Top misses" (grade) tables of per-row cards with `#SNO`, parameter name, FAILING / PENDING pill, weight badge and reason text. Per-row `scoring_NN` issues render a compact fact card (Section · Expected · Evidence · Remarks). |

## 4. Functional end-to-end verification (Ajay)

Confirmed in the browser at `http://localhost:3000/cases/7bdea924-…`:

- **Verification tab → L1**: Passing Rules pill shows **5 pass** (was 3) — commute + business-GPS now anchored.
- **Verification tab → L1.5**: Passing Rules pill shows **14 pass** (was 8) — bureau-present + 6 co-app mirrors.
- **Verification tab → L2**: Passing Rules pill shows **5 pass** (was 4) — bank-statement-present.
- **Verification tab → L4**: Passing Rules pill shows **3 pass** (was 2) — loan-agreement-uploaded.
- **L1 Extraction Details**: 15 rows (was 12) — bill owner + bill address + biz reverse-geocode.
- **L2 Extraction Details**: new "Declared FOIR (CAM)" row reading `18.1%` in green.
- **Verification tab header**: "7-LEVEL CREDIT PIPELINE" collapses with a glance strip; expand-all / collapse-all moves into the expanded header.
- **L5 Section B**: red 13 / 35 score bar + 4-row "Causing the drop" table with severity pills + weight + reason text on the right panel.
- **Issue pill**: `gps_vs_aadhaar` on Ajay reads **JUSTIFIED · AWAITING MD** (amber), not the old generic ASSESSOR RESOLVED.

## 5. Backlog / next-session candidates

Ordered by estimated payoff.

| Ask | Why | Rough effort |
|---|---|---|
| **Wire `[CASE_SPECIFIC]` filtering into L6 `case_library_retrieval`** | The FE promises one-off MD approvals don't leak into future prompts; the precedent endpoint + AutoJustifier honour the tag, but L6's whole-case similarity retrieval does not (called out in an MD-approval Q during the session). | ½ day — add a filter step in `app/decisioning/steps/step_10_retrieval.py` that excludes cases whose decisive L-issues were all `[CASE_SPECIFIC]`. |
| **Split Learning-Rules `md_approved_count` → `approved (trains)` vs `approved (case-only)`** | Same integrity reason. The Learning Rules page currently inflates the training signal with one-offs. | 1–2 hours — two SQL counts in `/admin/rules/stats`, swap the FE card. |
| **Auto-suggest "Suppress?"** on high-confidence rules | Surfaces candidate rules (≥10 fires, ≥90% MD-approve) so the admin can act without scrolling. Called out at the end of the MD-approval Q. | 2–3 hours — new derived field in the stats endpoint + a chip on the Learning-Rules card. |
| **Phase 2 source-viewer: bounding-box highlighting** | `bbox` is already in the contract; populating it needs a per-field coord extractor pass (e.g., reusing the existing vision extractor). | 1–2 days, depending on extractor-side plumbing. |
| **Retrain loop — feed MD rationales into pre-L6 rule context** | Today only L6 (indirectly, via case library) sees MD signal. Pre-L6 cross-checks never do. Wiring the AutoJustifier into each L orchestrator is the first step; it exists but nothing calls it yet. | Multi-day design + implementation. |
| **Editable numeric thresholds** on Learning Rules | Admin can suppress / annotate a rule but can't tune threshold values (`avg_balance_vs_emi` multiplier 1.5×, `impulsive_debit_overspend` ratio, etc). | Full-day — `RuleOverride.parameters JSONB` + per-rule schema + engine plumbing. |
| **Hosting / production-readiness audit** | Carried over from the first handoff. CORS, JWT secret rotation, TLS, per-user case isolation, rate limiting, default-password rotation. | Half-day of diligence. |
| **Notifications bell** filter deleted cases | Still unaudited — bell endpoint may include deleted cases. | 20 min. |
| **Kotak (KKBK) bank-statement parser** | Still returns zero-transaction PARTIAL. Source-file viewer now cites the broken PDF so the MD can eyeball it, but the root cause persists. Spawned as a separate task previously. | 1 day. |
| **Migrate GCP API key** from `supreme-ops-491112` → dedicated `pfl-*` project | Env-var swap + enable Routes + Geocoding on the new project. | 30 min once the project is ready. |

## 6. Known limitations / gotchas

- **Docker bind-mount hot reload is flaky** for the L5 orchestrator
  — this session we had to `docker restart pfl-backend` twice and
  remove the `.pyc` cache before the new `failing_rows` code took
  effect. If a BE change doesn't seem to stick, check both
  `docker exec pfl-backend grep -c <symbol> /app/...` and the
  `__pycache__` directory.
- **Rule catalog is the single source of truth** for which rules
  show as PASS vs hide. Any NEW `sub_step_id` emitted by a backend
  `cross_check_*` needs a matching FE entry or it'll disappear
  from Passing Rules when it passes (and only show in the generic
  "Runtime issues" bucket when it fails). The audit done in commits
  `d41a26d` + `56da11a` caught every current emitter; the next
  cross-check added should also land an entry in the same PR.
- **FE evidence-hiding list** (`_HIDDEN_EVIDENCE_KEYS`) must cover
  any structured key a smart-layout already surfaces, or the same
  data shows twice (once in the smart card, once in the generic
  key/value fallback). Commit `a4176d5` added the L5 scoring keys;
  the existing hidden set covers `row`, `analyst`, `party`,
  `source_artifacts`, `usage`, `cost_usd`, `model_used`.
- **`VerificationResult.md_override_records`** is still a dead
  column — defined in the model, exported in the schema, not
  populated anywhere. The signal lives on `LevelIssue.md_rationale`.
  Safe to delete on a cleanup pass, or leave as reserved space.
- **`DecisionResult.token_usage`** (aggregate) is also read
  nowhere on the FE — the UsageSummary card computes its own from
  DecisionStep rows. Same kind of redundancy, no user-facing issue.

## 7. If you start a new session, do this first

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -8

# Read THIS file, then the preceding handoff for broader context.
cat docs/superpowers/RESUME_2026_04_24_EVENING_NEXT_SESSION.md
cat docs/superpowers/RESUME_2026_04_24_NEXT_SESSION.md

# Green-baseline smoke
cd backend && poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q
# Expect ~615 passed.

# Pick from §5. Highest ROI first two (L6 case-library CASE_SPECIFIC
# filter + Learning-Rules training-vs-case-only split) are both small
# and close the integrity gap the MD-approvals Q flagged.
```

## 8. Design artefacts + long-form specs

- L1 commute check design:
  `docs/superpowers/specs/2026-04-22-l1-house-business-commute-design.md`
- Earlier handoffs (each one continues the chain):
  `docs/superpowers/RESUME_2026_04_23_NEXT_SESSION.md`
  `docs/superpowers/RESUME_2026_04_24_NEXT_SESSION.md` (morning)
  `docs/superpowers/RESUME_2026_04_24_EVENING_NEXT_SESSION.md` (this file)
- Prior: `docs/superpowers/RESUME_2026_04_22_*`.

## 9. One-paragraph TL;DR

Session aligned the FE rule catalog and extraction-details lists
exhaustively with what the backend is actually emitting (five
rule-catalog gaps + four extraction-row gaps fixed, plus the
`ASSESSOR RESOLVED` → `Justified · awaiting MD` pill rename that was
misleading assessors into thinking the gate had cleared). Made the
7-Level pipeline summary collapsible with a one-line status glance
and wired **every** issue-mutation path to cross-invalidate
MD-queue / assessor-queue / every open case view through SWR key
predicates, so badge counts and screens update instantly. And
replaced the L5 scoring wall-of-text with structured score bars +
typed per-row tables backed by a new evidence shape on the
backend. **Next session: close the MD-approval integrity gap —
`[CASE_SPECIFIC]` filtering in L6 case-library retrieval and in the
Learning-Rules `md_approved_count` display.**
