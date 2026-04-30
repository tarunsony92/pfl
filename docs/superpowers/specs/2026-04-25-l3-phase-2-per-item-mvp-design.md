# L3 Phase 2 — Per-item stock breakdown · MVP design

**Date:** 2026-04-25
**Status:** Design (MVP). Replaces the `L3PerItemTablePlaceholder` with a real per-item table backed by the existing Opus business-premises scorer. Image crops + DB-backed price catalogue are explicitly **deferred** to Phase 2.5.
**Owner:** saksham@pflfinance.com

> Brief at `docs/superpowers/specs/2026-04-25-phase-2-evidence-enrichment-design-brief.md` §1 estimates the full L3 Phase 2 at 4 days. This MVP ships ~20% of that scope (vision-driven items + AI-estimated MRPs + display table) end-to-end in a single session, leaving the rest as a clearly-named follow-up.

## 1. Context

L3 today returns one aggregate `stock_value_estimate_inr` from the `BusinessPremisesScorer` Opus pass. The verification UI revamp shipped a placeholder card (`L3PerItemTablePlaceholder.tsx`) below the stock-analysis card to communicate the deferred per-item view. This MVP fills the placeholder slot.

**MVP scope (what ships):**
- Extend the existing Opus prompt to return a per-item array alongside the aggregates
- FE replaces the placeholder with a real `L3PerItemTable` consuming that array
- Stale L3 extractions (i.e. all existing cases) auto-rerun on first view so users don't need to manually click "Run L3"

**Explicitly out of scope (deferred to Phase 2.5):**
- DB-backed price catalogue keyed by `(business_type, item_canonical) → MRP` (Brief §1 calls for 1.5 days of work, requiring real public SKU data sourcing)
- Image crops per item (Pillow + S3 multipart upload pipeline; child-artifact storage; bbox)
- bbox-driven inline highlighting on the parent photo

## 2. Backend schema changes

### 2.1 `BusinessPremisesScorer` JSON schema extension

In `backend/app/verification/services/vision_scorers.py:222-241`, extend the schema with a new `items` array:

```json
{
  "business_type": "...",
  "business_type_confidence": 0.0,
  ...existing 13 fields unchanged...
  "items": [
    {
      "description": "barber chair (hydraulic)",
      "qty": 2,
      "category": "equipment",
      "mrp_estimate_inr": 8500,
      "mrp_confidence": "medium",
      "rationale": "two visible hydraulic chairs typical of village salons"
    },
    {
      "description": "wall mirror",
      "qty": 3,
      "category": "equipment",
      "mrp_estimate_inr": 1200,
      "mrp_confidence": "high",
      "rationale": "standard size, visible on three stations"
    },
    {
      "description": "shampoo bottles (assorted)",
      "qty": 6,
      "category": "consumable",
      "mrp_estimate_inr": 250,
      "mrp_confidence": "low",
      "rationale": "small bottles partially obscured; estimate per bottle"
    }
  ]
}
```

Field semantics:
- **`description`**: free text, lowercase, no leading "a"/"the". Specific enough for an assessor to confirm against the photo.
- **`qty`**: integer. If the model is uncertain, it must take its best count guess (no nulls); rationale should note the uncertainty.
- **`category`**: enum `equipment | stock | consumable | other`. Drives sum-by-category for the aggregates: `stock_value_estimate_inr ≈ Σ(stock|consumable line totals)`, `visible_equipment_value_inr ≈ Σ(equipment line totals)`. Aggregates remain authoritative for the existing rules — items are display-only.
- **`mrp_estimate_inr`**: integer (single per-unit MRP, not range). `null` only when the model has zero idea (`mrp_confidence = "low"` is still a number — the model commits to a guess).
- **`mrp_confidence`**: `high | medium | low`. The FE renders `low` as italic-grey, `null` MRP as em-dash.
- **`rationale`**: short string, ≤ 80 chars, used as a tooltip/hover on the row.

### 2.2 Prompt update (`_BUSINESS_SYSTEM`)

Add a Step 4 to the prompt (after the existing Step 3 — recommend) at `vision_scorers.py:215-220`:

```
Step 4 — ITEMISE THE VISIBLE COLLATERAL:
  - List EACH visible inventory line / fixed-equipment item separately in
    `items[]`. Group identical items into one row with qty (e.g. don't
    list "chair" three times — return {description:"barber chair", qty:3}).
  - For each item, include your best 2026 Indian retail MRP estimate
    (`mrp_estimate_inr`) and your confidence (`mrp_confidence`).
    For service consumables (shampoo, hair dye, scissors), use
    PER-UNIT MRP — line total will be qty × MRP.
  - The aggregate `stock_value_estimate_inr` should equal the sum of
    line totals where category ∈ {stock, consumable}; the aggregate
    `visible_equipment_value_inr` should equal the sum of line totals
    where category = equipment. State the math is consistent in
    `recommended_loan_rationale`.
  - If you cannot price an item at all, return mrp_estimate_inr=null
    with mrp_confidence="low" so the assessor sees the gap rather
    than a fabricated number.
```

### 2.3 `_EMPTY_DATA` shape

Add `"items": []` to the `_EMPTY_DATA` dict at `vision_scorers.py:268-284` so the empty / failed-scorer paths return the same shape (downstream code can iterate the array unconditionally).

### 2.4 `max_tokens` bump

`BusinessPremisesScorer.score()` invokes Claude with `max_tokens=1024` at `vision_scorers.py:330`. The new `items[]` array adds ~300-500 tokens of structured output (8-12 rows × ~30 tokens each, plus rationale strings). Combined with the existing aggregate fields + `concerns[]` + `positives[]`, 1024 is too tight — Opus may hit the ceiling mid-JSON, the `_extract_json` parse fails, and the scorer falls back to `_EMPTY_DATA` (silent data loss).

**Bump `max_tokens=1024` → `max_tokens=2048` at `vision_scorers.py:330`.** This is a one-line change that protects against the truncation mode entirely.

### 2.5 `build_stock_analysis` passthrough

`build_stock_analysis` at `level_3_vision.py:338-356` returns an explicit allowlist dict (not a `**biz_data` spread). Add `"items"` to the explicit allowlist — note this is structurally identical to the existing fields, just one more named entry:

```python
return {
    "business_type": business_type,
    ...existing 13 fields unchanged...
    "items": list(biz_data.get("items") or []),
}
```

That's it on the orchestrator side — no other changes.

### 2.6 Schema version bump (4 return sites)

Bump `BusinessPremisesScorer`'s schema_version from "1.0" to "2.0". The schema_version is already persisted on `CaseExtraction.schema_version` (DB column at `models/case_extraction.py:51`), so the FE can detect stale extractions by checking either `data.items === undefined` OR `extraction.schema_version === "1.0"`.

`BusinessPremisesScorer.score()` returns `ExtractionResult(...)` at **four** sites — all four must be updated to `schema_version="2.0"` so the version is consistent regardless of success/failure:

- `vision_scorers.py:297` — no-images PARTIAL path
- `vision_scorers.py:336` — vision call exception FAILED path
- `vision_scorers.py:347` — JSON parse exception FAILED path
- `vision_scorers.py:361` — SUCCESS path (`return ExtractionResult(...)` after `data = {**self._EMPTY_DATA, ...}` at line 358)

A FAILED extraction at "2.0" still indicates the v2 schema *was attempted* — the FE auto-refresh logic only fires on `data.items === undefined`, so FAILED paths with empty data still trigger an auto-refresh on the user's next view (which is the right behaviour: a failed extraction should re-run rather than render permanently empty).

## 3. Frontend changes

### 3.1 `L3PerItemTable.tsx` (new, replaces placeholder)

Path: `frontend/src/components/cases/evidence/L3PerItemTable.tsx`. Public interface matches the placeholder it replaces (no props, picks data from a parent-supplied evidence shape):

```tsx
type ItemRow = {
  description: string
  qty: number
  category: 'equipment' | 'stock' | 'consumable' | 'other'
  mrp_estimate_inr: number | null
  mrp_confidence: 'high' | 'medium' | 'low'
  rationale?: string
}

export function L3PerItemTable({
  items,
  onAutoRefresh,
}: {
  items: ItemRow[] | undefined
  onAutoRefresh?: () => void
}): JSX.Element
```

Three render paths:
- **`items === undefined`** (legacy extraction, schema_version 1.0): render a thin notice "Refreshing per-item breakdown…" + auto-fire `onAutoRefresh()` on mount via a `useEffect` (see §3.2).
- **`items.length === 0`** (scorer ran but found nothing — should be rare): render "No items extracted from this scorer pass."
- **`items.length > 0`**: render a table:
  ```
  | Description       | Qty | Category   | MRP (₹)         | Line total (₹) |
  | ----------------- | --- | ---------- | --------------- | -------------- |
  | barber chair      | 2   | EQUIPMENT  | 8,500           | 17,000         |
  | wall mirror       | 3   | EQUIPMENT  | 1,200           | 3,600          |
  | shampoo (bottles) | 6   | CONSUMABLE | 250 (low conf.) | 1,500          |
  | hair dye boxes    | 4   | CONSUMABLE | —               | —              |
  | ─────────────────────────────────────────────────────── |
  | GRAND TOTAL                                  ₹22,100   |
  ```

  - MRP column shows the integer when `mrp_estimate_inr != null`. When `mrp_confidence === "low"`, italic-grey + "(low conf.)" suffix. When `mrp_estimate_inr === null`, em-dash; line total is em-dash too.
  - Category cell: small uppercase pill matching the existing `nach_bounces` chip style.
  - Hover any row → tooltip with `rationale`.
  - Grand total = sum of priced line totals; unpriced rows excluded with a small "(N items unpriced)" caption next to the total.

### 3.2 Auto-rerun hook in `VerificationPanel.tsx`

In the L3 expansion at `VerificationPanel.tsx:3141`, replace `<L3PerItemTablePlaceholder />` with `<L3PerItemTable items={items} onAutoRefresh={…} />`. The codebase does NOT have a `useTriggerLevel` hook — the existing pattern is the local `handleTrigger` async function at `VerificationPanel.tsx:3286` that calls `casesApi.verificationTrigger(caseId, level)` then awaits the overview `mutate()`.

For Phase 2 we add a tiny inline equivalent that ALSO refreshes the L3 detail SWR cache (so the new `items` array surfaces once the backend completes):

```tsx
import { useEffect, useRef } from 'react'
import { mutate as swrMutate } from 'swr'
import { casesApi } from '@/lib/api'

const items = (
  l3Detail?.result?.sub_step_results?.stock_analysis?.items
) as ItemRow[] | undefined
const autoRefreshRef = useRef(false)

useEffect(() => {
  // Auto-rerun L3 ONCE per page-load when:
  //  (a) L3 detail has loaded, AND
  //  (b) items field is missing (legacy schema)
  if (!l3Detail || autoRefreshRef.current) return
  if (items !== undefined) return
  autoRefreshRef.current = true

  ;(async () => {
    try {
      await casesApi.verificationTrigger(caseId, 'L3_VISION')
    } catch {
      // Backend's 5-min concurrency guard may 409 — that's fine; the
      // existing in-flight run will produce the new schema. Don't
      // surface this error; the spinner will resolve when the cache
      // re-fetches.
    } finally {
      // Re-poll the L3 detail cache. The trigger endpoint runs the
      // orchestrator synchronously, so by this point a fresh
      // VerificationResult row exists in the DB; revalidate to pull
      // the new items array into view.
      await swrMutate(['verification-level', caseId, 'L3_VISION'])
      // Also refresh the overview so the L3 status pill updates.
      await swrMutate(['verification-overview', caseId])
    }
  })()
}, [l3Detail, items, caseId])
```

The trigger endpoint (`POST /cases/{case_id}/verification/{level_number}` at `verification.py:trigger_level`) runs the orchestrator **synchronously** and only returns after `await session.commit()`. So when the `try`/`finally` exits, the new `VerificationResult` is already persisted — the explicit `mutate()` calls force SWR to re-fetch and surface the new shape, no polling interval needed.

Backend's existing 5-min concurrency guard at `verification.py:192-215` prevents thundering-herd: if the user already triggered L3 in another tab, the auto-fire returns 409 silently. Our `catch` swallows that error; the subsequent `mutate()` still re-fetches and picks up the in-flight result if it has landed by then.

### 3.3 Registry / placeholder cleanup

- Delete `frontend/src/components/cases/evidence/L3PerItemTablePlaceholder.tsx` (replaced by the new table).
- No registry change — `L3PerItemTable` is rendered inline in `VerificationPanel.tsx`, not via the rule-id registry (it's a level-wide attachment, not a per-rule card).

## 4. Auto-rerun semantics

The auto-rerun is intentionally narrow:
- Only fires on the L3 panel — no other levels auto-rerun.
- Only fires when `items === undefined` (the legacy-extraction signal). Once the new schema lands, fresh extractions always include `items` and the hook is a no-op.
- One fire per page load, guarded by `useRef`.
- Backend concurrency guard ensures duplicates within 5 min are 409'd.
- Cost ceiling: one Opus call per stale case per session ≈ $0.05/case. With ~5 stale cases viewed per assessor per day, ~$0.25/day on the entire team — negligible.

The user's "need to auto run" requirement is fully covered without any new infrastructure.

## 5. Testing

**Backend (3 unit tests):**

1. `test_business_premises_scorer_empty_data_includes_items` — assert `_EMPTY_DATA["items"] == []`. Regression guard against schema drift.
2. `test_business_premises_scorer_passthrough_items` — stub the Claude response with a 2-item payload, confirm `data["items"]` equals the parsed array.
3. `test_build_stock_analysis_forwards_items` — pass a `biz_data` dict with 3 items, confirm the returned `stock_analysis` dict has the same `items` array.

**Frontend (1 vitest snapshot suite, 3 cases):**

1. `L3PerItemTable` renders 2 priced items with grand total
2. Renders a row with `mrp_estimate_inr === null` showing em-dash
3. Renders the "Refreshing per-item breakdown…" notice when `items === undefined` and exposes an `onAutoRefresh` callback that gets invoked on mount

## 6. Migration / deployment

No migration. The schema change is forward-compatible:
- Old `CaseExtraction` rows have no `items` key — FE renders the auto-refresh notice → triggers a fresh L3 run → new row has `items`.
- Backend's `build_stock_analysis` defaults `items` to `[]` when missing, so the old rules (`stock_vs_loan`, etc.) continue to consume the same aggregate fields they always did.

After deploy, every existing case's first L3 view auto-rolls forward to the v2 schema. No manual intervention.

## 7. Caveats / known limitations

1. **Aggregate consistency depends on the model.** The prompt asks Opus to ensure `Σ(stock|consumable line totals) ≈ stock_value_estimate_inr`. We're trusting the model. If it drifts in practice, a Phase 2.5 sanity-check could compute the sum server-side and warn when it diverges by >20%.

2. **Per-row source artefact still points at the parent photo** (the gallery already exists; the table doesn't crop). Phase 2.5 will swap the parent reference for a child crop artefact once the bbox + Pillow worker land.

3. **MRP estimates are AI-derived, not catalogue-backed.** Confidence-tagged + rationale-attached so the assessor can override. A future Phase 2.5 will replace the AI estimate with a DB lookup once the catalogue is seeded.

4. **Re-running L3 costs ~$0.05/case** (Opus call). The auto-refresh hook fires at most once per session per case. No way to bulk-rerun all cases without manual triggers — out of scope.

5. **`L3PerItemTablePlaceholder` is deleted, not soft-deprecated.** Anyone with an old PR open against this file will hit a merge conflict — acceptable for an in-flight feature.

## 8. Out of scope (Phase 2.5+ follow-ups)

- **Image crops**: Pillow worker, `BUSINESS_PREMISES_CROP` subtype, parent_artifact_id, S3 multipart upload, queue plumbing.
- **bbox extension**: scorer returns `bbox: [x0, y0, x1, y1]` per item; FE overlays the crop on the parent photo when the in-app PDF/image viewer (Phase 2 §4 of the brief) ships.
- **DB-backed price catalogue**: `(business_type, item_canonical) → MRP` table; fuzzy matching; seed data for barbershop / dairy / kirana / textile.
- **Sanity-check delta on aggregates**: server-side compute `abs(Σitems - aggregate)` and warn when >20%.
- **Bulk-rerun all stale cases**: a one-shot admin endpoint or DB migration would bring all existing cases up to v2 without per-case views. Not needed if traffic is low.

## 9. Files touched

### Modified
- `backend/app/verification/services/vision_scorers.py` — prompt + schema + `_EMPTY_DATA`
- `backend/app/verification/levels/level_3_vision.py` — `build_stock_analysis` passes through `items`
- `frontend/src/components/cases/VerificationPanel.tsx` — replace placeholder JSX + add auto-refresh hook
- `frontend/src/components/cases/evidence/L3PerItemTablePlaceholder.tsx` — **deleted**

### Created
- `frontend/src/components/cases/evidence/L3PerItemTable.tsx` — new component
- `backend/tests/unit/test_business_premises_scorer_items.py` — 2 tests on the scorer
- `backend/tests/unit/test_build_stock_analysis_items.py` — 1 test on the orchestrator helper
- `frontend/src/components/cases/evidence/__tests__/L3PerItemTable.test.tsx` — 3 vitest cases (if the project's vitest setup runs cleanly; otherwise one inline assertion in a co-located test)
