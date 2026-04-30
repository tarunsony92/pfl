# L3 always-visible visual evidence + cross-level `evidence` audit

**Date:** 2026-04-24
**Branch:** `4level-l1`
**Owner:** saksham@pflfinance.com
**Status:** Draft — post spec-review-1 revisions

## 1. Motivation

Three gaps in the verification UI surfaced in the evening session:

1. **L3 photos and stock analysis vanish when the level passes.** The MD
   reviewing a clean L3 case has no way to eyeball the house / business
   photos or the stock-value vs loan calculation — they are only
   attached to the issue `evidence` payloads, so they disappear the
   moment the concern resolves. This makes MDs quietly nervous about
   clean L3s and pushes them to open the raw artifact list to sanity
   check.
2. **`cattle_health` fires on non-dairy cases.** `cross_check_cattle_health`
   at `level_3_vision.py:206` fires whenever the scorer emits
   `cattle_health == "unhealthy"`, with no guard on `business_type`.
   The scorer's prompt says non-dairy businesses MUST return
   `"not_applicable"`, but Opus can disobey. Result: a barbershop
   with no cattle visible in any photo can still get flagged for
   unhealthy cattle. Needs a hard code-level guard.
3. **"What was checked" is sparse on most concerns.** The per-issue
   right-column panel (`IssueEvidencePanel`) already renders any
   structured evidence attached to an issue — but most `cross_check_*`
   emitters outside the Opus-powered ones don't populate anything
   beyond `{party, accounts_matched}`. Result: `house_living_condition`
   looks rich, but `stock_vs_loan`, `avg_balance_vs_emi`,
   `gps_vs_aadhaar` render as one-line descriptions with no structured
   "cause and checks" the MD can scan at a glance.

This spec splits the work into two PRs:

- **Part A (this spec)** — everything L3-only: the always-visible
  visual-evidence panel, the `cattle_health` business-type guard,
  surfacing the multi-angle photo-count in evidence, and the
  `stock_analysis` block on `sub_step_results`.
- **Part B (separate follow-up spec)** — cross-level `evidence` audit
  across L1, L1.5, L2, L4. Sketched in §12 here so Part A doesn't
  accidentally foreclose options; the dedicated spec will live at
  `docs/superpowers/specs/2026-04-25-cross-level-evidence-audit-design.md`.

## 2. User-visible outcome — Part A

After shipping Part A:

- **L3 detail view** grows a new **Visual evidence & stock analysis**
  header section that is always visible regardless of issue state:
  - **Stock analysis card** — loan amount, estimated stock value
    (+ equipment if service-biz), coverage %, business type,
    recommended loan amount and delta, reasoning paragraph. Renders
    whenever the business scorer ran (passing *and* failing).
  - **Photos gallery** — house photos + business premises photos as
    thumbnails with a click-to-enlarge lightbox exposing the GPS
    coordinates + capture timestamp embedded in the image metadata.
- **`cattle_health` no longer fires on non-dairy cases.** Hard guard
  at code level: fires only when `business_type ∈ {cattle_dairy, mixed}`
  AND `cattle_count > 0` AND `cattle_health == "unhealthy"`. Existing
  Ajay case and every future non-dairy case will no longer receive
  the false positive.
- **Multi-angle visibility.** A new evidence key
  `photos_evaluated_count` surfaces on every scorer-driven L3 concern
  plus on `sub_step_results.visual_evidence` so the MD can see how
  many business/house photos the model ingested before emitting its
  verdict. A low-count warning shows when fewer than 2 photos are
  available (surfaces the "single-photo" risk).
- **Click-to-expand on passing rules.** Each `PASS` / `N/A` row in
  the `PassingRulesPanel` becomes clickable and expands inline,
  mirroring the detail treatment failed concerns already get via
  `IssueEvidencePanel`. For L3's scorer-driven passes — especially
  `stock_vs_loan` — the expanded card shows the structured "how and
  why it passed" evidence: stock value vs loan amount side by side,
  equipment split (service biz), coverage %, recommended loan,
  scorer reasoning, and the photos the rule ran against. The MD can
  cross-check the scorer's conclusion against the photos in one
  place. Same pattern for `business_infrastructure`,
  `loan_amount_recommendation`, and `cattle_health` (the latter
  also names the reason it was skipped — e.g., "not a dairy
  business"). Other levels' passing rules get the click-affordance
  in Part A but render a placeholder "No additional pass-detail
  available yet" until Part B backfills their `pass_evidence` dicts.
- No change to issue severity thresholds, gate logic, scoring,
  decisioning, upload flow, or any level outside L3.

## 3. Non-goals — Part A

- New `STOCK_PHOTO` upload category or per-photo auto-classification.
- Map pins, video, bounding-box annotations, watermarks on photos.
- Changing any threshold in any `cross_check_*` function. The
  business-type guard on `cross_check_cattle_health` is a guard
  (rejecting a false-positive), not a threshold change.
- Wiring evidence into the decisioning L6 prompt set.
- Historical backfill — new schema is forward-only. Old L3 runs will
  not have the new panel until re-run.
- Cross-level evidence audit (moved to Part B).
- **Per-item stock itemization** in `stock_vs_loan` pass-detail.
  Today the scorer emits a single aggregate
  `stock_value_estimate_inr`, not a per-item price list. Producing
  a `[{item_type, count, unit_price_inr, subtotal_inr}]` table
  requires a scorer-prompt change and a new data shape — deferred
  to a follow-up scorer enhancement. Part A's `stock_vs_loan`
  pass-detail uses the existing aggregate fields.
- **Cross-level `pass_evidence` content** — Part A ships the FE
  click-to-expand infrastructure and populates L3 `pass_evidence`
  only. L1 / L1.5 / L2 / L4 rules get the affordance but render a
  "No additional pass-detail available yet" placeholder until
  Part B's audit fills them in.

## 4. Data & contract changes

### 4.1 New `sub_step_results` keys on L3

`VerificationResult.sub_step_results` for L3 gains two top-level
keys, both written by
`backend/app/verification/levels/level_3_vision.py`:

```python
sub_step_results = {
    # existing keys (unchanged)
    "house": {...},
    "business": {...},
    "house_photo_count": int,
    "business_photo_count": int,
    "issue_count": int,
    "suppressed_rules": [...],

    # NEW
    "visual_evidence": {
        "house_photos": [
            {
                "artifact_id": "uuid",
                "filename": "IMG_20260411_135700.jpg",
                "subtype": "HOUSE_VISIT_PHOTO",
            },
            # ...
        ],
        "business_photos": [
            # same shape, subtype == "BUSINESS_PREMISES_PHOTO"
        ],
        "house_photos_evaluated": int,     # what the scorer actually scored
        "business_photos_evaluated": int,
    },
    "stock_analysis": {
        # Present whenever the business scorer produced data (even on
        # PARTIAL). Absent when scorer errored.
        "business_type": "service" | "cattle_dairy" | "product_trading"
                       | "manufacturing" | "mixed" | "other" | "unknown"
                       | None,
        "business_subtype": str | None,
        "loan_amount_inr": int | None,
        "stock_value_estimate_inr": int | None,
        "visible_equipment_value_inr": int | None,  # scorer's real key name
        "visible_collateral_inr": int | None,       # stock + equipment for
                                                    # service biz, else stock
        "cattle_count": int | None,
        "cattle_health": str | None,
        "coverage_pct": float | None,               # visible_collateral / loan.
                                                    # For cattle_dairy,
                                                    # visible_collateral ==
                                                    # stock_value_estimate_inr
                                                    # (cattle × ₹60k proxy
                                                    # per scorer prompt).
        "floor_pct_critical": float | None,         # 0.40 service, 0.50 other
        "floor_pct_warning": float | None,          # 1.00 non-service only,
                                                    # null for service (40%
                                                    # is the sole threshold)
        "recommended_loan_amount_inr": int | None,
        "recommended_loan_rationale": str | None,
        "cut_pct": float | None,                    # 1 - rec/proposed
        "reasoning": str,                            # one-paragraph summary,
                                                    # always non-empty while
                                                    # scorer ran
    },
}
```

`visual_evidence` is **always present** when the level runs. Arrays
may be empty. Counts default to 0.

`stock_analysis` is present whenever `biz_data` has any content
(including PARTIAL with warnings). When the business scorer returns
`error_message`, `stock_analysis` is absent and the frontend renders
a "Stock analysis unavailable — scorer failed" card.

GPS and timestamp are **not** persisted on the per-photo entries in
`visual_evidence` — they live on the `CaseArtifact.metadata_json`
that `useCasePhotos` already hydrates client-side. This avoids
duplicating data and keeps the L3 emission shape minimal.

### 4.1.a New `pass_evidence` key on `sub_step_results` (L3)

In addition to the above, the orchestrator emits a top-level
`pass_evidence` dict — a map from `sub_step_id` to a
per-rule evidence dict populated **only when the rule passed**
(or skipped with N/A). This mirrors what `LevelIssue.evidence`
carries for failed concerns, but lives in `sub_step_results`
because passing rules don't create `LevelIssue` rows.

```python
sub_step_results = {
    # ... all above, plus:
    "pass_evidence": {
        "house_living_condition": {
            "overall_rating": "ok",
            "space_rating": "good",
            "upkeep_rating": "ok",
            "construction_type": "pakka",
            "positives": [...],
            "concerns": [...],           # may be [] on pass
            "photos_evaluated_count": int,
        },
        "business_infrastructure": {
            "infrastructure_rating": "good",
            "infrastructure_details": [...],
            "equipment_visible": bool,
            "photos_evaluated_count": int,
        },
        "stock_vs_loan": {
            # Core "why this passed" structured data. FE renders this
            # as a side-by-side "stock vs loan" comparison card.
            "business_type": str,
            "business_subtype": str | None,
            "loan_amount_inr": int | None,
            "stock_value_estimate_inr": int | None,
            "visible_equipment_value_inr": int | None,
            "visible_collateral_inr": int | None,
            "coverage_pct": float | None,
            "floor_pct_critical": float,
            "floor_pct_warning": float | None,
            "stock_condition": str | None,
            "stock_variety": str | None,
            "reasoning": str,
            "photos_evaluated_count": int,
        },
        "loan_amount_recommendation": {
            "loan_amount_inr": int | None,
            "recommended_loan_amount_inr": int | None,
            "cut_pct": float | None,           # 0 on pass means no cut
            "trigger_pct": float,              # 0.80
            "rationale": str | None,
            "photos_evaluated_count": int,
        },
        "cattle_health": {
            # For passes where business_type ∈ {cattle_dairy, mixed}:
            "business_type": str,
            "cattle_count": int | None,
            "cattle_health": str,
            # For N/A (non-dairy business):
            "skipped_reason": "not a dairy business (classified: <type>)",
        },
    },
}
```

Rules that haven't had their `pass_evidence` populated yet emit no
entry at all — the FE renders the placeholder described in §5.4.
This keeps the contract additive: Part B just adds more keys to
`pass_evidence` in other level orchestrators without changing the
schema.

### 4.2 Photo data source — FE plan

The frontend already hydrates photos via
`useCasePhotos(caseId)` (see `VerificationPanel.tsx:2327`) which
returns items with `artifact_id`, `filename`, `download_url`,
`subtype`, plus metadata. Part A keeps this hook as-is — it is the
canonical photo source. `sub_step_results.visual_evidence` provides
two pieces the hook doesn't:

- `house_photos_evaluated` / `business_photos_evaluated` — the
  counts the scorer actually processed (distinct from "uploaded",
  which is what the hook sees).
- Subset of artifact IDs the L3 scorer ingested, so the FE can
  filter the hook's output to just those (in case uploaded set
  diverges from scored set).

The L3 photo gallery component in §5 does this:

```ts
const { housePhotos, businessPhotos } = useCasePhotos(caseId)
// visual_evidence.house_photos + business_photos give artifact_id lists.
// Filter the hook's output to the scored subset — no second fetch.
```

No new network path, no signed-URL rotation concerns. The inside-
issue photo gallery currently at `VerificationPanel.tsx:2410–2460`
is removed (subsumed by the new header panel).

### 4.3 `cattle_health` guard

`cross_check_cattle_health` signature changes:

```python
def cross_check_cattle_health(
    health: str | None,
    *,
    business_type: str | None,
    cattle_count: int | None,
) -> dict[str, Any] | None:
    if health != "unhealthy":
        return None
    if business_type not in ("cattle_dairy", "mixed"):
        return None
    if not cattle_count or cattle_count <= 0:
        return None
    return {
        "sub_step_id": "cattle_health",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "Cattle appear unhealthy / malnourished in the photos. "
            "Milking yield + asset value are at risk. Require a vet "
            "health certificate before disbursing a dairy loan."
        ),
        "evidence": {
            "business_type": business_type,
            "cattle_count": cattle_count,
            "cattle_health": health,
        },
    }
```

The cross-check returns evidence with the three fields it actually
holds. `photos_evaluated_count` is **not** a placeholder here —
it's merged in by the orchestrator at the same call-site that
already attaches `source_artifacts` (`level_3_vision.py:380-386`),
so the merge pattern stays identical for every scorer-driven rule.

Orchestrator call-site change (at
`backend/app/verification/levels/level_3_vision.py:368`):

```python
# before
lambda: cross_check_cattle_health(b.data.get("cattle_health")),

# after
lambda: cross_check_cattle_health(
    b.data.get("cattle_health"),
    business_type=b.data.get("business_type"),
    cattle_count=b.data.get("cattle_count"),
),
```

The guard is a pure input check — the function still returns
`None` on all previously-passing cases; it will silently stop
emitting on cases where Opus wrongly tagged cattle_health on a
non-dairy business.

### 4.4 Existing keys being leaned on (confirmation)

The following are already emitted by `BusinessPremisesScorer.score()`
(`backend/app/verification/services/vision_scorers.py` — verified):

- `business_type`, `business_subtype`, `stock_value_estimate_inr`,
  `visible_equipment_value_inr`, `cattle_count`, `cattle_health`,
  `infrastructure_rating`, `recommended_loan_amount_inr`,
  `recommended_loan_rationale`, `cost_usd`, `usage`.

And these constants in `level_3_vision.py` drive the thresholds:

- `_SERVICE_COLLATERAL_FLOOR_PCT = 0.40` (line 78)
- `_STOCK_CRITICAL_PCT = 0.50` (line 79)
- `_LOAN_REDUCTION_TRIGGER_PCT = 0.80` (line 80)

`stock_analysis` derives `floor_pct_critical` + `floor_pct_warning`
from these — no magic numbers in the emitted dict.

## 5. L3 always-visible panel — design

### 5.1 Layout

```
┌──────────── ✗ L3 · Vision    1 CRITICAL ISSUE · 75% match ─────────┐
│ ┌─── VISUAL EVIDENCE & STOCK ANALYSIS (always visible, NEW) ─────┐ │
│ │ ┌─── STOCK ANALYSIS ──────────┐ ┌─── PHOTOS ─────────────────┐ │ │
│ │ │ Loan  ₹1,00,000              │ │ House visit (N evaluated)  │ │ │
│ │ │ Visible collateral ₹1,15,000 │ │ [▢] [▢] [▢] [▢] [▢]        │ │ │
│ │ │   · stock ₹1,05,000          │ │ Business premises (M eval) │ │ │
│ │ │   · equipment ₹10,000        │ │ [▢] [▢] [▢] [▢] [▢]        │ │ │
│ │ │ Coverage 115%  ·  floor 40%  │ │ click → lightbox           │ │ │
│ │ │ Rec. loan ₹1,00,000 (no cut) │ │   shows GPS + timestamp    │ │ │
│ │ │ Reasoning: Service biz …     │ └────────────────────────────┘ │ │
│ │ └──────────────────────────────┘                                │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                    │
│ ─── Concerns (existing, full width, L=why / R=what-was-checked) ──│
│ ✗ CRITICAL House living condition                                 │
│                                                                    │
│ ─── Passing rules · Extraction details (unchanged) ───────────────│
└────────────────────────────────────────────────────────────────────┘
```

Wide viewport (`xl:`): cards sit side by side ~55/45.
Narrow viewport: cards stack.

### 5.2 Components

- `L3StockAnalysisCard({ analysis })` — renders the
  `stock_analysis` dict. Colour-graded coverage pill:
  - **Non-service** (two thresholds): emerald ≥ `floor_pct_warning`
    (100%), amber ≥ `floor_pct_critical` (50%), else red.
  - **Service** (one threshold): emerald ≥ `floor_pct_critical`
    (40%), else red. No amber tier — service biz either clears
    the collateral-floor or doesn't; no middle band in policy.
  Service-biz rows include the equipment split. Shows
  "Stock analysis unavailable — scorer failed" fallback when
  `analysis` is absent.
- `L3PhotoGallery({ caseId, visualEvidence })` — uses existing
  `useCasePhotos(caseId)` hook, filtered by artifact IDs in
  `visualEvidence.house_photos` / `.business_photos`. Per-category
  section with "(N evaluated)" label. Low-count warning banner when
  `house_photos_evaluated < 2` or `business_photos_evaluated < 2`:
  *"Only N photo evaluated — consider re-inspection for confidence."*
  Click thumbnail → lightbox with filename, GPS (if present in the
  artifact metadata), capture time.

Both components sit in new files
`frontend/src/components/cases/l3/L3StockAnalysisCard.tsx` and
`frontend/src/components/cases/l3/L3PhotoGallery.tsx`. The
VerificationPanel imports them and calls them from the L3 detail
renderer. This keeps VerificationPanel.tsx (already 3916 LoC) from
growing further.

### 5.3 Fallbacks & empty states

| State | Stock card | Photo gallery |
|---|---|---|
| L3 never ran | hidden | hidden |
| L3 running | skeleton | skeleton |
| Scorer failed | "Unavailable" with pointer to `business_scorer_failed` concern | renders uploaded photos (hook still returns them) with "(0 evaluated)" |
| No business photos uploaded | renders numbers from scorer EMPTY_DATA | "No business premises photos uploaded" hint |
| Pass, all fine | full card with emerald coverage pill | gallery |
| 1 photo only | full card | "Only 1 photo evaluated — low confidence" banner |

### 5.4 Passing-rule click-to-expand

`LogicCheckRow` (currently a one-liner in
`VerificationPanel.tsx` rendered from inside
`PassingRulesPanel`) gains a click-to-toggle affordance identical
to the issue-row pattern:

- Row becomes a `<button>` / keyboard-accessible element with
  `aria-expanded`.
- Chevron `▸ / ▾` on the left side.
- Click the whole row → expands inline below.
- Expanded body reads `pass_evidence[sub_step_id]` and dispatches
  to one of:
  - **Smart layout (L3 scorer-driven rules)** — a dedicated mini
    component per rule:
    - `stock_vs_loan` → **`L3StockVsLoanPassCard`**: two-column
      table, left column "Visible collateral" (stock row +
      equipment row + total), right column "Loan amount" (just the
      figure), delta %, coverage pill, reasoning paragraph,
      strip of photo thumbnails the rule ran against. This is the
      "side-by-side stock vs loan" view the MD explicitly asked
      for.
    - `business_infrastructure` → `L3InfraPassCard`: rating pill,
      bullet list of `infrastructure_details`, photo strip.
    - `loan_amount_recommendation` → `L3LoanRecPassCard`:
      proposed vs recommended figures, delta %, rationale text.
    - `house_living_condition` → reuse the existing
      `IssueEvidencePanel`-style grid (ratings + concerns +
      positives) read from `pass_evidence.house_living_condition`.
    - `cattle_health` (N/A case) → single-line note naming the
      skip reason.
  - **Placeholder (all other rules, levels L1/L1.5/L2/L4)** — a
    muted row reading *"No additional pass-detail available
    yet — this will be populated when Part B of the evidence
    audit ships."* Keeps the affordance consistent so the MD
    doesn't learn "click sometimes does nothing".

Multiple rows can be expanded simultaneously. State is local to
the `PassingRulesPanel` (not URL-synced) — matches issue-row
behaviour today. Keyboard: `Enter` / `Space` toggles, `Tab` moves
between rows.

The L3 pass-card components live in
`frontend/src/components/cases/l3/` alongside
`L3StockAnalysisCard` — they share the number-formatting helpers
and colour-grade logic, so co-location keeps them consistent.

## 6. Backend implementation plan — Part A

Five commits, each independently runnable:

1. **`cross_check_cattle_health` guard** — signature + orchestrator
   call-site update. Unit test: barbershop case (business_type=service,
   cattle_health=unhealthy) no longer fires.
2. **`build_stock_analysis` pure helper + `build_visual_evidence`
   pure helper** — new functions in `level_3_vision.py` that return
   the dicts in §4.1 given the scorer outputs + loan amount +
   per-category photo lists. Unit tests: service biz, non-service,
   cattle_dairy, scorer-error.
3. **Wire `visual_evidence` + `stock_analysis` into
   `sub_step_results`** — orchestrator change. Also pass
   `photos_evaluated_count` into the per-issue `evidence` block on
   scorer-driven concerns (`house_living_condition`, `stock_vs_loan`,
   `business_infrastructure`, `cattle_health`, `loan_amount_reduction`).
4. **Refactor `cross_check_stock_vs_loan` to use `build_stock_analysis`**
   so the number-crunching only lives in one place. Keep the issue
   description generation in the cross-check; move the `stock`,
   `equipment`, `coverage`, `floor` computations into the helper.
5. **`build_pass_evidence` helper + orchestrator wire-up** — new
   pure function that, given the scorer outputs + loan amount +
   photo counts, returns the `pass_evidence` dict in §4.1.a for the
   five L3 rules. Populated for rules that passed (or are N/A).
   Orchestrator merges it into `sub_step_results`. Unit tests:
   passing service biz fills all 5 entries; failing case only fills
   the rules that passed (everything except `stock_vs_loan`);
   non-dairy case gets `cattle_health` as N/A with `skipped_reason`.

## 7. Frontend implementation plan — Part A

Five commits:

1. **Scaffolding + types** — add `visual_evidence`, `stock_analysis`,
   and `pass_evidence` to `frontend/src/lib/types.ts` under the L3
   `sub_step_results` shape. Add the new component files empty.
2. **L3StockAnalysisCard + L3PhotoGallery** — implement the two
   header components per §5.
3. **VerificationPanel L3 header wiring** — render the new header
   section on the L3 detail view. Delete the inline photo gallery
   inside the per-concern expanded view (the `{levelNumber ===
   'L3_VISION' && …source photos — visual evidence behind
   Claude's…}` block — subsumed by the new header panel). Verify
   `IssueSourceFilesButton` still works on individual concerns.
4. **LogicCheckRow click-to-expand infrastructure** — convert the
   row from a non-interactive `div` to a keyboard-accessible
   expandable element. Add the chevron affordance, local
   `expanded` state, placeholder body for rules without
   `pass_evidence`. Applies across every level (L1, L1.5, L2, L3,
   L4, L5) — rules without pass-detail yet render the placeholder
   message from §5.4.
5. **L3 pass-detail components** — implement
   `L3StockVsLoanPassCard`, `L3InfraPassCard`,
   `L3LoanRecPassCard`, and the reused-grid for
   `house_living_condition` + the N/A row for `cattle_health`.
   Dispatch from `LogicCheckRow` on `sub_step_id`. Share helpers
   with the header `L3StockAnalysisCard`.

## 8. Testing

- **Unit (backend)** — extend the existing
  `backend/tests/unit/test_verification_level_3_vision.py`:
  - `cross_check_cattle_health` guards: service biz with unhealthy
    cattle → no fire; cattle_dairy with unhealthy + count=3 →
    fires; cattle_dairy with unhealthy + count=0 → no fire;
    cattle_dairy with healthy + count=3 → no fire.
  - `build_stock_analysis` output shape for service, non-service,
    cattle_dairy, scorer-error.
  - `build_visual_evidence` counts match artifact list.
  - `build_pass_evidence` — passing service biz produces entries
    for all 5 rules; non-service cattle_dairy produces the cattle
    entry (not the N/A); failing-stock case produces 4 entries
    (all except `stock_vs_loan`); non-dairy case produces
    `cattle_health` with `skipped_reason`.
  - **Schema-drift guard** — feed `build_stock_analysis` a full
    scorer payload and assert all 13 documented keys in §4.1 are
    present (even if null). Do the same for
    `build_pass_evidence.stock_vs_loan`. Locks the contract so a
    future scorer rename surfaces as a test failure rather than
    silent FE zeros.
- **Integration (backend)** — re-run L3 for Ajay via
  `tests/integration/test_cases_service.py` equivalent, confirm
  `sub_step_results.visual_evidence` and `.stock_analysis` are
  populated.
- **Frontend** — manual: 3 screenshots of the L3 detail view:
  1. Pass case (new panel shows with emerald pill).
  2. Currently live Ajay (1 critical, panel renders above concerns).
  3. Scorer-failed case (contrived by forcing `h.error_message`) —
     panel renders "Unavailable" fallback.
- **Smoke** — `poetry run pytest tests/unit
  tests/integration/test_cases_service.py -q` stays green on every
  commit (~615 passed baseline per the resume doc).

## 9. Rollout

Single branch on top of `4level-l1` → PR → `main`. Live cases re-run
L3 once the BE change deploys (autorun handles it). Historical L3
runs that predate this change don't get the new panel until they're
manually re-run — acceptable because the case list has only one
live case (Ajay) and the Part B audit will push everyone to
re-run anyway.

## 10. Risks / open questions

- **Evidence payload size** — `visual_evidence` carries artifact IDs
  only. < 1 KB per L3 run. Fine.
- **`IssueEvidencePanel` regression risk for L5** — we are not
  touching `IssueEvidencePanel` in Part A. Part B will; Part A
  should not cause a regression. Included for transparency.
- **Opus lying about cattle fields** — even with the new guard, if
  Opus emits `business_type: "cattle_dairy"` on a barbershop, the
  guard won't help. Secondary mitigation: the same prompt's Hard
  Rules say service biz MUST classify as `service`, and `business_type`
  drift is rarer than `cattle_health` drift. If this surfaces, the
  follow-up is a scorer-level confidence threshold on `business_type`.
- **Low-count warning copy** — "Only 1 photo evaluated — low
  confidence" may pressure MDs into reject. If that's too strong,
  tone down to a neutral "N photos evaluated" label without the
  banner.
- **Lightbox performance** — thumbnails use
  `<img loading="lazy">` and the hook-returned `download_url`.
  Originals are loaded on lightbox open (click). At ~10 photos per
  case this is unmeasurable.
- **`stock_analysis` schema-drift** — once Part A ships the FE
  reads 13 specific keys. If a future scorer-prompt revision
  renames any of them (say `visible_equipment_value_inr` →
  `equipment_fixed_value_inr`), the FE silently shows zeros with
  no error. Mitigated by the schema-drift guard test in §8, but
  worth flagging to anyone touching `BusinessPremisesScorer`.

## 11. Spec-review-1 blockers — resolution log

Reviewer flagged the following. All resolved in this revision; noted
here so the next review has a diff base.

| # | Issue | Resolution |
|---|---|---|
| 1 | Wrong field name `equipment_value_estimate_inr` vs real `visible_equipment_value_inr` | Corrected in §4.1 and §4.4 |
| 2 | `loan_amount_reduction` threshold 0.85 vs real 0.80 | Not relevant to Part A (moved to Part B §12) |
| 3 | `house_business_commute` evidence keys phantom | Moved to Part B §12 with factual key list pending re-audit in that spec |
| 4 | `business_visit_gps` has no distance logic | Moved to Part B §12 with corrected fire-condition |
| 5 | `aadhaar_vs_bureau_address` returns boolean, not score | Moved to Part B §12 with corrected key list |
| 6 | Photo hook collision with `useCasePhotos` | §4.2 commits to keeping the hook; `visual_evidence` is metadata-only |
| 7 | Scope too large for one PR | Split — this is Part A (L3 only); Part B follows |
| 8 | L1.5 `worst_account.sanctioned_amount`/`overdue_amount` unverified | Deferred to Part B; its spec will verify against a sample bureau JSON before promising those keys |
| 9 | `ca_narrative_concerns`/`credit_analyst_failed` need new kwargs | Deferred to Part B |
| 10 | Non-service stock_vs_loan has two thresholds | `stock_analysis` now carries `floor_pct_critical` + `floor_pct_warning` |
| 11 | `cattle_health` fires on `"unhealthy"` not `"poor"`; `business_infrastructure` on `"worst"`/`"bad"` | `cattle_health` fix in §4.3 (Part A); `infrastructure_rating` evidence is unchanged in Part A and its richer `concerns[]`/`positives[]`/`equipment_visible` payload is deferred to Part B §12 |
| 12 | Missing risks | §10 now covers Opus-lies-about-cattle, lightbox perf, low-count-copy UX; §12 parking-lot inherits the rest for Part B |
| 13 | credit_score_floor thresholds | Confirmed correct — not in Part A scope anyway |

## 11.a Post-revision note — click-to-expand on passing rules added

The passing-rule click-to-expand feature was added after spec
review iteration 2. It extends Part A by one backend commit
(§6.5 `build_pass_evidence`) and two frontend commits (§7.4 row
infrastructure + §7.5 L3 pass-detail components). Non-L3 rules get
the affordance with a placeholder body; Part B fills them in.
Schema in §4.1.a is additive — other levels just add keys to
`pass_evidence` in their own orchestrators without changing
contract.

## 12. Out-of-scope parking lot (Part B and beyond)

Items explicitly deferred. The Part B spec will enumerate them
with verified field names, fire-conditions, and evidence keys
per `cross_check_*` function across L1, L1.5, L2, L4.

- Cross-level evidence audit — L1, L1.5, L2, L4 per-concern rich
  `evidence` dicts so the existing `IssueEvidencePanel` renders
  consistently.
- Smart-layout additions in `IssueEvidencePanel` for
  `stock_vs_loan`, `avg_balance_vs_emi`, `loan_amount_reduction`,
  `house_business_commute`, bureau status-account rows.
- Corrected `house_business_commute` evidence keys
  (`travel_minutes`, `dm_status`, `judge_verdict`,
  `judge_attempted`, origin/destination lat/lng pulled up from
  `_compute_commute_sub_step`).
- `business_visit_gps` — either expand the check to actually
  compute distance-from-house (meaningful feature) or drop the
  fake evidence keys.
- `aadhaar_vs_bureau_address` numeric score → either refactor to
  a score or commit to the boolean-only evidence shape.
- Centralise the 24 % flat-rate EMI assumption in
  `level_2_banking.estimate_proposed_emi_inr` (independent spec).
- Scorer-level `business_type` confidence threshold (see §10
  open question on Opus drift).
- Map-pin + geocoded place-name subtitle on the lightbox.
- Cross-level `pass_evidence` content for L1, L1.5, L2, L4 —
  populates the click-to-expand detail for every passing rule
  across the pipeline. Schema lives in `sub_step_results.pass_evidence`
  per §4.1.a and is additive.
- Per-item stock itemization in `stock_vs_loan` — a scorer-prompt
  revision that asks Opus to emit
  `[{item_type, count, unit_price_inr, subtotal_inr}]` so the
  pass-detail card can show a true per-item price table. Useful
  but requires a separate scorer-design pass.
