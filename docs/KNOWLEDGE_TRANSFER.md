# PFL Credit AI — End-to-End Knowledge Transfer

> One document, everything you need to ship code on this system.
> Pair with `README.md` (Quick Start) and `SESSION_HANDOFF.md` (latest
> dev-session notes). Living document — keep it current as you change
> the system.

**Last updated:** 2026-04-27 · maintained against branch `main` /
`4level-l1` (currently identical).

---

## Table of contents

1. [What this software does](#1-what-this-software-does)
2. [Architecture in one diagram](#2-architecture-in-one-diagram)
3. [Tech stack](#3-tech-stack)
4. [Repo layout](#4-repo-layout)
5. [Local setup (developer machine)](#5-local-setup-developer-machine)
6. [Hosting / deployment](#6-hosting--deployment)
7. [Backend code walkthrough](#7-backend-code-walkthrough)
8. [Frontend code walkthrough](#8-frontend-code-walkthrough)
9. [Verification levels deep-dive (L0 → L6)](#9-verification-levels-deep-dive-l0--l6)
10. [Phase-1 Decisioning engine (L6)](#10-phase-1-decisioning-engine-l6)
11. [Data model](#11-data-model)
12. [Background jobs & queues](#12-background-jobs--queues)
13. [External integrations](#13-external-integrations)
14. ["I want to…" cheat-sheet](#14-i-want-to-cheat-sheet)
15. [Testing](#15-testing)
16. [Migrations (Alembic)](#16-migrations-alembic)
17. [Conventions (code, branches, commits)](#17-conventions-code-branches-commits)
18. [Gotchas + FAQ](#18-gotchas--faq)
19. [Glossary](#19-glossary)

---

## 1. What this software does

**PFL Credit AI** is a two-phase credit-decisioning and auditing system
for **Premium Finlease Private Limited** (PFL), an Indian NBFC issuing
unsecured + lightly-secured loans to MFI / MSME borrowers.

**Problem it solves.** PFL's existing credit operations are spreadsheet-
and-paperwork heavy: a branch uploads a ZIP of borrower documents (KYC,
bank statement, electricity bill, ration card, photos, CAM workbook,
agreement PDF, dedupe report, TVR audio, NACH mandate, post-dated
cheque image, etc.), and a credit manager reads ~30 documents to make a
yes/no/rework decision. The manual review takes hours per case, is
inconsistent across branches, and produces no audit trail when an NPA
later occurs. PFL Credit AI turns that ZIP into a **structured, auditable,
mostly-automated decision** with:

- Mechanical extraction of every field the credit manager would read
  (CAM, bureau, bank statement, KYC).
- A **7-level verification gate** (L0 → L5.5) that flags every policy
  breach, fraud signal, or missing document with a CRITICAL / WARNING
  severity, source-file citation, and recommended fix.
- A **Phase-1 decisioning engine** (L6) — 11 Claude steps that synthesise
  all the verifications into a final approve / approve-with-conditions /
  reject / escalate-to-CEO recommendation, with reasoning + pros / cons
  / deviations.
- An assessor + MD approval workflow on every flagged concern: assessors
  resolve / waive issues with audit notes; MDs approve deviations.
- A **Final Verdict Report PDF** with AI-approved stamp, per-issue
  lifecycle audit, and L6 synthesis — the artifact handed to the
  applicant and the regulator.

**Two phases.** *Phase 1* is the pre-disbursal decision. *Phase 2* (M6,
upcoming) will run a 30-point retrospective audit on disbursed loans
that turn NPA — feeding back into the decisioning rules. This codebase
ships Phase 1 + the L0-L5.5 verification stack that powers it.

**Who uses it.** Branch ops upload ZIPs · Assessors resolve issues ·
Credit HO does TVR + fraud calls · MD / CEO approve deviations · Admin
manages users, learning-rules, MRP catalogue, negative-area pincode list,
re-runs.

---

## 2. Architecture in one diagram

```
                               ┌──────────────────────────┐
                               │  branch ops uploads ZIP  │
                               │  (or admin re-upload)    │
                               └────────────┬─────────────┘
                                            ▼
                              ┌─── Stage machine ────┐
                              │ UPLOADED → CLASSIFIED│
                              │ → EXTRACTING →       │
                              │    INGESTED          │
                              └──────────┬───────────┘
                                         │
                  ┌──────────────────────┴───────────────────────┐
                  │  Worker: ingestion pipeline                  │
                  │   1. download + unzip from S3                │
                  │   2. classify each file (subtype enum)       │
                  │   3. run extractors per subtype:             │
                  │        AutoCAM xlsx · PD sheet · Equifax     │
                  │        HTML · Bank stmt PDF · Ration / elec  │
                  │        bill · Aadhaar · PAN · Loan agree-    │
                  │        ment · Dedupe XLSX · Checklist xlsx   │
                  │   4. dedupe vs Customer_Dedupe table         │
                  │   5. checklist completeness validation       │
                  │   6. SES email — submitted / missing-docs    │
                  └──────────────────────┬───────────────────────┘
                                         ▼
                  ┌──── Verification pipeline (L0 → L5.5) ────┐
                  │  L0  CAM discrepancy gate                 │
                  │  L1  Address (Aadhaar + GPS + ration)     │
                  │  L1.5 Credit history (Equifax / CIBIL)    │
                  │  L2  Banking (Opus CA analyser + rules)   │
                  │  L3  Vision (house + business + stock)    │
                  │  L4  Loan-agreement audit                 │
                  │  L5  32-point FINPAGE rubric              │
                  │  L5.5 Dedupe + TVR + NACH + PDC checks    │
                  └──────────────────────┬────────────────────┘
                                         ▼
                ┌──── L6 / Phase-1 decisioning (worker) ────┐
                │   11 Claude steps:                         │
                │     1 policy gates (pure Python)           │
                │     2 banking · 3 income · 4 KYC           │
                │     5 address · 6 business · 7 stock       │
                │     8 reconciliation · 9 PD sheet          │
                │     10 retrieval (pgvector cases lib)      │
                │     11 synthesis (Opus, MD-grade)          │
                └──────────────────────┬─────────────────────┘
                                       ▼
                          ┌─── DecisionResult ────┐
                          │ APPROVE / APPROVE_WITH│
                          │ _CONDITIONS / REJECT /│
                          │ ESCALATE_TO_CEO       │
                          └────────────┬──────────┘
                                       ▼
                       Final Verdict Report PDF
                       (services/report_generator.py)
                       — AI-approved stamp, issue audit
                       trail, L6 synthesis
```

**Three runtime processes**, talking via Postgres + SQS:

1. **`backend`** (FastAPI) — HTTP API + auth + cookie sessions. Mounts
   ~14 routers. Synchronous from the FE's POV.
2. **`worker`** (`python -m app.worker`) — long-poll consumer of the
   `pfl-ingestion-dev` SQS queue. Runs the ingestion pipeline. Stateless,
   scalable horizontally.
3. **`pfl-decisioning-worker`** (`python -m app.worker_decisioning`) —
   long-poll consumer of `pfl-decisioning-jobs`. Runs the 11-step
   Phase-1 pipeline. Separate queue + worker because Claude calls are
   slow and we don't want them blocking ingestion.

**Storage layer.** Postgres (case state, extractions, issues, decisions)
+ S3 (ZIPs, individual artifacts, generated PDFs). LocalStack mocks S3 +
SQS + SES in dev so nothing hits real AWS.

**Verification levels are NOT background jobs.** They run **inline**
inside the `verification` router when the FE calls `POST /verification/
cases/{id}/levels/{N}/trigger`. The Auto-Run Provider on the FE
sequences L1 → L6 and polls; each level returns when its
`VerificationResult` row is committed. That is why the levels block UI
during execution — Claude calls within a level can take 30-90s.

---

## 3. Tech stack

### Backend
- **Python 3.12** + **Poetry** — `backend/pyproject.toml`.
- **FastAPI 0.115** + **Pydantic v2** + **uvicorn** — HTTP layer.
- **SQLAlchemy 2 (async)** + **asyncpg** — DB driver. Models use
  `Mapped[...]` typed annotations.
- **Alembic** — migrations under `backend/alembic/versions/`.
- **bcrypt + PyJWT + pyotp** — password hashing, JWT issuance, MFA TOTP.
- **aioboto3** — async AWS SDK for S3 / SQS / SES.
- **Anthropic SDK** (`anthropic ^0.96`) — Claude API. Multiple models
  used: Opus 4.7 (1M context) for synthesis + CA + vision; Sonnet 4.5
  for fast cross-checks.
- **rapidfuzz** — fuzzy name / address matching.
- **pdfplumber** — bank-statement + LAGR text extraction.
- **openpyxl** — CAM / dedupe / checklist xlsx parsing.
- **beautifulsoup4 + lxml** — Equifax / CIBIL HTML parsing.
- **reportlab** — Final Verdict Report PDF generation. Pure Python, no
  external binaries.
- **pgvector** — 8-dim case-similarity feature vector for the
  decisioning retrieval step.
- **pytest + pytest-asyncio** — testing.

### Frontend
- **Next.js 14** (App Router) + **TypeScript strict** + **React 18**.
- **Tailwind** + custom PFL palette (see `tailwind.config.ts`) +
  **shadcn/ui** primitives in `components/ui/` (button, card, dialog,
  dropdown, label, badge, skeleton, empty-state).
- **SWR** — data fetching + caching. Per-resource hooks in `lib/use*.ts`.
- **react-hook-form + zod** — form validation.
- **Vitest + @testing-library/react** — unit tests.
- **Playwright** — e2e under `frontend/e2e/`.

### Infra (dev)
- **Postgres 16 (Docker)** — single-node.
- **LocalStack 3** — mocks S3 + SQS + SES.
- **docker compose** — wires backend + worker + decisioning-worker +
  pfl-web (Next.js) + postgres + localstack.

### Infra (prod, planned M8)
- **AWS Mumbai (ap-south-1)** via **CDK**.
- ECS Fargate for backend + workers.
- RDS Postgres.
- S3 for artifacts.
- SQS for ingestion + decisioning queues.
- SES for transactional emails.

---

## 4. Repo layout

```
pfl-credit-system/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py             # FastAPI deps (session, current_user, role guards)
│   │   │   └── routers/            # one file per HTTP surface
│   │   │       ├── auth.py         # login + refresh + MFA
│   │   │       ├── users.py        # admin user mgmt
│   │   │       ├── cases.py        # case CRUD, finalize, artifacts, ZIP, reupload
│   │   │       ├── verification.py # trigger / overview / detail / resolve / decide
│   │   │       ├── cam_discrepancies.py
│   │   │       ├── dedupe_snapshots.py
│   │   │       ├── notifications.py
│   │   │       ├── incomplete_autorun.py
│   │   │       ├── admin_rules.py            # learning-rules / suppressions
│   │   │       ├── admin_l3_rerun.py         # bulk re-run L3 vision
│   │   │       ├── admin_negative_area.py    # pincode blocklist
│   │   │       ├── mrp_catalogue.py
│   │   │       └── health.py
│   │   ├── core/                   # security primitives, exceptions
│   │   ├── models/                 # SQLAlchemy ORM (one file per table)
│   │   ├── schemas/                # Pydantic request/response shapes
│   │   ├── services/               # business logic — pure async, no HTTP
│   │   │   ├── auth.py             # password + JWT + MFA
│   │   │   ├── cases.py            # initiate / finalize / reupload / soft-delete
│   │   │   ├── case_completeness.py # required-artefact computation
│   │   │   ├── stages.py           # case-stage state machine
│   │   │   ├── audit.py            # audit log writes
│   │   │   ├── storage.py          # S3 (aioboto3)
│   │   │   ├── queue.py            # SQS (aioboto3) — ingestion + decisioning
│   │   │   ├── email.py            # SES (transactional)
│   │   │   ├── notifications.py    # bell-feed for the topbar
│   │   │   ├── claude.py           # Anthropic SDK shim
│   │   │   ├── cam_discrepancy.py  # SystemCam ↔ CM CAM IL diff engine
│   │   │   ├── cam_discrepancy_report.py
│   │   │   ├── mrp_catalogue.py    # MRP lookup logic
│   │   │   └── users.py
│   │   ├── verification/
│   │   │   ├── levels/             # one file per level (L0–L5.5)
│   │   │   │   ├── _common.py      # carry_forward_prior_decisions, helpers
│   │   │   │   ├── level_1_address.py
│   │   │   │   ├── level_1_5_credit.py
│   │   │   │   ├── level_2_banking.py
│   │   │   │   ├── level_3_vision.py
│   │   │   │   ├── level_4_agreement.py
│   │   │   │   ├── level_5_scoring.py     # 32-point FINPAGE rubric
│   │   │   │   └── level_5_5_dedupe_tvr.py
│   │   │   ├── services/           # external integrations + Claude calls
│   │   │   │   ├── address_normalizer.py  # tokenisation + name_matches()
│   │   │   │   ├── bank_ca_analyzer.py    # Opus CA
│   │   │   │   ├── credit_analyst.py      # Opus willful-default scan
│   │   │   │   ├── commute_judge.py       # Opus house↔business commute
│   │   │   │   ├── google_maps.py         # geocoding + Routes API
│   │   │   │   ├── nominatim.py           # fallback geocoder
│   │   │   │   ├── pincode_lookup.py
│   │   │   │   ├── income_proof_analyzer.py # Opus 4.7 multi-doc
│   │   │   │   ├── pdc_verifier.py        # Claude vision PDC + bank match
│   │   │   │   ├── exif.py
│   │   │   │   ├── gps_watermark.py
│   │   │   │   ├── vision_scorers.py      # Sonnet vision (house + biz)
│   │   │   │   ├── auto_justifier.py
│   │   │   │   ├── scoring_model.py       # 32-pt resolvers r_a01 … r_d32
│   │   │   │   ├── report_generator.py    # Final Verdict PDF
│   │   │   │   └── commute_inputs.py
│   │   │   └── data/               # static data files (negative-area seed, etc.)
│   │   ├── decisioning/
│   │   │   ├── engine.py           # 11-step pipeline orchestrator
│   │   │   ├── case_library.py     # pgvector feature vector + retrieval
│   │   │   ├── mrp.py              # decisioning's MRP wrapper
│   │   │   └── steps/
│   │   │       ├── base.py
│   │   │       ├── _llm_helpers.py
│   │   │       ├── step_01_policy_gates.py
│   │   │       ├── step_02_banking.py
│   │   │       ├── step_03_income.py
│   │   │       ├── step_04_kyc.py
│   │   │       ├── step_05_address.py
│   │   │       ├── step_06_business.py
│   │   │       ├── step_07_stock.py
│   │   │       ├── step_08_reconciliation.py
│   │   │       ├── step_09_pd_sheet.py
│   │   │       ├── step_10_retrieval.py
│   │   │       └── step_11_synthesis.py
│   │   ├── memory/
│   │   │   ├── policy.yaml         # 100+ NBFC rules — prompt-cache prefilled
│   │   │   ├── heuristics.md       # domain wisdom — prompt-cache prefilled
│   │   │   └── loader.py
│   │   ├── worker/
│   │   │   ├── __main__.py         # `python -m app.worker` entry
│   │   │   ├── pipeline.py         # ingestion orchestrator (10 steps)
│   │   │   ├── classifier.py       # subtype assignment
│   │   │   ├── checklist_validator.py
│   │   │   ├── dedupe.py
│   │   │   ├── image_crop.py       # L3 bbox crops
│   │   │   ├── system_user.py
│   │   │   └── extractors/         # one file per artefact
│   │   │       ├── auto_cam.py
│   │   │       ├── autocam_discrepancies.py
│   │   │       ├── pd_sheet.py
│   │   │       ├── checklist.py
│   │   │       ├── equifax.py
│   │   │       ├── bank_statement.py
│   │   │       ├── ration_bill_scanner.py    # ration + electricity unified
│   │   │       ├── aadhaar_scanner.py
│   │   │       ├── pan_scanner.py
│   │   │       ├── loan_agreement_scanner.py
│   │   │       └── dedupe_report.py
│   │   ├── worker_decisioning/
│   │   │   └── __main__.py         # consumes pfl-decisioning-jobs queue
│   │   ├── templates/              # SES email templates (HTML + txt)
│   │   ├── cli.py                  # admin CLI (click) — seed-admin, etc.
│   │   ├── config.py               # pydantic-settings env load
│   │   ├── db.py                   # async engine + session factory
│   │   ├── enums.py                # ALL StrEnums (case stage, severity, subtype, …)
│   │   ├── main.py                 # FastAPI app — mounts routers + lifespan
│   │   └── startup.py              # dev-only: ensure_bucket / ensure_queues
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/               # migrations
│   ├── tests/
│   │   ├── unit/                   # pure-function tests (no DB)
│   │   ├── integration/            # DB + API tests via httpx + pytest-asyncio
│   │   └── fixtures/builders/      # equifax/bank/cam fixture builders
│   ├── Dockerfile
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx            # / → redirect to /cases
│   │   │   ├── login/page.tsx
│   │   │   ├── forbidden/page.tsx
│   │   │   ├── api/proxy/[...slug]/route.ts  # /api/proxy/* → backend (CSRF + cookies)
│   │   │   └── (app)/              # authenticated section
│   │   │       ├── cases/page.tsx          # list
│   │   │       ├── cases/new/page.tsx      # 3-step upload wizard
│   │   │       ├── cases/[id]/page.tsx     # detail with tabs
│   │   │       ├── assessor/queue/page.tsx
│   │   │       ├── settings/profile/page.tsx
│   │   │       └── admin/                  # admin pages
│   │   │           ├── users/page.tsx
│   │   │           ├── learning-rules/page.tsx
│   │   │           ├── negative-areas/page.tsx
│   │   │           ├── l3-rerun/page.tsx
│   │   │           ├── mrp-catalogue/page.tsx
│   │   │           ├── incomplete-autoruns/page.tsx
│   │   │           ├── dedupe-snapshots/page.tsx
│   │   │           └── approvals/page.tsx
│   │   ├── components/
│   │   │   ├── ui/                # shadcn primitives
│   │   │   ├── layout/            # Sidebar, NotificationsBell, Topbar
│   │   │   ├── auth/
│   │   │   ├── cases/
│   │   │   │   ├── VerificationPanel.tsx     # main rubric grid (large file)
│   │   │   │   ├── DecisioningPanel.tsx      # L6 / Phase 1 view
│   │   │   │   ├── CaseFinalReportCard.tsx   # download PDF
│   │   │   │   ├── CaseConcernsProgressCard.tsx
│   │   │   │   ├── CaseCamDiscrepancyCard.tsx
│   │   │   │   ├── CaseInsightsCard.tsx
│   │   │   │   ├── ChecklistMatrix.tsx
│   │   │   │   ├── DedupeMatchTable.tsx
│   │   │   │   ├── DiscrepanciesPanel.tsx
│   │   │   │   ├── ExtractionsPanel.tsx
│   │   │   │   ├── ArtifactGrid.tsx
│   │   │   │   ├── AuditLogTimeline.tsx
│   │   │   │   ├── FeedbackWidget.tsx
│   │   │   │   ├── StageBadge.tsx
│   │   │   │   ├── actions/         # ReuploadDialog, etc.
│   │   │   │   ├── evidence/        # ~33 per-rule "smart cards"
│   │   │   │   │   ├── registry.ts  # sub_step_id → card factory
│   │   │   │   │   ├── PassDetailDispatcher.tsx
│   │   │   │   │   ├── EvidenceTwoColumn.tsx
│   │   │   │   │   ├── _format.ts
│   │   │   │   │   └── *Card.tsx    # one per rule
│   │   │   │   └── l3/              # L3-specific cards
│   │   │   ├── autorun/             # AutoRunProvider, Modal, Dock, Trigger
│   │   │   ├── wizard/              # 3-step upload wizard
│   │   │   ├── settings/
│   │   │   └── admin/
│   │   └── lib/
│   │       ├── api.ts               # API client
│   │       ├── http.ts              # fetch wrapper + CSRF + refresh
│   │       ├── server-auth.ts       # SSR auth helpers
│   │       ├── enums.ts             # mirrored from backend (sync-enums.ts)
│   │       ├── types.ts             # shared TS types
│   │       ├── cn.ts                # classnames helper
│   │       └── use*.ts              # SWR hooks (useCase, useVerification, …)
│   ├── e2e/                         # Playwright
│   ├── scripts/sync-enums.ts        # backend → frontend enum sync (drift guard)
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.mjs
│   └── tsconfig.json
│
├── docs/
│   ├── KNOWLEDGE_TRANSFER.md   # ← you are here
│   ├── accessibility-m4.md
│   └── superpowers/
│       ├── specs/              # design specs per milestone
│       ├── plans/              # implementation plans per milestone
│       └── RESUME_*.md         # detailed dev-session resumes (deep context)
│
├── README.md                   # high-level overview + Quick Start
├── SESSION_HANDOFF.md          # rolling per-session notes
├── FOLLOW_UPS.md               # known follow-up items
├── docker-compose.yml
├── .env.example                # backend env template (copy to backend/.env)
├── frontend/.env.local.example # frontend env template
└── .gitignore
```

---

## 5. Local setup (developer machine)

### Prerequisites

- macOS / Linux / WSL2.
- **Docker Desktop** (or Colima) with `docker compose v2`.
- **Python 3.12** + **Poetry 1.8+** (only needed if you want to run the
  backend outside Docker, e.g. for tests).
- **Node 20** + **npm 10+** (only for non-Docker frontend dev).
- **Anthropic API key** (`sk-ant-...`) for L1.5 / L2 / L3 / L5 / L5.5 to
  work. Without it the stack still boots; those levels just fail their
  Claude calls.

### Step-by-step

```bash
git clone https://github.com/saksham7g1/pfl-credit-system.git
cd pfl-credit-system

# 1. Env templates — note the destinations
cp .env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 2. Edit backend/.env
#    - JWT_SECRET_KEY=<openssl rand -hex 32>
#    - ANTHROPIC_API_KEY=sk-ant-...
#    - GOOGLE_MAPS_API_KEY=... (only if you want L1 commute judge to work
#      against the real Routes API; defaults to a stub when blank)

# 3. Bring up the stack
docker compose up -d
# Containers:
#   pfl-postgres        :5432   (loopback only)
#   pfl-localstack      :4566   (S3 + SQS + SES mocks)
#   pfl-backend         :8000
#   pfl-worker                  (no port, SQS consumer)
#   pfl-decisioning-worker      (no port, SQS consumer)
#   pfl-web             :3001   (Next.js)

# 4. Tail logs to watch the alembic migrations + AWS resource init
docker compose logs -f backend

# 5. Once backend says "Application startup complete", seed an admin
docker compose exec backend python -m app.cli seed-admin \
  --email you@pflfinance.com --full-name "Your Name"
# Records the password in the terminal — note it.

# 6. Open the app
#    Web UI:   http://localhost:3001  (login with email + the printed pw)
#    API docs: http://localhost:8000/docs

# 7. (optional) Run backend tests outside Docker
cd backend
poetry install
poetry run pytest -v --cov=app

# 8. (optional) Run frontend dev server outside Docker
cd ../frontend
npm install
npm run dev    # serves on http://127.0.0.1:3000
```

### Everyday loop

- **Code edit (backend)** — `./backend/app/**` is bind-mounted into the
  container; uvicorn auto-reloads on save. Worker code edits require a
  `docker compose restart worker pfl-decisioning-worker`.
- **Code edit (frontend)** — `npm run dev` outside Docker is the fastest
  loop (HMR < 1s). The dockerised `pfl-web` is for "does it build?"
  validation.
- **DB schema change** — write an Alembic migration (see §16), then
  `docker compose exec backend alembic upgrade head`.
- **Reset DB** — `docker compose down -v && docker compose up -d`.
  Wipes both Postgres + LocalStack volumes. Useful when migrations
  diverge.
- **See worker logs** — `docker compose logs -f worker` (ingestion) or
  `docker compose logs -f pfl-decisioning-worker`.

---

## 6. Hosting / deployment

### Local-only (this repo, today)

The `docker compose` setup IS the supported "local production"
environment. Everything (DB, queues, S3, frontend, workers) runs on
`127.0.0.1:*` ports — none are exposed to the LAN. Suitable for
demoing on a developer machine.

### AWS Mumbai (M8 — planned, not yet shipped)

Target architecture (per the M8 milestone in README §Roadmap):

- **AWS region:** ap-south-1 (Mumbai) for data-residency compliance.
- **Compute:** ECS Fargate
  - Task A: `backend` (FastAPI, behind ALB).
  - Task B: `worker` (SQS-driven, Fargate-spot OK).
  - Task C: `pfl-decisioning-worker` (SQS-driven).
  - Task D: `pfl-web` (Next.js, behind ALB).
- **DB:** RDS Postgres with `pgvector` extension installed.
- **Storage:** S3 bucket `pfl-cases-prod` with SSE-KMS, Object Lock for
  audit (M8 spec).
- **Queues:** SQS `pfl-ingestion-prod` + DLQ; `pfl-decisioning-jobs-prod`
  + DLQ.
- **Secrets:** AWS Secrets Manager. JWT key, Anthropic key, DB password
  injected as ECS task env via secret references.
- **Email:** SES with verified `no-reply@pflfinance.com`.
- **CDN / ALB:** CloudFront in front of ALB; ACM cert; Route 53.
- **Provisioning:** AWS CDK (TypeScript) — to land in M8.

### "Self-host on a single VM" (recipe, not in repo today)

If you want to run on a single EC2 / DigitalOcean droplet:

1. Provision Ubuntu 22.04 with Docker + docker-compose-plugin.
2. Clone the repo, follow §5 setup. Use a **real** Anthropic key.
3. Replace LocalStack with real AWS (or skip the queues by running
   the worker inline — not currently a supported mode; would need
   code change).
4. Put nginx / Caddy in front of `127.0.0.1:8000` and `127.0.0.1:3001`
   for TLS termination.
5. Back up `pfl-postgres-data` volume nightly (e.g. via
   `pg_dump | gzip | aws s3 cp -`).

The Dockerfiles are production-shaped (`poetry install --only main`,
`next build` then `next start`) so this is plausible — but no smoke
tests have been run against a non-LocalStack deployment.

### Prod readiness gaps (worth knowing before shipping)

- Volume bind-mounts in `docker-compose.yml` are dev-only (`./backend/
  app:/app/app`). Strip these for prod images.
- `dev_auto_create_aws_resources=true` defaults to creating buckets +
  queues on startup. Set to `false` in prod (CDK should provision them).
- LocalStack endpoints (`http://localstack:4566`) are baked into the
  compose env — replace with real AWS endpoints (or omit
  `AWS_*_ENDPOINT_URL` to use defaults).
- `COOKIE_SECURE=false` on `pfl-web` env — flip to `true` for HTTPS.
- `APP_SECRET=dev-secret-change-me` on `pfl-web` env — must rotate.

---

## 7. Backend code walkthrough

### 7.1 Entry points

- **`app/main.py`** — FastAPI app. Mounts CORS middleware, lifespan
  (calls `init_aws_resources()` on startup), and 14 routers in order.
  See `_lifespan` for the boot order.
- **`app/worker/__main__.py`** — `python -m app.worker`. Long-poll loop
  pulling from `SQS_INGESTION_QUEUE`, dispatching to `worker/pipeline.py
  ::process_ingestion_job`.
- **`app/worker_decisioning/__main__.py`** — analogous for the
  decisioning queue.
- **`app/cli.py`** — click-based admin CLI. Sub-commands include
  `seed-admin`, `seed-system-user`, `mrp:sync`, etc.

### 7.2 Routers (`app/api/routers/`)

Each router is a focused HTTP surface. Everything follows:

```python
@router.post("/cases", response_model=CaseRead)
async def create_case(
    payload: CaseCreate,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    queue: QueueService = Depends(get_queue_dep),
    storage: StorageService = Depends(get_storage_dep),
):
    # validation → call service → return Pydantic schema
```

Key routers:

- **`auth.py`** — `/auth/login`, `/auth/refresh`, `/auth/mfa/*`. Sets
  HttpOnly cookies + JS-readable CSRF token. Single-flight refresh
  middleware lives on the FE side (`api/proxy/[...slug]/route.ts`).
- **`cases.py`** — case lifecycle. `initiate` (returns presigned upload
  URL), `finalize` (publishes ingestion job), artifact CRUD, ZIP
  download, `approve-reupload` (24h window), `reingest` (admin),
  delete-request flow with MD approval, checklist waive.
- **`verification.py`** — the gate. `POST /verification/cases/{id}/
  levels/{N}/trigger` runs that level inline (yes, in the request
  thread — see Gotcha §18). `GET .../overview` returns level
  statuses + issue counts. `GET .../levels/{N}` returns full detail
  with issues. `POST .../issues/{id}/resolve` (assessor) and
  `.../issues/{id}/decide` (MD) update lifecycle. Also exposes
  `md_router` for the MD queue.
- **`incomplete_autorun.py`** — backs the completeness gate (FE prompts
  before auto-run if required artefacts are missing). Persists every
  attempt that bypassed completeness as an audit trail.
- **`admin_*.py`** — admin-only control surfaces:
  - `admin_rules` — RuleOverride toggles (suppress a flaky rule
    globally, demote severity, etc.).
  - `admin_l3_rerun` — bulk re-run L3 vision when the prompt is
    re-tuned.
  - `admin_negative_area` — pincode blocklist for the L5 #11 negative-
    area rule.
  - `mrp_catalogue` — admin-managed MRP entries the L3 vision uses
    when scoring stock value.

### 7.3 Services (`app/services/`)

Pure async business logic — no FastAPI / HTTP imports. One module per
domain:

- **`auth.py`** — password hashing (bcrypt), JWT issuance/verification,
  TOTP MFA.
- **`cases.py`** — `initiate()`, `finalize()`, `add_artifact()`,
  `approve_reupload()`, `_archive_existing_state()`, soft-delete, MD
  delete-approval. Takes `session + storage + queue` as args; returns
  ORM rows or `(row, queue_payload)` tuples for the router to publish.
- **`stages.py`** — `transition_to(case, target_stage)`. Validates
  legal transitions (the 14-state CaseStage enum has explicit allowed
  edges). Raises `InvalidStateTransition` on a guarded edge.
- **`storage.py`** — wraps `aioboto3` S3. `upload_object`,
  `presigned_url`, `download_object`, `copy_object`, `delete_object`,
  `object_exists`. One service instance per process.
- **`queue.py`** — wraps SQS. `publish_job(payload: dict)`. Two queue
  identities: ingestion + decisioning.
- **`email.py`** — SES wrapper. Templates rendered from
  `app/templates/missing_docs.html` etc.
- **`audit.py`** — `log_action(actor, action, entity_type, entity_id,
  before, after)` writes to `audit_log`. Use it on every state-changing
  operation.
- **`case_completeness.py`** — `compute_missing_required_artifacts(
  case_id) -> list[ArtifactSubtype]`. Used by `incomplete_autorun`
  router and the FE's pre-run completeness gate.
- **`cam_discrepancy.py`** + **`cam_discrepancy_report.py`** — L0
  SystemCam vs CM CAM IL diff engine. Populates `cam_discrepancy_
  resolution` rows.

### 7.4 Verification (`app/verification/`)

See §9 for the per-level deep-dive. Module shape:

- **`levels/level_<N>_*.py`** — orchestrator + cross-checks +
  pass-evidence builder for that level. The orchestrator is `async
  def run_level_<N>_<name>(session, case_id, ...)` and is called from
  `routers/verification.py` when the FE triggers the level.
- **`services/`** — anything reusable across levels: external API
  clients (Google Maps, Nominatim), Claude callers (CA analyser,
  credit analyst, vision scorers, income proof), structured services
  (address normalizer, scoring model, report generator).

### 7.5 Decisioning (`app/decisioning/`)

11-step Phase 1 pipeline. See §10. Each step is a self-contained module
with `def run(case_id, ctx, claude, ...) -> StepOutput`. The engine
persists `DecisionStep` rows after every step and supports
resume-from-last-successful when re-triggered.

### 7.6 Worker (`app/worker/`)

- **`pipeline.py::process_ingestion_job(payload)`** — the orchestrator.
  10 steps (see file docstring). Critical to know:
  - Step 3 (`_upload_and_create_artifacts`) inlines classification —
    each new file gets its `subtype` set immediately.
  - Step 5 runs every extractor whose subtype matches; a `trigger=
    "reingest"` payload reruns extractors for **all** existing
    artifacts (not just new ones), so a classifier or extractor code
    change applies retroactively without a delete-and-reupload.
- **`classifier.py`** — keyword + fuzzy matching on filename + content
  hints. Outputs an `ArtifactSubtype` enum value.
- **`extractors/<name>.py`** — one per artefact:
  - `auto_cam.py` — 4-sheet xlsx → `CaseExtraction` rows for
    `system_cam`, `eligibility`, `cm_cam_il`, `health_sheet`.
  - `pd_sheet.py` — Personal-discussion sheet xlsx → applicant
    declarations.
  - `equifax.py` — bureau HTML → score + accounts + enquiries.
  - `bank_statement.py` — pdfplumber → transaction list + summary.
  - `ration_bill_scanner.py` — Claude-vision unified extractor for
    ration cards AND electricity bills (and water / gas / utility
    bills) — single prompt, returns name + father_or_husband_name +
    address + document_type.
  - Same for `aadhaar_scanner`, `pan_scanner`,
    `loan_agreement_scanner`, `dedupe_report`.

---

## 8. Frontend code walkthrough

### 8.1 App routes (`src/app/`)

The App-Router structure groups everything authenticated under
`(app)/`. The layout there enforces session-cookie auth via a server
middleware; logged-out users get redirected to `/login`.

- **`/login`** — email + password (+ TOTP if MFA enabled). Sets the
  HttpOnly refresh cookie + JS CSRF token.
- **`/cases`** — list, filter, paginated. `useCases()` hook fetches.
- **`/cases/new`** — 3-step upload wizard. Components live in
  `components/wizard/`. Step 1: borrower details. Step 2: ZIP upload
  via presigned URL. Step 3: confirm + finalize.
- **`/cases/[id]`** — the main case-detail page. Tabs (rendered
  client-side):
  - **Overview** — stage badge, AI insights, CAM check, concerns
    progress card, final-report card.
  - **Verification** — `VerificationPanel.tsx` (large file). Per-level
    accordion with per-rule rows. Auto-run trigger button.
  - **Verification 2 / Decisioning** — `DecisioningPanel.tsx`. L6
    Phase-1 progress + final decision card.
  - **Artifacts** — `ArtifactGrid.tsx`. Group by subtype.
  - **Extractions** — every CaseExtraction row in JSON form.
  - **Discrepancies** — `DiscrepanciesPanel.tsx` for L0 CAM diff.
  - **Checklist** — `ChecklistMatrix.tsx`.
  - **Dedupe** — `DedupeMatchTable.tsx`.
  - **Audit Log** — `AuditLogTimeline.tsx`.
- **`/assessor/queue`** — assessor's plate. Issues awaiting resolution
  across all cases.
- **`/admin/*`** — admin pages. Each is wired to a corresponding
  `admin_*` backend router.
- **`/api/proxy/[...slug]/route.ts`** — Next.js Route Handler that
  forwards every API call from the browser to the FastAPI backend,
  attaching the cookie + CSRF token. **All FE → backend traffic flows
  through this** so cookies stay HttpOnly and we never expose the
  refresh token to JS.

### 8.2 Components (`src/components/`)

- **`ui/`** — shadcn primitives (Button, Card, Dialog, …). Don't put
  domain logic here.
- **`layout/`** — `Sidebar`, `Topbar`, `NotificationsBell`. The sidebar
  is keyed off the user's role (admin sees admin section, assessors
  see queue link, etc.).
- **`cases/`** — domain components. `VerificationPanel.tsx` is the
  largest single file in the FE — it owns the rubric grid, expand/
  collapse rows, evidence rendering, auto-run handoff, MD/assessor
  action surfaces.
- **`cases/evidence/`** — ~33 per-rule "smart cards", one per
  `sub_step_id`. The dispatcher (`PassDetailDispatcher.tsx`) reads
  the rule id off the issue and looks up `registry.ts` to find the
  card factory; falls back to `GenericEvidenceTable` when no card is
  registered. Each card has the SAME shape on the fire path
  (CRITICAL/WARNING) and pass path — they read from `issue.evidence`
  or `pass_evidence[sub_step_id]`.
- **`cases/actions/`** — modal dialogs that mutate state: re-upload,
  re-ingest, add-artifact, request-deletion, MD-decide.
- **`autorun/`** — `AutoRunProvider` is the state machine that
  sequences L1 → L6. `STEP_ORDER` constant lists levels in run order;
  each step has a `runner` (calls trigger endpoint), a `poller` (waits
  for VR completion), and a `gate` (e.g. completeness check).
  `MissingDocsBanner` blocks auto-run when required docs are absent.

### 8.3 lib (`src/lib/`)

- **`api.ts`** — typed wrappers around `/api/proxy/*` endpoints. Group
  by domain: `auth.*`, `cases.*`, `verification.*`, `admin.*`.
- **`http.ts`** — base `fetch` wrapper. Reads the CSRF cookie and
  attaches `X-CSRF-Token` header on mutating requests.
- **`server-auth.ts`** — SSR helpers (used in route handlers /
  middleware) for reading the session cookie.
- **`enums.ts`** — generated mirror of `backend/app/enums.py`. **Do
  not edit by hand.** Run `npm run sync-enums` after a backend enum
  change. CI `npm run check:enums` fails the build if drift exists.
- **`use*.ts`** — SWR hooks. Each hook returns
  `{ data, error, isLoading, mutate }`. Cache keys are the API URL.

### 8.4 Tests

- **`*.test.tsx`** colocated with the component — Vitest + RTL.
- **`e2e/*.spec.ts`** — Playwright. Login → upload → run → view report.
- Coverage thresholds: `lib/` ≥80%, `components/cases/` ≥90%.

---

## 9. Verification levels deep-dive (L0 → L6)

Each level is independent — they share state only through the DB
(`VerificationResult` rows + `LevelIssue` rows). A level produces:

- One **`VerificationResult`** row (status: PASSED / FAILED /
  RUNNING / etc.) summarising the run.
- Zero or more **`LevelIssue`** rows — each with a `sub_step_id`,
  `severity` (CRITICAL / WARNING), `description`, structured
  `evidence` (dict), and lifecycle (`status`: OPEN / ASSESSOR_RESOLVED
  / MD_APPROVED / MD_REJECTED).
- A **`sub_step_results`** JSON blob on the VR with per-rule pass
  evidence (`pass_evidence[sub_step_id]`) for the FE smart cards.

When the FE's Auto-Run sequences L1 → L6, it triggers each level's
`POST /verification/cases/{id}/levels/{N}/trigger` endpoint. The
endpoint runs the level's orchestrator inline (so requests can be
30-90s long), then returns the new VR id. Auto-Run polls the VR
until it transitions out of RUNNING.

**`carry_forward_prior_decisions`** in
`verification/levels/_common.py` runs at the START of every level's
orchestrator. It looks at the previous VR for the same level and
copies forward terminal decisions (MD_APPROVED, MD_REJECTED) onto
the matching newly-emitted issue. Without this, a re-run would lose
every MD sign-off.

### L0 — CAM discrepancy gate

- **File:** `services/cam_discrepancy.py` + router
  `routers/cam_discrepancies.py`.
- **What it does:** Compares the SystemCam sheet (source of truth from
  the finpage) against the CM CAM IL sheet (manual data-entry). Flags
  every field that disagrees — applicant name, FOIR, loan amount,
  income, etc. The assessor must resolve each discrepancy before any
  Phase 1 decision can ship. Three resolution paths: "Correct CM CAM
  IL (assessor self-serve)", "Request SystemCam edit (CEO approval)",
  or "Justify (record why divergence is acceptable)".
- **Why it matters:** SystemCam is the financial truth. Anything in
  the CM CAM IL that doesn't match it is at risk of being a typo, a
  stale value, or fabrication.

### L1 — Address verification (`level_1_address.py`)

- **Sub-steps (rules):**
  - `applicant_coapp_address_match` — applicant + co-applicant Aadhaar
    addresses match (joint families).
  - `aadhaar_vs_bureau_address` — Aadhaar address matches the bureau
    report's address.
  - `gps_vs_aadhaar` — GPS-watermarked house photo's reverse-geocoded
    address matches Aadhaar.
  - `gps_watermark_present` — house + business premises photos have
    EXIF GPS / visible watermark.
  - `ration_owner_rule` — bill owner is the applicant / co-app /
    guarantor / father-or-husband (decision tree). Now also surfaces
    `bill_owner_loan_role` per recent commit `ecf4ed7`.
  - `business_visit_gps` — business premises photo has GPS coords.
  - `house_business_commute` — Google Maps Routes API drive time
    between house and business location is reasonable for the
    occupation. Falls back to an Opus judge for edge cases.
- **Key services:** `address_normalizer` (tokenisation,
  `name_matches`, `first_names_match`), `google_maps`,
  `commute_judge` (Opus).
- **Cross-checks return either `None` (pass)** or a dict with
  `severity / description / evidence`. Pass paths are also recorded
  in `build_pass_evidence_l1()` so the FE smart card has data to
  render.

### L1.5 — Credit history (`level_1_5_credit.py`)

- **Sub-steps:** six status scanners (write-off, loss, settled,
  substandard, doubtful, SMA), credit-score floor (680/700), bureau
  hit confirmation, plus a Claude Opus willful-default + fraud
  narrative.
- Runs against both applicant + co-applicant Equifax extractions.
- Hard rules are deterministic; the narrative is structured Opus
  with a strict JSON schema.

### L2 — Banking (`level_2_banking.py`)

- **Inputs:** the bank statement extraction (transaction list +
  summary).
- **Hard rules:** NACH bounces, ABB ratio vs proposed EMI, 3M credits
  vs declared income, single-payer concentration, impulsive debits,
  chronic low balance, 6-month coverage.
- **Soft rules:** the Opus CA analyser produces a structured
  positives/concerns list which becomes a `ca_narrative_concerns`
  WARNING when concerns exist.
- **File the Opus call lives in:** `services/bank_ca_analyzer.py`.

### L3 — Vision (`level_3_vision.py`)

- **Two Sonnet vision calls:** one bundles all `HOUSE_VISIT_PHOTO`
  artifacts and scores living conditions / cattle / etc.; the other
  bundles `BUSINESS_PREMISES_PHOTO` artifacts and produces a
  per-item stock breakdown with bbox crops + MRP catalogue lookup.
- **Output:** structured score (0-10 per parameter) + per-item stock
  list + MRP-cross-checked total stock value + cattle count + business
  type tag.
- **Cross-checks emit issues** when stock value is below loan amount,
  when the business-type tag conflicts with the applicant's declared
  occupation, etc.
- **MRP catalogue:** admin-managed table of `(business_type, item) ->
  MRP_INR`. The vision scorer uses it to convert "10 sacks of rice" to
  a rupee value.

### L4 — Loan-agreement audit (`level_4_agreement.py`)

- **Input:** the LAGR PDF artifact.
- **What it checks:** the agreement has a populated annexure section,
  hypothecation clause is present, asset count ≥ 1, parties section
  enumerates everyone (applicant, co-app, guarantors).

### L5 — 32-point FINPAGE rubric (`level_5_scoring.py`)

- **The big one.** Final scoring across the entire case. 32 weighted
  parameters in 4 sections:
  - **A — Credit Assessment & Eligibility** (45 pts) — household
    income, vintage, CIBIL, FOIR, DSCR, deviations, etc.
  - **B — QR & Banking** (35 pts) — shop QR, income proofs, banking
    ratios.
  - **C — Assets & Living** (13 pts) — purpose of loan (#25), end
    use (#26), house ownership, business ownership, additional
    assets.
  - **D — Reference & TVR** (7 pts) — BCM cross-verification (#30),
    TVR by Credit HO (#31), Fraud / Verification call (#32).
- **Each rule is a resolver** in `services/scoring_model.py` named
  `r_a01_household_income` … `r_d32_fraud_call`. Each takes a
  `ScoringContext` (the bundled inputs from L0-L4) and a weight, and
  returns `(Status, score, evidence, remarks)`.
- **`ParamDef` catalog** at the bottom of `scoring_model.py` lists
  every rule with sno + section + weight + resolver. New `force_critical:
  bool = False` field (commit `5789c8e`) marks a rule whose
  FAIL/PENDING outcome must escalate to CRITICAL severity regardless
  of weight (used for #25 / #26 mandatory CAM declarations).
- **Severity wiring** in `level_5_scoring.py`'s issue builder:
  - `FAIL` + weight ≥ 4 (or `force_critical=True`) → CRITICAL.
  - `FAIL` + weight ≥ 3 → WARNING.
  - `PENDING` → WARNING (CRITICAL when `force_critical=True`).
  - Section-level summary issue when section pct < 70%.
  - Grade-level summary when overall < 70%.
- **Pass evidence builder** at the bottom — populates
  `row.source_artifacts` with the actual artifact backing each PASS
  row, so the FE source-files panel cites the right doc.

### L5.5 — Dedupe + TVR + NACH + PDC (`level_5_5_dedupe_tvr.py`)

- Four cross-checks (three deterministic + one Claude vision):
  - `dedupe_clear` — dedupe XLSX matches → 0 rows = pass.
  - `tvr_present` — `TVR_AUDIO` artifact uploaded.
  - `pdc_present` — Claude vision confirms the artifact is actually a
    cheque, reads bank/IFSC/account/holder/signature.
  - `pdc_matches_bank` — cross-validates the cheque vs bank statement
    (IFSC, account-tail, holder name fuzz). Now records pass_evidence
    for skipped variants too (commit `21800ea`) so the FE renders the
    PDC ↔ bank match card explicitly instead of "no detail".
  - `nach_present` — NACH e-mandate artifact uploaded.

### L6 — Phase 1 Decisioning

See §10.

---

## 10. Phase-1 Decisioning engine (L6)

`backend/app/decisioning/engine.py` orchestrates 11 sequential steps.
Each step persists a `DecisionStep` row before moving on, so a
crashed run resumes from the last-successful step instead of restarting.

| Step | What it does | Who computes it |
|------|--------------|-----------------|
| 1 | Policy gates (FOIR, CIBIL floor, age, exposure caps) | Pure Python — `step_01_policy_gates.py` |
| 2 | Banking summary | Sonnet 4.5 |
| 3 | Income consolidation | Sonnet 4.5 |
| 4 | KYC integrity (Aadhaar + PAN consistency) | Sonnet 4.5 |
| 5 | Address verification synthesis | Sonnet 4.5 |
| 6 | Business activity tag | Sonnet 4.5 |
| 7 | Stock + assets reconciliation | Sonnet 4.5 |
| 8 | Cross-source reconciliation (CAM ↔ bureau ↔ bank) | Sonnet 4.5 |
| 9 | PD-sheet narrative consistency | Sonnet 4.5 |
| 10 | Retrieval (similar past cases via pgvector cosine) | Pure Python + DB |
| 11 | **Final synthesis** — Opus 4 produces the structured DecisionResult | Opus 4 |

**Inputs to step 11:** every prior step's output + the policy.yaml (100+
NBFC rules, prompt-cache prefilled) + heuristics.md (domain wisdom) +
top-5 retrieved similar cases.

**Output:** `DecisionResult` row with `final_decision` (one of
APPROVE / APPROVE_WITH_CONDITIONS / REJECT / ESCALATE_TO_CEO),
`approved_amount`, `confidence`, `reasoning`, `pros[]`, `cons[]`,
`conditions[]`, `deviations[]`, `risk_summary`.

**Trigger surface:** `POST /cases/{id}/phase1` enqueues a job on
`pfl-decisioning-jobs`. The decisioning worker
(`worker_decisioning/__main__.py`) consumes and runs `engine.py`. Status
polled via `GET /cases/{id}/phase1/result` from the FE
`DecisioningPanel.tsx`.

**Memory subsystem** (`app/memory/`) is loaded once per pipeline run
and prefilled into the Anthropic prompt cache so step 11's 16k+ token
context reuses cache between runs (~50% cost saving).

---

## 11. Data model

ER overview (~25 tables). Significant ones:

- **`users`** — auth identities. `role` ∈ {ADMIN, CEO, ASSESSOR,
  CREDIT_OFFICER, BCM, ...}.
- **`cases`** — the central entity. `current_stage` is the 14-state
  enum (UPLOADED → CLASSIFIED → EXTRACTING → INGESTED →
  CHECKLIST_MISSING_DOCS / CHECKLIST_VALIDATED → VERIFICATION_RUNNING
  → VERIFIED → DECISIONING → DECISIONED → FINALIZED, plus FAILED /
  CANCELLED states). Carries `loan_id` (unique while not deleted),
  `applicant_name`, `loan_amount`, `tenure`, `co_applicant_name`,
  `occupation`, `reupload_count`, `reupload_allowed_until`, soft-delete
  fields, MD-deletion-approval fields.
- **`case_artifacts`** — every file uploaded for a case. `artifact_type`
  (`ORIGINAL_ZIP` / `EXTRACTED_FILE` / `ADDITIONAL_FILE` /
  `REUPLOAD_ARCHIVE`) + `metadata_json.subtype` (the `ArtifactSubtype`
  enum value). `s3_key` is the storage pointer.
- **`case_extractions`** — output of every extractor. One row per
  (artifact, extractor_name) tuple, with `data` JSON payload + `status`
  (SUCCESS / PARTIAL / FAILED).
- **`verification_results`** — one row per (case, level, run). Multiple
  rows per (case, level) — re-runs append. The FE always displays the
  latest.
- **`level_issues`** — per-rule findings on a VR. Fields: `sub_step_id`,
  `severity`, `status` (OPEN / ASSESSOR_RESOLVED / MD_APPROVED /
  MD_REJECTED / SUPPRESSED), `description`, `evidence` JSON,
  `assessor_note`, `md_decision_note`, `decided_by`, `decided_at`,
  source-artifact pointers.
- **`cam_discrepancy_resolutions`** — L0 SystemCam vs CM CAM IL diff
  rows + assessor resolutions.
- **`checklist_validation_results`** — per-case completeness output.
  `missing_required[]`, `missing_soft[]`.
- **`dedupe_snapshots`** + **`dedupe_matches`** — admin-uploaded dedupe
  XLSX state + per-case matches.
- **`decision_results`** + **`decision_steps`** — Phase 1 pipeline state.
- **`audit_log`** — every state-changing operation, immutable, queried
  by case-detail audit timeline.
- **`mrp_catalogue_entries`** + **`mrp_entries`** — MRP tables for L3
  vision stock value computation.
- **`negative_area_pincodes`** — admin-managed blocklist for L5 #11.
- **`rule_overrides`** — admin "learning rules" that suppress / demote
  a rule globally based on past MD decisions.
- **`incomplete_autorun_log`** — every auto-run that bypassed the
  completeness gate, for auditability.
- **`l1_extracted_documents`** — bridge table linking L1's structured
  KYC extractions to artifacts.
- **`case_feedback`** — post-decision human verdict for the AI-learning
  loop (M7).
- **`system_cam_edit_requests`** — CEO-approval workflow for the L0 path
  "request SystemCam edit".

---

## 12. Background jobs & queues

Two SQS queues, two workers.

### Ingestion queue (`pfl-ingestion-dev`)

- **Producer:** `cases.finalize` after a ZIP upload.
- **Producer:** `cases.add_artifact` if the case was in
  `CHECKLIST_MISSING_DOCS` and the new artifact closes the gap.
- **Producer:** `POST /cases/{id}/reingest` (admin manual).
- **Consumer:** `pfl-worker` running `process_ingestion_job(payload)`.
- **DLQ:** `pfl-ingestion-dev-dlq`. Redrive policy with `maxReceiveCount=3`.
- **Payload shape:**
  ```json
  {"case_id": "uuid", "loan_id": "...", "zip_s3_key": "...",
   "trigger": "initial" | "reingest"}
  ```

### Decisioning queue (`pfl-decisioning-jobs`)

- **Producer:** `POST /cases/{id}/phase1` after the FE clicks
  "Run Phase 1" or after the auto-run finishes L5.5.
- **Consumer:** `pfl-decisioning-worker` running
  `decisioning/engine.py::run_pipeline(case_id)`.
- **DLQ:** `pfl-decisioning-dlq`.

### What is NOT a background job

Verification levels (L1 → L5.5) run **inline in the FastAPI request
thread** when the FE triggers `POST /verification/cases/{id}/levels/{N}/
trigger`. This is a deliberate design: it lets the FE's Auto-Run
sequence levels with deterministic ordering and per-step polling. The
trade-off is a 30-90s blocking request per level. Long-term (M8) we
plan to move them to the queue too.

---

## 13. External integrations

| Service | Used by | How it's mocked in dev |
|---------|---------|-------------------------|
| **AWS S3** (artefact storage) | `services/storage.py` | LocalStack |
| **AWS SQS** (ingestion + decisioning queues) | `services/queue.py`, workers | LocalStack |
| **AWS SES** (transactional emails) | `services/email.py` | LocalStack |
| **Anthropic Claude API** | every Opus / Sonnet call (CA, vision, decisioning, narrative, judge) | **Real Claude — no mock.** Set `ANTHROPIC_API_KEY` to test. Tests use recorded fixtures, not live calls. |
| **Google Maps Routes API + Geocoding** | `verification/services/google_maps.py` (L1 commute) | Stub when `GOOGLE_MAPS_API_KEY` blank — returns deterministic but unrealistic results. |
| **Nominatim (OSM)** | `verification/services/nominatim.py` (geocoder fallback) | Real public endpoint, low rate limit. |

---

## 14. "I want to…" cheat-sheet

| Goal | Open this file first |
|------|----------------------|
| Add a new verification rule | `verification/levels/level_<N>_*.py` — write `cross_check_<rule>(...) -> dict \| None`, wire it in the orchestrator, mirror in `build_pass_evidence_*`, register the `sub_step_id` in the FE `RULE_CATALOG.L<N>` |
| Tweak a 32-point rubric resolver | `verification/services/scoring_model.py` — edit the `r_*` function. If you also want CRITICAL severity regardless of weight, set `force_critical=True` on the catalog entry |
| Edit the Final Verdict PDF | `verification/services/report_generator.py` |
| Add an extractor for a new doc | `worker/extractors/<name>.py` + register in `worker/classifier.py` + add the subtype to `app/enums.py::ArtifactSubtype` |
| Add a subtype enum | `app/enums.py`. Update `tests/unit/test_enums.py` count assertion. Run `cd frontend && npm run sync-enums` |
| Add a new admin control | new router under `api/routers/admin_*.py` + sidebar entry in `frontend/src/components/layout/Sidebar.tsx` + admin page under `frontend/src/app/(app)/admin/*` |
| Render a smarter evidence card | `frontend/src/components/cases/evidence/<RuleName>Card.tsx` + register in `evidence/registry.ts` for that `sub_step_id` |
| Re-wire auto-run for a new level | `frontend/src/components/autorun/AutoRunProvider.tsx` (`STEP_ORDER`) |
| Suppress a flaky rule globally | `/admin/learning-rules` UI — backed by `RuleOverride`. Or hard-code in `services/audit.py` (don't) |
| Change the policy.yaml rules step 11 sees | `backend/app/memory/policy.yaml`. Memory loader auto-reads on the next decisioning run |
| Allow a new doc subtype on the upload wizard | `frontend/src/components/wizard/Step2Upload.tsx` + `backend/app/services/case_completeness.py` |
| Add a DB column | New Alembic migration (§16) + add a `Mapped[...]` attr to the model in `backend/app/models/<entity>.py` |
| Add an API endpoint | New route in the right `api/routers/<file>.py` + Pydantic schema in `app/schemas/` + (probably) a service function in `app/services/` |
| Add a frontend page | `frontend/src/app/(app)/<route>/page.tsx`. Sidebar link in `components/layout/Sidebar.tsx`. SWR hook in `lib/use*.ts` |

---

## 15. Testing

### Backend

- **Unit tests** (`backend/tests/unit/`) — pure functions, no DB. Run
  fast (~15s for ~770 tests).
- **Integration tests** (`backend/tests/integration/`) — full FastAPI
  app with a temp Postgres + LocalStack. Run with
  `poetry run pytest tests/integration -v`.
- **Fixtures** (`backend/tests/fixtures/builders/`) — equifax, bank,
  CAM, dedupe builders. Use these, not raw dicts.
- **Coverage target:** ≥70% on touched code per PR. Current overall
  coverage ~24% (low because the FE-coverage equivalent isn't run via
  pytest).
- **Run all:** `cd backend && poetry run pytest -v --cov=app`.
- **Run one file:** `poetry run pytest tests/unit/test_scoring_model.py -v`.
- **Run one test:** `poetry run pytest tests/unit/test_X.py::TestY::test_z -v`.

### Frontend

- **Vitest unit/RTL tests** colocated with components (`*.test.tsx`).
  Run with `npm test` (or `npm run test:watch`).
- **Playwright e2e** in `frontend/e2e/`. Run with `npm run test:e2e`.
- **Type check:** `npm run typecheck`. Pre-existing failure in
  `NotificationsBell.test.tsx` (Vitest type) — known, not blocking.
- **Enum drift check:** `npm run check:enums`. CI-required.
- **Coverage:** `lib/` ≥80%, `components/cases/` ≥90%.

### Pre-existing failures to be aware of

Three test files have pre-existing failures unrelated to recent work:

1. `tests/unit/test_verification_level_5_5_dedupe_tvr.py` — 7 tests
   fail. Need a fixture rewrite.
2. `tests/unit/test_verification_level_2_banking.py::test_ca_narrative_with_concerns_returns_warning`
   + 2 `TestBuildPassEvidenceL2` tests. Out-of-date assertion against
   the current `cross_check_ca_narrative` description format.

When making changes, always confirm your patch doesn't ADD failures.
Pre-existing ones can stay until specifically prioritised.

---

## 16. Migrations (Alembic)

### Workflow

```bash
# 1. Edit a model under backend/app/models/
# 2. Auto-generate the migration
cd backend
poetry run alembic revision --autogenerate -m "add foo column to bar"

# 3. REVIEW the generated file under alembic/versions/<hash>_*.py
#    Auto-generate is not perfect — fix:
#      - drop renames misdetected as drop+add
#      - server_default values
#      - index order

# 4. Apply
poetry run alembic upgrade head     # or via docker compose exec backend ...

# 5. Test rollback before committing
poetry run alembic downgrade -1
poetry run alembic upgrade head
```

### Conventions

- File prefix is a 12-hex hash; the generated naming uses underscores.
- Migrations are squash-resistant — review every `op.create_table` for
  column order matching the model exactly.
- Custom Postgres types (the `case_stage` ENUM, etc.) are
  `create_type=True` at first use; later migrations that reference
  the same enum must NOT recreate it — pass `create_type=False` or use
  `PgEnum(..., name="case_stage", create_type=False)`.
- `pgvector` extension is enabled in an early migration; never drop
  that.

---

## 17. Conventions (code, branches, commits)

### Code

- **Backend:** `ruff` for lint, `black` for format (line length 100),
  `mypy --strict`. Pre-commit-style — fix locally, no auto-formatter
  in CI.
- **Frontend:** Prettier + ESLint + `tsc --noEmit` strict. Tailwind
  class order via the prettier plugin.
- **Type annotations everywhere.** Backend Pydantic models for every
  request/response shape; FE has a generated mirror in `lib/enums.ts`
  + hand-rolled types in `lib/types.ts`.
- **No raw SQL in services.** Use SQLAlchemy. Exceptions: pgvector
  similarity (uses `pgvector` SQL operator) and full-text search.

### Branches

- **`main`** — canonical. Default branch on GitHub. Everything that's
  "production-shaped" lives here. Currently identical to `4level-l1`.
- **`4level-l1`** — active dev branch. Bigger session work lands here
  first, then gets fast-forwarded onto `main` when stable.
- **`feat/m1-*` … `feat/m5-*`** — historical milestone snapshot
  branches. Tagged + immutable. Don't push to these.
- **`claude/*`** — ephemeral agent worktree branches. Safe to delete.
- **`cam-discrepancy`** — older feature branch, mostly merged.

### Commits

- **Conventional Commits** style. Prefixes:
  - `feat(<area>):` new functionality.
  - `fix(<area>):` bug fix.
  - `docs(<area>):` docs only.
  - `chore(<area>):` plumbing.
  - `test(<area>):` tests only.
  - `refactor(<area>):` refactor without behaviour change.
- **Areas:** the level (`l1`, `l5.5`), the layer (`scoring-l5`,
  `verification`, `worker`, `report`), or `frontend` / `backend`.
- **Body:** explain WHY, not WHAT. The diff shows what.
- **Co-Authored-By:** include the AI assistant on AI-helped commits
  (`Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`).

### PRs (recommended once you've onboarded collaborators)

- Branch off `main`, name `feat/<short>` or `fix/<short>`.
- Open PR back into `main`.
- Description must cover: summary, test plan, screenshots if FE.
- Squash-merge into `main` (preserves linear history).

---

## 18. Gotchas + FAQ

**Q: Why do verification triggers block the request for 30-90s?**
A: Levels run inline in the FastAPI request thread (see §12).
M8 will move them to the queue. For now, the FE's AutoRunProvider
absorbs the wait by polling — don't let users trigger from a page that
might unmount.

**Q: I added a backend enum value but the FE doesn't see it.**
A: Run `cd frontend && npm run sync-enums`. CI's `npm run check:enums`
catches drift.

**Q: A test passes locally but CI fails the enum-count assertion.**
A: `tests/unit/test_enums.py` has hardcoded `assert len(list(...)) ==
N`. Bump N when you add a value. (See commit `5789c8e` for an example.)

**Q: Re-uploading a ZIP doesn't actually re-run the verifications.**
A: Correct. `POST /approve-reupload` only opens a 24h window. After
the new ZIP lands, ingestion runs (extractors + dedupe + checklist).
Verification levels (L1 → L6) only run when the FE explicitly clicks
Auto-Run. This is filed as Bug #7 in the ongoing fix list.

**Q: The Final Report PDF says "render_failed".**
A: Check `backend/app/verification/services/report_generator.py` —
the `_safe_*` defensive readers prevent crashes on malformed scoring
data, but a totally absent `sub_step_results.scoring` will still fail
gracefully. Look at the L5 VR; if it's not COMPLETED, re-run L5.

**Q: A rule keeps firing on every case but it's a known false positive.**
A: Either:
1. Fix the rule (right answer).
2. Open `/admin/learning-rules`, add a `RuleOverride` for that
   `sub_step_id` to suppress / demote globally. The MD-decision
   precedent informs this.

**Q: I want to test the Anthropic-dependent levels but don't want to
spend tokens.**
A: Tests use recorded fixtures, not live Claude. For interactive testing,
use a low-cost test key with `anthropic.beta.cache_control` enabled —
the prompt cache means a re-run on the same case is ~free.

**Q: The frontend redirects to `/login` even though I'm logged in.**
A: HttpOnly cookie + JS-readable CSRF token both have to land. Check
the browser cookies tab: `pfl_session` (HttpOnly), `pfl_csrf` (regular).
If `pfl_session` is missing, the login proxy didn't set it — check
`pfl-web` logs + `frontend/src/app/api/proxy/[...slug]/route.ts`.

**Q: `docker compose up` fails with "address already in use" on 5432.**
A: A local Postgres is conflicting. Either stop it
(`brew services stop postgresql`) or change the host port in
`docker-compose.yml`'s `pfl-postgres` block to `127.0.0.1:5433:5432`.

**Q: LocalStack returns 503 / 502 randomly.**
A: Bouncy on M-series Macs. Restart it: `docker compose restart
localstack`. Persist the volume (`pfl-localstack-data`) is enabled, so
state survives the restart.

**Q: Where do I find an example of a structured Claude call with a
schema?**
A: `backend/app/verification/services/credit_analyst.py` is the
canonical pattern. JSON schema in the system prompt, `response_format`
left default (Claude returns text, we parse via regex JSON-extract +
Pydantic validate).

**Q: My frontend dev server can't reach the backend at port 8000.**
A: `frontend/.env.local` must have `NEXT_PUBLIC_API_BASE_URL=http://
localhost:8000`. The dockerised `pfl-web` uses
`http://backend:8000` (Docker DNS) — that's different.

---

## 19. Glossary

- **AutoCAM / SystemCam** — auto-populated CAM (Credit Appraisal Memo)
  workbook from PFL's finpage. Source of truth for financial fields.
- **CM CAM IL** — manually-typed sheet inside the same CAM workbook.
  L0 diffs SystemCam against this.
- **PD sheet** — Personal Discussion sheet. Free-text notes from the
  branch credit officer's interview with the borrower.
- **LAGR** — Loan Agreement (the signed PDF artifact).
- **NACH / Nupay** — auto-debit e-mandate that drives EMI collection.
- **PDC** — Post-Dated Cheque, given as backup EMI-recovery instrument.
- **TVR** — Tele-Verification Report. Audio recording of Credit HO's
  call with the borrower.
- **FOIR** — Fixed Obligation to Income Ratio. Standard NBFC eligibility
  metric.
- **DSCR** — Debt Service Coverage Ratio.
- **CIBIL / Equifax / Highmark / Experian** — credit bureaus. We
  parse Equifax HTML by default; the others are accepted but
  deprioritised.
- **Aadhaar / PAN / Voter ID / DL** — Indian KYC documents.
- **MRP catalogue** — admin-managed list of `(business_type, item) ->
  rupee_value`. L3 vision uses it to convert "5 sacks of rice" to a
  rupee stock value.
- **MFI** — Microfinance Institution. PFL's lending segment.
- **MD** — Managing Director. Top approver in the assessor → MD chain.
- **CRO** — Credit Risk Officer.
- **BCM** — Branch Credit Manager.
- **HO** — Head Office (Credit HO does TVR + fraud calls).
- **BCM cross-verification (L5 #30)** — proof the BCM has met both
  parties. Evidence = the "References + Contact Details" screenshot
  from the LMS PD page.
- **RuleOverride / Learning Rules** — admin-toggled global rule
  suppressions, designed to encode "we keep approving these so stop
  flagging them" learnings.
- **Negative Area** — pincode blocklist; a case in a flagged pincode
  fails the L5 #11 negative-area check.
- **Auto-Run** — the FE button that sequences L1 → L6 in one click.

---

## Appendix A — A "first feature" walkthrough

Imagine you're adding a new L5 rubric rule: **#33 — Aadhaar gender
matches PD sheet**.

1. **Decide the data sources.** Aadhaar gender is on
   `L1ExtractedDocument.gender`. PD sheet doesn't have a gender field,
   so add one (or skip this).
2. **(if needed) Add the PD field.** Edit
   `backend/app/worker/extractors/pd_sheet.py` to add `("gender",
   "gender")` to the alias list. Add a test in
   `tests/unit/test_extractors_pd_sheet.py`.
3. **Write the resolver.** In
   `backend/app/verification/services/scoring_model.py`, add:
   ```python
   def r_d33_aadhaar_gender_pd(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
       aad = _gstr(ctx.aadhaar_extraction, "gender")
       pd = _gstr(ctx.pd_sheet, "gender")
       if not aad or not pd:
           return _pending(w, "Need both Aadhaar gender + PD gender.")
       if aad.lower() == pd.lower():
           return _pass(w, f"Aadhaar={aad}, PD={pd}.", "Gender consistent.")
       return _fail(w, f"Aadhaar={aad} ≠ PD={pd}.", "Gender mismatch — investigate.")
   ```
4. **Register in the catalog.** In the same file:
   ```python
   ParamDef(33, "D", "D: Reference & TVR", "Aadhaar Gender = PD",
            "Match", 1, "BCM", r_d33_aadhaar_gender_pd),
   ```
   Update `SECTIONS` if the section's max_score changes.
5. **Update test_enums.py if you bumped any enum.** N/A here.
6. **Wire FE catalog.** In
   `frontend/src/components/cases/VerificationPanel.tsx`'s
   `RULE_CATALOG.L5_SCORING`, add an entry with sub_step_id
   `scoring_33` + title + description.
7. **Test.** Add a unit test in
   `backend/tests/unit/test_scoring_model.py` covering pass / fail /
   pending paths.
8. **Commit.**
   ```bash
   git checkout -b feat/l5-rule-33-gender
   git add backend/app frontend/src
   git commit -m "feat(l5): rubric rule #33 — Aadhaar gender vs PD sheet"
   git push -u origin feat/l5-rule-33-gender
   gh pr create --title "..." --body "..."
   ```

---

## Appendix B — Where to find more

- **README.md** — high-level summary + Quick Start.
- **SESSION_HANDOFF.md** — what shipped in the latest dev session.
- **FOLLOW_UPS.md** — known-but-deferred items.
- **docs/Auto_Run_Document_Checklist.xlsx** — operator-facing checklist
  (3 sheets: Mandatory gate / If Co-Applicant / Level-specific) that
  enumerates every artifact subtype, format, who provides it, which
  level(s) consume it, and tick-boxes for "Available" + "Uploaded"
  with COUNTIF totals. Use it before triggering Auto-Run on any case.
- **docs/superpowers/specs/** — design specs per milestone (M1-M5
  each have one). Read these before any major architectural change.
- **docs/superpowers/plans/** — implementation plans per milestone.
- **docs/superpowers/RESUME_*.md** — deep, narrative context behind
  individual feature shipments. Useful when archaeology is needed
  ("why does this work this way?").
- **docs/accessibility-m4.md** — WCAG audit notes for the FE.

---

*Maintained by the team. When the architecture changes, update this
document in the same PR.*
