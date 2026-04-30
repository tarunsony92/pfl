# PFL Finance Credit AI

Two-phase credit decisioning and auditing system for Premium Finlease Private Limited.

**📖 New here? Read `docs/KNOWLEDGE_TRANSFER.md` first** — it covers the whole
system end-to-end (architecture, code walkthrough, setup, hosting, levels,
data model, conventions). This README is the quick-reference; KT is the
deep dive.

**Design spec:** `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md`
**Milestone 1 plan:** `docs/superpowers/plans/2026-04-18-m1-backend-foundation-auth.md`

## What's done

**M1 — Backend Foundation + Auth** (tag `m1-backend-foundation`)
- Auth (password + JWT + MFA), users, audit log, seed CLI, Docker

**M2 — Case Upload & Storage** (tag `m2-case-upload-storage`)
- Case and artifact entities with 14-state workflow enum
- Case stage machine with transition enforcement + audit
- S3 storage service (aioboto3) with LocalStack for dev
- SQS queue service with DLQ (RedrivePolicy, maxReceiveCount=3) for ingestion jobs
- 8 endpoints: initiate, finalize, artifact upload, list, detail, download, approve-reupload, soft-delete
- Re-upload flow with archival of prior state to versioned JSON
- Startup lifespan auto-creates bucket + queues in dev

**M3 — Ingestion Workers** (tag `m3-ingestion-workers`)
- ZIP-unpack + document classifier (keyword + fuzzy matching via rapidfuzz) for 30+ artifact subtypes
- Five extractors: AutoCAM (XLSX), PD Sheet (XLSX), Checklist (XLSX), Equifax HTML, Bank Statement (PDF/text)
- Checklist completeness validator (hard + soft requirement rules per spec §4.6)
- Fuzzy dedupe engine (RapidFuzz) comparing extracted applicant name/PAN against Customer_Dedupe table
- End-to-end ingestion pipeline with CaseExtraction + ChecklistValidationResult + DedupeSnapshot/Match persistence
- SES email notifications (submission confirmation, validation result, re-upload request)
- System worker user seeded on startup; Pydantic read schemas for extraction + dedupe endpoints
- 391 tests passing (unit + integration); ruff clean; mypy clean (58 files, 0 errors)

**M4 — Next.js Frontend** (tag `m4-frontend`)
- Next.js 14 (App Router), TypeScript strict, Tailwind + PFL palette, shadcn/ui primitives (Button, Input, Card, Badge, Dialog, Dropdown, Tabs, Toast)
- HttpOnly-cookie refresh flow + JS-readable CSRF token (closes M1-C1); Route Handler proxy at `/api/proxy/*` with single-flight refresh and X-CSRF-Token enforcement in `middleware.ts`
- Screens: `/login` (MFA-aware), `/cases` (filter + paginated table with StageBadge), `/cases/[id]` (Overview/Artifacts/Extractions/Checklist/Dedupe/AuditLog tabs + Re-upload/Re-ingest/Add-artifact dialogs), `/cases/new` (3-step upload wizard), `/settings/profile` (password + MFA), `/admin/users` (role/active toggles), `/admin/dedupe-snapshots` (xlsx upload)
- Polling hook (5s on in-flight stages, tab-visibility aware) keeps case detail fresh during worker processing
- 5 new backend endpoints: self-service password change, admin user active toggle (closes M1-I2), per-case audit log, underwriter own-case filter, cookie-based auth/refresh
- 198 Vitest tests + 3 Playwright E2E scenarios; coverage ≥80% on `lib/`, 90%+ on `components/cases/`; accessibility audit 20/20 PASS
- Docker: new `pfl-web` service wired into docker-compose alongside backend + worker + postgres + localstack

## Quick start (local)

1. Copy env templates. The backend container reads from `backend/.env`
   (see `docker-compose.yml`'s `env_file:`); the Next.js FE reads from
   `frontend/.env.local` only when run outside Docker:
   ```bash
   cp .env.example backend/.env
   cp frontend/.env.local.example frontend/.env.local
   # then edit backend/.env and rotate JWT_SECRET_KEY:
   #   openssl rand -hex 32
   # paste the result into JWT_SECRET_KEY=
   # set ANTHROPIC_API_KEY=sk-ant-... (required for L1.5 / L2 / L3 / L5 / L5.5
   # Claude calls — leave blank to bring the stack up but verification levels
   # that hit Claude will fail until a real key is set).
   ```

2. Boot stack:
   ```bash
   docker compose up -d
   ```
   Postgres + backend + worker + frontend (Next.js) + LocalStack all boot.
   Backend init creates the S3 bucket and SQS queues against LocalStack.

3. Create first admin:
   ```bash
   docker compose exec backend python -m app.cli seed-admin \
     --email you@pflfinance.com --full-name "Your Name"
   ```

4. Open the app:
   - Web UI:  http://localhost:3001  (login with the admin you just seeded)
   - API docs: http://localhost:8000/docs

## Testing

```bash
cd backend
export PATH="$HOME/.local/bin:$PATH"
poetry install
poetry run pytest -v --cov=app
```

**M5 — Phase 1 Decisioning Engine** (tag `m5-decisioning-engine`)
- 11-step Phase 1 decisioning pipeline with Claude API cascade (Opus 4 for synthesis, Sonnet 4.5 for steps 2-10, step 1 pure Python policy gates)
- Pipeline orchestrator (`engine.py`) with per-step DB persistence and resume-from-last-successful semantics
- Case library (pgvector 8-dim feature vector + cosine similarity retrieval via MRP pricing database)
- Memory subsystem: `policy.yaml` (100+ NBFC rules) + `heuristics.md` (domain wisdom) loaded with prompt-cache prefill
- Decisioning SQS worker (`worker_decisioning`) consuming `pfl-decisioning-jobs` queue
- 5 new API endpoints: `POST /cases/{id}/phase1`, `GET` result/steps/step-N, `POST` cancel
- Phase 1 tab in case detail UI: status badge, 11-step progress table, final decision card (outcome/amount/confidence/conditions/reasoning/pros-cons/deviations)
- 557 backend tests (10 new), 206 frontend tests (8 new); ruff clean; mypy clean; tsc clean

## Milestones roadmap

- **M1** ✅ Backend Foundation + Auth
- **M2** ✅ Case Upload & Storage
- **M3** ✅ Ingestion Workers (ZIP unpack, doc classification, CAM/Checklist/PD/Equifax extraction, dedupe, email)
- **M4** ✅ Next.js frontend (login, case list, case detail with 6 tabs, upload wizard, settings, admin screens, polling)
- **M5** ✅ Phase 1 Decisioning Engine (11-step pipeline, Claude API cascade, MRP database)
- **M6** ← *Next* Phase 2 Audit Engine (30-point scoring)
- **M6** Phase 2 Audit Engine (30-point scoring)
- **M7** Memory subsystem + NPA retrospective
- **M7** Memory subsystem + NPA retrospective
- **M8** AWS Mumbai deploy via CDK
- **M9** Shadow rollout + validation

## Architecture

See `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md` §4.

## Project layout

```
pfl-credit-system/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routers + deps
│   │   ├── core/             # security primitives + domain exceptions
│   │   ├── models/           # SQLAlchemy ORM models
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # business logic (auth, users, audit, cases, storage, queue)
│   │   ├── cli.py            # admin CLI (click-based)
│   │   ├── config.py         # env settings
│   │   ├── db.py             # async engine + session
│   │   ├── enums.py
│   │   ├── main.py
│   │   └── startup.py        # dev resource init (bucket + queues)
│   ├── alembic/              # migrations
│   ├── tests/                # pytest
│   ├── Dockerfile
│   └── pyproject.toml
├── docs/superpowers/         # specs + plans
├── docker-compose.yml
├── .env.example
└── README.md
```

## Notes

- CLI is implemented with `click` directly (not `typer`) due to a confirmed incompatibility between `typer` 0.12.5 and `click` 8.3 that treats string options as boolean flags.
- Dev database uses timezone-aware timestamps (`TIMESTAMP WITH TIME ZONE`) for `created_at`/`updated_at`; see Alembic migration `9270485d69ee`.

---

# Picking up the project

This section is the on-ramp for any developer joining the codebase. It maps
what exists today, where the moving pieces live, and which file to open
when a specific change is needed. Pair it with `SESSION_HANDOFF.md`
(latest session notes) and `docs/superpowers/RESUME_*.md` (deeper context
behind each shipped feature).

## Current state at a glance

The product has progressed well past M5. The branch `4level-l1` ships:

- **L0 — CAM discrepancy gate** — flags SystemCam vs CM CAM IL mismatches
  before any verification fires.
- **L1 — Address verification** — KYC + address proof + GPS-watermarked
  photo + Aadhaar/CIBIL address reconciliation, plus a Google-Maps
  driving-time commute check between house and business locations.
- **L1.5 — Credit history** — applicant + co-applicant Equifax/CIBIL
  scan: six status scanners (write-off / loss / settled / substandard /
  doubtful / SMA), a 680/700 credit-score floor, and a Claude Opus
  willful-default + fraud narrative.
- **L2 — Banking** — Claude Opus CA-grade analysis of the bank
  statement plus seven hard rules (NACH bounces, avg-balance vs EMI,
  credits vs declared income, payer concentration, impulsive debits,
  chronic low balance, 6-month coverage, narrative concerns).
- **L3 — Vision** — Claude Opus scoring of house + business premises
  photos; per-item stock breakdown with bbox crops + MRP catalogue
  lookup + cattle/service classification.
- **L4 — Agreement audit** — annexure / hypothecation / asset-count
  enforcement on the signed loan agreement PDF.
- **L5 — 32-point FINPAGE rubric** — final scoring across credit /
  banking / assets / references; pulls signal from L0–L4 and from a
  fresh Opus-4.7 income-proof analyser; section + grade summaries.
- **L5.5 — Dedupe + TVR + NACH + PDC** — dedupe XLSX scan, TVR audio
  presence, NACH mandate presence, plus a Claude vision PDC verifier
  with bank-statement cross-validation.
- **L6 — Decisioning synthesis** — 11-step Phase-1 pipeline (see M5)
  consumes the verification results at the highest weight and emits the
  final decision the cover page renders.
- **Auto-run orchestrator** (frontend): triggers L1 → L6 from a single
  click, with smart skip-already-passed, completeness-gate prompt for
  missing required artefacts, and a guaranteed L6 finisher.
- **MD approvals + assessor queues** with carry-forward of terminal
  decisions across re-runs.
- **Final Verdict Report** — ReportLab PDF with AI-approved stamp,
  per-issue lifecycle audit, and L6 synthesis section.

## Architecture in one diagram

```
        upload (zip / loose files)
                 │
                 ▼
   ┌────── Stage machine ──────┐
   │ UPLOADED → CLASSIFIED →   │
   │ EXTRACTING → INGESTED     │
   └─────────────┬─────────────┘
                 │
       ┌─────────┴──────────┐
       │  Worker pipeline   │   (worker/pipeline.py)
       │  - classifier      │   (worker/classifier.py)
       │  - extractors  ────┤   (worker/extractors/*.py)
       │  - dedupe          │   (services/dedupe + dedupe_snapshot)
       │  - email           │   (services/email.py)
       └─────────┬──────────┘
                 ▼
   ┌──────  Verification pipeline  ──────┐
   │ L0 CAM discrepancy → L1 → L1.5 →    │   (verification/levels/*.py)
   │ L2 → L3 → L4 → L5 → L5.5            │
   └─────────────────┬───────────────────┘
                     ▼
        ┌──── L6 / Phase-1 decisioning ────┐
        │   11 Claude steps → DecisionResult │   (decisioning/engine.py)
        └─────────────────┬─────────────────┘
                          ▼
              Final Verdict Report PDF
              (services/report_generator.py)
```

Auto-run dispatches each level via the existing
`POST /verification/cases/{id}/levels/{N}/trigger` endpoint, then polls
for completion. MD approvals and assessor resolutions write back to
`LevelIssue` rows — re-runs `carry_forward_prior_decisions` so terminal
decisions survive across triggers.

## Code map — where to make a change

### Verification levels (`backend/app/verification/levels/`)

Each file is the orchestrator for that level. Pure cross-checks
(`cross_check_*`) sit at the top, pass-evidence builders
(`build_pass_evidence_*`) in the middle, and the `async run_level_*`
orchestrator at the bottom. To add a rule:

1. Write a `cross_check_<rule>(...) -> dict | None` helper.
2. Wire it into the orchestrator's loop (mirror the existing entries).
3. Mirror it in `build_pass_evidence_*` so the FE sees a pass entry.
4. Register the `sub_step_id` in the frontend's `RULE_CATALOG.L<N>`.

### Verification services (`backend/app/verification/services/`)

External integrations + structured Claude calls. Notable entries:

- `address_normalizer.py` — address tokenisation + fuzzy-match.
- `bank_ca_analyzer.py` — Claude Opus CA analysis of bank statements.
- `commute_judge.py` — Opus judge for the house ↔ business commute.
- `credit_analyst.py` — Opus willful-default + fraud scan.
- `google_maps.py` — geocoding + Routes API + haversine.
- `income_proof_analyzer.py` — Opus 4.7 multi-doc income-proof analyser.
- `pdc_verifier.py` — Claude vision PDC cheque cross-validation.
- `report_generator.py` — ReportLab Final Verdict PDF.
- `scoring_model.py` — 32-point rubric resolvers (`r_a01` … `r_d32`).
- `vision_scorers.py` — Sonnet vision scorers for L3 house/business.

### Workers (`backend/app/worker/`)

- `pipeline.py` — orchestrates classify → extract → dedupe per case.
- `classifier.py` — keyword + fuzzy + heuristic doc classification.
- `extractors/` — one file per artefact type (auto_cam, bank_statement,
  equifax, aadhaar_scanner, pan_scanner, dedupe_report, etc.).
- `image_crop.py` — L3 per-item bbox crop helper.

### API (`backend/app/api/routers/`)

- `cases.py` — case CRUD, finalize, artifact upload, ZIP download,
  checklist waive, missing-doc PDD-request stubs.
- `verification.py` — trigger / overview / detail / resolve / decide.
  Holds the TOCTOU / SELECT FOR UPDATE concurrency for level promotion.
- `incomplete_autorun.py` — completeness gate + defaulter log.
- `admin_rules.py`, `mrp_catalogue.py`, `admin_negative_area.py`,
  `admin_l3_rerun.py` — admin control surfaces.
- `notifications.py` — topbar bell.

### Frontend (`frontend/src/`)

- `components/cases/` — case-detail tabs (Verification, Verification 2,
  Overview, Artifacts, Extractions, Audit, MD Approvals).
- `components/cases/evidence/` — per-rule "smart cards" rendered for
  individual fire / pass evidence (commute, bureau-row, distance,
  avg-balance vs EMI, dedupe identity, etc.).
- `components/autorun/` — `AutoRunProvider`, `AutoRunModal`,
  `AutoRunDock`, `AutoRunTrigger`, `MissingDocsBanner`.
- `app/(app)/cases/[id]/page.tsx` — top-level case detail screen.
- `app/(app)/admin/*` — admin pages (Learning Rules, MRP catalogue,
  Negative Areas, Stale L3 Rerun, Incomplete Auto-Runs).
- `lib/useVerification.ts` — verification hooks + queue subscriptions.

### Migrations (`backend/alembic/versions/`)

Filename prefix encodes order. Recent ones to know:

- `c4d5e6f7a8b9_4level_verification_l1.py` — verification tables.
- `b9c0d1e2f3a4_add_rule_overrides.py` — admin learning-rules.
- `d1e2f3a4b5c6_add_mrp_catalogue_entries.py` — MRP catalogue.
- `e2f3a4b5c6d7_add_negative_area_pincodes.py` — pincode blocklist.
- `g1h2i3j4k5l6_add_incomplete_autorun_log.py` — defaulter log.

## "I want to…" cheat-sheet

| Goal | Open this file first |
|---|---|
| Add a new verification rule | `verification/levels/level_<N>_*.py` |
| Tweak a 32-point rubric resolver | `verification/services/scoring_model.py` (`r_*` functions) |
| Edit the Final Report PDF | `verification/services/report_generator.py` |
| Add an extractor for a new doc | `worker/extractors/<name>.py` + register in `worker/classifier.py` |
| Add a subtype enum | `app/enums.py` (`ArtifactSubtype`), update tests in `tests/unit/test_enums.py` |
| Surface a new admin control | new router under `api/routers/admin_*.py` + sidebar entry in `components/layout/Sidebar.tsx` |
| Render a smarter evidence card | `components/cases/evidence/<RuleName>Card.tsx` + register in the dispatcher |
| Re-wire auto-run for a new level | `components/autorun/AutoRunProvider.tsx` (`STEP_ORDER`) |
| Suppress a flaky rule globally | `/admin/learning-rules` (admin UI) — backed by `RuleOverride` |
| Override an MRP for a business type | `/admin/mrp-catalogue` (admin UI) |

## Common commands

```bash
# Backend tests
cd backend && poetry run pytest -v --cov=app

# Frontend tests
cd frontend && npm test

# Boot full stack
docker compose up -d

# New Alembic migration
cd backend && poetry run alembic revision --autogenerate -m "<msg>"

# Run a single verification level on a case (CLI / shell)
curl -X POST "$API/verification/cases/<id>/levels/1/trigger" -H "$AUTH"
```

## Where to look when something is off

- **Auto-run hangs**: check `worker/pipeline.py` `_preflight_stage` (case
  may be stuck pre-`INGESTED`); check `frontend/.../AutoRunProvider.tsx`
  `STEP_ORDER` for a missing level.
- **PDF report 500s**: try/except wrapper is in `routers/verification.py`
  `download_final_report` — surfaces a `{error: render_failed, …}` JSON;
  the actual stack lives in the worker logs.
- **Concurrency bug on level promotion**: `routers/verification.py`
  around the `SELECT … FOR UPDATE` block on `decide_issue` — that
  serialises sibling MD decisions for one VR.
- **A rule fires when it shouldn't**: check
  `/admin/learning-rules` first (might be intentionally suppressed via
  `RuleOverride`); otherwise look for the `cross_check_*` source in
  `verification/levels/level_*.py`.
- **CAM extraction looks wrong**: `worker/extractors/auto_cam.py`
  scoped right-column scan + `services/cam_discrepancy.py` for the
  SystemCam vs CM CAM IL diff.

## Current open work / known gaps

See `SESSION_HANDOFF.md` for the latest session's bullet list. Persistent
items at time of writing:

- **Assessor PDD-request flow** — endpoint exists for admin/CEO `waive`
  but assessors still need a parallel "request PDD approval" path that
  raises a CRITICAL flag instead of waiving silently.
- **CAM-vs-agreement asset diff** — L4 currently only checks the
  agreement's own annexure. The cross-check against `auto_cam`'s asset
  list is gated on the CAM extractor surfacing a structured asset list,
  which it doesn't yet.
- **Memory subsystem (M7)** — `policy.yaml` + `heuristics.md` are wired,
  but the NPA retrospective loop that learns from outcomes is not.
- **AWS deploy (M8)** — local Docker only today; CDK stubs not started.

Refer to `FOLLOW_UPS.md` for the running scratch list.
