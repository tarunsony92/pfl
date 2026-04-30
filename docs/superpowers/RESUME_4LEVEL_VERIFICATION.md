# Resume — 4-Level Verification Gate + MD Approvals + AutoJustifier

> **Open a new Claude Code session in this repo and paste this file's path
> (`docs/superpowers/RESUME_4LEVEL_VERIFICATION.md`) to pick up exactly
> where the audit / verdict session left off.**

**Spawned:** 2026-04-22
**Parent session:** the audit / verdict session (branch `4level-l1`).
**Latest commit hash on branch:** run `git log --oneline -25` to see.
**Status at handoff:** Phases A→E of the 4-level gate shipped. MD Approvals
docket + photos endpoint + precedents endpoint + AutoJustifier service all
written (AutoJustifier not yet wired into level engines — see §4 below).
Backend tests: **698 passing · 7 skipped · 7 pre-existing MFA failures**
(unrelated to this work; caused by `DEV_BYPASS_MFA=true` in `backend/.env`).

---

## 1. What ships today (and works live on Ajay's case)

| Phase | Feature | Status | Tag |
|---|---|---|---|
| A | **L1 Address** — Aadhaar/PAN/ration Claude-vision scanners + GPS reverse-geocode + address cross-checks + resolve/MD-decide | Live | `4level-l1` |
| B | **L2 Banking** — NACH bounce, avg balance, credit-sum vs declared income, payer concentration, impulsive-debit ratio, Claude CA-narrative | Live | committed on branch |
| C | **L3 Vision** — Claude Sonnet vision on house + business photos, condition ratings, stock-vs-loan | Live | committed on branch |
| D | **L4 Agreement** — scanned-PDF annexure extractor (Claude Haiku vision), asset diff, hypothecation clause check | Live | committed on branch |
| E | **Step 11 upgrade** — 4-level outputs consumed at highest weight, confidence 60→70 | Live | committed on branch |
| + | **MD Approvals sidebar** — dedicated page `/admin/approvals` with docket view, filters, pending badge | Live | aa1cce9-ish |
| + | **Photos endpoint** `/cases/{id}/photos/{HOUSE_VISIT_PHOTO,BUSINESS_PREMISES_PHOTO}` | Live | not yet committed |
| + | **Precedents endpoint** `/verification/precedents/{sub_step_id}` | Live | not yet committed |
| + | **AutoJustifier service** — `app/verification/services/auto_justifier.py` | Written, NOT wired | not yet committed |
| + | **GPS watermark OCR fallback** — `app/verification/services/gps_watermark.py` (Claude Haiku reads the burn-in overlay on GPS-Map-Camera photos when EXIF is stripped by WhatsApp) | Live, wired into L1 engine | not yet committed |
| + | **Status label fix** — distinguishes "N ISSUES" (engine succeeded, raised concerns) from "PROCESS FAILED · reason" (engine errored); the old UI labelled both as FAIL | Live | not yet committed |
| + | **Test conftest hermetic teardown** — `DROP SCHEMA public CASCADE` so the test DB tolerates leftover tables from parallel sessions (primary's CAM-discrepancy tables used to block drop_all) | Live | not yet committed |

**Verified live on Ajay (`7bdea924-225e-4b70-9c46-2d2387fc884c`):**
- L1 BLOCKED by `ration_owner_rule` (HARJEET KAUR is not applicant/co-app)
- L2 BLOCKED by `chronic_low_balance` (avg balance ₹487)
- L3 BLOCKED by `house_living_condition` (Sonnet rated "bad")
- L4 not yet run on this session's reset; earlier run was BLOCKED by `asset_annexure_empty` (page 18 annexure has zero assets)
- L1+L2+L3 aggregate cost on live Anthropic: **$0.072** total.

---

## 2. How to resume

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git branch                     # confirm on 4level-l1
git log --oneline -25
git status                     # check uncommitted work from prior session

# Stack
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
# Expected: pfl-backend, pfl-worker, pfl-decisioning-worker, pfl-postgres, pfl-localstack all Up + healthy

# Frontend dev server (next.js) — runs on host, not in docker
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Login creds (dev only)
# saksham@pflfinance.com / Saksham123!  (role=admin, DEV_BYPASS_MFA on)
```

Point your browser at `http://localhost:3000`. Ajay's case id is
`7bdea924-225e-4b70-9c46-2d2387fc884c`. Use **Verification** tab to exercise
the gate, **MD Approvals** in the sidebar for the cross-case docket.

### Quick sanity checks
```bash
# Backend health
curl -s http://localhost:8000/health
# Expect: {"status":"ok"}

# Auth
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Overview (all 4 levels)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification | jq

# MD queue
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/verification/md-queue | jq '.total_awaiting_md, .total_open'

# Photos (house)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/photos/HOUSE_VISIT_PHOTO | jq '.items | length'
```

---

## 3. Architecture snapshot

### Backend
```
backend/app/
  verification/
    __init__.py
    engine.py                    # (not currently used — level engines are called directly)
    levels/
      __init__.py
      level_1_address.py         # 7 sub-steps + cross-check helpers + run_level_1_address()
      level_2_banking.py         # CA rules + Claude narrative + run_level_2_banking()
      level_3_vision.py          # house/business scorers + run_level_3_vision()
      level_4_agreement.py       # scanner + asset diff + run_level_4_agreement()
    services/
      address_normalizer.py      # rapidfuzz-based address + name matching
      exif.py                    # GPS from JPEG EXIF
      google_maps.py             # httpx → Google Geocoding API
      auto_justifier.py          # ⚠ written but NOT wired into engines — see §4
  api/routers/
    verification.py              # trigger / overview / detail / resolve / decide
                                 # + md-queue + photos + precedents
  models/
    verification_result.py
    l1_extracted_document.py
    level_issue.py
  schemas/verification.py        # Pydantic schemas for all responses
  worker/extractors/
    aadhaar_scanner.py           # Claude Haiku vision
    pan_scanner.py
    ration_bill_scanner.py
  decisioning/steps/
    step_11_synthesis.py         # modified in Phase E — consumes 4-level outputs
```

### Frontend
```
frontend/src/
  app/(app)/
    cases/[id]/page.tsx          # 8 tabs incl. Verification + MD Approvals
    admin/approvals/page.tsx     # MD Adjudication Docket
  components/
    cases/VerificationPanel.tsx  # clean structural level cards + photo gallery + precedents
    layout/Sidebar.tsx           # MD Approvals link + pending-count badge
  lib/
    types.ts                     # zod schemas for verification domain
    api.ts                       # cases.verification* + casePhotos + fetchPrecedents
    useVerification.ts           # SWR hooks: overview, level-detail, md-queue, photos, precedents
```

### DB tables added
- `verification_results` — one row per (case, level) run
- `l1_extracted_documents` — one row per scanned ID/address doc
- `level_issues` — concerns with lifecycle OPEN → ASSESSOR_RESOLVED → MD_APPROVED / MD_REJECTED

### Postgres enum types added
`verification_level_number`, `verification_level_status`, `level_issue_status`,
`level_issue_severity`, `l1_doc_type`, `l1_party`.

### Alembic migration
`backend/alembic/versions/c4d5e6f7a8b9_4level_verification_l1.py` — idempotent
up/down; run `alembic upgrade head` in the backend container after pulling.

---

## 4. ⚠️ AutoJustifier — written but NOT wired yet

`backend/app/verification/services/auto_justifier.py` implements the
Claude-Sonnet self-resolve pass. Given a fresh `LevelIssue` + past MD
rulings + case context, it asks Claude whether the concern can be dismissed
with ≥75% confidence (80% for CRITICAL, 70% for WARNING). Matching issues
are marked `MD_APPROVED` with the rationale prefixed
`[AI auto-justified @ confidence X%]` and `md_user_id = NULL` so the UI can
distinguish AI decisions from human ones.

### Required to finish the feature
1. **Hook into each level engine** — right before each `run_level_X_*()`
   computes `final_status` from the in-memory `issues` list. Insert:

   ```python
   # app/verification/levels/level_1_address.py (similar in L2/L3/L4)
   from app.verification.services.auto_justifier import (
       auto_justify_level_issues,
       AI_MARKER_MD_PREFIX,
   )
   from app.enums import LevelIssueStatus

   # persist issues first (already done above — session.add(LevelIssue(...)))
   await session.flush()

   # re-fetch persisted issues
   stmt = select(LevelIssue).where(LevelIssue.verification_result_id == result.id)
   issue_rows = list((await session.execute(stmt)).scalars())

   # let Claude try to self-resolve
   resolved_count, justify_cost = await auto_justify_level_issues(
       session=session,
       case_id=case_id,
       issue_rows=issue_rows,
       claude=claude,
   )
   total_cost += justify_cost

   # recompute final_status based on issues that are STILL OPEN after the pass
   remaining_critical = any(
       i.status in (LevelIssueStatus.OPEN, LevelIssueStatus.ASSESSOR_RESOLVED)
       and i.severity == LevelIssueSeverity.CRITICAL
       for i in issue_rows
   )
   any_auto_resolved = resolved_count > 0
   if remaining_critical:
       final_status = VerificationLevelStatus.BLOCKED
   elif any_auto_resolved:
       final_status = VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE
   else:
       final_status = VerificationLevelStatus.PASSED
   ```

2. **Frontend badge** — when `issue.md_user_id` is `null` and
   `issue.md_rationale.startswith("[AI auto-justified")`, render an
   "AI-resolved" purple pill on the issue row in:
   - `frontend/src/components/cases/VerificationPanel.tsx` (IssueRow)
   - `frontend/src/app/(app)/admin/approvals/page.tsx` (DocketRow)

3. **Unit tests** — `backend/tests/unit/test_auto_justifier.py`:
   - Mocks `ClaudeService`, passes a synthetic `LevelIssue`, verifies the
     right status transitions under each confidence/severity combo.
   - Guards: CRITICAL at 79% stays OPEN; WARNING at 70% auto-resolves;
     network/parse failure leaves status untouched.

4. **Cost budget** — target <$0.05 per case on average across auto-justify
   calls (typical 5-10 issues × ~$0.015 Sonnet per issue). Alert if
   `total_cost_usd > decisioning_cost_abort_usd * 0.3`.

---

## 5. Files changed in this session (not yet committed)

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status --short
```

Recent uncommitted (relative to `4level-l1` tip):

- `backend/app/api/routers/verification.py` — added md_router, `/md-queue`,
  `/photos/{subtype}`, `/precedents/{sub_step_id}` endpoints
- `backend/app/schemas/verification.py` — `MDQueueItem`, `MDQueueResponse`,
  `CasePhotoItem`, `CasePhotosResponse`, `PrecedentItem`, `PrecedentsResponse`
- `backend/app/verification/services/auto_justifier.py` — NEW
- `backend/app/main.py` — mounts `md_router`
- `backend/tests/conftest.py` — `DROP SCHEMA public CASCADE` fix so tests
  hermetic against primary session's CAM-discrepancy tables
- `frontend/src/components/layout/Sidebar.tsx` — MD Approvals link + badge
- `frontend/src/components/cases/VerificationPanel.tsx` — clean structural
  rewrite; photo gallery + precedents panel inline in IssueRow
- `frontend/src/app/(app)/admin/approvals/page.tsx` — NEW docket page
- `frontend/src/app/(app)/cases/[id]/page.tsx` — tab reorder (Overview →
  Verification → Phase 1 → rest)
- `frontend/src/app/layout.tsx` — Instrument Serif + JetBrains Mono fonts
  (still referenced via CSS variables but current UI uses Inter throughout)
- `frontend/src/lib/types.ts` — MDQueue, Photos, Precedents zod schemas
- `frontend/src/lib/api.ts` — cases.verification* + verification.mdQueue +
  casePhotos + fetchPrecedents
- `frontend/src/lib/useVerification.ts` — `useMDQueue`, `useCasePhotos`,
  `usePrecedents` SWR hooks

Suggested commit groupings when you pick this up:
1. `feat(4level): MD Approvals sidebar + docket page (/admin/approvals)`
2. `feat(4level): photos endpoint + precedents endpoint + inline UI`
3. `chore(tests): hermetic DROP SCHEMA CASCADE in conftest`
4. `feat(4level): AutoJustifier service + wire into L1/L2/L3/L4`
5. `feat(4level): frontend AI-resolved badge on issues`

---

## 6. Running tests

```bash
# Whole suite (takes ~70 s — Claude vision mocks + DB roundtrips)
docker exec -e TEST_DATABASE_URL='postgresql+asyncpg://pfl:pfl_dev@postgres:5432/pfl_test' \
  pfl-backend sh -c "cd /app && python -m pytest tests/ --tb=line --no-cov \
    -p no:cacheprovider --asyncio-mode=auto -q"

# Only verification-domain tests
docker exec -e TEST_DATABASE_URL='postgresql+asyncpg://pfl:pfl_dev@postgres:5432/pfl_test' \
  pfl-backend sh -c "cd /app && python -m pytest tests/unit/test_verification_* tests/unit/test_extractors_*_scanner.py tests/unit/test_vision_scorers.py --tb=short --no-cov -p no:cacheprovider --asyncio-mode=auto"

# Frontend typecheck
cd frontend && npx tsc --noEmit
# Expect 1 pre-existing error in DecisioningPanel.test.tsx (AWAITING_REVIEW stage), unrelated.
```

### Known-failing tests (not your bug — do not fix without user OK)

The 7 failing integration tests all live in:
- `tests/integration/test_auth_router.py` — 4 MFA flow tests
- `tests/integration/test_auth_service.py` — 3 MFA flow tests

They were green before `DEV_BYPASS_MFA=true` was added to `backend/.env`.
To run them cleanly, temporarily unset the env var:

```bash
docker exec -e DEV_BYPASS_MFA=false -e TEST_DATABASE_URL='postgresql+asyncpg://pfl:pfl_dev@postgres:5432/pfl_test' \
  pfl-backend sh -c "cd /app && python -m pytest tests/integration/test_auth_router.py tests/integration/test_auth_service.py -q"
```

---

## 7. Dev ergonomics quirks

| Symptom | Fix |
|---|---|
| Frontend shows "Something went wrong" after many HMR edits | Kill dev server, `rm -rf frontend/.next/cache frontend/.next/server/vendor-chunks`, restart `npm run dev`. Stale webpack vendor chunks are the usual cause. |
| Backend code changes not reflected | `docker restart pfl-backend` — uvicorn caches imports. Volume mounts are live (see `docker-compose.yml`), but the Python process must be bounced. |
| Test runs error: `DependentObjectsStillExistError: cannot drop table cases` | Fixed in this session — `conftest.py` now uses `DROP SCHEMA public CASCADE`. Before the fix, the primary session's CAM-discrepancy tables blocked schema teardown. |
| `pytest: not found` in pfl-backend | The prod image skips dev deps. Install runtime: `docker exec -u root pfl-backend pip install --quiet "pytest>=8.3,<9" "pytest-asyncio>=0.24,<1" pytest-cov moto factory-boy reportlab`. Persists across restarts until the container is rebuilt. |
| Localstack loses S3 state after restart | Re-upload case files. For Ajay: map filenames back from DB with `SELECT filename, s3_key FROM case_artifacts WHERE case_id = '...'` and `awslocal s3 cp` each local file into its expected key. Script from this session lives in the earlier RESUME_AUDIT_VERDICT_SESSION.md. |

---

## 8. Config + secrets

- `backend/.env` (gitignored) holds `ANTHROPIC_API_KEY`, `GOOGLE_MAPS_API_KEY`, `DEV_BYPASS_MFA`, plus standard DATABASE_URL / JWT_SECRET_KEY.
- Google Maps API key provisioned on 2026-04-22 for L1 GPS reverse-geocode — paid tier, has quota.
- Anthropic key is personal; Sonnet + Haiku calls are the dominant spend (~$0.05-0.15 per case for all 4 levels).

---

## 9. Next-up work queue (priority order)

### P0 — Finish AutoJustifier
Per §4 above. Estimated 1-2 hours including tests + wiring + the frontend badge.

### P1 — Photo gallery UX polish
- Lightbox for full-size zoom (currently opens in new tab).
- Show Claude's per-photo reasoning inline (currently only aggregate house/business
  rating is captured; add per-image narrative to the Claude prompt in
  `level_3_vision.py` and surface it under each thumbnail).

### P2 — Extractor address capture
L1's bureau/bank address cross-checks currently read `bureau_addresses_considered: []`
because the Equifax + bank_statement extractors don't pull address into `data.addresses`.
Fix:
- `backend/app/worker/extractors/equifax.py` — parse `<table id="addressTable">`
  or scan the raw HTML for `Address:` blocks. Current code returns `addresses: []`
  for all 3 Ajay reports.
- `backend/app/worker/extractors/bank_statement.py` — extract address from the
  header block (regex for lines that follow the account holder name in SBI
  format). Currently returns `address: null` / `account_holder_address: null`.

Once fixed, run `POST /cases/{id}/reingest` + `POST /cases/{id}/verification/L1_ADDRESS`
and the "0 found" ticks will go green.

### P3 — L3 merge logic: don't conflate different people
Ajay's case has `KYC_AADHAAR` files that include `UID front.PNG`, `UID back.PNG`,
AND Gordhan's Aadhaar (misclassified). My merge picks first-non-null per field,
so "applicant" can end up with Ajay's name + Gordhan's address. Fix:
- Group scans by identity (same `extracted_number` or high-similarity name).
- Reclassify Gordhan's Aadhaar as `CO_APPLICANT_AADHAAR` (or a new `FAMILY_AADHAAR`)
  in the classifier.

### P4 — Case row backfill
Ajay's `cases.loan_amount`, `cases.loan_tenure_months`, `cases.co_applicant_name`
are NULL (his case pre-dates those columns). Backfill:
```sql
UPDATE cases SET loan_amount = 100000, loan_tenure_months = 24,
  co_applicant_name = 'Gordhan' WHERE id = '7bdea924-225e-4b70-9c46-2d2387fc884c';
```
Then the Overview tab's "Loan Amount" and "Tenure" will stop showing "—".

### P5 — Async worker for level triggers
L3 Vision takes 30-60s synchronously. Move to the same SQS pattern as
`pfl-decisioning-worker`: new `pfl-verification-worker` that consumes
`pfl-verification-jobs`. Endpoint returns 202 + `verification_result_id`; UI
polls `GET /cases/{id}/verification/{level_number}` every 5s until status ≠ RUNNING.

### P6 — Learning engine v2
Today precedents are fetched at decision time via SQL. Upgrade:
- Add a `md_learning_corpus` table with a pgvector feature embedding of
  `(sub_step_id, case_extracts_summary, md_rationale)`.
- On new issue: embed the case-side signal, kNN against past MD decisions,
  feed top-5 into AutoJustifier as a much richer precedent set than raw SQL
  can give.

---

## 10. Key code landmarks (line numbers as of handoff)

- `backend/app/api/routers/verification.py:105` — `trigger_level` dispatcher
- `backend/app/api/routers/verification.py:344` — `decide_issue` (promotes to PASSED_WITH_MD_OVERRIDE when all issues settled)
- `backend/app/api/routers/verification.py:392` — `md_queue` (admin/CEO only)
- `backend/app/api/routers/verification.py:448` — `list_case_photos` (presigned URLs)
- `backend/app/api/routers/verification.py:503` — `get_precedents`
- `backend/app/verification/levels/level_1_address.py:233` — `run_level_1_address`
- `backend/app/verification/levels/level_1_address.py:540` — status calc + finalise (this is the hook-point for AutoJustifier)
- `backend/app/verification/services/auto_justifier.py:202` — `auto_justify_level_issues` entry-point
- `frontend/src/components/cases/VerificationPanel.tsx` — clean structural UI
- `frontend/src/app/(app)/admin/approvals/page.tsx` — MD docket

---

## 11. When you finish next chunk of work

1. Commit with focused messages (prefix `feat(4level):` or `chore(4level):`).
2. Update this file's §1 status table + §5 uncommitted list.
3. Tag release points: after AutoJustifier lands, tag `4level-autojustifier`.
4. Ping the primary session via `docs/superpowers/RESUME_AUDIT_VERDICT_SESSION.md`
   — append SHAs + one-liner under "Done in audit-session".
