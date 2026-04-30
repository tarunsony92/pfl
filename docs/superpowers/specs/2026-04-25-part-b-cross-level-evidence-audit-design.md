# Part B — Cross-level evidence audit + pass_evidence + smart layouts

**Date:** 2026-04-25
**Branch:** `4level-l1` (continuing from Part A, HEAD `ce18aee`)
**Owner:** saksham@pflfinance.com
**Status:** Draft — supersedes the Part A spec's §6 table (which had factually incorrect field names and fire conditions per spec-review iteration 1).

## 1. Motivation

After Part A, L3 is fully wired: the "What was checked" panel is rich on every concern, the click-to-expand on passing rules renders dedicated L3 cards. Every other level lags behind:

- L1.5 status scanners (write_off / loss / settled / substandard / doubtful / sma) emit **no evidence themselves** — the orchestrator only attaches `{party, accounts_matched}`. The MD sees a one-line description on each concern and nothing structured.
- Passing rules on L1 / L1.5 / L2 / L4 click-to-expand currently show the "No additional pass-detail available yet" placeholder because `sub_step_results.pass_evidence` is L3-only.
- A few common-pattern smart layouts (avg balance vs EMI bar, commute distance/time card, bureau status-account compact row) would reduce cognitive load on recurring issue shapes.

Part B closes these gaps across L1, L1.5, L2, L4. L5 is already rich from prior work; no changes there.

## 2. User-visible outcome

After Part B ships:

- **Fire paths everywhere get a meaningful "What was checked" panel.** No concern in L1.5 / L1 / L2 / L4 shows a sparse `{party, accounts_matched}` grid. Every concern carries rule-relevant evidence the MD can scan at a glance.
- **Click-to-expand on every level's passing rules renders a real structured detail card**, not the Part-B placeholder text. For each rule, the FE either dispatches to a level-specific pass card or falls back to the existing `IssueEvidencePanel` key-value grid.
- Three new smart layouts kick in where they add clarity:
  - `avg_balance_vs_emi` — a visual balance / EMI / multiplier bar.
  - `house_business_commute` — compact travel-minutes + distance card with judge-verdict badge.
  - Bureau status-account rows (write_off, loss, settled, substandard, doubtful, sma) — a compact "worst account" line with lender + status + opened date pulled from the real Equifax account shape.

## 3. Non-goals

- Changing any threshold, severity, gate, decisioning, scoring, or upload flow.
- Adding fields to the bureau scorer output (e.g. `sanctioned_amount`, `overdue_amount`) that don't exist today. Work with the real account dict keys only.
- Refactoring `addresses_match` to return a numeric score.
- Adding distance logic to `cross_check_business_gps_present` (spec reviewer confirmed the function only fires on missing coords — leave it that way).
- Backfilling historical cases. Forward-only — old runs get the new display on re-run.
- L3 / L5 evidence — both already rich.

## 4. Data & contract changes

### 4.1 Evidence-enrichment table (fire paths)

Evidence keys listed below are APPENDED to whatever the orchestrator already attaches. Nothing is removed; every listed key is **known to be in scope** at the cross-check's call-site per the 2026-04-25 audit.

#### L1 · Address

| sub_step_id | Evidence keys to add | Notes |
|---|---|---|
| `applicant_coapp_address_match` | `match_threshold: 0.85` (the `FUZZY_MATCH_THRESHOLD` constant in the module) | Existing `{applicant_address, co_applicant_address}` stays. |
| `gps_vs_aadhaar` | _no change_ | Already rich via `gps_match.to_dict()`. |
| `ration_owner_rule` | _no change_ | Already rich — six-path evidence dicts. |
| `business_visit_gps` | `photos_tried_count: int` (the number of BUSINESS_PREMISES_PHOTO artifacts the orchestrator tried before giving up) | Today the function returns `{}`; orchestrator attaches `source_artifacts`. Add the count so the MD knows whether "0 photos" or "5 photos but none had GPS." |
| `house_business_commute` | `threshold_min: 30.0` (the hardcoded over-commute cap) | Existing `{travel_minutes, distance_km, dm_status, judge_verdict, judge_attempted}` stays. |
| `aadhaar_vs_bureau_address` / `aadhaar_vs_bank_address` | `match_threshold: 0.85` | Existing `{aadhaar_address, bureau_addresses\|bank_addresses}` stays. No numeric score — the real `addresses_match` helper returns bool. |

#### L1.5 · Credit

Applicant scanners (and their `coapp_*` mirrors share the same shape via orchestrator re-tag):

| sub_step_id | Evidence keys to add | Notes |
|---|---|---|
| `credit_write_off` / `coapp_*` | `statuses_seen: list[str]` (raw status strings of matched accounts), `worst_account: {institution, status, date_opened, balance, type, product_type}` | Matches the real Equifax schema. Fixture variant's alternate keys (`lender`, `opened`) get normalised in the helper. |
| `credit_loss` / `coapp_*` | Same shape as write_off | |
| `credit_settled` / `coapp_*` | Same | |
| `credit_substandard` / `coapp_*` | Same | |
| `credit_doubtful` / `coapp_*` | Same | |
| `credit_sma` / `coapp_*` | Same | |
| `credit_score_floor` / `coapp_credit_score_floor` | `credit_score: int`, `threshold_critical: 680`, `threshold_warning: 700`, `band: "crit"\|"warn"` | Orchestrator's `{party, accounts_matched}` stays. |
| `bureau_report_missing` (inline) | `expected_subtype: "EQUIFAX_HTML"`, `equifax_rows_found: 0` | |
| `credit_analyst_failed` (inline) | `error_message: str` | `model_used` / `cost_usd` are NOT in scope on failure per audit — do not promise. |
| `opus_credit_verdict` | _no change_ | Already rich. |

#### L2 · Banking

L2's orchestrator overwrites `iss["evidence"]` with the entire `ca_data` dump (minus `usage`) on every cross-check emission, so fire-path evidence is already rich. Only meta-emitters need enrichment:

| sub_step_id | Evidence keys to add | Notes |
|---|---|---|
| `bank_statement_missing` (inline) | `expected_subtype: "BANK_STATEMENT_PDF"`, `tx_line_count: 0` | Already attaches `source_artifacts` if a failed-parse bank_art exists. |
| `ca_analyzer_failed` (inline) | `error_message: str` | `model_used` / `cost_usd` NOT in scope on failure. |
| Every `cross_check_*` in L2 | _no change_ | Orchestrator dump already covers it. Smart layouts (§4.3) reshape the presentation, not the evidence shape. |

#### L4 · Agreement

L4's orchestrator pattern mirrors L2 — dumps `res.data` on fire-path issues. Meta-emitters only:

| sub_step_id | Evidence keys to add | Notes |
|---|---|---|
| `loan_agreement_missing` (inline) | `expected_subtypes: ["LAGR", "LOAN_AGREEMENT", "LAPP", "DPN"]` | |
| `loan_agreement_scan_failed` (inline) | `error_message: str`, `artifact_id: str` | `model_used` / `cost_usd` NOT in scope on failure. |
| Every `cross_check_*` in L4 | _no change_ | Orchestrator dump already covers it. |

### 4.2 `pass_evidence` schema per level

`sub_step_results.pass_evidence` is a dict keyed by rule `sub_step_id`. Part A established the contract for L3. Part B extends it to L1 / L1.5 / L2 / L4. The dispatcher is already in place (`L3PassDetailDispatcher`); when it encounters an unknown `sub_step_id`, it renders the existing "No pass-detail" fallback. New level-specific cards are §4.3.

Key naming rule (caught as a Part A footgun): **the pass_evidence key MUST match the rule's `sub_step_id` in `RULE_CATALOG` exactly**.

#### L1 — pass_evidence keys

| sub_step_id | Payload |
|---|---|
| `applicant_coapp_address_match` | `{applicant_address, co_applicant_address, match_threshold: 0.85, verdict: "match"}` |
| `gps_vs_aadhaar` | Full `gps_match.to_dict()` + `applicant_aadhaar_address`, `gps_derived_address`, `gps_coords` |
| `ration_owner_rule` | `{bill_owner, bill_father_or_husband, applicant_name, co_applicant_name, verdict: "clean" \| "owner_is_party"}` |
| `business_visit_gps` | `{business_gps_coords: [lat, lng], photos_tried_count: int}` |
| `house_business_commute` | `{travel_minutes, distance_km, dm_status: "ok", threshold_min: 30.0, under_threshold: True}` |
| `aadhaar_vs_bureau_address` / `aadhaar_vs_bank_address` | `{aadhaar_address, bureau_addresses \| bank_addresses, match_threshold: 0.85, verdict: "matched"}` |

#### L1.5 — pass_evidence keys

| sub_step_id | Payload |
|---|---|
| Every status scanner (`credit_write_off`, …, `credit_sma`, `coapp_*` mirrors) | `{party, accounts_examined: int, statuses_clean: True}` |
| `credit_score_floor` / `coapp_credit_score_floor` | `{party, credit_score, threshold_critical: 680, threshold_warning: 700}` |
| `bureau_report_missing` | `{expected_subtype, equifax_rows_found: int (≥1)}` |
| `opus_credit_verdict` | The full `opus_evidence` dict (same shape Part A already emits on fire); applicant + co-applicant block verdicts, concerns, positives, per-party credit scores + narratives |

#### L2 — pass_evidence keys

Every rule gets the slice of `ca_data` that's relevant to it — mirrors the orchestrator's fire-path behavior but on the pass side:

| sub_step_id | Payload |
|---|---|
| `bank_statement_missing` | `{extraction_status: "ok", tx_line_count: int}` |
| `nach_bounces` | `{nach_bounce_count: 0, nach_bounces: []}` |
| `avg_balance_vs_emi` | `{avg_monthly_balance_inr, proposed_emi_inr, multiplier: 1.5, ratio}` — the same fields used by the new smart-layout card |
| `credits_vs_declared_income` | `{three_month_credit_sum_inr, declared_monthly_income_inr, floor_ratio: 0.50, ratio}` |
| `single_payer_concentration` | `{distinct_credit_payers, declared_monthly_income_inr, min_income_for_rule_inr: 15000}` |
| `impulsive_debit_overspend` | `{impulsive_debit_total_inr, declared_monthly_income_inr}` |
| `chronic_low_balance` | `{avg_monthly_balance_inr, min_floor_inr: 1000}` |
| `ca_narrative_concerns` | `{ca_concerns: [], ca_positives, overall_verdict: "clean"}` |

#### L4 — pass_evidence keys

| sub_step_id | Payload |
|---|---|
| `loan_agreement_missing` | `{agreement_filename, artifact_id}` |
| `loan_agreement_annexure` | `{annexure_present: True, annexure_page_hint}` |
| `hypothecation_clause` | `{hypothecation_clause_present: True}` |
| `asset_annexure_empty` | `{asset_count: int (≥1), assets: [...]}` |
| `loan_agreement_scan_failed` | not populated (this only fires on error) |

### 4.3 New FE smart layouts

Three compact cards, registered in the `IssueEvidencePanel` (fire path) AND the pass-detail dispatcher (pass path). Each lives in `frontend/src/components/cases/evidence/*.tsx`.

| Component | Triggered by | Renders |
|---|---|---|
| `AvgBalanceVsEmiCard` | `sub_step_id === "avg_balance_vs_emi"` | Horizontal stacked bar: avg balance segment vs required `proposed_emi × multiplier` segment, tinted by pass/fail. Labels with ₹ values. Small "multiplier 1.5×" chip below. |
| `CommuteCard` | `sub_step_id === "house_business_commute"` | Two-row mini: row 1 travel time + distance + dm_status pill; row 2 judge verdict (if present) with severity colour. |
| `BureauAccountRow` | sub_step_id ∈ {`credit_write_off`, `credit_loss`, `credit_settled`, `credit_substandard`, `credit_doubtful`, `credit_sma`, `coapp_*` mirrors} | Compact table: institution, status, opened, balance. Uses `worst_account` (from §4.1) first, falls back to listing the first 3 of `statuses_seen`. |

The existing generic `IssueEvidencePanel` key/value grid stays for every other `sub_step_id`.

## 5. Implementation plan — three phases, each independently mergeable

### Phase 5.1 — Evidence enrichment (backend, fire paths)

**One commit per level. Three commits.**

- **Commit B1** — L1.5 scanners + meta-emitters. `cross_check_write_off` / `loss` / `settled` / `substandard` / `doubtful` / `sma` gain `statuses_seen`, `worst_account` keys. `cross_check_credit_score` gains `{credit_score, threshold_critical, threshold_warning, band}`. Inline `bureau_report_missing` and `credit_analyst_failed` dicts gain their respective keys. Existing TDD patterns in `test_verification_level_1_5_credit.py` + the co-app mirror plumbing handle the co-app variants for free.
- **Commit B2** — L1 three touched rules. `applicant_coapp_address_match`, `business_visit_gps`, `house_business_commute`, `aadhaar_vs_bureau_address`, `aadhaar_vs_bank_address` — each gains its single threshold constant or count. Update `test_verification_level_1_address.py`.
- **Commit B3** — L2 + L4 meta-emitters. Four small enrichments: `bank_statement_missing`, `ca_analyzer_failed`, `loan_agreement_missing`, `loan_agreement_scan_failed`. Update both levels' test modules.

### Phase 5.2 — `pass_evidence` population (backend)

**One commit per level. Four commits.**

- **Commit B4** — `build_pass_evidence_l1` helper + orchestrator wire-up in `level_1_address.py`. Populates `sub_step_results.pass_evidence` for the 6 L1 rules (excluding fired ones per the Part A contract). Unit tests.
- **Commit B5** — Same for L1.5. The status scanners get a single-shape entry per rule (`accounts_examined` is the length of the account list at the time of scan).
- **Commit B6** — Same for L2. Keys slice `ca_data` per rule (see §4.2 table).
- **Commit B7** — Same for L4. Slices `res.data` per rule.

Each commit pattern mirrors Part A's `build_pass_evidence` in `level_3_vision.py`.

### Phase 5.3 — FE smart layouts

**One commit per component + one dispatcher-wiring commit. Four commits.**

- **Commit B8** — `AvgBalanceVsEmiCard` component. Lives in `frontend/src/components/cases/evidence/`. Sized to fit inside both `IssueEvidencePanel`'s right column and the pass-detail dispatcher's body.
- **Commit B9** — `CommuteCard` component.
- **Commit B10** — `BureauAccountRow` component.
- **Commit B11** — Wire all three into the `IssueEvidencePanel` smart-layout switch and the pass-detail dispatcher (extend `L3PassDetailDispatcher` → rename to a neutral `PassDetailDispatcher` that handles every level, OR keep L3-specific and add a separate dispatcher per level — decide during implementation based on how distinct the cards are).

### Phase gates

- Each phase green-baseline on merge (`poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q`).
- Phase 5.1 ships on its own — no dependency on 5.2 or 5.3.
- Phase 5.2 depends on 5.1's enriched evidence keys (so pass_evidence references the same field names).
- Phase 5.3 depends on 5.1 (it consumes the enriched fire-path evidence) and 5.2 (it consumes pass_evidence). Ship after both.

**Total: 11 commits across 3 phases.**

## 6. Testing

- **Unit** — for every `cross_check_*` function whose evidence we enrich, add a test asserting the new keys are present on fire, and that the dict is unchanged on no-fire.
- **Unit — schema-drift guards** — For `build_pass_evidence_l1 / l1_5 / l2 / l4` helpers, lock the key set via an `EXPECTED_KEYS` set assertion (same pattern Part A used on `build_stock_analysis`).
- **Integration** — each level's orchestrator test asserts `sub_step_results.pass_evidence` is populated on a passing case.
- **Frontend** — manual smoke against Ajay's case:
  - Every L1.5 passing rule click-to-expand now shows a real card, not the placeholder.
  - `avg_balance_vs_emi` pass (if applicable in the current Ajay state) shows the bar.
  - A bureau write_off/loss/settled concern (simulate by seeding if none fire naturally) shows the compact account row.

## 7. Risks / open questions

- **Co-app evidence duplication** — L1.5's co-app loop re-tags issues via string replacement. The new evidence keys on `cross_check_write_off` etc. naturally flow through the same loop. Verify no key conflicts (especially `party`).
- **Bureau account schema divergence** — real Equifax emits `institution, status, date_opened, balance, type, product_type`. Fixture emits `lender, opened, balance, status, type`. The `_format_account_refs` helper normalises to the old pair; the new `worst_account` dict should normalise too. If the two schemas coexist in production data, add a small accessor function.
- **Dispatcher generalisation** — renaming `L3PassDetailDispatcher` to `PassDetailDispatcher` and giving it non-L3 cases is an additive change but it touches the filename. Decide whether to rename (cleaner) or just import both side-by-side (avoids a rename churn).
- **Pass-evidence on MD-overridden rules** — a rule that fired but was MD-overridden still shows up in `PassingRulesPanel` today. Does it need a pass_evidence entry? Current behaviour: the FE reads `LevelIssue.evidence` for overridden rules (which has the fire-time evidence). Preserve that; don't write an `overridden` branch into `pass_evidence` unless a gap surfaces.
- **Ajay's current state** — some L2 rules fire as critical on Ajay (3 issues · 2 critical · 1 warning). Pass_evidence for those rules is absent from Ajay's case by design. Testing pass-evidence paths needs either a seeded clean case or the canned test fixtures.

## 8. Rollout

Single branch on top of `4level-l1` → PR → `main`. All three phases land on the same PR unless the reviewer pushes back; the phase-by-phase commit structure keeps review tractable.

## 9. Parking lot (do NOT implement in Part B)

- Per-rule suppression UX improvements.
- Cross-level `evidence` persistence on MD-overridden issues for learning-loop training signal.
- Scorer-level confidence thresholds for the vision scorer (parked in Part A §12).
- 24% flat-rate EMI assumption centralisation in L2.
- `house_living_condition` pass card proper ratings grid (Part A footgun).
- Map pin + geocoded subtitle on the L3 lightbox.
- L5.5 Dedupe + TVR verification (its own brief exists).
