# Continue from here

Short handoff note. For full context, open
[`RESUME_2026_04_22_PIPELINE_ONEPAGER.md`](RESUME_2026_04_22_PIPELINE_ONEPAGER.md).

---

## Where we are

**Branch:** `4level-l1` · **Commit tip at session start:** `6044b07` · all
work from the latest session is **uncommitted** in the working tree.

**What's live end-to-end:**

- **7-level credit pipeline** on a single Verification tab — L1 Address ·
  L1.5 Credit · L2 Banking · L3 Vision · L4 Agreement · L5 Scoring · L6
  Decisioning. The old "Verification 2" tab is gone.
- **MD Approvals** rewritten in the standard app aesthetic with three
  decision paths: green **Approve**, amber **Approve for this case only**
  (non-learning), red **Reject**.
- **Assessor Queue** (`/assessor/queue`) — OPEN-issues backlog with a
  3-step triage panel per issue (upload → re-run level → promote to MD),
  plus a `regenerate ZIP ↓` link per case dossier.
- **`GET /cases/{id}/artifacts/zip`** — streams a fresh archive of every
  non-deleted artifact.
- **Client-side auto-run orchestrator** — one button on the case detail
  header fires L1 → L6 sequentially with a progress modal, a minimised
  dock, and a live progress ring next to **View** on the Cases list.

**Known rough edges:**

1. Each level re-run appends a fresh `VerificationResult` + `LevelIssue`
   rows — the MD / Assessor queues don't collapse by latest-per-level, so
   Ajay's docket grew 42 → 61 during the session. See §5 P0 of the resume
   doc.
2. `startAutoRun` fires immediately after `finalize` / `reingest`; if
   extractions haven't finished, the first level calls mark themselves
   failed and the user has to hit **Resume**. §5 P1.
3. Tab close kills the auto-run (client-side orchestration). §5 P2 for a
   worker-backed version.

---

## Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -3

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 6
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Login: saksham@pflfinance.com / Saksham123!
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Sanity check: the new endpoints
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/verification/assessor-queue | python3 -c \
  "import json,sys;d=json.load(sys.stdin);print(d['total_open'],'open issues')"
```

**Pages to open:**

- `http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c`
  (Ajay — click **Auto-run all levels** top-right to watch the new modal)
- `http://localhost:3000/admin/approvals` (the three-button flow)
- `http://localhost:3000/assessor/queue` (gap-fix docket + ZIP)

---

## Where the code is

Each module has an opening comment explaining its role.

- `frontend/src/components/autorun/` — new. `AutoRunProvider` is the
  orchestrator + localStorage mirror. `AutoRunModal` / `AutoRunDock` /
  `AutoRunCaseBadge` / `AutoRunTrigger` are the UI surfaces. All
  mounted in `app/(app)/layout.tsx`.
- `frontend/src/components/cases/VerificationPanel.tsx` — L6 row +
  synthesized L6 card wrap live here (search `L6 · Decisioning`).
- `frontend/src/app/(app)/admin/approvals/page.tsx` — MD Approvals
  rewrite. `INTENT_META` constant at the top has the three-intent
  config. Backend marker is `[CASE_SPECIFIC]`.
- `frontend/src/app/(app)/assessor/queue/page.tsx` — Assessor Queue.
- `backend/app/verification/levels/level_5_scoring.py::_grade_drag_context`
  / `_section_drag_context` — the readable drag-context block the MD
  sees on `scoring_grade` and `scoring_section_*` issues.
- `backend/app/verification/levels/level_1_address.py::_load_or_scan_lagr_parties`
  — the LAGR cache UPSERT fix (prior bug: unique-constraint violation on
  L1 re-run).
- `backend/app/api/routers/verification.py::assessor_queue` — new
  `GET /verification/assessor-queue`.
- `backend/app/api/routers/cases.py::download_artifacts_zip` — new
  `GET /cases/{id}/artifacts/zip`.

---

## Next move

**Recommended pick-up:** §5 P0 in the resume doc — collapse the
`md_queue` / `assessor_queue` result sets to the latest
`VerificationResult` per `(case_id, level_number)` so re-running a level
doesn't double-count its issues. One SQL change in two places.

Alternative if you want smaller first: §5 P1 — wait-for-INGESTED before
auto-run kicks off L1 (stops the "failed → Resume" dance when
ingestion is still running).

**Before touching code:** see §2 of the resume doc for the 6 suggested
commit boundaries to cleanly land the existing uncommitted work.
