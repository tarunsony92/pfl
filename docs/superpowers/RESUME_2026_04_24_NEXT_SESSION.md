# Resume notes — 2026-04-24 session handoff

Start here in a fresh session. This doc is self-contained — you don't
need the previous chat to pick up where we left off.

## 1. Where we are

- **Branch:** `4level-l1`
- **Remote:** `https://github.com/saksham7g1/pfl-credit-system`
- **Open PR:** [#1](https://github.com/saksham7g1/pfl-credit-system/pull/1) at **61 commits** (pushed)
- **Last commit:** `0d58ecd` · feat(pipeline-summary): show actual issue count instead of 'HAS ISSUES'
- **Working tree:** clean.

This session's 10 commits (on top of the prior `5b287c7` handoff):

```bash
git log --oneline 5b287c7..HEAD
```

## 2. Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -10

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 6

# Migration already applied, but confirm head is up to date
docker exec pfl-backend alembic current       # → b9c0d1e2f3a4 (head)

# Frontend dev server — reuse if already running
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Login: saksham@pflfinance.com / Saksham123!
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Sanity: new /admin/rules/stats endpoint
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/admin/rules/stats \
  | python3 -c "import json,sys;print('rules:',len(json.load(sys.stdin)))"
# → 35+
```

**Reference case:** Ajay singh · loan `10006079` · id
`7bdea924-225e-4b70-9c46-2d2387fc884c`. Amit and Gaurav test cases
were soft-deleted. Ajay is the only active case.

## 3. What landed this session (10 commits)

Grouped by feature.

| Area | Commits | Summary |
|---|---|---|
| **Source-file viewer** | `17ddee9` · `4b4f866` · `8cf7203` | FE `IssueSourceFilesButton` + modal · BE `source_artifacts` schema populated on every L1/L1.5/L2/L3/L4/L5 issue emitter so the "View source" button opens the exact Aadhaar / ration bill / house-visit photo / bureau HTML / LAGR PDF that backs the check |
| **Level-card restructure** | `0a9f78a` | Replaces the old 2-column (Evidence Gathered / Logic Checks) layout with: BLOCKED BY banner → full-width CONCERNS strip → collapsed PASSING RULES pill → collapsed EXTRACTION DETAILS pill. Issue row expand keeps WHY \| WHAT WAS CHECKED side-by-side |
| **Plain-English descriptions** | `816a973` | Every issue description inlines the actual values being compared (Aadhaar says X · GPS says Y · bureau says Z). `opus_credit_verdict` rewritten with structured per-party evidence keys + multi-line English description; hides legacy `analyst` / `party` / `row` JSON blobs from generic fallback |
| **L6 Final Decision card** | `7078411` · `de1a292` | Hero banner (verdict pill · amount · tenure · coloured confidence bar). `splitRiskSummary` breaks LLM-joined prose into one amber bullet per concern; Python-list literal `['L1_ADDRESS', …]` softened to "L1_ADDRESS, L2_BANKING, …". API Usage & Cost + Pipeline Steps collapsed into pill-style headers |
| **Learning Rules** | `f020acd` | New admin-only `/admin/learning-rules` surface. BE: `RuleOverride` model + migration `b9c0d1e2f3a4` + `/admin/rules/*` endpoints + `filter_suppressed_issues` helper wired into every L-level orchestrator. FE: BrainIcon sidebar link (admin-only) below Dedupe Snapshots; filter chips (All / Has fired / MD signal / Suppressed); per-rule card with fire count + MD precedent breakdown + suppress toggle + admin-note editor + last 5 MD rationales |
| **Summary-table status** | `0d58ecd` | 7-Level Credit Pipeline table now reads `N ISSUES` off `sub_step_results.issue_count` instead of the generic `HAS ISSUES` pill |

## 4. Features shipped end-to-end this session

### 4.1 Source-file viewer
Every concern's `IssueEvidencePanel` header has a **View source (N)**
button. Opens a modal rendering each source artefact inline:
- Images as thumbnails (click → open full-size new tab).
- PDFs embedded via iframe + download link.
- HTML sandboxed iframe.
- Other types fall through to a labelled download row.

BE contract (`LevelIssue.evidence.source_artifacts[]`, JSONB):
```python
{
  "artifact_id": "<uuid>",           # FK to case_artifacts.id
  "filename":    "<original>",
  "relevance":   "Applicant Aadhaar — address field",
  "highlight_field": "address",       # optional, hints at field
  "page":        1,                   # optional, PDF page 1-indexed
  "bbox":        [x, y, w, h],        # optional, 0..1 normalised
}
```

Per-emitter coverage:

| sub_step_id | Cited artefacts |
|---|---|
| gps_vs_aadhaar | Aadhaar + exact GPS-source house photo (tracked via `gps_house_artifact`) |
| ration_owner_rule | Ration/bill + both Aadhaars + LAGR |
| business_visit_gps | Up to 5 BUSINESS_PREMISES_PHOTOs |
| house_business_commute | Exact house-GPS photo + biz-GPS photo pair |
| aadhaar_vs_bureau_address | Aadhaar + bureau HTML |
| aadhaar_vs_bank_address | Aadhaar + bank statement |
| L1.5 applicant/coapp hard rules | Applicant / co-app bureau HTML |
| L1.5 opus_credit_verdict | Both bureau HTMLs |
| L2 bank rules | Bank statement with per-rule `highlight_field` hint |
| L3 house_living_condition | Up to 8 HOUSE_VISIT_PHOTOs |
| L3 stock/cattle/infra/loan-reduction | Up to 8 BUSINESS_PREMISES_PHOTOs |
| L4 asset_annexure_empty / hypothecation_clause | LAGR with section hint |
| L5 scoring_* / section / grade | AutoCAM + PD sheet + bureau + bank |

**Phase 2 (not built):** per-field bounding-box coords. Requires a
new extraction pass that records them. `bbox` is already in the
contract for forward-compat.

### 4.2 Learning Rules (admin surface)

Live at `/admin/learning-rules` (admin-only). For every deterministic
rule the engine runs, shows:

- sub_step_id + catalogue title + description + level (L1..L5 or "Runtime")
- fire count (total LevelIssue rows emitted)
- open / MD-approved / MD-rejected counts
- is_suppressed flag with toggle
- admin-note editor (free-form, 2000 char max)
- last 5 MD rationales (tinted green/red by decision) — the
  "learning signal" the AI builds intuition from

Suppression semantics: when admin flips `is_suppressed = true`, the
matching issue is dropped from the persisted list **before** being
written as a LevelIssue row — the gate behaves as if the rule never
fired. Already-open issues from earlier runs are unaffected; re-run
the relevant level to clear them. Each VerificationResult's
`sub_step_results.suppressed_rules` captures which rules were
skipped on that run for audit.

BE endpoints (all admin-only):
- `GET /admin/rules/stats` — aggregated per-rule view
- `GET /admin/rules/overrides` — raw override list
- `PUT /admin/rules/overrides/{sub_step_id}` — upsert
- `DELETE /admin/rules/overrides/{sub_step_id}` — clear

`RULE_CATALOG`, `LEVEL_META`, `LEVELS`, `RuleCatalogEntry` now
exported from `VerificationPanel.tsx` so the admin page reuses them
(no duplication).

## 5. Next-session backlog

Nothing is in flight. These remain deferred from prior sessions or
emerged in this one:

| Ask | Status | Notes |
|---|---|---|
| Phase 2 source-viewer: **bounding-box highlighting** | Not built | Requires per-field coord extraction. Contract already has `bbox` field; populate it from a new extractor pass. |
| Learning Rules: **retrain-via-feedback loop** | Not built | Today the AI doesn't actually learn from MD decisions — the Learning Rules page only *surfaces* the decisions. Next step: feed MD rationales into Opus prompt context on same-rule future cases (not just the generic `case_library_retrieval`). |
| Learning Rules: **edit rule thresholds** | Not built | Currently admin can suppress or leave a note but can't edit numeric thresholds (e.g., `avg_balance_vs_emi` multiplier 1.5×). Add a `parameters JSON` column on `rule_overrides` + honour in each cross_check_*. |
| **Hosting / production-readiness audit** | Deferred | CORS, JWT secret rotation, TLS, per-user case isolation, rate limiting, default-password rotation. Pre-merge checklist sketched in earlier chat. |
| **Migrate GCP API key** from `supreme-ops-491112` → dedicated `pfl-*` project | Deferred | Code is project-agnostic — env-var swap + enable Routes + Geocoding on the new project. |
| **Kotak (KKBK) bank-statement parser** | Spawned off previously | L2 extractor returns PARTIAL with zero transactions on Kotak statements; the CRITICAL `bank_statement_missing` was misleading until this session's source_artifacts now cite the uploaded-but-broken PDF so the MD can eyeball it. |
| **Notifications bell** filter out deleted cases | Not audited | `app/services/notifications.py` may still include deleted cases. |

## 6. Known limitations / gotchas

- **Sidebar counts (MD Approvals, Assessor Queue)** still rely on SWR
  revalidation — a manual refresh is the fastest way to see a count
  drop after resolving an issue.
- **Preview-server interactive clicks** on Radix Tab components
  sometimes don't propagate via `preview_click`. Use `preview_eval`
  to dispatch `mousedown` + `click` on the button directly.
- **Alembic revision-id collision** bit us this session:
  `a8b9c0d1e2f3` was already taken by the deletion-request migration.
  My follow-up `rule_overrides` migration was renamed to
  `b9c0d1e2f3a4`. Keep an eye when scaffolding new ones.
- **Content-type on stored artifacts is often null** — the source-file
  viewer falls back to filename extension (`/\.pdf$/i`,
  `/\.(jpe?g|png|webp|...)$/i`) for render-type detection.
- **Signed URL expiry = 15 min**. Opening a tab for ≥15 min then
  reloading the modal will fail until the case refetches; this was
  deemed acceptable and is surfaced in-modal ("signed link expired").

## 7. If you start a new session, do this first

```bash
# 1. Confirm where the branch is
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -10

# 2. Read THIS file
cat docs/superpowers/RESUME_2026_04_24_NEXT_SESSION.md

# 3. Sanity-run the tests (expected: ~593+ passed)
cd backend && poetry run pytest tests/unit tests/integration/test_cases_service.py \
  --no-cov -q

# 4. Pick an item from §5 — highest value next: bounding-box
#    highlighting or Learning-Rules retrain loop.
```

## 8. Design artefacts + long-form specs

- L1 commute check design:
  `docs/superpowers/specs/2026-04-22-l1-house-business-commute-design.md`
- Today's handoff: this file
- Yesterday's handoff:
  `docs/superpowers/RESUME_2026_04_23_NEXT_SESSION.md`
- Earlier handoffs:
  `docs/superpowers/RESUME_2026_04_22_PIPELINE_ONEPAGER.md`,
  `docs/superpowers/README_CONTINUE.md`,
  `docs/superpowers/RESUME_2026_04_22_L5_SCORING.md`

## 9. One-paragraph TL;DR

Session shipped: a working **"View source" modal** on every issue
(backed by a `source_artifacts[]` contract populated across every L1
through L5 emitter), a full **level-card restructure** (concerns
strip / passing-rules pill / extraction-details pill), **plain-English
mismatch details** inlined in every issue description (`Aadhaar says
X, GPS says Y` instead of abstract "doesn't match"), a **rebuilt L6
Final Decision card** with a coloured confidence bar and per-concern
risk bullets, and a brand-new **Learning Rules admin surface** that
lists every deterministic rule the AI runs, shows the MD precedent
signal, and lets an admin suppress rules with an audit note (engine
honours suppression across every level). **Next session: pick
bounding-box source-highlighting, or wire MD rationales into the
Opus prompt as genuine learning signal.**
