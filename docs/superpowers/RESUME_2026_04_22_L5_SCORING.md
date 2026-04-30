# Resume — L1.5 Credit · L5 Scoring · Final Report PDF · MD Approvals UX

> **Open a new Claude Code session in this repo and paste this file's path
> (`docs/superpowers/RESUME_2026_04_22_L5_SCORING.md`) to pick up
> exactly where this session left off.**

**Spawned:** 2026-04-22 (evening)
**Parent:** `docs/superpowers/RESUME_2026_04_22_L1_SMART_MATCH.md`
**Branch:** `4level-l1` (tip: `6044b07`)
**Status:** 6-level verification gate live end-to-end (L1 → L1.5 → L2 → L3 → L4 → L5),
Final Verdict Report PDF gated on full issue resolution, MD Approvals
rebuilt with per-case collapsible dossiers + Approve/Reject with
mitigation/rejection reason tagging for training.

---

## 1. What shipped this session

### Commits landed (newest first)

| SHA | Subject |
|---|---|
| `6044b07` | **feat(ui): red-bubble pending-issue counts on Verification + Verification 2 tabs** — user commit |
| `7efbfe0` | **feat(decisioning): skip Verification-covered steps; rename Phase 1 → Verification 2** — user commit |
| `4e52143` | fix(l5+md-approvals): section/grade summary issues · collapsible MD dossiers with at-a-glance stat pills |
| `6052399` | feat(l5): 32-point NBFC FINPAGE scoring audit + gated Final Verdict Report PDF |
| `ec986e5` | feat(md-approvals): group-by-case docket + Approve/Reject split with mitigation/rejection reasons + MD short-circuit |
| `503ab0c` | feat(l1.5): Credit history — Opus-4.7 seasoned-analyst willful-default + fraud scan |
| `20e5154` | docs(superpowers): resume notes for 4-level prior session + L1 smart-match session |
| `15b3679` | feat(ui): expandable level cards + rule catalog + Overview AI Insights + CAM in-data check + admin approvals |
| `ee8b11a` | feat(services): AutoJustifier — Sonnet self-resolve pass on verification issues with MD-precedent lookup |
| `a19570a` | feat(l3): Opus upgrade — business-type classification + service-branch stock/equipment + loan-reduction |
| `0b7628c` | feat(cam): AutoCAM expense / disposable-income / FOIR-ratio extraction + scoped right-col scan |
| `4d60f18` | feat(l1): smart-match — Haryana pincode master, Nominatim, GPS watermark, S/O relation, inline LAGR |

### Functional summary

**L0 · In-data CAM check** (Overview card)
- `CaseCamDiscrepancyCard` cross-checks SystemCam ↔ CM CAM IL ↔ Elegibilty ↔ Health Sheet on applicant name / PAN / DOB / loan amount (CRITICAL) + CIBIL / income / FOIR (WARNING with ±0.5 pct-pt tolerance).
- Clean state: green shield "all sheets agree". 9 vitest cases covering both paths.

**Overview AI Insights**
- Monthly Expense pulled from CM CAM IL `household_expense` (real-file misspelling supported: "Hosehold Expanses").
- Net Surplus = CAM disposable_income if present, else `income × (1 − FOIR) − expense`, else pending. (i) tooltip shows formula + numbers.
- Existing Obligations: count of non-closed Equifax accounts + balance; falls back to CAM EMI Obligation.
- Total EMI Load = existing + proposed; (i) tooltip shows source.
- FOIR (i) tooltip enumerates 5 CAM sources (Elegibilty / CM CAM IL / Health Sheet / SystemCam Installment% / SystemCam Overall%) + independent computed cross-check, flags any source diverging >0.5 pct-pt.

**L1.5 · Credit (new 5th level)**
- `CreditAnalyst` (Opus-4.7) with hardcoded `CREDIT_GUARDRAILS` from the ops infographic: DPD 000/030/060/090; STD/SMA-0/1/2/SUB/DBT/LSS/WO/SETTLED/CLOSED meanings; willful-default set {WO, LSS, SETTLED, DBT}; fraud set {WO, LSS}.
- 7 pure Python hard rules on both applicant + co-applicant bureau accounts + credit score. WO/LSS/SETTLED → CRITICAL; SUB/DBT/SMA → WARNING; score <500 CRITICAL, <600 WARN.
- Ajay live: **PASS · 88% match · 7✓ 1!** — only WARN is Opus wanting MD sign-off because Gordhan is NTC (score -1). $0.10 Opus cost.

**L3 · Opus upgrade**
- `BusinessPremisesScorer._TIER = "opus"`; classifies `business_type` FIRST (product_trading / service / cattle_dairy / manufacturing / mixed / other).
- `cross_check_stock_vs_loan` branches on business_type: service uses stock+equipment vs 40% floor; product_trading keeps legacy 50/100%.
- New `cross_check_loan_amount_reduction` → WARN when Opus's recommended ticket <80% of proposed.
- Frontend: `skipIf` on cattle_health hides the row entirely when business_type ≠ cattle_dairy/mixed. N/A verdict added to the ladder (gray strikethrough, excluded from match-% denominator). "Vision model" callout shows business_type + recommended loan + stock + equipment + rationale.
- Ajay barbershop live: **1 CRITICAL · 75% match · 3✓ 0! 1✗ 1 n/a** — only critical is `house_living_condition`. Stock+equipment cover 83% of loan. Recommends ₹85k.

**MD Approvals (full rebuild)**
- Grouped by case into dossiers (one section per case). Sorted worst-severity-first; within a case CRITICAL → WARNING → INFO then ASSESSOR_RESOLVED → OPEN.
- **Collapsible dossiers** with +/– toggle. First dossier auto-expands, rest collapsed. Summary pills always visible on the collapsed header: **Total · Critical · Warning · Assessor→MD · Open** (each lights up red/amber/indigo/slate when non-zero, grey otherwise).
- Two-button Approve / Reject flow replaces the radio+submit. Each button explains what kind of reason it wants BEFORE the MD commits.
- Textarea swaps to the matching prompt with 3 domain-specific example lines + live character counter (≥10 chars to submit).
- Rationale persisted with structured tag: `[MITIGATION] ...` or `[REJECTION] ...` so future ML can distinguish approve-with-mitigation from uphold-with-rejection at a glance. `[AI auto-justified @ confidence X%]` tag already used by AutoJustifier precedents.
- Backend `decide_issue` endpoint relaxed: accepts OPEN status too (MD short-circuit path). When bypassing assessor, stamps `assessor_note = "[MD short-circuit] ..."` + `assessor_resolved_at = now` so the audit trail is clean.

**L5 · Scoring (new 6th level, final audit)**
- Transcribes the ops team's `32 Point Scoring Model Draft.xlsx` into a code catalog: 32 parameters across Section A (45 pts · 13 items), B (35 · 11), C (13 · 5), D (7 · 3) = 100.
- Per-parameter resolver reads CAM / Equifax / L2 CA-analyser / L3 vision / artifact-subtype signals and returns (PASS / FAIL / PENDING / NA, score, evidence, remarks).
- Graded resolvers for DSCR (1.2+=4 / 1.0-1.2=3 / 0.9-1.0=2 / 0.75-0.9=1) and ABB ratio (1.5+=4 / 1.2-1.5=3 / 1.0-1.2=2 / <1=0).
- Manual-override hook lets an assessor fill PENDING rows without touching rule code.
- Overall grade: ≥90 A+, ≥80 A, ≥70 B, ≥60 C, <60 D.
- Engine emits per-row issues for weight-≥3 FAILs, weight-≥4 PENDINGs, PLUS summary issues: `scoring_section_{a,b,c,d}` (WARN <70%, CRITICAL <50%) and `scoring_grade` (WARN <70%, CRITICAL <60%) so the frontend logic-checks column reflects real state.
- Ajay L5 live: **9 ISSUES · 6 CRITICAL · 3 WARNING · 48/100 · grade D** — A: 66.7% · B: 37.1% · C: 38.5% · D: 0%.

**Final Verdict Report PDF**
- `report_generator.py` (ReportLab, 4-page A4):
  - Page 1 cover — loan id, names, key facts, score banner, grade, final verdict.
  - Page 2 per-level scorecard (L1 → L5) with status, issue counts, MD ✓/✗, match %, cost.
  - Page 3 32-point audit table by section with status + score + evidence + remarks.
  - Page 4 decision & override log — every `md_rationale` on record, `[MITIGATION] / [REJECTION] / [AI]` tagged.
- Glyph sanitizer: `₹` → `Rs. `, `≥` → `>=`, `→` → `->`, `✓/✗` → `[Y]/[N]` — keeps default Helvetica, no TTF bundling.
- `GET /cases/{id}/final-report` — **hard gate**: every LevelIssue across all 6 levels must be MD_APPROVED or MD_REJECTED (AutoJustifier counts as MD_APPROVED). L5 must have been run. HTTP 409 with `{error, message, blocking: [{sub_step_id, status, severity, description}]}` otherwise. Audit-logged on each download with grade + verdict.
- Final verdict computed: any BLOCKED/FAILED → REJECT; all PASSED → APPROVE; else APPROVE_WITH_CONDITIONS.
- `CaseFinalReportCard` on Overview: big "Download final report (PDF)" button. On 409 renders the full blocker list (severity · sub_step_id · description) and reminds the user that MITIGATION rationales train the auto-justifier.

### User-added commits this session (`7efbfe0`, `6044b07`)

- **Verification 2 rename**: Phase 1 tab is now labelled "Verification 2" and skips steps already covered by the 6-level gate.
- **Red-bubble pending-issue counts** on Verification + Verification 2 tabs — visual consistency with MD Approvals sidebar badge.

---

## 2. Uncommitted working tree

```
 M backend/app/main.py                          ← user edits (notifications wiring)
 M frontend/src/lib/api.ts                      ← user edits (client additions)
?? backend/app/api/routers/notifications.py     ← user added
?? backend/app/services/notifications.py        ← user added
?? .claude/                                     ← local agent config (gitignore candidate)
?? FOLLOW_UPS.md                                ← scratch notes
?? "backend/.coverage 2"                        ← pytest scratch (gitignore candidate)
```

The two notifications-related files (router + service) plus the `main.py` / `api.ts` edits look like a new **Notifications** feature the user started — not committed yet. Check with the user before finishing or committing.

---

## 3. Key code landmarks

### Backend

- `backend/app/enums.py:147` — `VerificationLevelNumber` now has 6 values: `L1_ADDRESS` → `L1_5_CREDIT` → `L2_BANKING` → `L3_VISION` → `L4_AGREEMENT` → `L5_SCORING`.
- `backend/app/verification/services/credit_analyst.py` — Opus-4.7 L1.5 service with `CREDIT_GUARDRAILS` constant.
- `backend/app/verification/levels/level_1_5_credit.py` — 7 hard rules + Opus call.
- `backend/app/verification/services/scoring_model.py` — 32-param catalog with `ParamDef` + `SECTIONS` + `build_score()`.
- `backend/app/verification/levels/level_5_scoring.py` — L5 orchestrator + section/grade summary issue emission.
- `backend/app/verification/services/report_generator.py` — ReportLab PDF + `_CHAR_REPLACEMENTS` glyph sanitizer.
- `backend/app/api/routers/verification.py:downloaded_final_report` — gated endpoint.
- `backend/app/verification/services/auto_justifier.py` — AI precedent-driven auto-resolve (not yet wired into engine post-pass loops — see §5 P0).
- `backend/alembic/versions/d5e6f7a8b9c0_l1_5_credit_enum_value.py` + `e6f7a8b9c0d1_l5_scoring_enum_value.py` — enum-add migrations using `ALTER TYPE ADD VALUE AFTER`.

### Frontend

- `frontend/src/components/cases/VerificationPanel.tsx` — `RULE_CATALOG` for all 6 levels; `RuleState` has 5 verdicts (pass/warn/fail/overridden/na); `paramsForLevel` branch per level; "Vision model" callout on L3.
- `frontend/src/components/cases/CaseInsightsCard.tsx` — Monthly Expense / Net Surplus / Existing Obligations / Total EMI Load / FOIR rows with (i) tooltips.
- `frontend/src/components/cases/CaseCamDiscrepancyCard.tsx` — L0 in-data conflict detector.
- `frontend/src/components/cases/CaseFinalReportCard.tsx` — Final Report download button with gate-blocker UX.
- `frontend/src/app/(app)/admin/approvals/page.tsx` — grouped-by-case docket; collapsible dossiers; Approve/Reject split; [MITIGATION]/[REJECTION] tagging.
- `frontend/src/lib/api.ts:cases.finalReport` — fetches the PDF through `/api/proxy`, streams Blob; on 409 surfaces typed blocker list.

---

## 4. Ajay reference case (`7bdea924-225e-4b70-9c46-2d2387fc884c`)

Use this as the golden path for any regression check.

| Level | Status | Cost | Key finding |
|---|---|---|---|
| L1 Address | BLOCKED · 60% match · 2 issues | $0.019 | ration_owner_rule CRITICAL (SULTAN not on loan) · gps_vs_aadhaar WARN (doubtful) |
| L1.5 Credit | PASS · 88% · 1 issue | $0.101 | Opus caution — Gordhan NTC |
| L2 Banking | BLOCKED · 71% · 2 issues | $0.016 | chronic_low_balance CRITICAL (ABB ₹487) · ca_narrative_concerns WARN |
| L3 Vision | BLOCKED · 75% · 1 issue · 1 n/a | $0.166 | house_living_condition CRITICAL · barbershop classification + ₹85k recommended |
| L4 Agreement | NOT RUN | — | — |
| L5 Scoring | BLOCKED · 0% · 9 issues | $0.000 | 48/100 grade D · Section B 37.1% · Section D 0% |

Overall docket count: **32 issues** (20 critical, 12 warning). Final-report endpoint returns 409 with the full blocker list until each one is MD-adjudicated.

---

## 5. Next-up work queue (priority order)

### P0 — Wire the AutoJustifier into engine post-pass loops

`backend/app/verification/services/auto_justifier.py` ships as a service but nothing calls it. Add a post-engine pass at the end of `run_level_1_address`, `run_level_1_5_credit`, `run_level_2_banking`, `run_level_3_vision`, `run_level_5_scoring` that calls `auto_justify_level_issues(session, case_id, issues, claude)` before returning. Any issue the AI clears at ≥80% confidence (CRITICAL) / ≥75% (WARN) auto-flips to MD_APPROVED with the `[AI auto-justified @ confidence X%]` tag — the MD Approvals docket and the final-report gate both treat it as cleared. Expected effect on Ajay: 2-3 of the 32 pending issues auto-resolve on re-run once a couple of [MITIGATION] precedents exist.

### P1 — Notifications feature (user-started, uncommitted)

User has scaffolding in `backend/app/api/routers/notifications.py` + `backend/app/services/notifications.py`. Ask them what the feature is (Slack? in-app badges? email?) and finish wiring. `main.py` and `api.ts` already reference it.

### P2 — Scoring-model PENDING resolvers

These parameters currently always mark PENDING because no signal reaches the resolver:

| # | Parameter | Gap |
|---|---|---|
| 2 | Business Vintage | Extract "Vintage of Business: 5 Yrs." from CM CAM IL |
| 11 | Negative Area Check | Manual BM/Credit step — consider an input form |
| 13 | Deviation Approved | Depends on all gate issues cleared + explicit BCM sign-off |
| 14/15 | Shop QR Scanned / QR Owner Match | Needs a QR-screenshot artifact subtype + OCR |
| 17 | Co-borrower Income Proof | Add `COAPP_INCOME_PROOF` artifact subtype |
| 25 | Loan Purpose | Add `system_cam.loan_purpose` extraction |
| 28 | Business Ownership Proof | Add subtype (`UDYAM_CERTIFICATE`, `SHOP_LICENCE`) |
| 30/31/32 | BCM cross-verification / TVR / Fraud call | Manual ops steps — need a checklist UI |

### P3 — Unit tests we want

- `tests/unit/test_level_5_scoring.py` — covers context building from mixed extractions, section-summary issue emission, manual override path.
- `tests/unit/test_report_generator.py` — snapshot-style check on `generate_final_report` for empty / partial / full cases; verifies PDF is valid and text-extractable.
- `tests/unit/test_credit_analyst.py` — mock Opus, verify prompt includes `CREDIT_GUARDRAILS` + WO/LSS/SETTLED terminology, verify JSON-parse fallback.
- `frontend/.../CaseFinalReportCard.test.tsx` — gate-open blocker list rendering + download success path.

### P4 — Scoring-model Opus fallback

When the deterministic resolvers return PENDING for more than N rows, call Opus with the raw artifact set and ask it to fill in as much as possible (similar to how L1.5 CreditAnalyst works). The resolver calls this "Phase 2" in code comments. Watch for cost inflation.

### P5 — Multi-case MD Approvals dogfood

The collapsible dossier UX works on single-case Ajay. It still needs a genuinely multi-case test. Ingest a second synthetic case, confirm:
- Worst-severity case sorts to top, auto-expands.
- Other cases collapsed with clean summary pills.
- Stat pills accurate when mixed open/awaiting MD/approved.
- Page perf under 20+ cases (currently renders everything; may need virtualization above ~50 cases).

### P6 — Carried from parent resume docs

- Equifax extractor improvements: capture per-account `emi_amount` + `enquiries` list with dates so L1.5 rules `enquiry_pattern_summary` + `credit_utilization_summary` can actually be evaluated.
- Pincode masters for Punjab / Delhi / UP (Haryana only today).
- Address capture on equifax + bank_statement extractors so L1's `aadhaar_vs_bureau_address` + `aadhaar_vs_bank_address` rules stop silently passing.

---

## 6. How to resume

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -5

# Stack
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 5       # bounce after any python edit

# Frontend
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Alembic (both L1.5 + L5 enum values should already be present)
docker exec pfl-postgres psql -U pfl -d pfl -c "SELECT enum_range(NULL::verification_level_number);"
#  → {L1_ADDRESS, L1_5_CREDIT, L2_BANKING, L3_VISION, L4_AGREEMENT, L5_SCORING}

# Auth
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Re-trigger L5 on Ajay
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L5_SCORING \
  | python3 -m json.tool

# Probe the report gate (should 409 with the blocker list)
curl -s -w '\nHTTP %{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/final-report | head -30

# Open in browser
open "http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c"
open "http://localhost:3000/admin/approvals"
```

Login creds: `saksham@pflfinance.com` / `Saksham123!`.

You should see:
- Overview tab: AI Insights card with expense/surplus/obligations/EMI load/FOIR rows (each with an (i) tooltip), "In-data check — CAM sheets" card showing "All sheets agree", and the Final Verdict Report card listing 10+ pending blockers.
- Verification tab: L1 Address · L1.5 Credit · L2 Banking · L3 Vision · L4 Agreement · L5 Scoring expandable level cards. L3 shows the "Vision model" callout; L5 shows section-by-section scoring.
- /admin/approvals: Single "Ajay singh with Gordhan" dossier with stat pills (Total 32 · Critical 20 · Warning 12 · Assessor→MD 0 · Open 32). Clicking collapses it to a single summary row.

---

## 7. Quirks observed this session

| Symptom | Fix |
|---|---|
| `uvicorn` in `pfl-backend` caches python imports — `docker restart pfl-backend` required after every backend edit | (same as prior resume docs) |
| Alembic enum-add migrations use `ALTER TYPE ADD VALUE AFTER` — but Postgres won't run this in a transaction with other DDL. Keep enum-add migrations single-statement. | already done in d5e6f… and e6f7a8… |
| ReportLab default Helvetica lacks ₹ / ≥ / → / ✓ glyphs — renders as junk bytes. | `_CHAR_REPLACEMENTS` sanitizer in `report_generator.py` swaps to ASCII equivalents. |
| Literal `\u2192` strings in JSX text nodes render as backslash-u-2192 (escape sequences only work inside JS strings). | Use actual characters (→, —, ½) or wrap in `{'\u2192'}`. |
| First-click-doesn't-collapse bug on the MD dossier: `!undefined === true` keeps an auto-expanded state expanded. | Fixed — `toggleCase(id, currentlyExpanded)` now passes the effective state. |
| RULE_CATALOG rules show PASS when no backend issue matches their sub_step_id, even if the level is logically failing. | Fixed in L5 by having the engine emit `scoring_section_{a,b,c,d}` + `scoring_grade` summary issues. |
| Final-report 409 body shape: `{error, message, blocking: [...]}`. FastAPI's default 409 returns `{detail: {...}}` — so we return JSONResponse manually to keep the shape flat. | Intentional; `CaseFinalReportCard` relies on this flat shape. |

---

## 8. When you finish the next chunk

1. Commit with focused messages (mirror the `feat(l*): ...` style from this session).
2. Update §1 status table + §2 uncommitted list + §5 priority queue in a **new** `RESUME_*.md` (don't overwrite this one).
3. If AutoJustifier wiring lands, add integration tests that simulate a precedent-rich case and verify auto-clear at ≥80% confidence.
4. Append SHAs + a one-line summary so the next reader can diff forward.
