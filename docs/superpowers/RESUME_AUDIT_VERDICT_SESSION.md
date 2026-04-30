# Resume — Audit + Verdict Engine Feedback Session

> **Open a new Claude Code session in this same repo and paste this file's
> path** (`docs/superpowers/RESUME_AUDIT_VERDICT_SESSION.md`) to spin up a
> sibling Claude that can work on the audit / verdict engine while the
> primary session is busy building the CAM discrepancy feature.

**Spawned:** 2026-04-22
**Parent HEAD commit:** `9cf4b3a` — `feat(m4): token + cost calculator on Phase 1 tab`
**Primary session is working on:** CAM discrepancy detection + resolution UI (see "File-ownership matrix" below for conflict-avoidance rules)

---

## Quick context (read first)

### Where the project stands today
| Milestone | Status | Tag |
|---|---|---|
| M1 Auth + Foundation | Shipped | `m1-backend-foundation` |
| M2 Case Upload | Shipped | `m2-case-upload-storage` |
| M3 Ingestion Workers | Shipped | `m3-ingestion-workers` |
| M4 Frontend | Shipped | `m4-frontend-1.2` |
| M5 Phase 1 Decisioning | **Shipped + live-verified** | `m5-decisioning-engine` |
| M6 Phase 2 Audit Engine | **Spec drafted, not built** | spec at `docs/superpowers/specs/2026-04-21-m6-audit-engine-design.md` |
| M7 Memory / Learning | Spec only | parent spec §7 |
| M8 AWS deploy | — | — |
| M9 Shadow rollout | — | — |

### What the two "engines" mean in this codebase
- **Phase 1 Decisioning Engine** = the 11-step pipeline already shipped in M5.
  Code lives in `backend/app/decisioning/`. Produces a `DecisionResult` row
  with `final_decision` ∈ {APPROVE, APPROVE_WITH_CONDITIONS, REJECT,
  ESCALATE_TO_CEO}. This is what the user calls "the verdict engine".
- **Phase 2 Audit Engine (M6)** = independent arm's-length verification that
  runs AFTER Phase 1. Layer A (30-point credit audit, full auto-fill), Layer
  B (150-point loan audit, partial fill), doc cross-verification, exec
  summary. Not yet built — only the spec exists. Emits its own verdict
  PASS / CONCERN / FAIL.
- **CAM Discrepancy Engine** (primary session's WIP) = a pre-decisioning
  gate that flags numeric conflicts between the auto-populated SystemCam
  sheet and the manually-filled CM CAM IL sheet in the Auto CAM xlsx.
  Blocks Phase 1 until the assessor resolves each CRITICAL flag. **Must
  fit alongside both engines without colliding.**

### Live verification status (as of parent HEAD)
- Phase 1 runs end-to-end against Anthropic API — cost was $0.27 on the
  Ajay test case, final verdict `REJECT` with confidence 92%, all 11
  steps `SUCCEEDED`, reasoning markdown intact.
- Per-step token + cost breakdown is visible on the UI (see
  `frontend/src/components/cases/DecisioningPanel.tsx::UsageSummary`).
- Extractors all `SUCCESS` on Ajay's real files:
  - auto_cam × 2 (full 4-sheet + single-sheet CAM_REPORT variant)
  - bank_statement (752 transactions parsed from SBI PDF)
  - equifax × 3 (Ajay hit=834, Gordhan + Pinki NTC score=-1 preserved)
  - pd_sheet (narrative docx, 65 paragraphs)
  - checklist

---

## What you are here to do in this session

The user has issues with the **audit engine + verdict engine** that they want
to discuss and implement in parallel to the CAM discrepancy work going on in
the other session.

### Expected flow
1. **User dumps a list of concerns / proposed changes** into this chat.
2. **You clarify ambiguities** one question at a time; don't jump to
   implementation before the user has approved a plan.
3. **Group the concerns** into: Phase 1 decisioning issues (M5 code) vs Phase
   2 audit issues (M6 design, not yet built) vs reporting / exec summary
   issues vs cross-cutting.
4. **For each actionable item**, decide the smallest viable fix. Default to
   surgical backend / frontend patches, not new subsystems, unless the
   user explicitly wants a new subsystem.
5. **Save useful domain knowledge to memory** (user, feedback, project) as
   you learn it, same as the primary session does. Example domain rules
   already captured: `memory/project_autocam_sheet_authority.md` — SystemCam
   is authoritative, CM CAM IL is manual.
6. **Commit often** with focused messages, standard Co-Authored-By footer.

### Expected output
A series of commits (or a plan + commits) that addresses the audit / verdict
issues the user raises. When you think you've hit a natural pause, update
`docs/superpowers/RESUME_HERE.md` and tell the user.

---

## File-ownership matrix (avoid conflicts with primary session)

The primary session is building the CAM discrepancy feature. To prevent
merge conflicts, **this session should avoid editing the files marked ❌**.

| Path | Owner | Notes |
|---|---|---|
| `backend/app/worker/extractors/autocam_discrepancies.py` | ❌ primary | New file, discrepancy detector |
| `backend/app/models/cam_discrepancy_resolution.py` | ❌ primary | New model |
| `backend/app/schemas/cam_discrepancy.py` | ❌ primary | New schema |
| `backend/alembic/versions/*cam_discrepancy*.py` | ❌ primary | New migration |
| `backend/app/api/routers/cases.py` | ⚠️ shared | Primary is APPENDING discrepancy endpoints + editing the Phase 1 trigger to gate. Other session: coordinate or avoid this file; if you must edit, commit small isolated chunks and mention "discrepancy gate" if you touch Phase 1 trigger. |
| `backend/app/decisioning/**` | ✅ OK to edit | M5 code — audit / verdict issues almost certainly land here |
| `backend/app/decisioning/steps/**` | ✅ OK | Per-step logic |
| `backend/app/decisioning/prompts/**` | ✅ OK | Jinja2 templates — tweaking these is the common fix for Phase 1 quality issues |
| `backend/app/decisioning/case_library.py` | ✅ OK | |
| `backend/app/decisioning/mrp.py` | ✅ OK | |
| `backend/app/services/claude.py` | ✅ OK | Model cascade logic |
| `backend/app/models/decision_result.py` / `decision_step.py` | ✅ OK | |
| `docs/superpowers/specs/2026-04-21-m6-audit-engine-design.md` | ✅ OK | M6 spec — edit freely if the user proposes audit-engine changes |
| `frontend/src/components/cases/DiscrepanciesPanel.tsx` | ❌ primary | New component |
| `frontend/src/components/cases/DecisioningPanel.tsx` | ⚠️ shared | Primary is adding a "Start Phase 1" disabled-tooltip gate. Other session: if you need to touch this file, commit a small diff and be explicit about which region you changed. |
| `frontend/src/app/(app)/cases/[id]/page.tsx` | ⚠️ shared | Primary is adding a "Discrepancies" tab between Extractions and Phase 1. |
| `frontend/src/lib/api.ts` / `types.ts` | ⚠️ shared | Append-only is safe; both sessions append |
| Everything else | ✅ OK | |

**Rule of thumb:** if you're editing decisioning prompts, step logic, cost
accounting, or M6 spec — you won't collide. If you're touching the case
detail page or cases router, pause and rebase before editing.

---

## How to resume

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git fetch --tags
git log --oneline -8
git status                 # should show primary session's WIP as untracked or ahead

# Bring up the stack (same as primary)
docker compose up -d postgres localstack backend worker pfl-decisioning-worker
cd frontend && npm run dev    # http://localhost:3000

# Log in: saksham@pflfinance.com / Saksham123!
# DEV_BYPASS_MFA=true is set in backend/.env (gitignored).
```

Test data is case `7bdea924-225e-4b70-9c46-2d2387fc884c` (loan_id 10006079,
Ajay Singh). Phase 1 has already been run — result visible on the Phase 1
tab.

---

## Reference reading for this session

1. `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md` §5
   (Phase 1 Decisioning — the "Saksham algorithm") and §6 (Phase 2 Audit).
2. `docs/superpowers/specs/2026-04-18-m5-decisioning-engine-design.md` —
   canonical spec for the decisioning engine currently in prod.
3. `docs/superpowers/specs/2026-04-21-m6-audit-engine-design.md` — draft
   spec for the audit engine. Subagent-generated 2026-04-21, not yet
   human-reviewed. If the user wants audit-engine changes, edit this spec
   first, then the implementation.
4. `docs/superpowers/RESUME_HERE.md` — the primary session's resume file.
   Skim the §A1–§A40 deviations for all the non-obvious gotchas that have
   accumulated.

---

## Handoff protocol

When this session reaches a natural break:
1. Commit all WIP with focused messages.
2. Append a "Done in audit-session" section at the bottom of this file
   listing SHAs + one-liner what was shipped.
3. If you made decisions that affect the primary session's CAM-discrepancy
   work (e.g. you changed the Phase 1 trigger endpoint signature), leave
   a note under "Coordination with primary session" below.
4. Update `docs/superpowers/RESUME_HERE.md` with a "2026-04-22 audit-session
   shipped" entry so the next main-line session picks it up.

---

## Coordination with primary session

_(Add entries here if your changes affect files the primary session is
editing. Primary session will do the same.)_

- `TBD`

## Done in audit-session

**Branch: `4level-l1`** (not yet merged to main). **Phases A → E of the plan
all shipped**, all four verification levels live, Step 11 consumes them at
highest weight. Verified live on Ajay's case.

| SHA | Phase | Summary |
|---|---|---|
| `4895972` | A | feat(4level): foundation — enums, models, migration for L1 address gate |
| `8fc84e2` | A | feat(4level): Claude-vision scanners for L1 — Aadhaar, PAN, ration/bill (18 tests) |
| `8bc2628` | A | feat(4level): L1 services — address normalizer, EXIF GPS, Google Maps geocode (26 tests) |
| `d08d53b` | A | feat(4level): Level 1 address engine — 7 sub-steps + cross-check rules (14 tests) |
| `26c84e5` | A | feat(4level): HTTP endpoints for trigger/overview/detail/resolve/decide |
| `c5ab51f` | A | chore(dev): mount backend app/alembic/tests as volumes into all backend containers |
| `aa1cce9` | A | feat(4level): Verification tab in case detail — L1 trigger, resolve, MD decide |
| `942e08b` | A | docs(4level): record Phase A shipped — 7 SHAs + live-verified Ajay run |
| (after)   | D | feat(4level): Phase D — Level 4 loan-agreement asset audit (12 tests) |
| (after)   | E | feat(4level): Phase E — Step 11 consumes 4-level outputs at highest weight (4 new tests; pre-existing 14 still pass) |
| (after)   | B | feat(4level): Phase B — Level 2 Banking (CA-grade Claude analysis + 7 rules, 25 tests) |
| (after)   | C | feat(4level): Phase C — Level 3 Vision (house + business premises scoring, 19 tests) |

**Live verification on Ajay (`7bdea924-225e-4b70-9c46-2d2387fc884c`):**
All four levels run + Phase 1 re-ran with the 4-level outputs feeding Step 11.

| Level | Duration | Cost | Status | Real findings |
|---|---|---|---|---|
| L1 Address | 19.9 s | $0.0111 | BLOCKED → MD override → PASSED_WITH_MD_OVERRIDE | Ration card in HARJEET KAUR's name (unrelated), missing GPS EXIF |
| L2 Banking | 9.2 s | $0.0161 | BLOCKED | Avg balance ₹487 (chronic), 10 CA concerns — fragmented 87-payer network, no salary credits, informal lending pattern |
| L3 Vision | 30.8 s | $0.0442 | BLOCKED | House rated "bad" — cemented floor, bare plaster, no high-value assets, kitchen cluttered |
| L4 Agreement | 11.2 s | $0.0598 | BLOCKED | Annexure present on page 18 but empty — zero assets enumerated |
| **Phase 1** | 160 s | $0.2911 | **ESCALATE_TO_CEO (conf 45)** | Opus autonomously applied the 4-level override |

**Phase 1 Opus reasoning (verbatim from `reasoning_markdown`):**
> Decision: ESCALATE_TO_CEO
>
> 4-Level Gate Assessment (Highest Weight):
> - L1 PASSED_WITH_MD_OVERRIDE — Mild uncertainty penalty (-5)
> - L2 BLOCKED — Hard cap on confidence; forces escalation
> - L3 BLOCKED — Hard cap on confidence; forces escalation
> - L4 BLOCKED — Hard cap on confidence; forces escalation
>
> Per decision rules, any BLOCKED/FAILED/PENDING gate caps confidence at 70
> and mandates ESCALATE_TO_CEO. Two gates are BLOCKED, which is non-negotiable.

The post-processing override also appended `"unresolved 4-level gates: ['L2_BANKING', 'L3_VISION', 'L4_AGREEMENT']"` to `risk_summary`, and a `verification_summary` snapshot is persisted on `decision_steps.output_data[11]` for audit.

**Total per-case cost end-to-end:**
L1 $0.011 + L2 $0.016 + L3 $0.044 + L4 $0.060 + Phase 1 (Opus) $0.291 = **$0.422**. Well under a typical ₹40-80 CBC ceiling.

**Test totals (this branch):** ~140 new backend unit tests across four
levels, three scanners, three services, and the Step 11 integration — all
pass. The pre-existing 7 MFA-related failures (due to `DEV_BYPASS_MFA=true`)
remain and are unrelated.

**Known follow-ups (not blockers for main):**
- L1 + L3 + L4 trigger endpoints still run synchronously (blocks 20-30 s).
  Move them to SQS workers once the verdict loop is validated on 10+ cases.
- L2's "challenge the credit person" Q&A + MD-approval learning engine
  (precedents table, cross-case retrieval) is deferred. The CA narrative
  concerns surface today as a WARNING issue so the assessor still sees them.
- L3 first-100-case calibration where MD tunes bifurcation is deferred;
  Sonnet's fixed-scale rating is the stand-in.
- L4 CAM-vs-agreement asset diff is deferred until the `auto_cam` extractor
  surfaces a structured asset list (today it returns only 4 top-level keys).
- Cases Gaurav (10006570) / Bane (10006439) / Amit (10006148) are available
  but not yet re-uploaded through the wizard since localstack S3 lost state
  between sessions. The engine has proven itself on Ajay's real artifacts.

## Coordination with primary session

- **Shared file edits (commit `aa1cce9`):** added a `Verification` tab to
  `frontend/src/app/(app)/cases/[id]/page.tsx` between `Dedupe` and `Phase 1`
  tabs. Primary's `Discrepancies` tab is NOT disturbed. If primary lands
  their CAM-discrepancy work after this branch merges, the expected tab order
  will be: Overview | Artifacts | Extractions | Checklist | Dedupe |
  **Discrepancies** (primary) | **Verification** (this branch, L1-only) |
  Phase 1 | Audit Log.
- **Shared file edits (commit `aa1cce9`):** appended to
  `frontend/src/lib/api.ts` (`cases.verification*` methods) and
  `frontend/src/lib/types.ts` (Verification zod schemas). Both are
  append-only so primary can add their CAM-discrepancy types safely on top.
- **Shared file edits (commit `26c84e5`):** mounted a new FastAPI router
  (`app.api.routers.verification`) in `backend/app/main.py`. Primary's
  changes to `backend/app/api/routers/cases.py` are NOT touched.
- **Dev volume mount (commit `c5ab51f`):** `docker-compose.yml` now mounts
  `./backend/{app,alembic,tests}` into all three backend containers so code
  edits are live without rebuild. Primary session should benefit from this
  too.

**No conflicts expected with primary's CAM-discrepancy work** since forbidden
paths from `docs/superpowers/RESUME_AUDIT_VERDICT_SESSION.md` §"File-ownership
matrix" were respected (autocam_discrepancies.py, cam_discrepancy_resolution.py,
cam_discrepancy schema, cam_discrepancy migration, DiscrepanciesPanel.tsx
were all untouched).
