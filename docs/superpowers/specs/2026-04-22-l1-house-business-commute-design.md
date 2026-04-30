# Level 1 — House ↔ Business Commute Check — Design Spec

**Project:** PFL Finance Credit AI Platform
**Feature:** L1 sub-step 3b — house-to-business travel-time flag
**Version:** 1.0
**Spec date:** 2026-04-22
**Author:** Saksham Gupta (with Claude)
**Status:** Draft — pending spec review
**Parent levels doc:** `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md` §3.1 (Level 1 Address)
**Branch:** `4level-l1`

---

## 1. Executive Summary

We add one small check to Level 1 Address verification: the travel time by car between the applicant's house (derived from house-visit photo GPS) and business premises (derived from business-visit photo GPS) must be ≤ 30 minutes. Above that threshold, a Claude Opus judge evaluates the applicant's profile and decides whether the commute is reviewable (WARNING — assessor can justify) or absurd (CRITICAL — MD approval only). Missing business-photo GPS is itself CRITICAL.

The feature reuses Level 1's existing GPS pipeline (EXIF → Haiku watermark OCR → reverse-geocode) against `BUSINESS_PREMISES_PHOTO` artifacts (a subtype that already exists and is used by Level 3 Vision). A new `distance_matrix_driving` helper in the Google Maps wrapper and a new `commute_judge` service are the only new units.

Cost envelope per case: $0.005–$0.009 on first L1 run; **$0 on re-run** when house and business coordinates are unchanged, because we reuse the prior `VerificationResult.sub_step_results`. Upper bound on the Opus judge call is ~$0.045 (cold cache) and it fires only when `travel_minutes > 30`.

---

## 2. Scope

### 2.1 In scope

- Business-photo GPS extraction (EXIF + watermark OCR fallback) inside `run_level_1_address`.
- New helper `distance_matrix_driving` in `backend/app/verification/services/google_maps.py`.
- New service module `backend/app/verification/services/commute_judge.py` (Opus, profile-aware judge).
- Two new pure cross-checks in `level_1_address.py`: `cross_check_business_gps_present`, `cross_check_commute`.
- Additive keys on `VerificationResult.sub_step_results` (nothing removed or renamed).
- Two new `LevelIssue.sub_step_id` values: `business_visit_gps`, `house_business_commute`.
- Three additional `Param` rows in the L1 card inside `frontend/src/components/cases/VerificationPanel.tsx`.
- Unit + integration tests matching the existing L1 test harness.

### 2.2 Out of scope

- Walking / bicycling / transit modes (driving only).
- Live-traffic-aware duration (deterministic driving time only, no `departure_time`).
- New database tables or migrations. Everything rides on the existing `verification_results` / `level_issues` tables.
- Changes to the 7-level strip, auto-run orchestrator, MD Approvals page, Assessor Queue, notifications bell, checklist validator, L3 Vision, or any other level.
- Configurable threshold — 30 min is hard-coded as a module constant; can be revisited later.
- A new artifact subtype — reuses `BUSINESS_PREMISES_PHOTO` verbatim.

### 2.3 Non-goals

- Does not replace the existing L3 Vision business-premises scoring.
- Does not cross-check the business address against any other bureau/registry source.
- Does not validate that the GPS-extracted business address matches any field on the loan application (that would be a future L1 sub-step).

---

## 3. User-visible behaviour

### 3.1 Happy path

A case with house + business photos, both yielding GPS (via EXIF or watermark), Distance Matrix returns `OK` with `travel_minutes ≤ 30`:
- L1 sub-step results gain `business_gps_coords`, `commute_distance_km`, `commute_travel_minutes`, `commute_sub_step_status: "pass"`.
- No new `LevelIssue` is emitted.
- L1 card renders three new rows: "Business-visit photo GPS" (pass), "House → Business commute" (pass, e.g. `"18 min · 9.2 km (driving)"`), no "Commute AI review" row.
- L1 status unchanged by this feature.

### 3.2 Over-threshold — reviewable

`travel_minutes > 30`, Opus judge returns `severity=WARNING`:
- WARNING `LevelIssue` emitted with `sub_step_id="house_business_commute"`.
- L1 card shows the "Commute AI review" row with the judge's reason text.
- Level 1 still PASSES (WARNING does not block).
- Assessor can close the issue via the existing Assessor Queue justification flow.

### 3.3 Over-threshold — absurd

`travel_minutes > 30`, Opus judge returns `severity=CRITICAL`:
- CRITICAL `LevelIssue` emitted with `sub_step_id="house_business_commute"`.
- Level 1 BLOCKS (critical aggregation unchanged).
- Surfaces on MD Approvals with the three-button flow: Approve / Approve-for-this-case-only / Reject.

### 3.4 Missing business GPS

No `BUSINESS_PREMISES_PHOTO` artifact yields coordinates (EXIF stripped AND watermark unreadable on every biz photo):
- CRITICAL `LevelIssue` emitted with `sub_step_id="business_visit_gps"`.
- Distance Matrix + judge are both skipped.
- L1 BLOCKS, MD-only resolution.
- Copy: *"Business-visit photo GPS could not be recovered. Upload a business-premises photo with intact EXIF or a legible GPS-Map-Camera overlay, or MD-approve this case on the specific context."*

### 3.5 Distance Matrix failures

- `ZERO_RESULTS` / `NOT_FOUND` element → CRITICAL `house_business_commute`. Implies garbage coordinates or an impossible route (e.g. separated by water); operator should investigate.
- Network error / non-OK HTTP / missing API key → WARNING `house_business_commute` with copy "Distance Matrix unavailable; re-run L1 or verify manually."

### 3.6 Opus judge failures

`travel_minutes > 30` but the Opus call raises / returns unparseable JSON:
- WARNING `house_business_commute` with copy "AI commute judge unavailable — please review manually (travel time X min, distance Y km)."
- We deliberately do **not** escalate to CRITICAL on a flaky model call.

### 3.7 Re-run behaviour

On a subsequent L1 run with the same house and business coordinates:
- Distance Matrix is NOT called; `commute_distance_km` / `commute_travel_minutes` are copied from the latest prior `VerificationResult.sub_step_results` for this `(case_id, L1_ADDRESS)`.
- Opus judge is NOT re-called; `commute_judge_verdict` is copied verbatim.
- Cost of the commute check on re-run: $0.

Any change to either coordinate pair invalidates the cache and the full chain re-runs.

---

## 4. Architecture

### 4.1 Component layout

```
backend/app/verification/
├── levels/
│   └── level_1_address.py           # orchestrator — 2 new cross-checks added
└── services/
    ├── google_maps.py                # + distance_matrix_driving()
    ├── commute_judge.py              # NEW — Opus reasonableness judge
    ├── exif.py                       # unchanged — reused for biz photos
    └── gps_watermark.py               # unchanged — reused for biz photos
```

```
frontend/src/components/cases/
└── VerificationPanel.tsx             # + 3 Param rows in L1 builder
```

### 4.2 Data flow (Level 1, sub-steps 3/3a'/3b)

```
for each HOUSE_VISIT_PHOTO:                 [existing]
  try EXIF → watermark OCR → reverse-geocode → stop on first hit
  → gps_coords, gps_source, gps_watermark_meta, gps_addr, gps_match

for each BUSINESS_PREMISES_PHOTO:            [new — identical loop]
  try EXIF → watermark OCR → stop on first hit
  → business_gps_coords, business_gps_source, business_gps_watermark_meta

if business_gps_coords is None:              [new]
  emit CRITICAL business_visit_gps
  commute_sub_step_status = "skipped_missing_business_gps"
  → skip 3b

elif gps_coords is None:                     [new]
  commute_sub_step_status = "skipped_missing_house_gps"
  (existing gps_vs_aadhaar critical covers this)
  → skip 3b

else:                                        [new — sub-step 3b]
  if cache_hit(house_coords, business_coords):
    reuse prior commute_* values
  else:
    dm = distance_matrix_driving(house, business)
    if dm is None (infra error):
      emit WARNING house_business_commute ("DM unavailable")
    elif dm.raw_status == "zero_results":
      emit CRITICAL house_business_commute ("no drivable route")
    elif dm.travel_minutes <= 30:
      no issue
    else:
      v = commute_judge(profile_inputs, dm.distance_km, dm.travel_minutes)
      if v is None (Opus failed):
        emit WARNING ("judge unavailable")
      elif v.severity == "WARNING":
        emit WARNING with v.reason
      else:  # CRITICAL
        emit CRITICAL with v.reason

final_status = BLOCKED if any critical else PASSED    [existing aggregation]
```

### 4.3 Cache strategy

No new tables. The orchestrator does a single SELECT at the top of sub-step 3b:

```python
prior = (await session.execute(
  select(VerificationResult)
  .where(
    VerificationResult.case_id == case_id,
    VerificationResult.level_number == VerificationLevelNumber.L1_ADDRESS,
    VerificationResult.status.in_([PASSED, BLOCKED]),
  )
  .order_by(VerificationResult.completed_at.desc())
  .limit(1)
)).scalar_one_or_none()
```

If `prior.sub_step_results["gps_coords"] == new_house_coords` **and** `prior.sub_step_results["business_gps_coords"] == new_business_coords`, copy the commute fields from `prior.sub_step_results`. Otherwise compute fresh.

Equality is on the rounded-to-5-decimal-places tuple (~1.1 m resolution, well under GPS noise).

---

## 5. Interfaces

### 5.1 `google_maps.distance_matrix_driving`

```python
from dataclasses import dataclass

@dataclass
class DistanceMatrixResult:
    distance_km: float
    travel_minutes: float
    raw_status: str   # "ok" | "zero_results" | "not_found"

async def distance_matrix_driving(
    *,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    api_key: str | None,
    client_factory: Callable[[], Any] = _default_client_factory,
) -> DistanceMatrixResult | None:
    """Returns None on any infra failure (missing key, HTTP error, non-OK
    top-level status, network timeout). Returns a populated result with
    raw_status='zero_results' / 'not_found' on per-element failures so
    callers can distinguish 'no route' from 'service broken'."""
```

Endpoint: `https://maps.googleapis.com/maps/api/distancematrix/json`, params `origins`, `destinations`, `mode=driving`, `key`. Timeout 8s (same default as `reverse_geocode`).

### 5.2 `commute_judge.judge_commute_reasonableness`

```python
@dataclass
class CommuteJudgeVerdict:
    severity: Literal["WARNING", "CRITICAL"]
    reason: str
    confidence: Literal["low", "medium", "high"]
    model_used: str
    cost_usd: Decimal

async def judge_commute_reasonableness(
    *,
    travel_minutes: float,
    distance_km: float,
    applicant_occupation_from_form: str | None,
    applicant_business_type_hint: str | None,
    loan_amount_inr: int | None,
    area_class: Literal["rural", "urban"] | None,
    bureau_occupation_history: str | None,
    bank_income_pattern: Literal["salary_credits", "cash_deposits", "mixed"] | None,
    house_derived_address: str | None,
    business_derived_address: str | None,
    claude: Any,
) -> CommuteJudgeVerdict | None:
    """Returns None on any failure (Claude error, unparseable JSON, schema
    violation). Returns a valid verdict otherwise. Hard rule: severity is
    never 'NONE' / 'PASS' — by contract this function is only called when
    travel_minutes > 30, and the floor is WARNING."""
```

Model: `tier="opus"`, `cache_system=True`, `max_tokens=400`, `temperature` omitted (Opus rejects it).

### 5.3 Prompt contract (summarised)

System prompt (cached) states:
- baseline expectation for small-ticket Indian MFI: business typically within 30 min of home;
- typical failure modes: proxy borrower, data-entry error, inactive business, wrong address;
- severity definitions: WARNING = reviewable (assessor can justify), CRITICAL = absurd (MD approval only);
- required output JSON shape (below);
- must reference at least one profile input in the `reason`.

User message (not cached) carries the dict of inputs. Missing inputs are sent as JSON `null`; the prompt tells the judge fields may be null.

Output:
```json
{
  "severity": "WARNING" | "CRITICAL",
  "reason": "<one or two sentence audit-ready rationale>",
  "confidence": "low" | "medium" | "high"
}
```

### 5.4 `sub_step_results` — new keys (additive)

| Key | Type | Populated when |
|---|---|---|
| `business_gps_coords` | `[float, float] \| null` | Always (null if no biz photo yielded coords) |
| `business_gps_source` | `"exif" \| "watermark" \| null` | When coords are present |
| `business_gps_watermark_meta` | `object \| null` | When watermark OCR was used |
| `commute_distance_km` | `float \| null` | When DM call succeeded |
| `commute_travel_minutes` | `float \| null` | When DM call succeeded |
| `commute_judge_verdict` | `object \| null` | When judge was invoked |
| `commute_sub_step_status` | `string` | Always (one of the 8 enumerated values per §6) |

### 5.5 New `LevelIssue.sub_step_id` values

- `business_visit_gps` — missing business-photo GPS. Severity always CRITICAL.
- `house_business_commute` — commute-related issue. Severity WARNING or CRITICAL depending on branch.

---

## 6. Issue severity matrix

| Situation | `commute_sub_step_status` | Issue `sub_step_id` | Severity | Resolver |
|---|---|---|---|---|
| House GPS missing | `skipped_missing_house_gps` | (existing `gps_vs_aadhaar`) | — | — |
| Business GPS missing | `skipped_missing_business_gps` | `business_visit_gps` | CRITICAL | MD only |
| DM `ZERO_RESULTS` / `NOT_FOUND` | `block_no_route` | `house_business_commute` | CRITICAL | MD only |
| DM infra failure | `warn_dm_unavailable` | `house_business_commute` | WARNING | Assessor justify |
| `travel_minutes ≤ 30` | `pass` | — | — | — |
| `> 30 min`, judge WARNING | `flag_reviewable` | `house_business_commute` | WARNING | Assessor justify |
| `> 30 min`, judge CRITICAL | `block_absurd` | `house_business_commute` | CRITICAL | MD only |
| `> 30 min`, judge call failed | `warn_judge_unavailable` | `house_business_commute` | WARNING | Assessor justify |

Final L1 status aggregation (`BLOCKED if any critical else PASSED`) is unchanged — the new critical rows plug into the existing check.

---

## 7. Profile inputs & their sources

The Opus judge receives the following fields, all read at L1 orchestration time:

| Field | Source |
|---|---|
| `travel_minutes`, `distance_km` | `distance_matrix_driving` result |
| `applicant_occupation_from_form` | `Case.occupation` (from loan application form) |
| `applicant_business_type_hint` | Latest prior L3 `VerificationResult.sub_step_results["business"]["business_type"]` if a prior L3 run exists, else None. **No** fresh L3 call triggered by L1. |
| `loan_amount_inr` | `Case.loan_amount` |
| `area_class` | Derived from `gps_nominatim.place_type` or Google reverse-geocode "locality" types: coarse rural/urban classifier (`rural` if "village" / "hamlet" / "suburb"; `urban` if "city" / "town"; else None). Pure helper. |
| `bureau_occupation_history` | First occupation snippet from `case_extractions` row with `extractor_name="equifax"`, or None. |
| `bank_income_pattern` | Cheap heuristic on `case_extractions` row with `extractor_name="bank_statement"`: count NEFT/IMPS credits with salary-keyword narration → `salary_credits` vs cash-deposit-dominant → `cash_deposits` vs neither → `mixed`. Pure helper, unit-tested. |
| `house_derived_address`, `business_derived_address` | L1's existing `gps_addr` (house) and, for business, a one-off `reverse_geocode(business_coords)` call. Fails silently to None. |

L1 already reads `case_extractions` for sub-step 6, so the bureau and bank reads are not new database work — they're one extra iteration over rows we already have loaded.

---

## 8. UI surface

`frontend/src/components/cases/VerificationPanel.tsx` in the L1 builder (`if (level === 'L1_ADDRESS') { ... return [Param, ...] }`):

Inserted **after** the existing "Reverse-geocode" row:

1. **"Business-visit photo GPS"**
   `value`: `"28.12345, 77.67890 (from burn-in overlay)"` / `"28.12345, 77.67890 (from EXIF)"` / `"not recovered"`
   `verdict`: `'pass'` if coords present, `'fail'` if missing
   `hint`: mirrors the house-GPS row hint
2. **"House → Business commute"**
   `value`: `"18 min · 9.2 km (driving)"` / `"over 30 min (45 min · 38 km)"` / `"no drivable route found"` / `"Distance Matrix unavailable"`
   `verdict`: `'pass' | 'warn' | 'fail'` driven by `commute_sub_step_status`
   `hint`: *"Google Distance Matrix, driving mode without live traffic. Cases over 30 min are reviewed by Claude Opus."*
3. **"Commute AI review"** (rendered only if `commute_judge_verdict` is non-null)
   `value`: `"FLAG: <reason>"` or `"BLOCK: <reason>"`
   `verdict`: `'warn'` or `'fail'`
   `hint`: *"Claude Opus reviewed applicant occupation, loan amount, area classification, bureau occupation history, and bank income pattern."*

LevelIssue chips (right-hand side of the L1 card and in the top-bar notifications bell) render from the existing `level_issues` table — no changes needed. MD Approvals surfaces new CRITICAL issues automatically via the existing `[CASE_SPECIFIC]` intent flow.

---

## 9. Testing strategy

### 9.1 Pure cross-check unit tests (`tests/unit/test_level_1_address.py`)

- `cross_check_business_gps_present` — 2 cases: None → CRITICAL dict; tuple → None.
- `cross_check_commute` — 7 cases, one per severity matrix row (§6) excluding the "house GPS missing" row (covered by existing `gps_vs_aadhaar` tests).

### 9.2 Service unit tests

- `tests/unit/test_google_maps.py::test_distance_matrix_driving_*` — 3 cases using the existing mock-httpx pattern: OK element, ZERO_RESULTS element, network error.
- `tests/unit/test_commute_judge.py` (new file) — 3 cases using the existing fake `ClaudeService`: WARNING JSON, CRITICAL JSON, junk response → None.
- `tests/unit/test_bank_income_classifier.py` (new file) — 3 cases: salary-dominant, cash-dominant, mixed. Pure function over a list of transaction dicts.
- `tests/unit/test_area_classifier.py` (new file) — 3 cases: rural place_type, urban place_type, unknown.

### 9.3 Orchestrator integration tests (`tests/integration/test_level_1_address.py`)

Extend the existing fixture with business-photo artifacts. Five new tests:

1. `test_commute_happy_path_under_30` — EXIF present on both sides, DM fake returns 15 min, no new issue, L1 PASSES.
2. `test_commute_missing_business_gps` — biz photos have no EXIF and watermark OCR returns None, CRITICAL `business_visit_gps`, L1 BLOCKED.
3. `test_commute_over_30_judge_warning` — DM fake returns 42 min, judge fake returns WARNING, WARNING `house_business_commute`, L1 PASSES.
4. `test_commute_over_30_judge_critical` — DM fake returns 95 min, judge fake returns CRITICAL, L1 BLOCKED.
5. `test_commute_rerun_reuses_cache` — run L1 twice with unchanged artifacts; assert DM fake called once and judge fake called once.

No real Google Maps or Claude calls in any test. DM client is injected via `client_factory`. `ClaudeService` is the existing fake.

### 9.4 Coverage

New code targets ≥85% line coverage, matching the project standard.

---

## 10. Error handling & failure modes

| Failure | Behaviour |
|---|---|
| Business photo download fails (S3 error) | Log WARNING, continue to next biz photo. Matches existing house-photo loop. |
| Claude Haiku watermark OCR raises | Returns None, we move to the next biz photo. |
| Both EXIF and watermark fail on every biz photo | CRITICAL `business_visit_gps` emitted. |
| Google Maps API key missing | `distance_matrix_driving` returns None → WARNING `house_business_commute` ("DM unavailable"). Same stance as `reverse_geocode`. |
| Distance Matrix network timeout | Same — WARNING. |
| Distance Matrix returns non-OK top-level status (e.g. `REQUEST_DENIED`) | Log WARNING, return None → WARNING `house_business_commute`. |
| Distance Matrix returns `OK` with element `ZERO_RESULTS` or `NOT_FOUND` | CRITICAL `house_business_commute` ("no drivable route"). |
| Opus judge call raises | Return None → WARNING "judge unavailable". |
| Opus returns JSON with `severity` outside `{WARNING, CRITICAL}` | Treat as parse failure → WARNING "judge unavailable". |
| Cache-lookup SELECT fails | Log WARNING, fall through to fresh computation. |

---

## 11. Cost analysis

Per case, fresh run:

| Step | Cost | Trigger |
|---|---|---|
| Biz EXIF scan | $0 | always |
| Biz watermark OCR (Haiku) | ~$0.002 per photo, fires only when EXIF stripped | WhatsApp-sourced biz photos |
| Distance Matrix (Google) | ~$0.005 | when both sides have coords |
| Business reverse-geocode (Google) | ~$0.005 | when biz coords present |
| Opus judge (warm cache) | ~$0.022 | when `travel_minutes > 30` |
| Opus judge (cold cache) | ~$0.045 | when `travel_minutes > 30` AND >5 min since last call |

Typical case (≤ 30 min, EXIF present): **~$0.010**.
Worst case (stripped EXIF + > 30 min + cold cache): **~$0.054**.
Re-run of the same case: **$0** for the commute check (cache reuse).

Fits well within the existing L1 budget (~$0.20 per case for KYC + LAGR scans).

---

## 12. Open questions

1. Should we also record the Google Maps `origin_addresses[0]` / `destination_addresses[0]` strings from the Distance Matrix response? Cheap extra audit evidence. Proposed: yes, store in `sub_step_results.commute_dm_origin_text` / `_dest_text`.
2. Should the WARNING severity on "DM unavailable" block the assessor from signing off without a manual coords check? Current design leaves it as an ordinary WARNING. If operators want a "distance check uncompleted" block, escalate to CRITICAL instead.
3. Threshold (30 min) is hard-coded. If operations wants to tune this per-region later, promote to a `settings.commute_max_minutes` with a default of 30.

None of these three block the current spec — all are additive follow-ups.

---

## 13. Migration & rollout

- No database migration required.
- No feature flag — this is a small additive check; worst case we revert the level_1_address.py change.
- Deployment is a single backend container rebuild. Frontend change is a three-row addition in one file.
- Backfill: not applicable. New L1 runs pick up the check; historical `VerificationResult` rows are untouched.
