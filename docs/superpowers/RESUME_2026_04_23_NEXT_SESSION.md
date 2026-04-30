# Resume notes — 2026-04-23 session handoff

Start here in a fresh session. This doc is self-contained — you don't need
the previous chat to pick up where we left off.

## 1. Where we are

- **Branch:** `4level-l1`
- **Remote:** `https://github.com/saksham7g1/pfl-credit-system`
- **Open PR:** [#1](https://github.com/saksham7g1/pfl-credit-system/pull/1) at **51 commits**
- **Last commit:** `c7aeed6` · feat(level-card): evidence counts on header · evidence panel side-by-side
- **Working tree:** clean at session end except for the *frontend half* of the source-file viewer (§4 below) which is mid-flight and not committed.

The whole session's work is squashed in PR #1. To see just this session's commits:

```bash
git log --oneline main..HEAD
```

## 2. Boot in ~60 seconds

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status                                 # confirm clean / see in-flight changes
git log --oneline -5

# Services
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
docker restart pfl-backend && sleep 5
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Login: saksham@pflfinance.com / Saksham123!
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Sanity check: Ajay's open-issue count (should be ~70)
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print('open:',d.get('open_issue_count'),'stage:',d.get('current_stage'))"
```

**Reference case:** Ajay singh · loan `10006079` · id `7bdea924-225e-4b70-9c46-2d2387fc884c`. Amit and Gaurav test cases were deleted today; Ajay is the only active case.

**GCP Routes API** is enabled on project `supreme-ops-491112` under the
current `GOOGLE_MAPS_API_KEY`. House→business commute check returns real
driving verdicts now (Ajay's is 1.45 min · 291 m → PASS).

## 3. What landed this session (51 commits → 16 new on PR #1)

Grouped by feature. Every commit is pushed.

| Area | Commits | Summary |
|---|---|---|
| L1 commute feature | `9d21202` · `b87b860` · `092553c` · `ddd1bea` | Design spec · main impl · cache-bug fix · code-review fixes |
| Routes API migration | `8d722ba` | Legacy Distance Matrix → `routes.googleapis.com/directions/v2:computeRoutes` |
| L1 commute UI rows | `49a232c` | 3 new `Param` rows in VerificationPanel |
| Case.occupation | `ef43784` | Migration + wizard form field + L1 judge input plumbed |
| area_class google fallback | `bd675ad` | Keyword match on formatted address when Nominatim isn't the geocoder |
| §2 commit boundaries from handoff | `5dec842` · `c507fa1` · `7444904` · `f3357f6` · `5861de1` · `cb87f40` · `d035b07` | L5 drag-context, decisioning unwrap, MD approvals rewrite, assessor queue, L6 merge, autorun orchestrator, docs/gitignore |
| Autorun timing + smart rerun + L6 belt | `96408f4` · `(part of)` | `waitForCaseReady` · `identifyStepsNeedingRerun` · belt-and-braces L6 fire |
| Issue evidence drill-down | `a47b00f` | `IssueEvidencePanel` component — side-by-side addresses, owner-vs-parties grid, GPS match score, key/value fallback |
| UI cleanups | `90d007a` | Compact Evidence Gathered · structured L6 `ReasoningSection` |
| Ration-scanner test fix | `76c2060` | schema_version drift from `"1.0"` → `"1.1"` (was breaking the backend suite) |
| Deletion-approval flow | `af72b71` · `00e2a74` | Migration + endpoints + `DeletionRequestButton` (case detail) + `DeletionRowAction` (cases list row) |
| Deleted cases off MD queue + stage badge red | `b539cbd` | Queue filter · `open_issue_count` on `CaseRead` · `StageBadge` red override |
| Level-card header + side-by-side evidence | `c7aeed6` | Header subtitle `N checks · P pass · K concerns` · IssueRow expands with 2-col WHY/WHAT on xl |

## 4. What we were building when context ran out — source-file viewer

**The ask:** every issue should have a **"View source"** button that opens the actual file / image / PDF snapshot the data was extracted from, so the MD can see exactly where the mismatch lives.

**Status:** design understood, frontend stub started but not committed, backend design note written below.

### 4.1 Frontend — what to build

Location: add to `frontend/src/components/cases/VerificationPanel.tsx` inside the existing `IssueEvidencePanel` component.

Component sketch:

```tsx
function IssueSourceFilesButton({
  issue,
  caseId,
}: { issue: LevelIssueRead; caseId: string }) {
  // 1) Collect artifact refs from issue.evidence.source_artifacts[] if set,
  //    otherwise fall back to the single issue.artifact_id.
  // 2) On click → open a modal that fetches /cases/:id (has signed download
  //    URLs on each artifact) and renders each referenced artifact inline:
  //      - image/jpeg|png|webp → <img> thumbnail, click to open full-size
  //      - application/pdf     → PDF download link + embed if < 5MB
  //      - anything else       → download link with filename + size
  //    Each artifact row shows its "relevance" string ("Applicant
  //    Aadhaar — address field", "Ration bill — owner name line", …).
  // 3) Disable the button / hide it if no source artifacts are available
  //    on this issue (silent degradation).
}
```

The modal should use the existing `Dialog` primitive (see `DeletionRequestButton` for the pattern).

Reading the artifact URLs: `api.cases.get(caseId)` already returns `artifacts[]` with `download_url` signed for 15 min. Memoise the call with SWR (`useCase(caseId)` hook likely exists — check `frontend/src/lib/useCases.ts`).

### 4.2 Backend — design note for the team

The `LevelIssue.evidence` JSON column already exists and each issue emitter populates whatever it wants in there. Today the shape is per-issue-type and ad-hoc. We need a **standard key** for source artefacts so the frontend has a contract.

**Proposed standard key** on every `LevelIssue.evidence`:

```python
{
  # …existing keys…
  "source_artifacts": [
    {
      "artifact_id": "7bdea924-225e-4b70-9c46-2d2387fc884c",  # FK to case_artifacts.id
      "relevance": "Applicant Aadhaar — address field",         # human-readable label
      "page": 1,               # PDF page, 1-indexed; omit for images
      "highlight_field": "address",   # logical field name (optional)
      "bbox": [x, y, w, h]     # page-normalised 0..1, optional, for future highlights
    },
    # ...one entry per contributing artefact
  ]
}
```

**Migration path — none required.** `LevelIssue.evidence` is already
`JSONB` and nullable. Existing issues without `source_artifacts` render
the "View source" button as disabled / hidden.

**Where to populate (per issue emitter):**

| sub_step_id | Source artefacts to include |
|---|---|
| `applicant_coapp_address_match` | Both KYC_AADHAAR artefacts (applicant + co-applicant) |
| `gps_vs_aadhaar` | HOUSE_VISIT_PHOTO (the one that yielded the GPS) + applicant KYC_AADHAAR |
| `ration_owner_rule` | RATION_CARD *or* ELECTRICITY_BILL + applicant KYC_AADHAAR + (if mentioned) co-applicant KYC_AADHAAR + LAGR PDF |
| `aadhaar_vs_bureau_address` · `aadhaar_vs_bank_address` | applicant KYC_AADHAAR + EQUIFAX_HTML / BANK_STATEMENT |
| `business_visit_gps` | the BUSINESS_PREMISES_PHOTO(s) tried (all of them if none yielded coords) |
| `house_business_commute` | HOUSE_VISIT_PHOTO (house-gps source) + BUSINESS_PREMISES_PHOTO (biz-gps source) |
| `bureau_report_missing` | — (nothing uploaded) |
| `bank_statement_missing` | BANK_STATEMENT artefact if PARTIAL-with-zero-tx; else empty |
| `loan_agreement_missing` | LAGR PDF if uploaded but blank annexure; else empty |
| `opus_credit_verdict` | both EQUIFAX_HTML artefacts (applicant + co-app) |
| L3 scoring issues (house/business scorer) | All HOUSE_VISIT_PHOTO or BUSINESS_PREMISES_PHOTO artefacts respectively |
| L5 rubric / grade issues | The artefacts that backed the underscoring rubric rows (AUTO_CAM, BANK_STATEMENT, EQUIFAX_HTML, PD_SHEET — whichever fed the failing row) |

**Implementation pattern (helper in `level_1_address.py`):**

```python
def _source_artifacts(
    artifacts: list[CaseArtifact],
    *,
    subtypes: tuple[str, ...],
    relevance: str,
) -> list[dict[str, Any]]:
    """Collect matching artefacts by subtype and stamp a relevance label."""
    out: list[dict[str, Any]] = []
    for a in artifacts:
        if (a.metadata_json or {}).get("subtype") in subtypes:
            out.append({
                "artifact_id": str(a.id),
                "filename": a.filename,
                "relevance": relevance,
            })
    return out

# In each cross_check_* / orchestrator code path, build source_artifacts
# and merge into evidence:
evidence = {
    "applicant_address": applicant_addr,
    "co_applicant_address": coapp_addr,
    "source_artifacts": (
        _source_artifacts(artifacts, subtypes=("KYC_AADHAAR",), relevance="Applicant Aadhaar")
        + _source_artifacts(artifacts, subtypes=("CO_APPLICANT_AADHAAR",), relevance="Co-applicant Aadhaar")
    ),
}
```

Cross-check helpers are currently pure — they receive addresses/names
already extracted and don't see the raw artefact list. The orchestrator
(`run_level_1_address`) has the `artifacts` list and does the emitting.
**Refactor option:** change cross-check signatures to take the artefacts
list (or a pre-built source-artefact list) and plumb through; alternative:
keep cross-checks pure and have the orchestrator merge `source_artifacts`
into the returned dict before persisting (less invasive, preferred).

**Existing single-artifact field.** `LevelIssue.artifact_id` is already a
nullable FK — it covers the single-source case today. `source_artifacts`
is a *superset* that handles the cross-compare issues (which naturally
span 2-3 artefacts). Keep `artifact_id` for backwards compat; frontend
reads `source_artifacts` first and falls back to `artifact_id`.

**Testing hook.** When you add `source_artifacts` to an issue, the
existing integration tests in `tests/integration/test_level_1_address.py`
should gain an assertion on the expected shape. Keep them tight — one
sub-step per test.

### 4.3 Order to build

1. **Backend first** — add `source_artifacts` to two or three highest-value issue emitters (`ration_owner_rule`, `gps_vs_aadhaar`, `business_visit_gps`). Re-run L1 on Ajay, confirm the field appears in `issue.evidence`.
2. **Frontend button** — `IssueSourceFilesButton` wired to read those fields. Show inline images, link for PDFs.
3. **Expand backend coverage** — add `source_artifacts` to the remaining issue types per the table above.
4. **Phase 2 (not on critical path):** bounding-box highlighting. Requires an extraction pass that records per-field coords. Worth a separate design spec.

## 5. Backlog / stacked asks still open

These came in rapid fire across today's session and aren't fully done:

| Ask | Status | Notes |
|---|---|---|
| **Source-file viewer** on every error | In flight (see §4) | Biggest outstanding ask — build this first next session |
| **Bigger level-card restructure** (issue strip above · full-width logic checks · collapsed passing rules · collapsed extraction details) | Designed but not built | Full ASCII layout was shown to user; I delivered only the header-subtitle + issue side-by-side parts. Wait for explicit "go" before building the remainder. Details in commit message of `c7aeed6` and the chat. |
| **Hosting / production-readiness audit** | Deferred by user | CORS, JWT secret rotation, TLS, per-user case isolation, rate limiting, default-password rotation. See the pre-merge audit I sketched in-chat. |
| **Migrate GCP API key** from `supreme-ops-491112` → a dedicated `pfl-*` GCP project | Deferred by user | Code is project-agnostic; just an env-var swap + enable Routes + Geocoding on the new project. |
| **Kotak (KKBK) bank-statement parser** | Spawned to a separate session via `spawn_task` | Currently the L2 extractor returns PARTIAL with zero transactions on Kotak statements; the CRITICAL `bank_statement_missing` is misleading. Follow-up agent has the full brief. |
| **Case.occupation on Case form** | Shipped | Optional input in Step 1 wizard, persisted on Case, fed to L1 commute judge. |
| **Notifications bell `/notifications` endpoint** filter out deleted cases | Not audited | Only md-queue + assessor-queue were filtered in `b539cbd`. The bell endpoint (`/notifications`) likely needs the same filter — check `app/services/notifications.py`. |

## 6. Known limitations / gotchas

- **Sidebar counts (MD Approvals 124 · Assessor Queue 124)** are fetched by `useSidebarCounts` or similar — may not invalidate on case deletion until SWR refetches. Not a bug per se; a hard refresh fixes it.
- **Preview server login loop** — the `mcp__Claude_Preview__preview_click('button[type=submit]')` flow sometimes lands back on `/login`. Retrying twice usually works. Browser-based interactive verification during the session was unreliable — TS typecheck + curl smoke tests were the reliable gates.
- **Ration-scanner test** was fixed in `76c2060` but watch for future schema bumps that drop through. The pattern is: test pins `schema_version = "X.Y"` verbatim; production bumps X.Y with a real schema change → test fails. Keep them in sync.
- **AutoRunProvider `runAll`** was in flight for 3 separate edits today (`waitForCaseReady`, `force` option, `onlyKeys` filter, belt-and-braces L6). Any further changes: re-read the current file before editing — the structure has shifted.

## 7. If you start a new session, do this first

```bash
# 1. Confirm where the branch is
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status
git log --oneline -5

# 2. Read THIS file
cat docs/superpowers/RESUME_2026_04_23_NEXT_SESSION.md

# 3. Pick up the source-file viewer work — start with §4.3 step 1.

# 4. Before editing, run the test suite to confirm green baseline:
cd backend && poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q
# Expect: ~593+ passed.
```

## 8. Design artefacts + long-form specs

- Design spec for the L1 commute check: `docs/superpowers/specs/2026-04-22-l1-house-business-commute-design.md`
- Today's forward-looking resume: this file
- Prior-session handoffs kept as-is: `docs/superpowers/RESUME_2026_04_22_PIPELINE_ONEPAGER.md`, `docs/superpowers/README_CONTINUE.md`, `docs/superpowers/RESUME_2026_04_22_L5_SCORING.md`

## 9. One-paragraph TL;DR

Session shipped: L1 house↔business commute check end-to-end (Routes API + Opus judge + UI rows + Case.occupation form + area_class fallback); two-step MD-approved delete flow (backend + per-row + case-detail buttons + MD approve/reject modals + audit log); MD/assessor queue filters out deleted cases; stage badge flips red with concern count when issues are unresolved; level-card header gained `N checks · P pass · K concerns · $cost`; issue expand is now description||evidence side-by-side on wide viewports; compact Evidence Gathered + structured L6 rationale (raw markdown behind toggle); ration-scanner test schema drift fixed. **Next session starts at §4 — build source-file viewer (backend helper + frontend button + modal).**
