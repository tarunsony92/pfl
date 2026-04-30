# Resume — L1 smart-match, pincode master, LAGR guarantor scan, L3 Opus upgrade

> **Open a new Claude Code session in this repo and paste this file's path
> (`docs/superpowers/RESUME_2026_04_22_L1_SMART_MATCH.md`) to pick up
> exactly where this session left off.**

**Spawned:** 2026-04-22
**Parent:** `docs/superpowers/RESUME_4LEVEL_VERIFICATION.md`
**Branch:** `4level-l1` (tip: `0ceee16` — nothing has been committed this session)
**Status:** L1 engine rewritten end-to-end with district-aware matching,
watermark-pincode trust, LAGR inline scanner, and a live Ajay run that
correctly returns `2 issues · 60% match · S/O Sultan · LAGR parties extracted`.
L3 vision scorer upgrade to Opus is **partially started** (see §4 below).

---

## 1. What shipped this session (live on Ajay, verified in browser)

### Backend

| # | Concern | Shipped |
|---|---|---|
| A | **Lint/build cleanup** from prior session: 29 ESLint errors across 8 files fixed + Suspense wrap on `src/app/login/page.tsx` for Next 14 static prerender | `next build` now passes (13/13 routes); frontend pytest 233/233; backend pytest 698/698 (7 known MFA skips) |
| B | **GPS watermark OCR fallback** wiring confirmed (prior session's code hadn't been mounted in uvicorn) | Re-trigger succeeded, coords extracted from burn-in |
| C | **Google Maps REQUEST_DENIED** fallback → OpenStreetMap Nominatim | `backend/app/verification/services/nominatim.py` |
| D | **`google_maps.py` log level bumped** INFO→WARNING for `REQUEST_DENIED` / `OVER_QUERY_LIMIT` / `INVALID_REQUEST` (ZERO_RESULTS stays INFO) | |
| E | **Smart Aadhaar ↔ GPS match** with verdict ladder `match` / `doubtful` / `mismatch` + score 0-100 + reason; Nominatim `addressdetails=1` structured response; district comparison prefers India-Post master over OSM tags | `address_normalizer.compare_aadhaar_to_gps`, `nominatim.GPSAddress` |
| F | **Haryana pincode master** from `data.gov.in/all_india_pin_code.csv` (official India-Post snapshot); 301 pincodes bundled at `backend/app/verification/data/haryana_pincodes.json`; `pincode_lookup.lookup_pincode()` service with lru_cache | Fixes Ajay's false "mismatch" — Nominatim tagged `127045` as Hisar, India Post says Bhiwani; watermark's own `125007` correctly = Hisar. |
| G | **Watermark pincode precedence** over Nominatim-guessed pincode — GPS-Map-Camera's burn-in pincode is the phone's own geocode, never a reverse-geocode guess | `level_1_address.py` GPS loop — parses 6-digit from `wm.place`, passes via `effective_pincode` |
| H | **Ration/electricity bill scanner**: Haiku → **Sonnet** + hardened prompt with anti-hallucination + explicit NAME&ADDRESS layout hints; extracts `name` / `father_or_husband_name` / `relation` cleanly | `backend/app/worker/extractors/ration_bill_scanner.py` schema v1.1; Ajay now reads **SULTAN** (not hallucinated "HARJEET KAUR") with father **SH SADHU RAM CHOUDHAR** |
| I | **Aadhaar scanner captures C/O name** separately (prompted for `care_of_name` vs `father_name` vs `husband_name`); collapses to a single `father_name` alias for the L1 mapper | Ajay's Aadhaar now stores `extracted_father_name: "Sultan"` |
| J | **Ration owner rule rewritten** with 6-path decision tree; new Path 3 recognises *"applicant is S/O bill-owner via Aadhaar C/O"* and emits CRITICAL only if the owner isn't on the loan as co-app/guarantor | `cross_check_ration_owner_rule` in `level_1_address.py:173` |
| K | **S/O vs C/O language** — `_relation_label(gender)` returns `S/O` for Male, `W/O` for Female, defaults `S/O` (microfinance default). Replaced literal "C/O Sultan" in rule descriptions | `level_1_address.py:137` |
| L | **LAGR inline scanner from L1** — `_load_or_scan_lagr_parties()` runs the `LoanAgreementScanner` the first time L1 needs guarantor names, persists to `case_extractions` (keyed by `(case_id, 'loan_agreement_scanner', artifact_id)`), reuses on subsequent L1 runs → pay once per case | `level_1_address.py:62` |
| M | **Loan-agreement scanner** extended with `co_applicants` / `guarantors` / `witnesses` lists (prompt recognises Hindi labels `जमानती`/`ज़ामिन` for guarantor) | `loan_agreement_scanner.py` schema v1.0 |
| N | **Explicit "we inspected the LAGR PDF" message** on the ration_owner CRITICAL — lists the exact parties found so the assessor knows this claim doesn't rely on L4 having run | |
| O | **Case row backfill** — Ajay's `loan_amount=100000`, `loan_tenure_months=24`, `co_applicant_name='Gordhan'` | Manual SQL update — other cases affected by the resume doc §9 P4 still need backfilling |

### Frontend

| # | Concern | Shipped |
|---|---|---|
| α | **Expandable level card** — collapsed header shows level title + status pill + **`% match`** badge + **`⚑ ADDRESS MISMATCH`** red pill (when `gps_vs_aadhaar` CRITICAL + unresolved) + counters + cost + last-run | `VerificationPanel.tsx` |
| β | **2-column layout** on expand: **LEFT** = *Evidence gathered* (all extraction status + GPS + addresses + **LAGR parties row**); **RIGHT** = *Logic checks* — one card per rule in `RULE_CATALOG[level]` showing PASS (green) / WARNING (amber) / CRITICAL (red) / MD-OVERRIDDEN (indigo), with inline IssueRow (assessor resolve → MD decide) embedded on every failure | `RULE_CATALOG`, `reconcileRules`, `LogicChecksColumn`, `LogicCheckRow` |
| γ | **Rule catalog** for all four levels (L1 has 5 rules, L2 has 7, L3 has 4, L4 has 3). PASS is computed as "no unresolved issue for this sub_step_id"; MD_APPROVED = overridden (counts as pass); MD_REJECTED or unresolved CRITICAL = fail | |
| δ | **LAGR parties row** on L1 — shows `borrower: AJAY SINGH · co-app: GORDHAN · guarantor: PINKI`; independent of L4 run state | |
| ε | **Reverse-geocode row** relabelled — now `"Hisar II Block, Hisar, Haryana, 127045 (via OpenStreetMap)"` when Nominatim resolved it | |

---

## 2. Key code landmarks

- `backend/app/verification/services/nominatim.py` — NEW. `GPSAddress` dataclass (state/district/village/postcode/country). Uses `addressdetails=1`.
- `backend/app/verification/services/pincode_lookup.py` — NEW. Lru-cached master-file loader. Extend to more states by dropping `<state>_pincodes.json` into `backend/app/verification/data/`.
- `backend/app/verification/data/haryana_pincodes.json` — NEW. 301 pincodes, sourced from `data.gov.in/all_india_pin_code.csv` (see §6 for how to refresh).
- `backend/app/verification/services/address_normalizer.py:165` — `GPSMatch` dataclass + `compare_aadhaar_to_gps()`. Pincode-master districts override OSM tags when both resolve.
- `backend/app/verification/services/gps_watermark.py` — added `GPSWatermark.pincode` field; regex-extracts 6-digit from Haiku's `place` field.
- `backend/app/verification/levels/level_1_address.py:62` — `_load_or_scan_lagr_parties` helper (cache-or-scan LAGR).
- `backend/app/verification/levels/level_1_address.py:137` — `_relation_label(gender)` → "S/O" / "W/O".
- `backend/app/verification/levels/level_1_address.py:173` — `cross_check_ration_owner_rule` 6-path decision tree.
- `backend/app/verification/levels/level_1_address.py:745` — GPS extraction loop with watermark-pincode precedence.
- `backend/app/worker/extractors/ration_bill_scanner.py:_TIER = "sonnet"` — upgraded from haiku.
- `frontend/src/components/cases/VerificationPanel.tsx` — `RULE_CATALOG`, `reconcileRules`, `LogicChecksColumn`, `MatchBadge`, LAGR-parties row.

---

## 3. Uncommitted files (all from this + prior session)

```
M  backend/app/api/routers/verification.py
M  backend/app/main.py
M  backend/app/schemas/verification.py
M  backend/app/verification/levels/level_1_address.py
M  backend/app/verification/services/address_normalizer.py
M  backend/app/verification/services/google_maps.py
M  backend/app/verification/services/vision_scorers.py   ← partial Opus upgrade, see §4
M  backend/app/worker/extractors/aadhaar_scanner.py
M  backend/app/worker/extractors/loan_agreement_scanner.py
M  backend/app/worker/extractors/ration_bill_scanner.py
M  backend/tests/conftest.py
M  frontend/src/app/(app)/cases/[id]/page.tsx
M  frontend/src/app/layout.tsx
M  frontend/src/app/login/page.tsx
M  frontend/src/components/cases/CaseInsightsCard.tsx
M  frontend/src/components/cases/DecisioningPanel.tsx
M  frontend/src/components/cases/VerificationPanel.tsx
M  frontend/src/components/cases/__tests__/DecisioningPanel.test.tsx
M  frontend/src/components/cases/__tests__/FeedbackWidget.test.tsx
M  frontend/src/components/layout/Sidebar.tsx
M  frontend/src/lib/api.ts
M  frontend/src/lib/types.ts
M  frontend/src/lib/useVerification.ts
?? backend/app/verification/data/                          ← NEW — haryana_pincodes.json
?? backend/app/verification/services/auto_justifier.py     ← from prior session
?? backend/app/verification/services/gps_watermark.py      ← from prior session
?? backend/app/verification/services/nominatim.py          ← NEW this session
?? backend/app/verification/services/pincode_lookup.py     ← NEW this session
?? docs/superpowers/RESUME_4LEVEL_VERIFICATION.md          ← parent resume
?? docs/superpowers/RESUME_2026_04_22_L1_SMART_MATCH.md    ← this file
?? frontend/src/app/(app)/admin/approvals/                 ← from prior session
```

### Suggested commit groupings
1. `feat(l1): address matching via district master-file (data.gov.in Haryana pincodes)`
2. `feat(l1): Nominatim structured reverse-geocode + watermark-pincode precedence`
3. `feat(l1): ration bill Sonnet + C/O→S/O relation label + guardian-on-loan rule`
4. `feat(l1): inline LAGR scan for guarantor names (cached in case_extractions)`
5. `feat(ui): expandable level cards with % match + Evidence | Logic-checks 2-column split`
6. `chore(frontend): lint + Suspense fixes so next build passes`

---

## 4. ⚠️ In-flight work when session ended

### L3 Vision — Opus + business-type awareness (PARTIAL)

User flagged (screenshot of Ajay's L3) two bugs on a photographed
barbershop ("Sanky Salon"):

1. **Cattle shown PASS** when there are obviously no cattle → should be
   **N/A** (and hidden from the pass-rate denominator).
2. **Stock shown PASS** when the photos clearly show a service business
   with minimal consumables. The rule's `stock_value_estimate_inr` ≈ ₹15,000
   vs loan ₹1,00,000 (15%) — should be CRITICAL with a loan-reduction
   recommendation, not PASS.

User asked for: **Opus tier** (not Sonnet) + **business-type classification**
+ a **`recommended_loan_amount_inr`** field the MD can act on + auto-learning
feedback loop on the new issue type.

**What's DONE:**
- `backend/app/verification/services/vision_scorers.py`:
  - Prompt rewritten to classify `business_type` (`product_trading` / `service` / `cattle_dairy` / `manufacturing` / `mixed` / `other` / `unknown`) FIRST, then value collateral appropriate to the type, then recommend a loan amount.
  - New fields on output: `business_type`, `business_type_confidence`, `business_subtype`, `visible_equipment_value_inr`, `recommended_loan_amount_inr`, `recommended_loan_rationale`.
  - `BusinessPremisesScorer._TIER = "opus"`; `_EMPTY_DATA` extended to match.
  - Hard rules in the prompt: "A service business MUST have cattle_count=0, cattle_health=not_applicable"; "Do NOT claim stock is adequate for a service business just because you see consumables on a shelf."

**What's NOT YET DONE:**
1. **L3 engine rules** (`backend/app/verification/levels/level_3_vision.py`):
   - `cross_check_cattle_health` — currently emits CRITICAL only when health=`unhealthy`. Leave as-is but… the frontend needs to hide the `cattle_health` rule row entirely when `business_type != cattle_dairy` and not count it in the denominator. The scorer now always emits `cattle_health=not_applicable` for service businesses, so the frontend has a clean signal.
   - `cross_check_stock_vs_loan` — needs to branch on `business_type`:
     - For `service`: compare `(stock_value + visible_equipment_value)` to loan; if the combined collateral is < X% (say 40%), emit CRITICAL with the scorer's `recommended_loan_amount_inr` in the description.
     - For `product_trading`: keep existing 50/100% thresholds on stock only.
     - For `cattle_dairy`: use `cattle_count × ₹60,000` as the stock baseline (prompt already does this).
   - New `cross_check_loan_amount_reduction` — always fires when `recommended_loan_amount_inr < loan_amount × 0.8`, severity WARNING, description includes the recommended amount + Opus's rationale.

2. **Frontend**:
   - `RULE_CATALOG.L3_VISION` — add `loan_amount_reduction` row.
   - `reconcileRules` — handle new verdict `"n/a"`. When the backend's `sub_step_results.business.business_type != 'cattle_dairy'`, mark `cattle_health` rule as N/A in the column (gray, strikethrough, excluded from match %).
   - `MatchBadge` — exclude N/A rules from the denominator.
   - New "Recommended loan ₹X" callout when `recommended_loan_amount_inr` is set and differs from proposed.

3. **MD auto-learning** — mirror the prior-session AutoJustifier pattern for L3 issues. When the MD overrides a `loan_amount_reduction` (accepting the reduced ticket), write the rationale into the precedents table so future cases with similar `business_type` + `visible_equipment_value` ratios get auto-justified.

**Current state of the vision_scorers.py file:**
- Prompt + `_EMPTY_DATA` + `_TIER` all changed
- No backend restart yet — Opus call is more expensive; test carefully

**User's request quote:**
> "there is no cattle so the software should just throw non cattle business
> instead of approving cattle. there is absolutely no stock seen on this
> premisis but still stock has been shown as green and good, need to use opus
> for this and do a detailed analysis, since stock is not there loan amount
> reduction recommendation should be given for this specific case, business
> photos attached, the same needs to be done in the software as MD feedback
> for auto learning, in the same manner we are doing right now"

---

## 5. How to resume

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git status                          # confirm the files in §3
git log --oneline -5

# Stack
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl
# Backend should be Up (healthy). If you touched python files, bounce it:
docker restart pfl-backend && sleep 5

# Frontend dev (also need to restart if you touched TS files)
pgrep -f "next dev" || (cd frontend && nohup npm run dev > /tmp/pfl-web.log 2>&1 &)

# Auth
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# Re-trigger L1 on Ajay to prove the pipeline is still clean
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L1_ADDRESS \
  | python3 -m json.tool

# Check the fresh sub_step_results — should have gps_match.verdict=="doubtful",
# loan_agreement_parties with PINKI/GORDHAN, S/O Sultan in the rule description.
docker exec pfl-postgres psql -U pfl -d pfl -c "\
  SELECT jsonb_pretty(sub_step_results->'gps_match'), \
         jsonb_pretty(sub_step_results->'loan_agreement_parties') \
    FROM verification_results \
   WHERE case_id = '7bdea924-225e-4b70-9c46-2d2387fc884c' \
     AND level_number = 'L1_ADDRESS' \
   ORDER BY created_at DESC LIMIT 1;"
```

Login creds: `saksham@pflfinance.com` / `Saksham123!` (DEV_BYPASS_MFA=true).
Open `http://localhost:3000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c` →
Verification tab. You should see:
- L1 · Address · `2 ISSUES · 1 CRITICAL · 1 WARNING` · **60% match** (amber)
- **No "ADDRESS MISMATCH" red pill** (verdict is `doubtful`, not `mismatch`)
- Right column has 3✓ 1! 1✗ rules
- Left column includes the new "Loan-agreement parties scanned" row with `PINKI, GORDHAN`

---

## 6. Refreshing the pincode master

The bundled file is a state-filtered slice of the official India-Post snapshot.
To refresh or add more states:

```bash
curl -sL "https://www.data.gov.in/sites/default/files/all_india_pin_code.csv" \
  -o /tmp/all_india_pincode.csv

python3 <<'PY'
import csv, json, collections, pathlib
rows = []
with open('/tmp/all_india_pincode.csv', encoding='utf-8', errors='replace') as f:
    for row in csv.DictReader(f):
        if (row.get('statename') or '').strip().upper() == 'HARYANA':
            rows.append(row)

pin_map = {}
for pin, counter in collections.defaultdict(collections.Counter, {}).items():
    pass
counts = collections.defaultdict(collections.Counter)
for r in rows:
    pin = (r.get('pincode') or '').strip()
    dist = (r.get('Districtname') or '').strip().title()
    taluk = (r.get('Taluk') or '').strip().title()
    if pin and dist:
        counts[pin][(dist, taluk)] += 1
for pin, c in counts.items():
    (d, t), _ = c.most_common(1)[0]
    pin_map[pin] = {'district': d, 'taluk': t}

out = pathlib.Path('backend/app/verification/data/haryana_pincodes.json')
out.write_text(json.dumps({
    'source': 'data.gov.in/all_india_pin_code.csv · 2026-04-22 snapshot',
    'state': 'Haryana',
    'pincodes': pin_map,
}, indent=0))
print('wrote', out, '·', len(pin_map), 'unique pincodes')
PY
```

`pincode_lookup._load_master()` is `lru_cache(maxsize=1)` — a backend
restart is required to pick up a fresh master file.

---

## 7. Running tests

```bash
# Backend
docker exec -e TEST_DATABASE_URL='postgresql+asyncpg://pfl:pfl_dev@postgres:5432/pfl_test' \
  pfl-backend sh -c "cd /app && python -m pytest tests/ --tb=line --no-cov \
    -p no:cacheprovider --asyncio-mode=auto -q"
# Expected: 698 passed · 7 skipped · 7 known MFA failures (DEV_BYPASS_MFA=true in .env)

# Frontend
cd frontend
npx tsc --noEmit      # 1 known pre-existing error in DecisioningPanel.test.tsx (AWAITING_REVIEW stage)
npm run lint          # should be 0 errors, only <img> warnings
npm test              # vitest 233/233 (ignore the stray e2e/auth.spec.ts Playwright suite picked up by the glob)
npm run build         # MUST pass — this session fixed the Suspense/login prerender + 29 lint errors that had been blocking it
```

### New unit tests wanted (not yet written)
- `tests/unit/test_nominatim.py` — mock httpx, verify addressdetails=1 parsing.
- `tests/unit/test_compare_aadhaar_to_gps.py` — verdict ladder: match / doubtful / mismatch; India-Post override beats OSM tags.
- `tests/unit/test_pincode_lookup.py` — Haryana seed hits (125001→Hisar, 127045→Bhiwani).
- `tests/unit/test_cross_check_ration_owner_rule.py` — Path 3 (applicant S/O bill owner + owner not on loan) → CRITICAL; same + owner in guarantor_names → pass.
- `tests/unit/test_loan_agreement_scanner.py` — guarantor/co_applicant/witness extraction (mock Claude).

---

## 8. Next-up work queue (priority order)

### P0 — Finish L3 Opus upgrade (§4 above)
Estimated 2-3 hours. The scorer prompt + tier are done; remaining is:
engine rules, frontend N/A rendering, recommended-loan callout, MD precedent
feedback. Expect cost per L3 run to climb from ~$0.04 to ~$0.15 (Opus).

### P1 — Write the unit tests listed in §7.
Especially the ration-owner rule paths and pincode-master override logic
which are now the load-bearing credit checks.

### P2 — Commit the uncommitted work (§3)
Branch is `4level-l1`; nothing from this session is committed. Suggested
groupings in §3. The diff is large — split it to keep reviewable.

### P3 — Pincode master for remaining states
Currently Haryana only (301 pincodes). Most PFL operations are Haryana +
Punjab + Delhi + UP — extending is a 5-minute re-run of §6 per state.

### P4 — AutoJustifier wiring (carried from parent resume doc §4)
Still not wired into L1/L2/L3/L4 engines. With the new rule semantics
(S/O relation, LAGR parties, pincode-aware matching), the precedent
corpus will be much richer.

### P5 — Extractor address capture (equifax / bank_statement)
Left column still shows `Equifax addresses considered: 0 found` and
`Bank-statement addresses considered: 0 found`. Would close out the
`aadhaar_vs_bureau_address` and `aadhaar_vs_bank_address` rules (currently
silently passing because lists are empty). See parent resume doc §9 P2.

---

## 9. Quirks observed this session

| Symptom | Fix |
|---|---|
| `uvicorn` in `pfl-backend` caches python imports; `docker restart pfl-backend` required after every backend edit | (same as parent resume doc §7) |
| Frontend dev server holds `.next/` — can't run `npm run build` concurrently with `next dev` | Stop dev → build → restart dev |
| `preview_start` (MCP) collides with user's own `next dev -H 127.0.0.1` on port 3000 | `pkill -TERM -f "next dev"` then `preview_start` |
| Nominatim returns `state_district="Hisar"` for coords that India Post assigns to Bhiwani district | India Post master wins — handled in `compare_aadhaar_to_gps` |
| OSM-mapped `county="Hisar"` + a road tagged under `municipality="Hisar II Block"` inside administrative Bhiwani | Same as above — pincode is the tiebreaker |
| Haiku hallucinates plausible Indian names ("HARJEET KAUR") when thermal-paper scans are faded/torn | Upgraded ration-bill scanner to Sonnet + anti-hallucination prompt |

---

## 10. When you finish the next chunk

1. Commit with focused messages (see §3 groupings).
2. Update §1 status table + §3 uncommitted list in this file.
3. If L3 Opus work lands, tag `l3-opus` after verification.
4. Append SHAs + a one-line summary under a new `## 11. Done` section so
   the next reader can diff forward.
