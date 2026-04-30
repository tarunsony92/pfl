# PFL Credit Decisioning & Audit System — Design Spec

**Project:** Premium Finlease (PFL Finance) Credit AI Platform
**Spec date:** 2026-04-18
**Author:** Saksham Gupta (with Claude)
**Status:** Draft — pending spec review + user sign-off
**Target MVP ship:** 4–6 weeks from plan approval

---

## 1. Executive Summary

A two-phase AI system that mirrors Saksham's credit-head judgment and produces audit-grade reports for every PFL Individual Loan (IL) case. Phase 1 (Decisioning) acts as "Saksham-as-credit-head" — reads the full case kit, applies codified policy plus personally-taught heuristics, and produces an APPROVE / APPROVE_WITH_CONDITIONS / REJECT / ESCALATE_TO_CEO recommendation with evidence-cited reasoning. Phase 2 (Auditing) acts as an independent auditor — cross-verifies the team's CAM, Checklist, PD Sheet and recommendations against source documents (Equifax/CIBIL, bank statement, KYC images, visit photos, electricity bill), fills the 30-point scoring model, and issues PASS / CONCERN / FAIL.

The system learns continuously via three signals: (a) Saksham's per-case feedback on Phase 1/Phase 2 outputs, (b) retrospective NPA analysis that mines signals missed at decision time, (c) approved deviations that update the heuristics library. Hosted on AWS Mumbai, uses the Anthropic API with a tiered model cascade (Haiku → Sonnet → Opus) to minimize inference cost.

---

## 2. Purpose, Scope, and Non-Goals

### 2.1 Purpose

- Replace the manual gap-check between what the team's CAM claims and what source documents actually show.
- Codify Saksham's accumulated credit judgment so it can be applied consistently across every case by the team — without losing his personal review on critical decisions.
- Flag deviations automatically and route them to the CEO via email, fully documented.
- Learn continuously from feedback + NPA outcomes so the model improves over time.
- Produce audit-trail outputs compatible with current PFL templates (30-point scoring, filled CAM replicas, exec summary Word doc).

### 2.2 In scope for v1

- Individual Loan (IL) product, ticket sizes 50k–150k.
- Manual ZIP upload of case kits (standardized naming from Finpage).
- Phase 1 Decisioning engine, end-to-end.
- Phase 2 Auditing engine — 30-point scoring model fully auto-filled; 150-point operational audit schema prepped but deep-fill deferred.
- Memory & learning subsystem (policy, heuristics, case library, MRP database, NPA retrospective).
- Six-way address verification cascade.
- Stock quantification per case with vision-driven item + quantity + price extraction.
- Dedupe via uploaded `Customer_Dedupe.xlsx` (Finpage export).
- Settings page (policy version upload, role management, notification preferences, parameter overrides).
- Shadow-mode rollout for first 100 cases before team-live.
- AWS Mumbai deployment with IaC.

### 2.3 Explicitly deferred / v2

- 150-point operational audit deep-fill (pending Finpage API).
- 200k–300k product (ITR/GST layer).
- Loan Against Property (LAP) product (property-layer schema placeholder only).
- Direct bureau API pull (CIBIL/Equifax/Experian/CRIF) — replaces manual HTML upload.
- Finpage API integration (case metadata pull, dedupe live-query).
- KYC video vision analysis (liveness + face match).
- Signature matching across documents.
- Mobile-responsive UI optimization (desktop-first for v1).
- Portfolio-level dashboards and monthly reports.
- Collection-side integration.

### 2.4 Non-goals

- The system does not replace the human final approver. Every case ends with a human click.
- The system does not train / fine-tune any underlying LLM — "learning" is entirely memory-file based (policy, heuristics, case library, MRP DB).
- The system does not communicate with borrowers — it is a purely internal tool.
- The system does not replace RBI-mandated manual compliance steps — it logs them for audit, not executes them.

---

## 3. Users, Roles, and Access

### 3.1 Roles (v1)

| Role | Who | Can do |
|---|---|---|
| **Admin / Trainer** | Saksham | Everything. Edit policy, approve heuristics, manage users, view all cases, give training feedback, override decisions, upload NPA list. Only role that can edit `policy.yaml` and `heuristics.md`. |
| **CEO** | (Name TBD) | View all cases. Approve/reject deviations. Receive auto-reject notification emails. Can give feedback that updates heuristics. |
| **Credit HO** | (Head Office credit role) | View all cases. Give feedback that updates heuristics. Cannot unilaterally approve deviations (escalates to CEO). |
| **AI Analyser / Operator** | (Person who uploads & operates the system) | Upload case ZIPs. View cases. Trigger re-runs. Cannot edit policy or heuristics. |
| **Underwriter** | Team members (added later) | Upload cases assigned to them; view their own cases + any team-visible ones. Cannot edit policy or heuristics. |

### 3.2 Role management

- Settings page has a "Users & Roles" tab.
- Admin can create new roles and assign granular permissions (placeholder: all-visible in v1; restriction toggles added in v1.1).
- Audit log records who did what when, per case and per settings change.

### 3.3 Authentication

- Email + password with bcrypt-hashed storage.
- MFA (TOTP) required for Admin, CEO, Credit HO; optional for others.
- Session-based, HTTPS-only cookies, 8-hour idle timeout.
- Password reset via email with time-limited token.

---

## 4. High-Level Architecture

```
                              ┌─────────────────────────┐
                              │  Underwriter / Operator │
                              │   (browser, anywhere)   │
                              └───────────┬─────────────┘
                                          │ HTTPS
                                          ▼
                     ┌────────────────────────────────────┐
                     │        AWS Mumbai (ap-south-1)     │
                     │                                    │
                     │  ┌──────────────────────────────┐  │
                     │  │  Next.js Web App (ECS/Fargate│  │
                     │  │   or Amplify) — UI + Auth    │  │
                     │  └──────────┬───────────────────┘  │
                     │             │                      │
                     │  ┌──────────▼─────────────────┐    │
                     │  │  Python API (FastAPI)      │    │
                     │  │  on ECS/Fargate            │    │
                     │  │  • case ingest             │    │
                     │  │  • workflow orchestrator   │    │
                     │  │  • settings / users        │    │
                     │  └──────┬──────────┬──────────┘    │
                     │         │          │               │
                     │  ┌──────▼──┐  ┌────▼────────────┐  │
                     │  │ RDS     │  │  S3 (case       │  │
                     │  │ Postgres│  │  artifacts,     │  │
                     │  │ (meta,  │  │  reports)       │  │
                     │  │ memory) │  └─────────────────┘  │
                     │  └─────────┘                       │
                     │         ▲                          │
                     │         │                          │
                     │  ┌──────┴──────────────────────┐   │
                     │  │  Worker pool (SQS + ECS)    │   │
                     │  │  • Phase 1 decisioning      │   │
                     │  │  • Phase 2 audit layers     │   │
                     │  │  • NPA retrospective jobs   │   │
                     │  │  • Heuristic distillation   │   │
                     │  │  • Email notifier (SES)     │   │
                     │  └──────┬──────────────────────┘   │
                     │         │                          │
                     └─────────┼──────────────────────────┘
                               │ HTTPS
                               ▼
                    ┌──────────────────────────────┐
                    │   Anthropic API              │
                    │   • Haiku 4.7 (bulk)         │
                    │   • Sonnet 4.7 (synthesis)   │
                    │   • Opus 4.7 (judgment)      │
                    │   • Prompt caching on        │
                    │     policy + heuristics      │
                    └──────────────────────────────┘
```

### 4.1 Component responsibilities

- **Next.js web app** — Frontend UI (React Server Components). Case dashboard, case detail views (Phase 1/2 side-by-side), policy editor, heuristics library, settings, NPA upload form, feedback forms. PFL branded (blue + grey per logo at pflfinance.com).
- **Python API (FastAPI)** — Authentication, authorization, case CRUD, file upload/download (presigned S3), workflow state transitions, settings management. Emits jobs to SQS queues.
- **Worker pool** — Consumes SQS jobs. Stateless Python workers for: ingestion (parse ZIP, extract Excel/HTML/PDF/image), Phase 1 decisioning, Phase 2 audit layers (A/B/C in parallel), NPA retrospective analysis, heuristic distillation, email sending.
- **RDS Postgres** — Case metadata, user/role data, workflow stage, memory tables (policy versions, heuristics, case library index, MRP database, NPA records, audit log).
- **S3** — Raw case ZIPs and extracted artifacts, generated output files (filled templates, Word summaries), historical backups.
- **SQS** — Work queues for each job type with DLQs for failures.
- **SES** — Outbound email (CEO notifications, deviation alerts, feedback prompts, system status).

### 4.2 Model cascade (cost-optimized)

| Task | Model | Rationale |
|---|---|---|
| File classification, KYC image OCR, bank statement PDF extraction | Haiku 4.7 (vision) | High volume, well-defined task |
| 30-point audit items + 150-point bulk boolean items | Haiku 4.7 (parallelized, ~10 items per call) | Bulk boolean judgments |
| Document cross-verification synthesis | Sonnet 4.7 | Multi-source reconciliation needs judgment |
| Phase 1 decisioning (core "Saksham" judgment) | **Opus 4.7** | Highest-stakes reasoning |
| Phase 2 verdict + exec summary | Sonnet 4.7 | Synthesis / summarization |
| Heuristic distillation from feedback | Sonnet 4.7 | Rule extraction |
| NPA retrospective analysis | Opus 4.7 | Subtle signal detection across history |
| Case library retrieval | Voyage embeddings | Cheap semantic search (non-LLM) |

Prompt caching applied to `policy.yaml` + `heuristics.md` + recent NPA summary (read on every case, rarely change). Expected effective reduction: 40–60% of input token cost in steady state.

### 4.3 Estimated cost per case

**Target: $1.00–$2.00 per case at steady state** (with caching).

| Stage | Est. cost |
|---|---|
| Ingestion + classification | $0.01 |
| KYC image OCR + match | $0.02–0.05 |
| Bank statement extraction (PDF) | $0.05–0.10 |
| Address cascade verification (6-way) | $0.05 |
| Stock quantification (vision on 3+ business photos) | $0.10–0.20 |
| 30-point audit fill | $0.15–0.30 |
| Doc cross-verification synthesis | $0.20–0.40 |
| **Phase 1 decisioning (Opus)** | $0.80–1.50 |
| Phase 2 verdict + exec summary | $0.10–0.20 |
| **Per-case total (with caching)** | **$1.00–2.00** |

At 20 cases/day, ≈$30–60/day = ₹75k–150k/month. Variable, controllable by adjusting which stages use which model.

---

## 5. Phase 1 — Credit Decisioning Engine

### 5.1 Purpose

Given a fully-ingested case kit, produce a credit decision recommendation that mirrors how Saksham (as credit head) would decide.

### 5.2 Decision outputs

Every Phase 1 run produces:

- **Decision:** `APPROVE` | `APPROVE_WITH_CONDITIONS` | `REJECT` | `ESCALATE_TO_CEO`
- **Recommended amount** (if approve) — from the ticket grid (50k/60k/75k/100k/125k/150k)
- **Recommended tenure** (from grid, per amount)
- **Conditions** (if approve-with-conditions) — e.g., "subject to updated ITR", "subject to guarantor addition"
- **Reasoning** — narrative, every claim cited to a specific field in a specific document
- **Pros / cons table** — side-by-side, for the underwriter's decision support
- **Deviations flagged** — each deviation type named + policy rule breached + severity
- **Risk summary** — top-3 risks
- **Confidence score** — 0–100

### 5.3 Decision logic flow (the "Saksham algorithm")

Steps run sequentially. Any hard-rule fail → short-circuit to REJECT or ESCALATE (with full reasoning still produced).

```
┌─ STEP 1: HARD POLICY GATES (deterministic Python, no LLM) ─┐
│  • CIBIL ≥ 700 both applicant & co-app (else REJECT)       │
│  • No Written-off/Suit-filed/LSS (else REJECT)             │
│  • Negative business list match (else REJECT + CEO email)  │
│  • Indebtedness <₹5L including this loan (else REJECT)     │
│  • Age in range (21–60 App / 21–65 CoApp) (else REJECT)    │
│  • Geo within 25 km of branch (else REJECT)                │
│  • Required doc checklist complete (else pause for upload) │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 2: BANKING CHECK (deterministic + Haiku for PDF) ────┐
│  • Extract last 6 months of balances from bank statement   │
│  • Compute ABB (avg bank balance)                          │
│  • Rule: ABB ≥ proposed monthly EMI                        │
│  • Count bounces / NACH returns (rule: zero bounces pref)  │
│  • Flag: high-value entries, suspicious round-number dep.  │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 3: INCOME SOURCE CLASSIFICATION (Haiku) ─────────────┐
│  • Classify each credit entry: business / salary /         │
│    transfer / refund / suspicious                          │
│  • Compute business-income-share of total inflows          │
│  • Count distinct income sources (heuristic: >1 preferred) │
│  • Count earning family members (from CAM + PD Sheet)      │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 4: KYC & DEMOGRAPHIC MATCH (Haiku vision) ───────────┐
│  • OCR Aadhaar, PAN, voter, DL — extract name/DOB/addr     │
│  • Face match Aadhaar photo ↔ KYC video thumbnail          │
│    ↔ residence photo ↔ business photo                      │
│  • Name variants allowed (initials, spouse's surname)      │
│  • DOB must match exactly across all IDs                   │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 5: SIX-WAY ADDRESS VERIFICATION (Sonnet) ────────────┐
│  Address sources:                                          │
│   (a) Aadhaar card                                         │
│   (b) PAN card                                             │
│   (c) CIBIL / Equifax report address                       │
│   (d) Electricity bill                                     │
│   (e) Bank statement address                               │
│   (f) GPS coordinates of house visit photo                 │
│  Rule: ≥4 of 6 must match (same village + pincode)         │
│  Any mismatch logged as mismatch evidence                  │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 6: BUSINESS PREMISES CHECK (Sonnet vision) ──────────┐
│  • Verify business visit GPS is "justifiable distance"     │
│    from house (rule: ≤25 km; >10 km = flag)                │
│  • Rule: house OR business premises must be owned          │
│  • Premises structure quality (permanent / kuccha)         │
│  • Reject if thela/rehdi/temporary                         │
│  • Roof type (RCC/stone slab required)                     │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 7: STOCK QUANTIFICATION (Opus vision) ───────────────┐
│  For each business photo (min 3):                          │
│   • Identify visible items (description)                   │
│   • Estimate quantity (exact / range / qualitative)        │
│   • Look up unit price: MRP database first, fall back      │
│     to web-search knowledge, fall back to Opus estimate    │
│   • Compute per-item total value                           │
│   • Aggregate total stock value                            │
│  Store inventory record to case + update MRP database      │
│  Rule: total stock value > loan amount requested           │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 8: INCOME vs STOCK vs BANK RECONCILIATION (Sonnet) ──┐
│  • Stock value reasonable for declared monthly sales?      │
│    (e.g., inventory turnover days check)                   │
│  • Bank statement credits align with declared sales?       │
│    (±15% tolerance)                                        │
│  • Income proof amounts align with bank + declared?        │
│  • FOIR calculation: sum obligations ÷ income              │
│    (policy cap 50%, heuristic alert at 40%)                │
│  • IDIR check (50% cap)                                    │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 9: PD SHEET ANALYSIS (Sonnet) ───────────────────────┐
│  • Extract interview narrative from PD Sheet.docx          │
│  • Consistency with CAM + source docs                      │
│  • Specific questions asked & answers                      │
│  • Red flags (evasive, contradictory, coached answers)     │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 10: CASE LIBRARY RETRIEVAL (embeddings) ─────────────┐
│  • Embed current case feature vector                       │
│  • Retrieve top 5–10 similar past decided cases            │
│  • Include their decisions + outcomes + Saksham's          │
│    feedback as reference                                   │
│  • Graceful degradation: if case library is empty          │
│    (shadow-mode pre-case-100), skip this step with a       │
│    note in Phase 1 output — downstream synthesis (Step 11) │
│    treats retrieved cases as optional supporting context   │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ STEP 11: JUDGMENT SYNTHESIS (Opus) ───────────────────────┐
│  Inputs: all prior step outputs + policy.yaml +            │
│          heuristics.md + retrieved past cases +            │
│          NPA pattern warnings                              │
│  Outputs: Decision + amount + conditions + reasoning +     │
│          pros/cons + deviations + confidence               │
│  If ANY deviation → decision = ESCALATE_TO_CEO             │
│  If confidence <60 → decision = ESCALATE_TO_CEO            │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
                      Phase 1 output saved
                      Ready for Phase 2
```

### 5.4 Hard-rule reject policy (short-circuit from any step)

The following conditions cause immediate REJECT + CEO email (no further steps run):

1. CIBIL < 700 (either applicant or co-applicant)
2. Written-off / suit-filed / LSS status on CIBIL
3. Negative business list match (hard-prohibited category)
4. Total indebtedness ≥ ₹5L including proposed loan
5. Age out of range
6. Business > 25 km from branch
7. Business operates from non-permanent structure (thela/rehdi/kuccha)
8. Both residence and business rented (neither owned)

### 5.5 Auto-escalation policy

Any case with ANY of these → `ESCALATE_TO_CEO`:

- Any policy deviation (regardless of severity)
- Confidence score < 60
- NTC applicant with loan > 50k
- FOIR 40–50% (warning zone; >50% is hard reject)
- CIBIL in the band `[700, 749]` (750 is policy ideal; 700 is the floor set by Saksham; everything strictly below 700 is auto-reject per §5.4)
- DPD presence in last 24 months (policy says 6 months; Saksham heuristic)
- Stock value 0.8–1.0× loan amount (marginal)
- Six-way address match with 2+ mismatches

Note: `REJECT` and `ESCALATE_TO_CEO` are distinct terminal states — REJECT is used for hard-rule breaches (§5.4), ESCALATE is used when a human (CEO) must make the judgment call. Both trigger CEO email but have different workflow next-steps.

### 5.6 Email notifications triggered by Phase 1

| Trigger | Recipients | Template |
|---|---|---|
| Decision = REJECT (hard-rule fail) | CEO, Admin | Loan ID, applicant, primary reason, link to case |
| Decision = ESCALATE_TO_CEO | CEO, Admin, Credit HO | Loan ID, applicant, deviations list, link |
| Decision = APPROVE_WITH_CONDITIONS | Underwriter, Admin | Loan ID, conditions checklist |
| Negative business match | CEO, Admin | Loan ID, business name, matched category |

---

## 6. Phase 2 — Audit Engine

### 6.1 Purpose

Independent arm's-length verification of Phase 1 decision AND team's CAM/Checklist/PD. Two layers in v1:

- **Layer A: 30-point credit audit** (fully auto-filled) — pre-approval gate
- **Layer B: 150-point loan audit** (schema + partial fill) — prepped for when Finpage API arrives; deep-fill deferred

### 6.2 Layer A: 30-point credit audit (v1 full)

Auto-fills `30 Point Scoring Model Draft.xlsx` based on current PFL template. Each item gets:
- Status: Pass / Fail / N/A / Partial
- Score earned (0 to weight)
- Evidence pointer (file + field or cell reference)
- Deviation notes (if any)
- Risk flag (if relevant)

Sections:
- **A: Credit Assessment & Eligibility** (items 1–13, max 47 pts)
- **B: QR and Banking Check** (items 14–22, max 30 pts)
- **C: Assets & Living Standard** (items 23–27, max 15 pts)
- **D: Reference Checks & TVR** (items 28–30, max 8 pts)

**Overall verdict thresholds** (per user):
- **Pass:** ≥ 90
- **Concern:** 70–89
- **Fail:** < 70

Additional computed blocks:
- **Eligibility vs Banking & Living Standard Analysis** (Declared income vs Bank credit 6M, ABB vs EMI, Income variance %, FOIR, Eligibility calculator amount vs Sanctioned, Living standard rating, EB verdict)
- **Deviation & Error Log** (up to 10 rows, each with S.No, Category, Description, Role, Step Violated, Impact, Default Risk, Action, Status, Notes)

### 6.3 Layer B: 150-point operational audit (v1 schema only, partial fill)

Schema prepped (17 sections A–Q: KYC, Basic Info, Product, Financials-App, Financials-CoApp, Vintage, Assets, CIBIL, Dedupe/Fraud, QR, TVR, Credit Assessment, Documents, Ops, Accounts, Role Comments, Site Visit).

v1 fills items where data is available from the case kit alone (est. ~60–80 of 150). Remaining items show "Pending API" status. Full auto-fill arrives in v2 once Finpage API is integrated (3–4 months per user's timeline).

### 6.4 Audit runs in parallel

Worker dispatches three parallel sub-jobs on Phase 2 trigger:
- Layer A fill
- Layer B partial fill  
- Doc cross-verification + exec summary

All three merge results into final Phase 2 output.

### 6.5 Phase 2 outputs

- `{loan_id}_30pt_audit_filled.xlsx`
- `{loan_id}_150pt_audit_partial.xlsx`
- `{loan_id}_mismatch_log.xlsx` (doc cross-verification findings)
- `{loan_id}_audit_summary.docx` (Word exec summary, 1–2 pages)
- Audit verdict: PASS / CONCERN / FAIL
- Mismatch count, deviation count, critical issues count

---

## 7. Memory & Learning Subsystem

### 7.1 Four memory stores

**1. `policy.yaml`** — Hard rules, seeded from IL Product & Policy doc. Versioned.

Example structure:
```yaml
version: "2026-04-18-v1"
effective_from: "2026-04-18"
product: "IL"
amount_range: [50000, 150000]
bureau:
  cibil_min: 700
  no_dpd_months: 24
  reject_statuses: ["written_off", "suit_filed", "lss"]
foir_cap_pct: 50
idir_cap_pct: 50
total_indebtedness_cap_inr: 500000
age:
  applicant: [21, 60]
  co_applicant_1: [21, 65]
  co_applicant_other: [21, 75]
  guarantor: [30, 65]
  exit_age_max: 60
stability:
  residence_years_min: 3
  business_years_min: 3
  both_rented_allowed: false
geo_radius_km: 25
stock_to_loan_min_ratio: 1.0
address_match_min_of_six: 4
banking:
  min_months: 6
  abb_to_emi_min_ratio: 1.0
  max_gap_before_disb_days: 20
negative_business_list: [...]  # 30+ categories from policy doc
ntc:
  max_loan_without_guarantor: 50000
ticket_grid:
  - {amount: 50000, tenure: 12, roi: 32, emi: 4924}
  - {amount: 75000, tenure: 18, roi: 32, emi: 5301}
  # ... etc
moratorium_days_if_disbursed_after_15th: 30
deviation_approver: "CEO"
```

Admin-only edit. Version history retained. Upload tab in settings accepts new YAML; system validates schema and activates on apply.

**2. `heuristics.md`** — Seeded with user's 11 rules. Grows semi-automatically.

Initial seed:
```markdown
# Saksham's Credit Heuristics (seed v1)

## Hard rules beyond policy
- House address on Aadhaar must match CIBIL address, PAN address, electricity bill address, and GPS coordinates of house visit.
- Business visit GPS must be at justifiable distance (≤25 km) from house address.
- Either house or business premises must be owned — both-rented combinations rejected.
- Stock value in business must exceed loan amount requested.
- Bank statement credits must align with declared sales and income proof (±15%).
- No DPDs in CB report for past 24 months minimum.
- CB score must be >700 (anything else auto-reject).
- Borrower should have some unsecured loan exposure to track behavior pattern.
- Consumer FOIR should not exceed 50%.
- Borrower should have NACH clearances and no bounces in bank statement.

## Soft signals that increase confidence
- More than one earning family member → higher confidence in repayment.
- Income from multiple sources → higher confidence.
```

Growth via semi-automatic distillation: after every feedback from Saksham/CEO/Credit HO, the system proposes a draft heuristic, user approves/edits/rejects, approved heuristic appended with source reference (which case, which feedback).

**Heuristic approval UI unification:** The approval flow for (a) case-feedback-derived heuristics (§7.3 step 6) and (b) NPA-retrospective-derived heuristics (§7.2 step 4) share the same web UI surface — a "Proposed Heuristics" queue in the Heuristics tab of Settings, tagged by source. Reviewer sees the proposed rule text, source evidence (case IDs or NPA pattern), and three buttons: Approve / Edit-then-Approve / Reject. Unified surface prevents fragmentation and gives a single review inbox.

**3. `case_library/`** — Every past case + final decision + feedback + outcome. Indexed by embeddings for similarity retrieval.

Per case record:
```json
{
  "loan_id": "10006484",
  "submitted_at": "2026-04-18T10:34:00+05:30",
  "applicant_feature_vector": [...],
  "phase_1_output": {...},
  "phase_2_output": {...},
  "human_feedback": [
    {"reviewer": "saksham", "at": "...", "text": "...",
     "heuristic_proposed": "...", "accepted": true}
  ],
  "final_decision": "APPROVED",
  "final_approver": "saksham",
  "downstream_outcome": "REPAID" | "NPA" | "DELINQUENT" | null,  // updated later
  "embedding_id": "..."
}
```

**4. `mrp_database.json`** — Product → price catalog. Grows per case.

Per entry:
```json
{
  "item": "Lakme Foundation 30ml",
  "category": "cosmetics",
  "unit_price_inr": {"min": 250, "median": 320, "max": 450, "currency": "INR"},
  "sources": ["case-10006484-photo-2", "case-10006512-photo-1", "web:amazon.in"],
  "confidence": 0.85,
  "last_updated": "2026-04-18"
}
```

Used in Step 7 of Phase 1 before falling back to LLM estimation. Saves inference cost over time.

### 7.2 NPA retrospective learning

**Trigger:** Admin uploads NPA list (Excel with columns: Loan ID, NPA date, stage, loss amount, reason if known).

**Process:**
1. For each loan ID in NPA list, retrieve the original case from `case_library/`.
2. Run Opus on the set of NPA cases with prompt: *"What signals were present at decision time that we missed, but look significant in retrospect?"*
3. Opus outputs candidate patterns: e.g., "8 of 14 NPA cases had FOIR 40–50% + 2+ bank bounces in prior 6 months + only 1 earning family member — combination appears predictive of NPA."
4. Each candidate pattern → shown to Saksham for approval.
5. Approved patterns → appended to `heuristics.md` and flagged as "derived from NPA retrospective".
6. Subsequent Phase 1 runs include these NPA-derived heuristics.

### 7.3 Feedback loop flow

After every Phase 1 + Phase 2 produces outputs:

1. Human (Saksham first 100 cases; later also CEO/Credit HO) reviews both phases side-by-side in web UI.
2. Final decision action: Approve / Modify & Approve / Reject / Escalate.
3. Feedback form prompts: *"Was the AI's decision correct? If not, what did it miss?"*
4. Text feedback submitted.
5. Worker runs **heuristic distillation (Sonnet)**: extracts candidate rule from feedback.
6. Candidate rule shown to reviewer with Approve / Edit / Reject.
7. If Approve → rule appended to `heuristics.md` with citation.
8. Case marked complete, added to `case_library/` with full trail.

---

## 8. Data Model (key entities)

**users** — id, email, hashed_password, role, created_at, mfa_enabled, mfa_secret, last_login
**cases** — id, loan_id (unique, from Finpage), uploaded_by, uploaded_at, zip_s3_key, current_stage, assigned_to, created_at, updated_at
**case_artifacts** — id, case_id, artifact_type (auto_cam | checklist | pd_sheet | equifax | bank_stmt | kyc_image | visit_photo | electricity_bill | kyc_video | other), filename, s3_key, extracted_at
**case_extractions** — id, case_id, extractor_name, extraction_json, confidence, model_used, cost_usd, created_at
**phase_1_outputs** — id, case_id, decision, amount, tenure, conditions_json, reasoning_md, pros_cons_json, deviations_json, confidence, model_used, cost_usd, created_at
**phase_2_outputs** — id, case_id, verdict, score_30pt, score_150pt_partial, mismatch_count, deviation_count, summary_md, artifacts_s3_keys, cost_usd, created_at
**feedback** — id, case_id, phase (1|2), reviewer_user_id, feedback_text, distilled_heuristic, heuristic_accepted, created_at
**heuristics** — id, text, source_case_id, source_feedback_id, is_from_npa, accepted_by, accepted_at, active
**policy_versions** — id, version_name, yaml_content, uploaded_by, uploaded_at, activated_at, is_active
**mrp_entries** — id, item_name, category, price_min, price_median, price_max, sources_json, confidence, last_updated
**npa_uploads** — id, uploaded_by, uploaded_at, excel_s3_key, loan_id_count, analysis_job_id
**npa_records** — id, loan_id, npa_date, stage, loss_amount_inr, reason, analyzed, patterns_extracted_json
**audit_log** — id, user_id, action, entity_type, entity_id, before_json, after_json, at
**case_inventory** — id, case_id, extracted_from_photo_s3_key, items_json (array of {description, quantity, unit_price, source, total_value, confidence}), total_stock_value_inr, extraction_confidence, created_at
**dedupe_uploads** — id, uploaded_by, uploaded_at, excel_s3_key (snapshot of Customer_Dedupe.xlsx, versioned)

---

## 9. Workflow Stages

Enforced state machine per case:

```
UPLOADED                    → Case ZIP received, awaits validation
     │
     ▼
CHECKLIST_VALIDATION        → Running doc completeness check
     │
     ├──→ CHECKLIST_MISSING_DOCS (pause state; underwriter notified;
     │     state held until missing artifacts uploaded, then returns
     │     to CHECKLIST_VALIDATION)
     │
     ▼
CHECKLIST_VALIDATED         → All required artifacts present
     │
     ▼
INGESTED                    → All artifacts extracted, fields indexed
     │
     ▼
PHASE_1_DECISIONING         → Worker processing; ~2–5 min
     │
     ├──→ PHASE_1_REJECTED  (hard-rule fail; CEO emailed; terminal)
     │
     ▼
PHASE_1_COMPLETE            → Human reviews Phase 1 output
     │
     ▼
PHASE_2_AUDITING            → Worker processing audits; ~3–7 min
     │
     ▼
PHASE_2_COMPLETE            → Human reviews Phase 2 output
     │
     ▼
HUMAN_REVIEW                → Saksham (first 100) / CEO / Credit HO reviews
     │
     ├──→ APPROVED
     ├──→ REJECTED
     ├──→ ESCALATED_TO_CEO  (CEO approval needed)
     │        │
     │        ├──→ APPROVED  (after CEO sign-off)
     │        └──→ REJECTED
     │
     ▼
[Operational stages — v2 when Finpage API arrives]
DISBURSED → POST_AUDIT_DONE → CLOSED
```

### 9.1 State transition rules

- Only Admin/CEO/Credit HO can transition a case to `APPROVED` / `REJECTED` in v1.
- Any transition records to `audit_log` (user, timestamp, before/after state).
- Automated transitions (UPLOADED → CHECKLIST_VALIDATED → INGESTED → PHASE_1_DECISIONING → PHASE_1_COMPLETE → PHASE_2_AUDITING → PHASE_2_COMPLETE → HUMAN_REVIEW) happen without user action.
- `CHECKLIST_MISSING_DOCS` pauses state machine; resumes when missing files uploaded.

---

## 10. Settings Page

Tabs accessible to Admin only (unless noted):

1. **Policy** — view current active `policy.yaml`; upload new version; activate a version; view version history and diffs.
2. **Heuristics** — view all heuristics (active + archived); edit text directly; archive individual rules; export full list.
3. **Users & Roles** — CRUD users; assign role; reset password; force MFA enroll; view last login.
4. **Permissions** — (v1.1) fine-grained toggles per role × resource.
5. **Notifications** — configure recipient list per trigger type (CEO email, reject email, escalation email); email template overrides.
6. **Deviation Approver** — default: CEO; configurable to other role assignments per deviation type.
7. **Parameters** — overrides for policy values (CIBIL threshold, FOIR cap, geo radius, stock-to-loan ratio); changes tracked and versioned.
8. **MRP Database** — view, edit, bulk import/export the price catalog.
9. **Dedupe** — upload new `Customer_Dedupe.xlsx` (Finpage export); view history.
10. **NPA Upload** — upload NPA list Excel, trigger retrospective analysis, view extracted patterns, approve/reject proposed heuristics.
11. **Audit Log** — filter by user/date/entity, export.
12. **Integrations** — Finpage API config (v2), Bureau API config (v2), AWS/SES config.

---

## 11. Infrastructure & Deployment (AWS Mumbai)

### 11.1 Region + services

- Region: `ap-south-1` (Mumbai) — RBI-friendly for data residency.
- Compute: ECS/Fargate for web + API + workers (container-based, no server mgmt).
- Database: RDS Postgres (db.t4g.medium initially, scalable).
- Storage: S3 (case files, outputs, backups); versioning enabled.
- Queue: SQS (one queue per job type: ingestion, phase1, phase2, npa, heuristic-distill, email).
- Email: SES (outbound only; domain verification required).
- Secrets: AWS Secrets Manager (Anthropic API key, DB password, JWT secret).
- CDN: CloudFront in front of web app; ACM-issued TLS cert.
- DNS: Route 53 for custom domain (e.g., `credits.pflfinance.com`).
- Monitoring: CloudWatch logs + metrics; Sentry for error tracking.
- IaC: AWS CDK (TypeScript) — fully reproducible environment.

### 11.2 Estimated infra cost (steady state, 20 cases/day)

| Service | Est. cost |
|---|---|
| ECS Fargate (2 web + 1 API + 2 worker tasks) | $80/mo |
| RDS Postgres t4g.medium | $70/mo |
| S3 (50 GB active + 500 GB backup) | $20/mo |
| SQS | <$1/mo |
| SES (low volume email) | <$1/mo |
| CloudFront + Route 53 | $5/mo |
| CloudWatch | $10/mo |
| **Total AWS** | **~$190/mo (~₹16k/mo)** |
| + Anthropic API (var) | ₹75k–150k/mo @ 20 cases/day |
| **Grand total** | **~₹95k–170k/mo** |

### 11.3 Setup flow (user-facing)

1. Admin triggers "Deploy to AWS" in setup UI on Saksham's Mac Studio.
2. System prompts for: AWS account ID, AWS Access Key + Secret (least-privilege IAM user), AWS payment method verification (card on file in AWS).
3. CDK deploys stack; takes ~15–20 min.
4. System prompts for Anthropic API key → stored in Secrets Manager.
5. System prompts for custom domain (default: auto-generated `*.pflcredits.com` or similar) → Route 53 + ACM setup.
6. System sends Saksham initial admin login email with temp password + MFA enrollment link.
7. Ready to ingest first case.

### 11.4 Backup & disaster recovery

- RDS automated backups (7-day retention).
- S3 versioning + cross-region replication (to `ap-south-2` Hyderabad) for case files.
- Daily DB snapshot exported to S3.
- RPO: 24 hours. RTO: 4 hours.

---

## 12. Security & Compliance

### 12.1 Data handling

- All case data stored in AWS Mumbai.
- All S3 objects encrypted at rest (AWS KMS, customer-managed key).
- All RDS data encrypted at rest.
- TLS 1.2+ in transit (CloudFront + ALB).
- Data sent to Anthropic API at inference time — pay-as-you-go API has no training on user data (verified in Anthropic DPA).
- Retention: 7 years per user requirement, then automatic deletion with audit log entry.

### 12.2 Access control

- Least-privilege IAM roles for each service.
- No long-lived AWS credentials stored in application code; use IAM task roles.
- Anthropic API key only accessible to worker tasks, via Secrets Manager.
- Session tokens short-lived + HttpOnly cookies.
- MFA required for Admin/CEO/Credit HO.

### 12.3 Audit trail

- Every user action on a case logged.
- Every settings change logged.
- Every automated decision logged with model used, prompt version, cost.
- Export as CSV for RBI/internal audit.

### 12.4 PII masking

- Aadhaar masked in UI by default (last 4 digits visible, full visible on click with audit-log entry).
- PAN similarly masked.
- Bank account numbers masked.
- Generated Word/Excel outputs include full PII (necessary for audit) but are behind role-gated download.

### 12.5 Compliance flags

- RBI Fair Practice Code: no borrower-facing outputs in v1; system is internal only.
- DPDP Act (Digital Personal Data Protection Act 2023): data residency in India ✓, purpose limitation ✓, consent tracking through Finpage (upstream).
- This is an internal audit tool, not a credit bureau or CIC — so CIC regulations don't apply.

---

## 13. Validation & Rollout

### 13.1 Validation dataset

**Before shadow mode:** Saksham will provide 10–20 historical cases with known 30-point scores, CAM, decisions, and outcomes. System runs them through Phase 1 + Phase 2 and compares:

- Decision agreement rate (target: ≥80% directional agreement in first pass)
- 30-point score deviation (target: ±10 points average)
- Mismatch detection accuracy (target: ≥70% of known mismatches caught)
- Hallucination rate (target: 0 invented facts)

If thresholds not met, iterate on prompts + heuristics before shadow mode.

**Additional metric — threshold-flip accuracy:** Since Phase 2's verdict comes from bucketed thresholds (Pass ≥ 90, Concern 70–89, Fail < 70), a score that's within the ±10 average tolerance can still flip verdicts at a boundary (e.g., predicted 95, actual 85 → Pass flips to Concern). We track **verdict-flip rate** separately and target < 15% of validation cases flipping bucket vs. ground truth.

### 13.2 Shadow mode rollout

**Phase A (first 100 cases):** Only Saksham uses the system. Team continues existing manual workflow. Saksham reviews every case's AI output, gives feedback, watches heuristics grow. Target duration: 2–4 weeks.

**Phase B (cases 101–250):** Team can submit cases to AI system in parallel with their manual process. Saksham spot-checks. CEO/Credit HO begin giving feedback too. System remains advisory.

**Phase C (cut over):** Team uses AI system as primary. Manual process becomes fallback. Continue monitoring + feedback for 4 weeks.

**Phase D (production):** AI system is the workflow. Manual fallback retained.

### 13.3 Rollback plan

- Anytime: toggle "AI system maintenance mode" in settings → team falls back to manual workflow.
- Prompt regressions caught by validation set re-runs (nightly).
- Any per-case catastrophic output → one-click "Ignore this AI output and decide manually" in case UI.
- Policy version rollback: activate older version in Settings → Policy.

---

## 14. Future-Proofing (designed for, not built in v1)

### 14.1 200k–300k product

When PFL scales to 200k–300k tickets:
- New policy version with: CIBIL floor 750, mandatory GST upload, mandatory ITR, stronger vintage proof, deeper banking analysis.
- Schema already supports per-product policy differences via `policy.yaml.products[].overrides`.
- Ingestion adds GST PDF + ITR PDF extractors (Haiku).
- Decisioning adds GST sales-reconciliation and ITR-reconciliation steps.

### 14.2 LAP (Loan Against Property)

Schema placeholder:
- `property_artifacts` — valuation report, title search, encumbrance cert, legal opinion, RM inspection photos.
- `property_layer` extension in `policy.yaml`: LTV cap, property-type whitelist, title-search-required flag, 2-valuer requirement, industry-standard legal checks.
- New Phase 1 steps: property cross-verification (2 valuers agreement), LTV calc, title clear check.

### 14.3 Finpage API integration (3–4 months per user)

When Saksham's own software is ready:
- Replace manual ZIP upload with Finpage webhook or pull endpoint.
- Replace `Customer_Dedupe.xlsx` upload with live dedupe API call.
- Fill ~60 more items of 150-point audit via API (post-disbursement operational items: NACH, disbursement, UTR, e-sign, ₹1 test).
- Bi-directional: AI decision writes back to Finpage.

### 14.4 Bureau API direct

Replace Equifax HTML upload with direct API pull (CIBIL/Experian/Equifax/CRIF).

---

## 15. Open Questions / TBD

1. Exact Mac Studio → AWS initial data upload mechanism (not a blocker, addressed at setup time).
2. CEO email address (user to provide at setup).
3. Credit HO user (identity) to onboard.
4. Domain name for production (`credits.pflfinance.com` or alternative).
5. SES sender domain verification target email.
6. Branch list + GPS coordinates (for the 25 km geo-radius check) — will be populated from first cases or provided separately.
7. Validation dataset (10–20 historical cases) — user to provide before shadow mode.
8. NPA historical list — user to provide when ready.
9. Moratorium calculation nuance: does the 30-day moratorium shift the first EMI date only, or the whole schedule? (Will clarify with user when we wire up EMI reconciliation.)
10. Guarantor flow: policy mentions guarantor for NTC >50k; UI flow for capturing guarantor docs deferred to v1.1.

---

## 16. Appendix A — Policy rules extracted from FINAL IL Product & Policy.docx

### Eligibility
- Age: Applicant 21–60, Co-App1 21–65, Other CoApp 21–75, Guarantor 30–65, Exit age ≤ 60.
- Business vintage: minimum 3 years same line of business, same location.
- Residence: 3 years same premises (per product specs table, binding).
- Annual sales: >₹10 lakh (services >₹50k).
- Annual household income: >₹3.5 lakh.
- Permanent structure only; RCC/stone-slab roof.

### Bureau
- CIBIL ≥ 750 policy / ≥ 700 Saksham override (auto-reject <700).
- No DPD last 24 months (Saksham heuristic; policy says 6 months).
- No Written-off / Suit-filed / LSS.
- Bureau report ≤30 days at disbursement; validity 14 days.
- NTC: loan >50k restricted; guarantor + owned-house mandatory.

### Product grid
| Amount | Tenure | ROI | EMI |
|---|---|---|---|
| 50,000 | 12 | 32% | 4,924 |
| 60,000 | 15 | 32% | 4,906 |
| 75,000 | 18 | 32% | 5,301 |
| 100,000 | 20 | 32% | 6,516 |
| 125,000 | 22 | 32% | 7,584 |
| 150,000 | 24 | 32% | 8,542 |

### Ratios & caps
- FOIR ≤ 50% (heuristic alert at 40%).
- IDIR ≤ 50%.
- Total indebtedness <₹5L including proposed loan.
- Credit card obligation: 5% of outstanding.
- Gold / KCC / Priority-sector: interest paid only as obligation.
- Stock-to-loan ratio: ≥1.0.

### Geographic
- 25 km radius from PFL branch.

### Documents (min kit)
- KYC: Aadhaar, PAN, Voter/DL
- Residence proof (matches Aadhaar/Voter)
- Bank statement (6 months)
- Business premises photos (≥3 different angles)
- Residence photos (≥3 with borrower/co-borrower)
- Equifax/CIBIL report
- PD Sheet
- Electricity bill (new: for 6-way address match)
- Checklist
- Auto CAM
- KYC video

### Negative business list (auto-reject, CEO notified)
Seasonal (tent house, catering, DJ); alcohol; tobacco; weapons; gambling; casinos; pornography; prostitution; forced/child labour; politicians; lawyers (except tax solicitor firms); journalists; police; money lenders; pawn shops; cybercafés; video libraries; MLM/network marketing; astrologers/purohits; security firms; DSAs/collection agencies; media companies; small money exchangers; film industry personnel; builders/real-estate developers; cable operators; manpower consultants; small STD/PCO outlets; chit funds.

---

## 17. Appendix B — Saksham's initial heuristics seed

1. House address must match across: Aadhaar, PAN, CIBIL, electricity bill, bank statement, GPS of house visit (6-way match; ≥4 of 6 required, mismatches logged).
2. Business visit GPS must be at justifiable distance (≤25 km) from house.
3. Either house or business premises must be owned.
4. Stock in business must match sales / income in bank statement.
5. Stock value must exceed loan amount.
6. Income proof must match business stock and income in bank statement.
7. No DPDs in CB report for past 24 months minimum.
8. CB score must be >700.
9. Borrower should have some unsecured loan exposure (to track behavior).
10. Consumer FOIR should not exceed 50%.
11. Borrower should have NACH clearances, no bounces in bank statement.
12. More than one earning family member increases confidence.
13. Income from multiple sources increases confidence.

---

## 18. Appendix C — Tech stack summary

| Layer | Tech |
|---|---|
| Frontend | Next.js 14 (TypeScript), React Server Components, Tailwind CSS, shadcn/ui |
| Backend API | FastAPI (Python 3.12) |
| Workers | Python 3.12 (Claude SDK, openpyxl, python-docx, pdfplumber, Pillow) |
| Database | PostgreSQL 16 (RDS) |
| Storage | S3 |
| Queue | SQS |
| Auth | Custom + bcrypt + TOTP (speakeasy-py) |
| Email | AWS SES + Jinja2 templates |
| LLM | Anthropic API (Haiku/Sonnet/Opus 4.7) + prompt caching |
| Embeddings | Voyage AI |
| IaC | AWS CDK (TypeScript) |
| CI/CD | GitHub Actions → ECR → ECS deploy |
| Monitoring | CloudWatch + Sentry |
| Dev env | Docker Compose (local Postgres + LocalStack S3/SQS) |

---

## 19. Appendix D — PFL Branding

- Logo: provided by user (PFL Finance, blue + grey with handshake + rupee bag motif).
- Primary color: PFL blue (to be extracted from logo image, approx. `#1E3A8A` / royal blue).
- Secondary color: PFL grey (approx. `#6B7280`).
- Typography: match pflfinance.com style.
- Web app header has PFL logo + "Credit AI" as product name.
- Generated Word/Excel outputs include PFL letterhead.

---

*End of spec. Next step: spec review loop → user review → writing-plans skill to produce the implementation plan.*
