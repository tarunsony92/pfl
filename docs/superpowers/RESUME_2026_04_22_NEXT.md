# 🚦 PFL Credit AI — Resume for Further Functionality

> Paste this file's path into a new Claude Code session to pick up exactly
> where we stopped. Everything needed to ship the next feature is either in
> this file or referenced from it.

**Last updated:** 2026-04-22 (after Phase 1 skip-redundancy + rename +
notifications bell + CAM discrepancy engine landed)

**Active branches:**
| Branch | HEAD | What's on it |
|---|---|---|
| `main` | `da1ae01` docs(resume) | M1–M5 + M4 polish + CAM discrepancy engine |
| `4level-l1` | `0d543d0` feat(notifications) | Everything on main + 4-Level Verification gate + skip-redundancy + bell |

**Latest tag:** `m4-frontend-1.2` (predates both the 4-level gate and the
discrepancy engine — cut a new tag after the branch merge below).

---

## ✅ What shipped in the session just completed

| SHA | Branch | Scope |
|---|---|---|
| [7efbfe0](../../commit/7efbfe0) | `4level-l1` | Skip Verification-covered Phase 1 steps (2/4/5/6/7) + rename "Phase 1" → "Verification 2" in the UI |
| [0d543d0](../../commit/0d543d0) | `4level-l1` | Topbar notifications bell + backend `/notifications` service |
| [c6daee2](../../commit/c6daee2) | `main` | CAM discrepancy detector + models + migration + 20 unit tests |
| [9fc9765](../../commit/9fc9765) | `main` | Discrepancy HTTP router + Phase 1 gate + 11 integration tests |
| [83ab04f](../../commit/83ab04f) | `main` | Discrepancies frontend tab + resolve UI |
| [d22afb6](../../commit/d22afb6) | `main` | Overview banner + Phase 1 "Start" button tooltip |
| [1371c36](../../commit/1371c36) | `main` | XLSX report exporter |

**Live verification on Ajay (`7bdea924-…`):**
- Phase 1 now runs 6 steps, skips 5 (all SUCCEEDED / SKIPPED). Cost
  dropped from $0.47 → $0.43 per run. Final verdict unchanged
  (ESCALATE_TO_CEO — L2 and L3 still BLOCKED in Verification, correct).
- Discrepancy detector flags the 7.25 pp FOIR gap between SystemCam
  (25.35 %) and CM CAM IL (18.1 %), persisted as a WARNING row.
- Notifications bell serves `GET /notifications` HTTP 200 via proxy.

---

## 🔀 Blocking: `4level-l1` → `main` merge must happen before ANY further live feature

Both branches touch the same files (tabs, types, api.ts) and both added
an alembic head on top of `b2c3d4e5f6a7`. Before shipping anything else
live, do this merge:

### 1. Reconcile alembic heads
`main` has `c3d4e5f6a7b8` (cam discrepancy), `4level-l1` has
`c4d5e6f7a8b9` (verification). Same parent. Pick one to become the
child of the other. Recommended:
```bash
git checkout 4level-l1
git rebase main
# rebase will stop on the migration. Edit
# backend/alembic/versions/c4d5e6f7a8b9_...py
# and set  down_revision = "c3d4e5f6a7b8"
git add backend/alembic/versions/c4d5e6f7a8b9_*.py
git rebase --continue
```

### 2. Resolve expected conflicts
Hotspots (both branches appended):
- `frontend/src/app/(app)/cases/[id]/page.tsx` — both added tabs + imports.
- `frontend/src/lib/types.ts` — both appended Zod schemas.
- `frontend/src/lib/api.ts` — both appended client methods.

Each is append-only style so the resolution is "keep both"; just de-dup
any duplicate imports/types if they overlap (the `dedupeSnapshots` and
`verification` exports, the `CaseExtractionRead` type, etc.).

### 3. Apply the combined migration to the live `pfl` DB
```bash
docker compose exec backend alembic upgrade head
```
The live test DB (`pfl_test`) is rebuilt from `Base.metadata` per-run
(see `backend/tests/conftest.py`) so tests stay independent of this.

### 4. Rebuild all containers, then live-verify on Ajay
```bash
docker compose build backend worker pfl-decisioning-worker pfl-web
docker compose up -d --force-recreate
```
Expected: Overview banner lit, Discrepancies tab active, Verification
tab lit, Verification 2 tab runs 6 / skips 5, bell icon populates.

### 5. Tag it
`m4-frontend-1.3` (rename for the merged branch → `main` state). Push
the tag.

---

## 🧠 Notifications feature — v1 is intentionally minimal

Current shipped behavior:
- Computed on demand from existing tables (no per-user state).
- Sources: missing docs, failed extractors, critical extractor
  warnings, blocking CAM discrepancies (when that service is present).
- Polls `/notifications` every 60 s + revalidates on window focus.
- Click → jumps to `/cases/{id}?tab={action_tab}`.

Obvious follow-ups if you want them, ordered by value / effort:

1. **Read / dismiss state** (per-user) — needs a `notification_reads`
   table keyed on `(user_id, notif_id_hash)`. Bell goes dim after read.
   Effort: half-day.
2. **Server-Sent Events push** — replace polling with real-time push
   on audit-log write. Much snappier for assessors on active cases.
   Effort: 1 day.
3. **Scope filter by `assigned_to`** — right now EVERY assessor sees
   every case's issues. Filter to assigned + own uploaded. Effort:
   small backend query + role-aware endpoint.
4. **Per-extractor warning allow-list config** — some warnings are
   noise per reviewer. Store a user-scoped mute list. Effort: small.
5. **Inline re-upload right from the dropdown** — user clicks
   notification → inline modal to upload the missing file without
   leaving the bell. Effort: medium (wizard Step 2 is reusable).

---

## 🎯 Remaining milestones (parent spec)

| Milestone | Status | Blocking on |
|---|---|---|
| M6 — Phase 2 Audit Engine | **Spec drafted**, build deferred. 30-point full fill + 150-point partial + mismatch log + 1-2 page exec summary. | Spec at `docs/superpowers/specs/2026-04-21-m6-audit-engine-design.md`. Needs user's `30 Point Scoring Model Draft.xlsx` + `150-point` template + a sample exec summary before code starts. |
| M7 — Memory / Learning | Seed only. Replace M5's 8-dim feature vector with Voyage embeddings; UI for policy.yaml + heuristics.md; NPA retrospective loop; synthesize heuristic proposals from case feedback. | Needs `policy.yaml` seed, past-case dataset with downstream outcome labels, Voyage API key. |
| M8 — AWS Mumbai deploy | — | Needs AWS account (ap-south-1), domain, SES sender verification, budget ceiling. |
| M9 — Shadow rollout | — | Needs 20-30-case validation dataset + 100 live cases + on-call rotation + rollback criteria. |

The gap list (what to ask the user for at each milestone start) lives
in `RESUME_HERE.md` under "What I need from you".

---

## 🧹 Near-term polish tasks (no spec needed, do when relevant)

- **Bell unread count after merge:** once the 4-level merge lands, the
  bell will start surfacing both `DISCREPANCY_BLOCKING` and verification-
  level BLOCKED notifications at the same time. Consider grouping by
  kind in the dropdown to avoid visual noise on a single noisy case.
- **MD Approvals sidebar counter:** the sibling's `MD Approvals` item
  shows a live count (19–32 in recent screenshots). The bell's
  "awaiting_md" signal should reuse the same query for consistency.
- **Verification 2 tab — expand SKIPPED rows:** currently just shows
  "covered by L2 Banking" as italic subtitle. Could link that text
  straight to the Verification tab → L2 detail card. Tiny UX win.
- **XLSX report → add the 4-level verdicts** (L1 PASSED / L2 BLOCKED
  etc.) to the Summary sheet. Credit ops wants one sheet per case
  that tells the whole story.
- **Phase 1 gate for verification BLOCKED** — currently `cases.py`
  Phase 1 trigger only blocks on unresolved CRITICAL discrepancies. A
  BLOCKED verification level should also 409 with a structured payload
  pointing to the Verification tab. Parallel of the discrepancy gate.
- **Extractor logs surfaced to notifications:** today only `warnings[]`
  feeds the bell. A failed-extract with `error_message` but no
  `warnings` entry would miss. Add `error_message` check into the
  notifications service.

---

## 🧪 Test + CI status at session end

| Suite | Count | Notes |
|---|---|---|
| Backend (`main`) | 619 passed, 7 skipped | conftest MFA bypass hardening applied |
| Backend (`4level-l1`) | 737 passed, 7 skipped, 1 failure | 1 sibling test `test_ration_scanner_name_and_schema_version` — unrelated to this session |
| Frontend (`main`) | 243 passed | +2 pre-existing sibling typecheck warnings on `admin/approvals/page.tsx` (missing L5_SCORING map key) |
| Frontend (`4level-l1`) | +3 NotificationsBell tests | Radix DropdownMenu jsdom limitation — production click-through verified manually |

---

## 🛠️ Environment refresher

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
docker compose up -d postgres localstack backend worker pfl-decisioning-worker

# Frontend (native, not docker)
cd frontend && npm run dev   # → http://localhost:3000

# Log in
#   email:    saksham@pflfinance.com
#   password: Saksham123!
#   (DEV_BYPASS_MFA=true in backend/.env — gitignored)
```

Test case: `7bdea924-225e-4b70-9c46-2d2387fc884c` (loan_id `10006079`,
Ajay Singh). All 41 artifacts classified, extractions run, Phase 1 +
Verification 2 already completed.

Anthropic API key lives in `backend/.env` (gitignored, auto-loaded via
`env_file:` directive on every compose service that needs it).

Port lock-down: all dev ports bound to `127.0.0.1` only. LAN
unreachable.

---

## 📌 Handoff protocol for the next session

1. Start by reading this file top to "Blocking".
2. If the 4level-l1 → main merge hasn't happened yet, that is the
   **first task** — everything else depends on it. Follow the 5-step
   plan above.
3. After merge + live-verify, decide between:
   - **M6 start** (Phase 2 Audit Engine — ask user for the xlsx templates)
   - **Near-term polish** (pick from the list above based on what the
     user pointed at last)
   - **Notifications feature-set expansion** (read/dismiss, SSE, scope)
4. Commit per logical chunk. Always re-run `pytest -q` + `vitest run`
   before committing.
5. Update this file + `RESUME_HERE.md` at session end.

---

*End of forward-looking resume. Session state verified live on the
running stack as of commit `0d543d0`.*
