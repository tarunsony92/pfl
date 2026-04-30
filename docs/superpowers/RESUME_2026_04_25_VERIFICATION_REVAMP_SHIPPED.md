# Resume — 2026-04-25 (verification UI revamp shipped end-to-end)

Pick up here next session. Continues from
`RESUME_2026_04_25_NEW_SESSION.md`.

## 1. Where we are

- **Branch:** `4level-l1` · all commits pushed
- **HEAD:** `8de8881` · `feat(l5): unified 32-rubric audit table replaces issue/pass split`
- **Open PR:** [#1](https://github.com/saksham7g1/pfl-credit-system/pull/1) (5 new commits since last handoff)
- **Working tree:** clean
- **Backend baseline:** **718 passing** — no BE changes in this session
- **Frontend tsc:** clean except the pre-existing `NotificationsBell.test.tsx:54` you can ignore
- **Live case:** Ajay singh · loan `10006079` · `7bdea924-225e-4b70-9c46-2d2387fc884c`
- **Login:** `saksham@pflfinance.com` / `Saksham123!`

## 2. Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -8

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 8

# Frontend dev server
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Sanity — backend health
curl -s -o /dev/null -w "health: %{http_code}\n" http://localhost:8000/health

# Sanity — Ajay's L5 carries the full rubric tree
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L5_SCORING" \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
sc=(d.get('result') or {}).get('sub_step_results',{}).get('scoring',{})
print('grade:',sc.get('grade'),'overall:',sc.get('overall_pct'))
print('sections:',[(s.get('section_id'),f\"{len(s.get('rows') or [])} rows\") for s in sc.get('sections') or []])
"
```

## 3. What just shipped (5 commits)

The full verification UI revamp from
`~/.claude/plans/this-is-the-kinf-piped-pumpkin.md`. Every concern
and every passing rule on every level (L1, L1.5, L2, L3, L4, L5)
now renders the same grammar: claim left, source right, verdict pill
at top, "Description of issue" subsection, inline image/PDF preview by
default. A 30-year underwriter walks the same shell on every level.

### 3.1 PR1 — Foundation + L1 + L1.5 (`f169c64`)

- New `evidence/` modules: `EvidenceTwoColumn.tsx` (60/40 ≥md, 55/45
  ≥xl, header bar with verdict pill + headline), `_format.ts`
  (helpers + `useResolvedArtifacts` SWR hook), `registry.ts` (single
  rule→card map for both fire and pass paths), `SourceArtifactCard.tsx`
  (extracted from `VerificationPanel.tsx`).
- 8 new smart cards: `GpsVsAadhaarCard`, `RationOwnerCard`,
  `AddressMatchCard` (covers 3 rules), `BusinessGpsCard`,
  `CreditScoreFloorCard` (applicant + co-app), `BureauReportMissingCard`,
  `OpusCreditVerdictCard`, `BureauWorstCaseStrip` (top-of-L1.5 per-party
  roll-up: "Applicant clean · Co-applicant clean").
- `PassDetailDispatcher.tsx` rewired through registry + takes `caseId`
  prop + wraps every card in `EvidenceTwoColumn`.
- `IssueEvidencePanel` refactored to the same pattern; `LevelSourceFilesPanel`
  + dead `IssueSourceFilesInline` deleted (each rule's right card carries
  its own source now, the aggregate is redundant noise).
- `VerificationPanel.tsx` shrunk 17% (~4018 → ~3344 lines).

### 3.2 PR2 — L2 + L4 + inline source viewer (`f3e4dd4`)

- 7 L2 cards: `BankStatementMissingCard`, `NachBouncesCard` (txn-level
  table), `CreditsVsIncomeCard` (formula spelled out, ratio %),
  `SinglePayerConcentrationCard`, `ImpulsiveDebitCard`, `ChronicLowBalanceCard`,
  `CaNarrativeCard` (Concerns ↔ Positives stacked tabular blocks +
  verdict pill).
- 4 L4 cards: `LoanAgreementMissingCard`, `AnnexurePresenceCard` (page-hint
  deep-link headline), `HypothecationClauseCard`, `AssetAnnexureCard`
  (assets table).
- **`SourceArtifactCard` upgrade — every source card now opens an
  inline viewer by default** (image inline / PDF or HTML iframe with
  `loading="lazy"`). PDFs deep-link to `#page=N` when the evidence
  carries one (annexure_page_hint, etc.) so opening the agreement
  source lands the viewer on the correct page.

### 3.3 Description-in-panel fix (`0a8d440`)

The new inline source viewer made the right column tall enough that
the LEFT column had spare space. The issue narrative used to render
as a separate paragraph above the panel, duplicating the row preview.
Now `EvidenceTwoColumn` accepts an optional `description` prop and
renders it as a "DESCRIPTION OF ISSUE" subsection at the top of the
LEFT column. `IssueRow` stops rendering the duplicate `<p>` and
clamps the closed-row preview to 2 lines.

### 3.4 PR3 — L3 + L5 overview + L6 declutter (`af87dfc`)

- `L3PerItemTablePlaceholder.tsx` — empty card stating "Per-item stock
  breakdown · coming in Phase 2" sitting below the L3 stock-analysis
  + photo gallery split. Communicates the deferred BE work explicitly.
- `L5ScoringOverviewStrip.tsx` — top-of-L5 grade pill + overall pct +
  EB verdict + per-section bars (mirror of `BureauWorstCaseStrip`
  pattern). L5 issues now route through `EvidenceTwoColumn` so they
  get the same shell as every other level.
- `DecisioningPanel` (L6) restructure:
  - `LevelStatusRow` under the verdict hero — 6 mini-tiles (L1, L1.5,
    L2, L3, L4, L5) with click-to-scroll-and-flash to the
    corresponding level expand.
  - Conditions / Risk Summary / Pros-Cons / Deviations wrapped in a
    native `<details>` `CollapsibleSection`. Conditions open by
    default (actionable); the rest closed by default.
- `LevelCard` root gains `id="level-{LEVEL}"` + `scroll-mt-4` so the
  L6 tiles can scroll-target the level expand.

### 3.5 L5 unified rubric table (`8de8881`)

- New `L5ScoringRubricTable.tsx` renders all 32 rubric rows in one
  table grouped by section. Each row clickable to expand inline with
  resolver evidence (Section / Role / Expected / Evidence / Remarks)
  on the left + source artefacts on the right inside the standard
  `EvidenceTwoColumn` shell.
- Section groups auto-expand if any row in them is non-PASS so the
  eye lands on failures first; clean sections collapse.
- Suppressed rules (`sub_step_results.suppressed_rules`) render with
  strikethrough + "suppressed by admin" caption — never silently
  dropped.
- `LevelCard` L5-specific wiring: keeps `IssuesStrip` below for the
  resolve/decide workflow, hides `PassingRulesPanel` (rubric covers
  passes) and `ExtractionDetailsPanel` (overview strip covers params).

## 4. Quick verification on Ajay (do this first)

Open
`http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c?tab=verification`
and click through each level. Expected behaviour:

- **L1 → click any concern** → "WHAT WAS CHECKED · FAIL" panel with
  "Description of issue" subsection on the LEFT, structured fields
  below (e.g. address pair, bill-vs-loan-parties), Source files (N) on
  the RIGHT each with **inline preview by default** + Open / Download.
- **L1.5 → expand** → "Bureau worst-case roll-up" strip at top showing
  "Applicant clean · Co-applicant clean".
- **L2 → click `ca_narrative_concerns`** → tabular Concerns(N) +
  Positives(N) bullet blocks on left, bank-statement source preview
  on right, "N concerns · N positives" headline at the top.
- **L3 → expand** → existing stock-analysis card + photo gallery + a
  dashed "PHASE 2 · Per-item stock breakdown · coming" card below.
- **L4 → click `loan_agreement_annexure`** if it fires → "page hint N"
  headline; the agreement PDF opens with `#page={N}` fragment so the
  built-in PDF viewer jumps to the page.
- **L5 → expand** → SCORING OVERVIEW strip (grade pill, overall pct,
  per-section bars) + 32-RUBRIC AUDIT table grouped by section, click
  any row to expand the resolver detail.
- **L6 → expand** → 6-tile LevelStatusRow under the verdict hero,
  click a tile to scroll-and-flash the corresponding level expand;
  Conditions section open, Risk Summary / Pros-Cons / Deviations
  collapsed.

If anything looks off, hard refresh (`Cmd+Shift+R`) to clear HMR
state.

## 5. Next-session candidates (ordered by ROI)

| Item | Why | Rough effort |
|---|---|---|
| **Phase 2 evidence enrichment** | Design brief at `docs/superpowers/specs/2026-04-25-phase-2-evidence-enrichment-design-brief.md`. 5 items totalling ~10.5 days of backend work; each plugs new structured fields into the FE shell that's already built. **Suggested order: L4 per-asset anchors (1d) → L5 per-rubric source_artifacts (1d) → L2 txn-anchored CA (2d) → in-app PDF viewer with bbox (2.5d) → L3 per-item stock + crops (4d).** | 10.5 days BE + small FE follow-ons |
| **L5.5 · Dedupe + TVR verification** | Carried forward — design brief at `specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md`. Phase 1 (~1.5–2 days) is fully deterministic, no extra AI cost. | 1.5–2 days |
| **L5 Section D data anomaly investigation** | On Ajay's case the L5 audit shows Section D "8/7 · 0%" — denominator/percentage mismatch. Likely a backend data bug in `scoring_model.py` or its resolvers; the new rubric table surfaces it but doesn't cause it. | 1–2 hrs |
| **M7 — auto-justifier wire-up or delete** | Carried forward from prior resume. `auto_justify_level_issues` advertised in the gate but never called. Product call required. | 2 hrs |
| **`house_living_condition` pass card ratings grid** | Carried forward. Today still uses a JSON pretty-print fallback. 5 labeled rows + 2 bullet lists. | 30 min |
| **`[CASE_SPECIFIC]` filter in L6 case-library retrieval** | Carried forward. One-off MD approvals leak into future prompts. | ½ day |
| **Production-readiness audit** | Carried forward. CORS, JWT secret rotation, TLS, per-user case isolation, rate limiting, default-password rotation. | Half-day |
| **Notifications bell deleted-case filter** | Carried forward. Bell endpoint may include deleted cases. | 20 min |
| **Migrate GCP API key** `supreme-ops-491112` → `pfl-*` | Carried forward. Env-var swap + enable Routes/Geocoding on new project. | 30 min |

## 6. Known limitations / gotchas

- **Pre-existing FE tsc error** at
  `frontend/src/components/layout/__tests__/NotificationsBell.test.tsx:54`.
  Not new this session; filter it out.
- **L5 SC-D anomaly** flagged above. Cosmetic on the new rubric table;
  worth fixing in the scoring model.
- **Ajay's L1 / L1.5 / L2 / L4 `pass_evidence` is empty** even after
  re-runs in this session. Older Ajay state issue; doesn't affect the
  new UI shell, but means the pass-path detail dispatcher renders the
  generic key/value table on those rules until the orchestrators
  re-emit pass_evidence on a fresh run with all conditions met.
- **Inline source viewer auto-fired GETs concern** — addressed by
  `loading="lazy"` on iframes/images in `SourceArtifactCard`. With
  the level-wide aggregate panel removed in PR1, cards now stack
  vertically inside one EvidenceTwoColumn at a time, so the cumulative
  request fan-out is bounded by what's visible.
- **Carry-forward + suppressed_rules** combination still untested
  (carried forward from prior handoff).
- **Source artefact rendering depends on storage backend** —
  `download_url` is inline-disposition (works for previewing in
  browser); `attachment_url` is attachment-disposition (forces save).
  The card uses `download_url` for the inline preview + Open, falls
  back to `attachment_url` for the Download button. Localstack PDFs
  occasionally typed `application/octet-stream` may still trigger
  Save dialogs on Open — production S3 returns proper Content-Type.

## 7. Spec / brief / plan inventory

Live design docs in `docs/superpowers/specs/` and plans in
`docs/superpowers/plans/`. Most recent first:

- `specs/2026-04-25-phase-2-evidence-enrichment-design-brief.md` —
  Phase 2 backend enrichments. **Just shipped** — captures the 10.5
  days of backend work that lights up the FE shell's reserved slots.
- `specs/2026-04-25-part-b-cross-level-evidence-audit-design.md` —
  Part B (cross-level evidence audit). **Shipped previously.**
- `specs/2026-04-24-l5.5-dedupe-tvr-design-brief.md` — L5.5 stub
  brief. Still not yet shipped; promote to a full spec when ready.
- `specs/2026-04-24-l3-visual-evidence-and-cross-level-evidence-audit-design.md` —
  Part A. **Shipped previously.**
- Locked plan: `~/.claude/plans/this-is-the-kinf-piped-pumpkin.md` —
  the verification UI revamp plan. **Closed end-to-end this session.**

## 8. Recent commit log (for orientation)

```text
8de8881 feat(l5): unified 32-rubric audit table replaces issue/pass split
af87dfc feat(verification): L3 placeholder + L5 overview strip + L6 declutter (PR3)
0a8d440 fix(evidence): pull issue description into WHAT WAS CHECKED container
f3e4dd4 feat(evidence): L2 + L4 cards + inline source-file viewer (PR2 of revamp)
f169c64 feat(evidence): EvidenceTwoColumn primitive + L1/L1.5 smart cards (PR1 of revamp)
51a2faa docs: resume readme for next session — post-overnight + source-card fix
4c00f67 fix(case-view): compact source-file cards — kill auto-download on render + restore parallel grid
b9fe42e docs: overnight handoff — Part B shipped end-to-end + audit-fix pass
06f3dcf fix(l3-vision): attach evidence with error_message + source_artifacts on scorer-failed paths
05b3ceb fix(l1.5-credit): attribute bureau source_artifacts by party, not by artifact-list position
```

## 9. One-paragraph TL;DR

The verification UI revamp closed end-to-end this session. Every
concern and every passing rule on every level now renders inside one
`EvidenceTwoColumn` shell — claim left, source right, verdict pill
at top, "Description of issue" subsection, inline image/PDF preview by
default, source files with Open + Download (PDFs deep-linked via
`#page=N`). New per-rule smart cards (~20 of them) cover L1/L1.5/L2/L4
rules + the existing L3 cards auto-wrap through the dispatcher. L1.5
leads with a Bureau Worst-Case Roll-Up; L5 leads with a Scoring
Overview strip + a unified 32-row rubric audit table that replaces
the issue/pass split for L5; L6 decisioning leads with a 6-tile
level-status row that scrolls-and-flashes the corresponding level
above + collapsible sections for Conditions / Risk / Deviations.
`LevelSourceFilesPanel` and the dead `IssueSourceFilesInline` are
removed; `VerificationPanel.tsx` is 17% smaller than where it
started. **5 commits on `4level-l1`, all pushed, 718 baseline tests
passing, working tree clean. Highest-ROI next move: pick the cheapest
Phase 2 backend item (L4 per-asset page anchors, 1 day) to start
lighting up the FE shell's reserved slots.**
