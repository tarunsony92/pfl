# Session handoff — PFL Credit AI

**Branch:** `4level-l1`
**Last working commit (origin/4level-l1):** `add8dfe`
**Working tree:** lots of uncommitted changes from this session — see `git status`.
**Today:** 2026-04-27

---

## What shipped this session (chronological)

### 1. Final Verdict Report — fix HTTP 500 + auditor-grade rewrite
- `_scoring_table()` in [`backend/app/verification/services/report_generator.py`](backend/app/verification/services/report_generator.py) now uses `_safe_str/_safe_int/_safe_float` defensive readers; renderer never crashes on a malformed `l5.sub_step_results.scoring`
- Wrapped `generate_final_report()` call in [`backend/app/api/routers/verification.py`](backend/app/api/routers/verification.py) `download_final_report` with try/except → structured `{error: render_failed, message, blocking:[]}` 500 instead of bare crash
- Moved `reportlab` from `[tool.poetry.group.dev.dependencies]` → `[tool.poetry.dependencies]` in `backend/pyproject.toml`; regenerated `poetry.lock`. Production image's `poetry install --only main` now actually installs it.
- Added **AI APPROVED stamp** on cover page 1 — pure ReportLab canvas (`_draw_ai_approved_stamp`), no asset file. Stamp date pulls from `data.generated_at`.
- Added **Issue Audit Trail** section (`_issue_audit_trail`) — replaces the old `_decision_log`. Per-issue lifecycle: raised-at → assessor mitigation (timestamp + note) → MD/AI decision (timestamp + actor + status) → rationale. Built from EVERY `LevelIssue`, not just MD-rationaled ones.
- Cover verdict now reads from `DecisionResult.final_decision` (was a heuristic from level statuses)
- Added **Decisioning synthesis (L6)** section — final-decision banner, 11-step pipeline grid, Opus reasoning, pros/cons, conditions, deviations, risk summary
- Total report grew from 7 → 10 pages

### 2. Concerns Resolution progress card on Overview tab
- New endpoint counts: added `md_approved_count` + `md_rejected_count` to `VerificationOverview` Pydantic + Zod schemas
- New [`frontend/src/components/cases/CaseConcernsProgressCard.tsx`](frontend/src/components/cases/CaseConcernsProgressCard.tsx) — stacked bar (green approved + red rejected + amber awaiting + slate open) + breakdown chips + ready-for-report message
- Mounted in [`frontend/src/app/(app)/cases/[id]/page.tsx`](frontend/src/app/(app)/cases/[id]/page.tsx) Overview tab between AI Insights and CAM check
- **Then later moved Final Verdict Report card from Overview → Verification tab** (per user request) so the operator only triggers the download after walking the gate

### 3. Auto-run UX hardening
- Added **`'blocked'` status** to `AutoRunProvider` for `CHECKLIST_MISSING_DOCS` cases. Was previously firing "All steps failed" — now shows distinct amber "Missing required documents" with the actual missing-docs list pulled from `/checklist-validation`
- New [`MissingDocsBanner` + `MissingDocRow`](frontend/src/components/autorun/AutoRunModal.tsx) — admin/CEO-only **Waive** button per missing doc, calls new `POST /cases/{id}/checklist/waive` endpoint
- Backend waive endpoint at [`backend/app/api/routers/cases.py`](backend/app/api/routers/cases.py) — body `{doc_type, justification}`, mutates `present_docs`/`missing_docs` JSONB in-place (no migration), if all blockers cleared chains case stage `CHECKLIST_MISSING_DOCS → CHECKLIST_VALIDATION → CHECKLIST_VALIDATED → INGESTED`. Audit-logs `CHECKLIST_DOC_WAIVED`.
- New **`Download artifacts ZIP`** button on case header — wraps existing `/cases/{id}/artifacts/zip` endpoint
- Added **% progress ring** to AutoRunTrigger button — uses existing `CircularRing` from `AutoRunDock.tsx` so trigger + dock pill match
- Fixed **`L5_5_DEDUPE_TVR` missing from `STEP_ORDER`** — auto-run was jumping L5 → L6 and never firing L5.5. Added to `AutoRunStepKey`, `STEP_ORDER`, and the smart-rerun `verLevels` array
- Fixed the **finalize → ingestion-worker race**: `case_svc.finalize()` and `case_svc.add_artifact()` now return `(case, payload)` tuple, route handler publishes to SQS *after* `session.commit()`. Was producing wedged cases that auto-run polled forever waiting for `CHECKLIST_VALIDATION → INGESTED`.
- Belt-and-braces in [`backend/app/worker/pipeline.py`](backend/app/worker/pipeline.py) `_preflight_stage` — added `CaseStage.UPLOADED` to the self-transition set (worker self-heals if it ever races a finalize commit again)
- Fixed **worker docker healthcheck** — workers have no HTTP server but were inheriting the FastAPI `/health` probe → permanently "unhealthy". Overrode in `docker-compose.yml` with `python -c "import sys; sys.exit(0)"`.
- Fixed pre-existing **`FeedbackWidget` undefined crash** in [page.tsx:408](frontend/src/app/(app)/cases/[id]/page.tsx) — import was commented out earlier but usage wasn't, hard-crashed the case page after dev-server reload

### 4. L5 scoring — every PENDING raises a flag
- [`backend/app/verification/levels/level_5_scoring.py:548`](backend/app/verification/levels/level_5_scoring.py) — dropped the `weight >= 4` filter on PENDING. Every PENDING row now raises a WARNING `LevelIssue` that needs MD/assessor settlement before the final report can render. Description nudges: *"Capture from CAM / source doc, or have MD waive."*

### 5. L5.5 = Dedupe + TVR + NACH + PDC (with Claude vision)
- Renamed level in every label site (admin/approvals, assessor/queue, VerificationPanel title + subtitle, report `level_titles` dict)
- Added **`NACH` presence check** — `nach_present` sub-step in [`level_5_5_dedupe_tvr.py`](backend/app/verification/levels/level_5_5_dedupe_tvr.py); CRITICAL when missing
- Added new artifact subtype **`PDC_CHEQUE`** in `enums.py` + classifier rule in `worker/classifier.py` (matches `pdc`, `post_dated_cheque` filenames BEFORE the generic `BANK_ACCOUNT_PROOF` cancelled-cheque rule)
- Built [`backend/app/verification/services/pdc_verifier.py`](backend/app/verification/services/pdc_verifier.py) — single Sonnet vision call returns `{is_cheque, confidence, bank_name, ifsc, account_number, account_holder, cheque_number, signature_present, is_cancelled, concerns}`. All failures degrade to `vision_error` instead of raising. ~$0.003-0.006 per case.
- L5.5 `pdc_present` sub-step: missing → CRITICAL, vision rejects → CRITICAL, vision errored → WARNING (MD can clear), confirmed → PASS with full evidence
- Added **`pdc_matches_bank` cross-validation** — same module — fetches latest SUCCESS-status `bank_statement` extraction, compares cheque IFSC + account-tail (last 4 digits, masking-aware so `******2084` ↔ `1348002084` matches) + holder name (rapidfuzz token-set ratio, threshold 70). IFSC mismatch → CRITICAL. Account-tail mismatch → CRITICAL. Name fuzz < 70 → WARNING. Either side missing → silently skipped. 6/6 unit-test cases pass.
- Added **PDD escalation block** in `IssueRow` for `pdc_present`/`pdc_matches_bank` CRITICAL OPEN issues (admin/CEO only): one-click **"Resolve with PDD approval"** button that wraps existing `decide_issue` endpoint with `[PDD] PDC to be collected post-disbursement. <justification>` rationale prefix. Uses the MD-short-circuit path (status OPEN → MD_APPROVED, no assessor handoff needed).

### 6. L1 — Geocoded distance between mismatched addresses *(today)*
- Added [`google_maps.forward_geocode`](backend/app/verification/services/google_maps.py) (address → `(lat, lon)`) and [`haversine_km`](backend/app/verification/services/google_maps.py) (great-circle km) helpers
- L1 engine in [`level_1_address.py`](backend/app/verification/levels/level_1_address.py) computes distance via forward-geocode + haversine for BOTH:
  - `applicant_coapp_address_match` — both addresses text → forward-geocode both
  - `gps_vs_aadhaar` — Aadhaar address text → forward-geocode it, photo coords already lat/lng
- Distance stamped into `issue.evidence['distance_km']` (rounded to 3 dp) + appended to description as `Geocoded distance ≈ X.XX km.`
- New [`frontend/src/components/cases/evidence/DistanceBadge.tsx`](frontend/src/components/cases/evidence/DistanceBadge.tsx) — colored pill: <1 km green ("walking distance / joint family"), 1-10 km amber ("same town"), ≥10 km red ("different localities")
- Wired into both `AddressMatchCard` and `GpsVsAadhaarCard` (the dedicated evidence-registry cards for these sub_step_ids — NOT the GenericFireBody fallback)
- Verified end-to-end on case `4e9432d9-…` (Gaurav Baroka): both issues now show `distance_km: 2.618` and `2.546` km, FE renders the amber badge.

---

## Things to pick up next (in priority order)

### A. Assessor PDD-request flow *(deferred — user asked, then pivoted)*
**The ask:** in the missing-docs banner, the assessor (not just MD) needs a button to request PDD approval. Auto-run should then proceed; a CRITICAL "PDD unavailable" flag gets raised somewhere; MD later approves → flips to MD_APPROVED.

**Sketch design:**
- New endpoint `POST /cases/{id}/checklist/request-pdd` (any role)
  - Body `{doc_type, justification}`
  - Same JSONB mutation as `/waive` but adds `pdd_pending: true` to the present_docs entry
  - Stage transitions still happen → auto-run unblocks
- Frontend: in `MissingDocRow`, add a second button "Request PDD approval" alongside "Waive" (which is admin/CEO-only). PDD button is visible to assessors too.
- After auto-run runs, L5.5 (or a new L5.6) should detect `present_docs.pdd_pending=true` entries and create CRITICAL `LevelIssue` rows tagged `pdd_pending_<doc_type>` with status=ASSESSOR_RESOLVED + assessor_note=`[PDD-REQUEST] <justification>`
- MD adjudicates via the existing `/decide` endpoint → flips MD_APPROVED or MD_REJECTED
- Final report's audit trail picks it up automatically (already iterates every LevelIssue)

**Where to start:** `backend/app/api/routers/cases.py` next to the existing `waive_missing_doc`. Frontend `AutoRunModal.tsx` `MissingDocRow` component.

### B. PDC field-level cross-validation v2
- Currently `pdc_matches_bank` only compares cheque ↔ bank statement
- User asked for it; v1 is shipped. Next refinement: also compare against L1's KYC scan (Aadhaar holder name) so a cheque in the spouse's name is caught even when the bank statement is in the right account
- Look at `gps_vs_aadhaar`'s `addresses_match` fuzz utility for the matching pattern

### C. Test the full PDC happy path with a real cheque image
- Case 7bdea924 has a `10006079_NACH_1.jpeg` artifact tagged `NACH` (not PDC). Vision check skipped because no PDC artifact found.
- Upload a real cheque via Add Artifact dialog with PDC filename pattern → re-run L5.5 → should hit Sonnet vision, extract IFSC/account/name, then `pdc_matches_bank` should run against bank statement
- Look at the screenshot the user attached earlier in the session — the Kotak cheque with UMRN `KKBK7031604261002563`, account `1348002084`, IFSC `KKBK0004328`, Customer: AMIT KUMAR

### D. Clean up any orphan code / unused imports
- The `decisions: list[DecisionBrief]` field on `FinalReportData` was removed cleanly; verify no test still references it
- The `waive` endpoint is named — should probably rename for consistency with REST patterns later (`PATCH /checklist/waivers` etc) but not blocking

---

## How the local dev environment is wired

- **Compose:** `docker-compose.yml` at repo root. Services: `pfl-backend` (FastAPI on `:8000`), `pfl-worker` (SQS consumer), `pfl-decisioning-worker`, `pfl-postgres`, `pfl-localstack` (S3 + SQS).
- **Backend hot-reload:** the volume mounts `./backend/app:/app/app` make file changes visible inside the container, but uvicorn runs WITHOUT `--reload`. `docker restart pfl-backend` to pick up Python changes. Same for `pfl-worker`.
- **Frontend dev server:** `preview_start name=frontend` from launch.json — `npm run dev --prefix frontend` on `:3000`. Has HMR.
- **Browser preview server ID:** check `preview_list` — currently `be588d6e-7e7b-4602-90f3-f8823d5219c4` for the frontend.
- **Test user:** `saksham@pflfinance.com`, role=`admin`. Auth via `/users/me` (NOT `/auth/me` — that returns 404).
- **Csrf:** mutating endpoints require `x-csrf-token` header. Read from `csrf_token` cookie. Admin POSTs from preview_eval need this.
- **Google Maps API key:** `GOOGLE_MAPS_API_KEY` env var on `pfl-backend` (already configured in `.env`). Used for reverse-geocode + the new forward_geocode.

## Recurring "things that bit me"

1. **CSS uppercase tricks the `innerText` check** — `class="uppercase"` doesn't change DOM text. Search by source case, not rendered case.
2. **Radix Tabs need PointerEvent** — `.click()` alone doesn't switch tabs. Use `['pointerdown','mousedown','pointerup','mouseup','click'].forEach(t => el.dispatchEvent(new PointerEvent(t, {bubbles:true})))`.
3. **Container restart loses pip-installs** — `pip install` inside a running container is reset on `docker restart` since the venv is not on the volume mount. Either bake into the image (Dockerfile / pyproject) or accept it'll go away.
4. **The `Verification` tab text is `"Verification1"` etc.** because the badge "1" is concatenated with no separator in `innerText`. Use `startsWith('Verification')` not `=== 'Verification'`.
5. **Worker `_preflight_stage` is the gate that wedges cases** when stage=UPLOADED reaches the worker before the route handler commits. Now self-heals, but watch this if a new "stage X is not a valid re-ingest stage" warning appears.

## Files modified this session (scope)

```
backend/app/api/routers/cases.py          waiver endpoint + finalize race fix
backend/app/api/routers/verification.py   final-report router + L6 wire + counts
backend/app/enums.py                      PDC_CHEQUE
backend/app/models/checklist_validation_result.py    (untouched, JSONB-only mutation)
backend/app/pyproject.toml                reportlab → main
backend/poetry.lock                       regenerated
backend/app/schemas/verification.py       md_approved_count + md_rejected_count
backend/app/services/cases.py             finalize/add_artifact return (entity, payload)
backend/app/verification/levels/level_1_address.py    distance_km wiring
backend/app/verification/levels/level_5_5_dedupe_tvr.py   NACH + PDC + pdc_matches_bank
backend/app/verification/levels/level_5_scoring.py    every PENDING raises issue
backend/app/verification/services/google_maps.py      forward_geocode + haversine_km
backend/app/verification/services/pdc_verifier.py     NEW
backend/app/verification/services/report_generator.py   defensive + stamp + audit trail + decisioning + IssueLifecycle
backend/app/worker/classifier.py          PDC_CHEQUE filename rule
backend/app/worker/pipeline.py            preflight tolerates UPLOADED
docker-compose.yml                        worker healthcheck override

frontend/src/app/(app)/admin/approvals/page.tsx       L5.5 label
frontend/src/app/(app)/assessor/queue/page.tsx        L5.5 label
frontend/src/app/(app)/cases/[id]/page.tsx            ProgressCard mount, FinalReportCard moved, ZIP button, FeedbackWidget fix
frontend/src/components/autorun/AutoRunCaseBadge.tsx  blocked status
frontend/src/components/autorun/AutoRunDock.tsx       blocked status, ring colors
frontend/src/components/autorun/AutoRunModal.tsx      MissingDocsBanner + MissingDocRow + Waive flow + blocked status
frontend/src/components/autorun/AutoRunProvider.tsx   blocked status, L5.5 in STEP_ORDER, race-fix wait logic, RUN_BLOCKED action
frontend/src/components/autorun/AutoRunTrigger.tsx    % ring + blocked status handling
frontend/src/components/cases/CaseConcernsProgressCard.tsx  NEW
frontend/src/components/cases/VerificationPanel.tsx   PDD escalation block, L5.5 rules + label, distance refactored to dedicated cards
frontend/src/components/cases/actions/DownloadArtifactsZipButton.tsx  NEW
frontend/src/components/cases/evidence/AddressMatchCard.tsx   distance badge wire
frontend/src/components/cases/evidence/DistanceBadge.tsx  NEW
frontend/src/components/cases/evidence/GpsVsAadhaarCard.tsx   distance badge wire
frontend/src/lib/api.ts                   checklistWaive client
frontend/src/lib/types.ts                 VerificationOverview new fields
```

## What I'd do first if I picked this up cold

1. `git status` to see the uncommitted spread
2. Boot the stack: `docker compose up -d backend worker pfl-decisioning-worker postgres localstack` then `preview_start name=frontend`
3. Open `localhost:3000/cases/4e9432d9-66b8-48ea-b82f-454d8101f1a4` (Gaurav Baroka, INGESTED, has both L1 distance issues triggered)
4. Verify the screenshot still matches what's in this README — the **DISTANCE BETWEEN ADDRESSES · 2.62 km apart** badge should be visible above the applicant/co-applicant address pair on the L1 panel
5. If everything still works → tackle item A (assessor PDD-request flow) first, that's the most-overdue user ask
6. Final-report PDF: `curl /cases/{id}/final-report` should return 200 with ~34KB / 10 pages. Use this as the smoke test that nothing's broken.
