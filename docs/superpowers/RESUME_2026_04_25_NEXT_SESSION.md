# Resume notes — 2026-04-25 handoff (after L3 Visual Evidence Part A)

Continues from
`docs/superpowers/RESUME_2026_04_24_EVENING_NEXT_SESSION.md`.
Part A of the L3 Visual Evidence design landed this session.

## 1. Where we are

- **Branch:** `4level-l1` · 16 commits ahead of origin
- **HEAD:** `581146a` · fix(l3): align pass_evidence key with rule sub_step_id (loan_amount_reduction)
- **Working tree:** clean
- **Open PR:** [#1](https://github.com/saksham7g1/pfl-credit-system/pull/1)

Baseline tests: **637 passing** (615 pre-session + 22 new from Part A).

## 2. Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -8

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 8

# Frontend dev server is already running at 127.0.0.1:3000 (pid 21876)
# If not: (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Login: saksham@pflfinance.com / Saksham123!
# Ajay case: 7bdea924-225e-4b70-9c46-2d2387fc884c

# Verify the new L3 sub_step_results shape is live:
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
print('new keys:', [k for k in ssr if k in ('visual_evidence','stock_analysis','pass_evidence')])
print('pass_evidence:', sorted((ssr.get('pass_evidence') or {}).keys()))
"
# Expect: new keys: ['visual_evidence', 'stock_analysis', 'pass_evidence']
# and pass_evidence has business_infrastructure / cattle_health /
# loan_amount_reduction / stock_vs_loan entries.
```

## 3. What landed this session (16 commits)

Grouped by workstream. See spec at
`docs/superpowers/specs/2026-04-24-l3-visual-evidence-and-cross-level-evidence-audit-design.md`
and plan at
`docs/superpowers/plans/2026-04-24-l3-visual-evidence-part-a.md`.

| Workstream | Commits | Summary |
|---|---|---|
| **L1.5 credit threshold bump + co-app mirror** (completed earlier, includes test fix from this session) | `28d87b6` · `76f6c41` · `3117852` | Thresholds 500/600 → 680/700 critical/warning. New `coapp_credit_score_floor` rule mirrors the applicant check for the co-applicant bureau pull. Stale tests aligned to the new thresholds. |
| **L5.5 design brief (stub)** | `7688c5f` | Design brief for a future L5.5 level: auto-ingest dedupe xlsx + TVR audio, presence-check + row-count-based dedupe verdict, optional Phase-2 Hindi TVR transcription via Whisper + Opus cross-check. Not implemented yet — parked until Part A stabilises. See `docs/superpowers/specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md`. |
| **L3 · cattle_health guard** | `3a5922d` · `b95ea16` | Added hard code-level guard on `cross_check_cattle_health` — fires only when `business_type ∈ {cattle_dairy, mixed}` AND `cattle_count > 0`. Previously fired on any "unhealthy" scorer emission regardless of business type; barbershops were being flagged for malnourished cattle. |
| **L3 pure helpers** | `2065f59` · `bb0d28d` · `2ba4c5d` | Three new pure functions in `level_3_vision.py`: `build_stock_analysis`, `build_visual_evidence`, `build_pass_evidence`. Each unit-tested with schema-drift guards. |
| **L3 cross_check_stock_vs_loan refactor** | `5bf458b` | Routed number-crunching through `build_stock_analysis`; no behaviour change, issue descriptions byte-for-byte identical. |
| **L3 orchestrator wire-up** | `f85ef72` | Added three top-level keys to `sub_step_results`: `visual_evidence`, `stock_analysis`, `pass_evidence`. Merged `photos_evaluated_count` onto every scorer-driven issue's evidence. Integration tests cover all three shapes end-to-end. |
| **Frontend types + helpers** | `a190493` · `865d7e0` | `L3VisualEvidence` / `L3StockAnalysis` / `L3PassEvidence` types. Shared formatters (`formatInr`, `formatPct`, `coverageTone`). |
| **L3 header components** | `0b5c6f0` · `9cd420f` · `b210203` | `L3StockAnalysisCard` (loan vs visible collateral, coverage pill, reasoning) and `L3PhotoGallery` (two `useCasePhotos` calls filtered by artifact-id, low-count warning banner, full-screen lightbox). Wired into the L3 detail view as a 55/45 xl-split header above concerns. Removed the duplicate inline photo gallery that previously lived inside each expanded concern. |
| **Click-to-expand on passing rules** | `86ac879` · `74563c5` · `581146a` | `LogicCheckRow` is now keyboard-accessible + expandable (role=button, Enter/Space toggle, chevron). Expanded body for L3 dispatches to `L3PassDetailDispatcher` → `L3StockVsLoanPassCard` (side-by-side Stock-+-Equipment vs Loan table, coverage pill, reasoning), `L3InfraPassCard` (rating + bullet list), `L3LoanRecPassCard` (proposed vs recommended with cut pill), or a cattle-N/A / JSON-pretty-print fallback. Other levels render a "Part B" placeholder. Fixup `581146a` aligned the dispatcher's `loan_amount_reduction` key with the rule catalog's sub_step_id (was wrongly `loan_amount_recommendation`). |

## 4. Functional end-to-end verification (Ajay)

Confirmed in the browser at `http://localhost:3000/cases/7bdea924-…` on L3 · Vision:

- **Header section always visible**: "Stock Analysis" card + "Photos" gallery side by side at the top, regardless of the `house_living_condition` critical concern below.
  - Stock analysis: service · barbershop, loan ₹1,00,000 vs visible collateral ₹70,000 (stock ₹5,000 + equipment ₹65,000), coverage 70%, floor 40% critical, recommended ₹1,00,000, full reasoning paragraph.
  - Photos: 5 house + 6 business thumbnails; "N uploaded · M evaluated" label per section; click thumbnail → full-screen lightbox with close button.
- **Passing rules click-to-expand**:
  - `stock_vs_loan` → side-by-side table (Visible Collateral breakdown left, Loan Amount right), emerald coverage pill, reasoning, "6 photos evaluated".
  - `business_infrastructure` → rating line + bullet list of details.
  - `loan_amount_recommendation` → proposed vs recommended (no cut on Ajay).
  - `cattle_health` (N/A) → "Skipped — not a dairy business (classified: service). Does not count toward the match %."
- **Cattle silenced**: no `cattle_health` concern fires on Ajay's service biz (guard working).
- **Other levels**: clicking any L1 / L1.5 / L2 / L4 / L5 passing rule expand shows "No additional pass-detail available yet — populated when Part B ships."

## 5. Part B backlog — cross-level evidence audit

Sketched in the spec's §12 parking lot. Next logical session:

- **L1, L1.5, L2, L4 `cross_check_*` evidence audit** — each emitter attaches a rich evidence dict, so the per-issue "What was checked" panel renders consistently (instead of the sparse `{party, accounts_matched}` many rules have today). Per-rule target schemas are in `docs/superpowers/specs/2026-04-24-l3-visual-evidence-and-cross-level-evidence-audit-design.md` §6, but those tables need re-verification — the spec reviewer flagged factual gaps (`house_business_commute` evidence keys, `business_visit_gps` fire-condition, `aadhaar_vs_bureau_address` score vs boolean) before we split Part A off. Rewrite those tables against the real code before implementing.
- **Cross-level `pass_evidence` populate** — same levels as above; fills the placeholder that currently shows on every non-L3 passing rule expand.
- **New smart layouts in `IssueEvidencePanel`** — stock_vs_loan mini-card, avg_balance_vs_emi bar, loan_amount_reduction card, commute distance/time, bureau status-account card.

## 6. Other backlog (carried forward)

- **L5.5 · Dedupe + TVR verification** — design brief ready at `docs/superpowers/specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md`. Phase 1 (presence + dedupe row-count) is 1.5–2 days; Phase 2 (Hindi Whisper transcription + Opus cross-check) is feature-flagged follow-up. Trigger: after Part B ships and the business confirms phase preference.
- **`[CASE_SPECIFIC]` filtering in L6 case-library retrieval** — still in the prior session's backlog. The precedent endpoint + AutoJustifier honour the tag; L6's whole-case similarity retrieval doesn't.
- **Learning-Rules `md_approved_count` split** — trains-vs-case-only.
- **Auto-suggest "Suppress?"** on high-confidence rules.
- **24% flat-rate EMI constant** centralisation in L2 (magic number in `estimate_proposed_emi_inr`).
- **`house_living_condition` pass card proper ratings grid** — currently JSON pretty-print (minimum viable). ~30 min work.
- **`business_type` scorer confidence threshold** — defence against Opus drift.
- Hosting / production-readiness audit, notifications bell deleted-case filter, Kotak KKBK bank-statement parser, GCP API key migration — all unchanged from prior session's backlog.

## 7. Known limitations / gotchas

- **Docker bind-mount HMR is flaky on the L5 orchestrator** — we restarted the BE container 3× this session without issue. If a BE change doesn't stick, `docker exec pfl-backend grep -c <symbol> /app/...` and check the `__pycache__`.
- **`FloorPctWarning` nullability** — service biz has a single critical floor (40%) and null warning tier; non-service has both (50% crit / 100% warn). The coverage tone helper on the FE handles both; if you add cattle_dairy-specific tiers later, revisit.
- **`NotificationsBell.test.tsx:54` pre-existing type error** stays on every tsc run. Not this session's work; carry forward.
- **`pass_evidence` key must match the rule's `sub_step_id`** — the fixup commit `581146a` caught a naming mismatch (`loan_amount_recommendation` key vs `loan_amount_reduction` rule id). When populating pass_evidence for other rules in Part B, the key MUST match the rule's sub_step_id in `RULE_CATALOG`, or the FE lookup silently falls through to the placeholder.

## 8. If you start a new session

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -8

# Read this file, then the preceding handoff for broader context.
cat docs/superpowers/RESUME_2026_04_25_NEXT_SESSION.md
cat docs/superpowers/RESUME_2026_04_24_EVENING_NEXT_SESSION.md

# Green-baseline smoke
cd backend && poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q
# Expect 637 passed.

# Next work candidate (highest ROI): kick off Part B
# — the cross-level evidence audit. Re-verify each table in §6 of
# the 2026-04-24 spec against the real code before implementing,
# since the spec reviewer flagged factual gaps there.
```

## 9. Design artefacts

- **Spec**: `docs/superpowers/specs/2026-04-24-l3-visual-evidence-and-cross-level-evidence-audit-design.md` (Part A body + Part B parking lot §12 + post-review resolution log §11).
- **Plan (executed this session)**: `docs/superpowers/plans/2026-04-24-l3-visual-evidence-part-a.md`.
- **L5.5 brief**: `docs/superpowers/specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md`.
- **Prior handoffs** (chain):
  - `docs/superpowers/RESUME_2026_04_24_EVENING_NEXT_SESSION.md`
  - `docs/superpowers/RESUME_2026_04_24_NEXT_SESSION.md`
  - `docs/superpowers/RESUME_2026_04_23_NEXT_SESSION.md`

## 10. One-paragraph TL;DR

Shipped Part A of the L3 Visual Evidence design: always-visible
Stock Analysis card + Photos gallery header on the L3 detail view
(no more clean-L3 cases with zero visibility into what the vision
scorer saw), click-to-expand on passing rules with dedicated L3
pass cards (the MD can now see the stock-vs-loan breakdown in a
side-by-side table on a passing case, not just a single-line
description), a hard code-level guard on `cross_check_cattle_health`
so non-dairy cases stop getting false cattle-malnutrition concerns,
and surfaced "photos evaluated" counts so the MD sees how many
angles Opus actually looked at. 16 commits, 637 tests green, live
on `4level-l1`, not yet pushed. **Next session: Part B — the cross-
level evidence audit for L1 / L1.5 / L2 / L4, which fills the
"Part B placeholder" copy currently showing on every non-L3
passing rule expand. Re-verify §6 tables of the 2026-04-24 spec
against real code before starting — the spec reviewer flagged
factual gaps there.**
