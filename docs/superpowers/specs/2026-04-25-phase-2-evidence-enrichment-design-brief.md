# Phase 2 — Evidence-enrichment design brief

## Context

The verification UI revamp shipped on `4level-l1` (commits `f169c64`,
`f3e4dd4`, `0a8d440`, `af87dfc`, `8de8881`) standardised every
concern + every passing rule on every level into one
`EvidenceTwoColumn` shell — claim left, source right, verdict pill at
top. The redesign is now ~95% pure-FE; the remaining 5% is structured
data the backend doesn't emit yet. This brief captures that remaining
work so a future session can land it without re-deriving the gaps.

The redesign was scoped FE-first (per the locked plan at
`~/.claude/plans/this-is-the-kinf-piped-pumpkin.md`, decisioning
question 1) so the visible UI could ship immediately. The Phase 2
items below are all backend pre-requisites — they don't change the FE
shell, only what plugs into it.

---

## 1. L3 per-item stock breakdown + auto-cropped photos

### Why

Today L3's `build_stock_analysis` returns one aggregate
`stock_value_estimate_inr` from a Claude Opus pass over the photo
bundle. The FE renders it via `L3StockAnalysisCard` plus the gallery
`L3PhotoGallery`. Saksham's spec called for a tabular per-item view:
description × MRP-from-database × qty × line-total + auto-cropped photo
per item so the assessor can verify each line independently. The slot
is reserved on the FE today via `L3PerItemTablePlaceholder.tsx` — it
just needs the data.

### Backend pieces

- **Vision pass returning structured items** — modify `vision_scorers`
  prompt to return:
  ```python
  [{"description": "...", "qty": int, "category": "...",
    "bbox": [x0, y0, x1, y1], "source_artifact_id": "..."}, ...]
  ```
  Probable model: Sonnet (cheap, structured-output friendly) or Opus if
  Sonnet under-fits on hardware-heavy salons / dairy. Budget ~$0.01–$0.03
  extra per case.
- **Price catalogue lookup** — DB-backed table keyed by
  `(business_type, item_description_canonical)` returning per-item MRP.
  Seed from publicly-available SKU catalogues for the dominant
  business types (barbershop / dairy / kirana / textile). Fuzzy-match
  on description with a confidence floor; below confidence, leave MRP
  null and let the per-item table show the gap.
- **Image-crop worker** — image processing service that crops each
  bbox out of its parent photo and stores the crop as a child artefact
  (`subtype=BUSINESS_PREMISES_CROP`, `parent_artifact_id` pointing to
  the source). Returns `download_url` / `attachment_url` like any
  artefact so `SourceArtifactCard` renders it inline without changes.
  Use Pillow + S3 multipart upload; queue via the existing worker
  pool.
- **Evidence shape** — extend `stock_analysis` with:
  ```python
  {
    "items": [{"description", "qty", "mrp_inr", "line_total_inr",
               "source_artifacts": [{artifact_id, bbox, ...}]}],
    "grand_total_inr": int,
    "stock_value_estimate_inr": int  # kept for legacy callers
  }
  ```
- **Per-item rule passes** — leave the existing rules
  (`stock_vs_loan`, `business_infrastructure`, `loan_amount_reduction`)
  unchanged; they consume aggregate fields. The per-item table is
  display-only — no new rules.

### FE pieces (after BE ships)

- Replace `L3PerItemTablePlaceholder` with `L3PerItemTable` consuming
  `items[]`. One row per item: cropped photo on left (renders via
  `SourceArtifactCard` since each crop is a real child artefact), then
  description, MRP, qty, line total. Grand total in a sticky footer
  row.
- The `bbox` field on `source_artifacts` lights up the long-deferred
  Phase 2 source-viewer (rectangle overlay on the parent photo) — same
  data structure the `SourceArtifactRef` type already reserves.

### Effort

- Vision prompt change + JSON-schema validation: 0.5 day
- Image crop worker + child-artefact storage: 1 day
- Price-catalogue table + seed + fuzzy match: 1.5 days (most of the
  effort here is the catalogue itself; the lookup is trivial)
- Evidence-shape migration + tests: 0.5 day
- FE per-item table: 0.5 day

**Total: 4 days** + ongoing AI-cost increase ~$0.02/case.

---

## 2. L4 per-asset page anchors

### Why

L4's loan-agreement scanner returns a single `annexure_page_hint`
covering the asset annexure as a whole. The FE deep-links to it via
`#page=N` already (PR2 commit `f3e4dd4` extended `SourceArtifactCard`
for this). Per-asset anchors would let the assessor click a specific
asset row in the annexure and jump straight to its line in the PDF —
useful when the agreement has 10+ assets.

### Backend pieces

- **Scanner returns per-asset page+line** — extend
  `loan_agreement_scanner` (`backend/app/worker/extractors/loan_agreement_scanner.py`,
  not in current grep but referenced from `level_4_agreement.py:188-196`)
  to return:
  ```python
  assets: [{"description", "category", "page_hint", "line_hint"}, ...]
  ```
  `line_hint` can be a character offset into the page text or a 0–N
  line index — whatever the scanner can stably emit.
- **Evidence shape** — `asset_annexure_empty` and the level-summary
  `assets[]` keep the same outer shape; just gain the two new optional
  fields.

### FE pieces

- `AssetAnnexureCard` already renders the asset rows; add a click
  handler that opens the agreement PDF with `#page={page_hint}` (and
  scrolls to the line server-side once we move to in-app PDF viewer
  with bbox highlight — see §4 below).

### Effort

- Scanner + extraction: 0.5 day (depends on whether the scanner is
  regex-based or LLM-based; LLM path needs prompt iteration)
- Evidence-shape migration: 0.25 day
- FE click-to-page: 0.25 day

**Total: 1 day**.

---

## 3. L2 transaction-anchored CA narrative

### Why

`bank_ca_analyzer` returns `ca_concerns` and `ca_positives` as freeform
strings (`["Salary not credited in Mar 2026", ...]`). The FE renders
them as bullet lists in the new `CaNarrativeCard`. A 30-year underwriter
will ask "show me the transactions that prove that" — today that's a
page-and-search exercise on the bank statement PDF. Anchoring each
narrative bullet to the underlying transaction IDs gives one-click
drill-down.

### Backend pieces

- **CA analyser returns structured concerns** — modify the Haiku prompt
  in `bank_ca_analyzer.py` to return:
  ```python
  ca_concerns: [{"text": "Salary not credited in Mar 2026",
                 "txn_ids": ["txn_abc", "txn_def"],
                 "amount_inr": null,
                 "severity": "warn"}]
  ```
  with a JSON schema. `txn_ids` references the bank-statement
  extraction's per-transaction IDs (`bank_statement_scanner` already
  emits these per-row).
- **Truncation budget** — the analyser currently passes the last 400
  txn lines (`max_tx_lines: 400`). With txn IDs in scope, we can drop
  the truncation: have the analyser run on the full statement and
  reference any txn id it cites. Sonnet can handle the longer context
  cheaply with caching.
- Same shape for `ca_positives`.

### FE pieces

- `CaNarrativeCard` gets a per-bullet expand: click a concern → inline
  table of the linked transactions (date, description, amount). A
  small "+3 more" chip when txn_ids.length > 5.
- Optional: a deep-link to the bank-statement PDF page where that txn
  appears, once the bank-statement scanner emits per-txn page numbers.

### Effort

- CA analyser prompt + schema + tests: 1 day
- Truncation removal + caching tuning: 0.5 day
- FE expand-with-txn-table: 0.5 day

**Total: 2 days**.

---

## 4. In-app PDF viewer with bbox highlight (Phase 2.5)

### Why

`SourceArtifactCard` currently renders PDFs in a plain `<iframe>` with
the browser's built-in viewer. `#page=N` deep-link works but bbox
highlight (the x0/y0/x1/y1 reserved on `SourceArtifactRef`) doesn't —
browsers don't honour bbox fragments. To highlight a specific clause in
the agreement, we need a real PDF renderer.

### Backend pieces

- None. `bbox` is already in the contract.

### FE pieces

- Drop in `pdf.js` (Mozilla's renderer) or a thin wrapper like
  `react-pdf-viewer`. Replace the iframe in `SourceArtifactCard` with
  the new component when the artefact is a PDF.
- When `ref.page` and `ref.bbox` are both present, render a
  semi-transparent rectangle overlay on the page at the bbox coords.
- Keep the iframe fallback for cases where the renderer fails to load
  (CSP / corporate-network gotchas).

### Effort

- Library evaluation + integration: 1 day
- Bbox overlay component: 1 day
- QA across the 3-4 PDF flavours we see (loan agreement, bank
  statement, bureau report): 0.5 day

**Total: 2.5 days**.

---

## 5. L5 per-rubric source artefacts

### Why (lower priority than 1-3)

Today's L5 `ScoringResult.to_dict()` returns per-rubric
`{passed, rationale, evidence}` strings. The new
`L5ScoringRubricTable` renders them in `EvidenceTwoColumn` but the
right column is always "Source files not yet attached for this rule"
because L5 evidence doesn't carry `source_artifacts`. This is fine —
L5 is an aggregator that consumes L0-L4 — but the assessor would
benefit from each rubric pointing back to the L0-L4 evidence row that
fed the verdict.

### Backend pieces

- Each rubric resolver in `scoring_resolvers/*.py` already has a
  `ScoringContext` carrying the L0-L4 evidence. Have the resolver
  populate `source_artifacts: SourceArtifactRef[]` on the row by
  forwarding the relevant L0-L4 evidence's `source_artifacts`.
  Mechanical change per resolver.
- `ScoreRow.to_dict()` gains an optional `source_artifacts` field.

### Effort

- One pass through all 32 resolvers: 0.5 day (mostly mapping rubric →
  upstream level)
- Tests: 0.5 day

**Total: 1 day**.

---

## Sequencing recommendation

1. **L4 per-asset page anchors** (1 day) — quickest win, smallest
   surface area
2. **L5 per-rubric source artefacts** (1 day) — cheap, high marginal
   value for the new rubric table
3. **L2 transaction-anchored CA narrative** (2 days) — biggest UX lift
   for L2 drill-down
4. **In-app PDF viewer with bbox** (2.5 days) — unblocks the bbox
   contract reservation; nice-to-have
5. **L3 per-item stock + crops** (4 days) — biggest piece, requires
   price catalogue work

Total: **10.5 days** of backend work to fully complete the original
verification UI revamp spec. The FE shell shipped on `4level-l1`
absorbs each of these without further refactor — every Phase 2 item
just plugs new structured fields into the existing `EvidenceTwoColumn`
+ `registry.ts` machinery.

---

## Out of scope

- Per-page text extraction with character-offset spans — requires
  upgrading the extractor pipeline; bigger than this brief.
- Side-by-side image diff for "before / after" KYC photos — useful for
  fraud detection but separate epic.
- L5 rubric editor (admin tunes thresholds without a code change) —
  parked under "Editable numeric thresholds on Learning Rules" in the
  prior resume doc; separate spec.
