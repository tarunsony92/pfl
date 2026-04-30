# L3 visual-evidence panel + click-to-expand pass detail (Part A) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Part A of the L3 visual-evidence design — an always-visible "Visual evidence & stock analysis" header section on the L3 verification panel, a business-type guard on `cross_check_cattle_health`, multi-angle photo-count visibility, and click-to-expand pass-detail on every `PassingRulesPanel` row (with dedicated L3 pass-detail cards; other levels get a placeholder until Part B).

**Architecture:** Additive `sub_step_results` keys on the L3 orchestrator (`visual_evidence`, `stock_analysis`, `pass_evidence`) produced by three new pure helper functions. Frontend reads those keys, renders a new header section (stock-analysis card + photo gallery), and promotes each `LogicCheckRow` to a keyboard-accessible expandable element that dispatches to dedicated L3 pass-detail cards on `sub_step_id`.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / pytest (backend); Next.js 14 / React / TypeScript / Tailwind / SWR (frontend).

**Spec:** [docs/superpowers/specs/2026-04-24-l3-visual-evidence-and-cross-level-evidence-audit-design.md](../specs/2026-04-24-l3-visual-evidence-and-cross-level-evidence-audit-design.md)

---

## File Structure

### Backend — modify

- `backend/app/verification/levels/level_3_vision.py`
  - Add three pure helpers: `build_stock_analysis`, `build_visual_evidence`, `build_pass_evidence`
  - Update `cross_check_cattle_health` signature + add guard
  - Refactor `cross_check_stock_vs_loan` to use `build_stock_analysis`
  - Orchestrator wires all three helpers into `sub_step_results` and updates the cattle-health call-site
- `backend/tests/unit/test_verification_level_3_vision.py`
  - Extend with new unit tests for all four above changes

### Frontend — create

- `frontend/src/components/cases/l3/helpers.ts`
  - Shared INR formatter + pct colour-grade logic + number helpers
- `frontend/src/components/cases/l3/L3StockAnalysisCard.tsx`
  - Header-level card: loan vs visible collateral, coverage pill, reasoning
- `frontend/src/components/cases/l3/L3PhotoGallery.tsx`
  - Header-level gallery: house + business thumbnails with lightbox
- `frontend/src/components/cases/l3/L3StockVsLoanPassCard.tsx`
  - Click-to-expand pass detail for `stock_vs_loan` — side-by-side table
- `frontend/src/components/cases/l3/L3InfraPassCard.tsx`
  - Click-to-expand pass detail for `business_infrastructure`
- `frontend/src/components/cases/l3/L3LoanRecPassCard.tsx`
  - Click-to-expand pass detail for `loan_amount_recommendation`

### Frontend — modify

- `frontend/src/lib/types.ts`
  - Add `visual_evidence`, `stock_analysis`, `pass_evidence` shapes under L3 `sub_step_results`
- `frontend/src/components/cases/VerificationPanel.tsx`
  - Wire L3 header section above concerns
  - Remove inline photo gallery inside per-concern expanded view (subsumed)
  - Promote `LogicCheckRow` to a keyboard-accessible expandable element
  - Dispatch pass-detail component on `sub_step_id` for L3 rules; placeholder otherwise

---

## Pre-flight checks

- [ ] **Step 0a: Verify tree state**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system" && git status && git log --oneline -3
```

Expected: clean tree, HEAD at `74d86f8 docs(specs): L3 visual-evidence + cross-level evidence audit (Part A spec)` on branch `4level-l1`.

- [ ] **Step 0b: Confirm baseline test suite is green**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q 2>&1 | tail -8
```

Expected: ~615 passed. If not green, STOP — do not proceed with any task until the baseline is clean.

- [ ] **Step 0c: Confirm Docker + frontend are up**

Run:
```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep pfl && pgrep -lf "next dev" | head -1
```

Expected: `pfl-backend` and `pfl-postgres` running; a `next dev` process running. If not, start them per the resume doc.

---

## Phase 1 — Backend pure helpers + guards

### Task 1: `cross_check_cattle_health` business-type guard

**Files:**
- Modify: `backend/app/verification/levels/level_3_vision.py:206-217, 368`
- Test: `backend/tests/unit/test_verification_level_3_vision.py`

- [ ] **Step 1.1: Write failing tests**

Add to `tests/unit/test_verification_level_3_vision.py`:

```python
class TestCattleHealthGuard:
    """cross_check_cattle_health must only fire for cattle_dairy / mixed
    businesses with an actual cattle count. Protects against Opus
    wrongly emitting cattle_health="unhealthy" on non-dairy cases."""

    def test_service_biz_unhealthy_cattle_no_fire(self) -> None:
        from app.verification.levels.level_3_vision import cross_check_cattle_health

        result = cross_check_cattle_health(
            "unhealthy",
            business_type="service",
            cattle_count=0,
        )
        assert result is None

    def test_product_trading_unhealthy_no_fire(self) -> None:
        from app.verification.levels.level_3_vision import cross_check_cattle_health

        result = cross_check_cattle_health(
            "unhealthy",
            business_type="product_trading",
            cattle_count=None,
        )
        assert result is None

    def test_cattle_dairy_unhealthy_count_3_fires(self) -> None:
        from app.verification.levels.level_3_vision import cross_check_cattle_health

        result = cross_check_cattle_health(
            "unhealthy",
            business_type="cattle_dairy",
            cattle_count=3,
        )
        assert result is not None
        assert result["sub_step_id"] == "cattle_health"
        assert result["severity"] == "critical"
        assert result["evidence"]["business_type"] == "cattle_dairy"
        assert result["evidence"]["cattle_count"] == 3
        assert result["evidence"]["cattle_health"] == "unhealthy"

    def test_cattle_dairy_unhealthy_count_0_no_fire(self) -> None:
        from app.verification.levels.level_3_vision import cross_check_cattle_health

        result = cross_check_cattle_health(
            "unhealthy",
            business_type="cattle_dairy",
            cattle_count=0,
        )
        assert result is None

    def test_cattle_dairy_healthy_no_fire(self) -> None:
        from app.verification.levels.level_3_vision import cross_check_cattle_health

        result = cross_check_cattle_health(
            "healthy",
            business_type="cattle_dairy",
            cattle_count=3,
        )
        assert result is None

    def test_mixed_biz_unhealthy_count_2_fires(self) -> None:
        from app.verification.levels.level_3_vision import cross_check_cattle_health

        result = cross_check_cattle_health(
            "unhealthy",
            business_type="mixed",
            cattle_count=2,
        )
        assert result is not None
        assert result["sub_step_id"] == "cattle_health"
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestCattleHealthGuard -xvs --no-cov 2>&1 | tail -20
```

Expected: **FAIL** — the current `cross_check_cattle_health` signature only takes `health`, so `TypeError: unexpected keyword argument 'business_type'` on most tests.

- [ ] **Step 1.3: Update `cross_check_cattle_health` signature**

In `backend/app/verification/levels/level_3_vision.py`, replace:

```python
def cross_check_cattle_health(health: str | None) -> dict[str, Any] | None:
    if health == "unhealthy":
        return {
            "sub_step_id": "cattle_health",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                "Cattle appear unhealthy / malnourished in the photos. "
                "Milking yield + asset value are at risk. Require a vet "
                "health certificate before disbursing a dairy loan."
            ),
        }
    return None
```

with:

```python
def cross_check_cattle_health(
    health: str | None,
    *,
    business_type: str | None = None,
    cattle_count: int | None = None,
) -> dict[str, Any] | None:
    """Fire only when the business is actually a dairy operation with
    cattle on site AND the scorer flagged them as unhealthy. Guards
    against Opus wrongly emitting cattle_health on non-dairy
    businesses — a service biz (barbershop) should never trigger a
    dairy-specific concern."""
    if health != "unhealthy":
        return None
    if business_type not in ("cattle_dairy", "mixed"):
        return None
    if not cattle_count or cattle_count <= 0:
        return None
    return {
        "sub_step_id": "cattle_health",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "Cattle appear unhealthy / malnourished in the photos. "
            "Milking yield + asset value are at risk. Require a vet "
            "health certificate before disbursing a dairy loan."
        ),
        "evidence": {
            "business_type": business_type,
            "cattle_count": cattle_count,
            "cattle_health": health,
        },
    }
```

- [ ] **Step 1.4: Update orchestrator call-site**

In `backend/app/verification/levels/level_3_vision.py` around line 368, replace:

```python
lambda: cross_check_cattle_health(b.data.get("cattle_health")),
```

with:

```python
lambda: cross_check_cattle_health(
    b.data.get("cattle_health"),
    business_type=b.data.get("business_type"),
    cattle_count=b.data.get("cattle_count"),
),
```

- [ ] **Step 1.5: Run tests to verify they pass**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestCattleHealthGuard -xvs --no-cov 2>&1 | tail -15
```

Expected: **PASS** on all 6 tests.

- [ ] **Step 1.6: Run full L3 test module to catch regressions**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py -q --no-cov 2>&1 | tail -8
```

Expected: all tests pass. If any pre-existing tests broke, the orchestrator change is likely wrong — investigate the failing test first before moving on.

- [ ] **Step 1.7: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/app/verification/levels/level_3_vision.py backend/tests/unit/test_verification_level_3_vision.py
git commit -m "$(cat <<'EOF'
fix(l3-vision): guard cattle_health on business_type so non-dairy cases don't falsely fire

cross_check_cattle_health previously fired whenever the scorer emitted
cattle_health="unhealthy", regardless of business type. The scorer's
prompt tells Opus that non-dairy businesses MUST return "not_applicable",
but Opus can disobey — real cases with barbershop photos were being
flagged for malnourished cattle. Added a hard code-level guard:

  - business_type must be cattle_dairy or mixed
  - cattle_count must be > 0
  - AND cattle_health == "unhealthy"

Also moved the previously orchestrator-attached evidence
({party, accounts_matched} — wrong dict for L3) onto the cross-check
itself, so the issue now carries business_type, cattle_count, and the
raw cattle_health string.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `build_stock_analysis` pure helper

**Files:**
- Modify: `backend/app/verification/levels/level_3_vision.py` (new helper, top of orchestrator section)
- Test: `backend/tests/unit/test_verification_level_3_vision.py`

- [ ] **Step 2.1: Write failing tests — service biz**

Add to `tests/unit/test_verification_level_3_vision.py`:

```python
class TestBuildStockAnalysis:
    """build_stock_analysis is a pure function that packages the
    business scorer's output plus the case loan amount into the
    sub_step_results.stock_analysis dict shape. Always produces a
    well-formed dict when given scorer data; returns None only when
    the scorer errored. The frontend renders 13 specific keys from
    this dict — missing any breaks the FE silently."""

    EXPECTED_KEYS = {
        "business_type", "business_subtype", "loan_amount_inr",
        "stock_value_estimate_inr", "visible_equipment_value_inr",
        "visible_collateral_inr", "cattle_count", "cattle_health",
        "coverage_pct", "floor_pct_critical", "floor_pct_warning",
        "recommended_loan_amount_inr", "recommended_loan_rationale",
        "cut_pct", "reasoning", "stock_condition", "stock_variety",
    }

    def test_service_biz_all_keys_present(self) -> None:
        from app.verification.levels.level_3_vision import build_stock_analysis

        biz_data = {
            "business_type": "service",
            "business_subtype": "barbershop",
            "stock_value_estimate_inr": 5_000,
            "visible_equipment_value_inr": 45_000,
            "cattle_count": 0,
            "cattle_health": "not_applicable",
            "stock_condition": "ok",
            "stock_variety": "narrow",
            "recommended_loan_amount_inr": 50_000,
            "recommended_loan_rationale": "covers equipment only",
        }
        out = build_stock_analysis(biz_data, loan_amount_inr=50_000)
        assert out is not None
        assert set(out.keys()) == self.EXPECTED_KEYS
        assert out["business_type"] == "service"
        assert out["visible_collateral_inr"] == 50_000  # 5k stock + 45k equipment
        assert out["coverage_pct"] == pytest.approx(1.0)
        assert out["floor_pct_critical"] == 0.40
        assert out["floor_pct_warning"] is None  # service has only one tier
        assert out["cut_pct"] == 0.0
        assert "Service" in out["reasoning"] or "service" in out["reasoning"]

    def test_product_trading_non_service(self) -> None:
        from app.verification.levels.level_3_vision import build_stock_analysis

        biz_data = {
            "business_type": "product_trading",
            "business_subtype": "kirana store",
            "stock_value_estimate_inr": 80_000,
            "visible_equipment_value_inr": 0,
            "cattle_count": 0,
            "cattle_health": "not_applicable",
            "recommended_loan_amount_inr": 80_000,
            "recommended_loan_rationale": "stock covers loan fully",
        }
        out = build_stock_analysis(biz_data, loan_amount_inr=100_000)
        assert out is not None
        assert out["business_type"] == "product_trading"
        assert out["visible_collateral_inr"] == 80_000  # no equipment for non-service
        assert out["coverage_pct"] == pytest.approx(0.80)
        assert out["floor_pct_critical"] == 0.50
        assert out["floor_pct_warning"] == 1.00  # non-service has two tiers
        assert out["cut_pct"] == pytest.approx(0.20)

    def test_cattle_dairy(self) -> None:
        from app.verification.levels.level_3_vision import build_stock_analysis

        biz_data = {
            "business_type": "cattle_dairy",
            "business_subtype": "buffalo dairy",
            "stock_value_estimate_inr": 240_000,  # 4 × 60k
            "cattle_count": 4,
            "cattle_health": "healthy",
            "recommended_loan_amount_inr": 200_000,
            "recommended_loan_rationale": "4 cattle at ₹60k each",
        }
        out = build_stock_analysis(biz_data, loan_amount_inr=200_000)
        assert out["visible_collateral_inr"] == 240_000
        assert out["cattle_count"] == 4
        assert out["coverage_pct"] == pytest.approx(1.20)

    def test_scorer_error_returns_none(self) -> None:
        """Empty / error-path scorer data → build_stock_analysis should
        return None so the orchestrator simply omits the key."""
        from app.verification.levels.level_3_vision import build_stock_analysis

        assert build_stock_analysis({}, loan_amount_inr=50_000) is None
        assert build_stock_analysis(None, loan_amount_inr=50_000) is None

    def test_missing_loan_amount_still_produces_partial_output(self) -> None:
        from app.verification.levels.level_3_vision import build_stock_analysis

        biz_data = {
            "business_type": "service",
            "stock_value_estimate_inr": 5_000,
            "visible_equipment_value_inr": 45_000,
        }
        out = build_stock_analysis(biz_data, loan_amount_inr=None)
        assert out is not None
        assert out["loan_amount_inr"] is None
        assert out["coverage_pct"] is None
        assert out["cut_pct"] is None
```

Also at the top of the file, ensure `import pytest` is already there (it is in every other test module).

- [ ] **Step 2.2: Run tests to verify they fail**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestBuildStockAnalysis -xvs --no-cov 2>&1 | tail -20
```

Expected: **FAIL** — `ImportError: cannot import name 'build_stock_analysis'`.

- [ ] **Step 2.3: Implement `build_stock_analysis`**

In `backend/app/verification/levels/level_3_vision.py`, add directly after `cross_check_infrastructure_rating` (around line 240, just before the `# Orchestrator` comment):

```python
def build_stock_analysis(
    biz_data: dict[str, Any] | None,
    *,
    loan_amount_inr: int | None,
) -> dict[str, Any] | None:
    """Package the business scorer's output + the case's loan amount into
    the sub_step_results.stock_analysis dict shape consumed by the L3
    frontend. Pure function; returns None when the scorer produced
    nothing (error path). See spec §4.1 for the 13-key contract.

    Non-service businesses have two thresholds (critical 50%, warning
    100%); service businesses have one (critical 40% — stock +
    equipment together). Null loan_amount → partial dict with
    coverage_pct / cut_pct set to None.
    """
    if not biz_data:
        return None

    business_type = biz_data.get("business_type")
    stock = biz_data.get("stock_value_estimate_inr") or 0
    equipment = biz_data.get("visible_equipment_value_inr") or 0

    is_service = business_type == "service"
    visible_collateral = (stock + equipment) if is_service else stock

    coverage_pct: float | None = None
    if loan_amount_inr and loan_amount_inr > 0:
        coverage_pct = visible_collateral / loan_amount_inr

    floor_pct_critical = (
        _SERVICE_COLLATERAL_FLOOR_PCT if is_service else _STOCK_CRITICAL_PCT
    )
    floor_pct_warning = None if is_service else 1.0

    recommended = biz_data.get("recommended_loan_amount_inr")
    cut_pct: float | None = None
    if recommended is not None and loan_amount_inr and loan_amount_inr > 0:
        cut_pct = max(0.0, 1 - recommended / loan_amount_inr)

    reasoning_bits: list[str] = []
    if business_type:
        reasoning_bits.append(f"Classified as **{business_type}**.")
    if is_service:
        reasoning_bits.append(
            f"Visible collateral = stock ₹{stock:,} + equipment ₹{equipment:,} "
            f"= ₹{visible_collateral:,}. Service biz collateral floor is "
            f"{int(floor_pct_critical * 100)}% of the loan."
        )
    else:
        reasoning_bits.append(
            f"Visible stock ≈ ₹{visible_collateral:,}. Non-service biz "
            f"critical floor is {int(floor_pct_critical * 100)}% of the loan; "
            f"warning tier is {int((floor_pct_warning or 1) * 100)}%."
        )
    if coverage_pct is not None:
        reasoning_bits.append(f"Coverage ratio: {coverage_pct:.0%}.")
    if recommended is not None and loan_amount_inr:
        if recommended < loan_amount_inr:
            reasoning_bits.append(
                f"Scorer recommends reducing to ₹{recommended:,} "
                f"(cut of {cut_pct:.0%})."
            )
        else:
            reasoning_bits.append(
                f"Scorer endorses the proposed ₹{loan_amount_inr:,}."
            )

    return {
        "business_type": business_type,
        "business_subtype": biz_data.get("business_subtype"),
        "loan_amount_inr": loan_amount_inr,
        "stock_value_estimate_inr": stock or None,
        "visible_equipment_value_inr": equipment or None,
        "visible_collateral_inr": visible_collateral or None,
        "cattle_count": biz_data.get("cattle_count"),
        "cattle_health": biz_data.get("cattle_health"),
        "stock_condition": biz_data.get("stock_condition"),
        "stock_variety": biz_data.get("stock_variety"),
        "coverage_pct": coverage_pct,
        "floor_pct_critical": floor_pct_critical,
        "floor_pct_warning": floor_pct_warning,
        "recommended_loan_amount_inr": recommended,
        "recommended_loan_rationale": biz_data.get("recommended_loan_rationale"),
        "cut_pct": cut_pct,
        "reasoning": " ".join(reasoning_bits) if reasoning_bits else "",
    }
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestBuildStockAnalysis -xvs --no-cov 2>&1 | tail -15
```

Expected: **PASS** on all 5 tests. If any test fails for a missing/mismatched key, double-check `EXPECTED_KEYS` vs the returned dict (the "17 keys" list in the test includes 4 keys beyond the 13 visible in the spec table — `business_subtype`, `stock_condition`, `stock_variety`, `cattle_count`, `cattle_health` — verify all are emitted).

- [ ] **Step 2.5: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/app/verification/levels/level_3_vision.py backend/tests/unit/test_verification_level_3_vision.py
git commit -m "$(cat <<'EOF'
feat(l3-vision): build_stock_analysis pure helper for the new header panel

Pure function that packages the business scorer's output + the case
loan amount into the sub_step_results.stock_analysis dict the L3
frontend header will render. Derives:

  - visible_collateral_inr (stock + equipment for service, stock only
    otherwise)
  - coverage_pct, cut_pct against the proposed loan
  - floor_pct_critical / floor_pct_warning sourced from the existing
    _SERVICE_COLLATERAL_FLOOR_PCT / _STOCK_CRITICAL_PCT constants so
    magic numbers stay out of the emitted shape
  - a one-paragraph reasoning string covering classification, visible
    collateral, coverage, and the scorer's loan recommendation

Schema-drift guard: a test asserts all documented keys are in the
returned dict — renames / removals in the scorer will fail loudly
rather than silently zeroing out the FE.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `build_visual_evidence` pure helper

**Files:**
- Modify: `backend/app/verification/levels/level_3_vision.py`
- Test: `backend/tests/unit/test_verification_level_3_vision.py`

- [ ] **Step 3.1: Write failing tests**

Add to `tests/unit/test_verification_level_3_vision.py`:

```python
class TestBuildVisualEvidence:
    """build_visual_evidence returns a dict with artifact-id lists the
    frontend uses to filter the useCasePhotos hook output. Counts
    (photos_evaluated) are the lengths of the image bytes lists fed
    to the scorers — distinct from the uploaded artifact counts,
    since the scorer may skip an artifact that failed to download."""

    def _mk_artifact(self, aid: str, subtype: str, filename: str):
        """Build a minimal CaseArtifact-shaped object for the test."""
        class _A:
            id = aid
            metadata_json = {"subtype": subtype}
        _A.filename = filename
        return _A

    def test_empty_lists(self) -> None:
        from app.verification.levels.level_3_vision import build_visual_evidence
        out = build_visual_evidence(
            house_arts=[],
            biz_arts=[],
            house_imgs_count=0,
            biz_imgs_count=0,
        )
        assert out == {
            "house_photos": [],
            "business_photos": [],
            "house_photos_evaluated": 0,
            "business_photos_evaluated": 0,
        }

    def test_full_lists(self) -> None:
        from app.verification.levels.level_3_vision import build_visual_evidence
        house = [
            self._mk_artifact("h1", "HOUSE_VISIT_PHOTO", "house1.jpg"),
            self._mk_artifact("h2", "HOUSE_VISIT_PHOTO", "house2.jpg"),
        ]
        biz = [
            self._mk_artifact("b1", "BUSINESS_PREMISES_PHOTO", "biz1.jpg"),
            self._mk_artifact("b2", "BUSINESS_PREMISES_PHOTO", "biz2.jpg"),
            self._mk_artifact("b3", "BUSINESS_PREMISES_PHOTO", "biz3.jpg"),
        ]
        out = build_visual_evidence(
            house_arts=house,
            biz_arts=biz,
            house_imgs_count=2,
            biz_imgs_count=3,
        )
        assert out["house_photos_evaluated"] == 2
        assert out["business_photos_evaluated"] == 3
        assert [p["artifact_id"] for p in out["house_photos"]] == ["h1", "h2"]
        assert [p["artifact_id"] for p in out["business_photos"]] == ["b1", "b2", "b3"]
        assert out["business_photos"][0]["filename"] == "biz1.jpg"
        assert out["business_photos"][0]["subtype"] == "BUSINESS_PREMISES_PHOTO"

    def test_uploaded_exceeds_evaluated(self) -> None:
        """If the scorer dropped an artifact (fetch failure), evaluated
        count can be < uploaded count. Both surface in the dict."""
        from app.verification.levels.level_3_vision import build_visual_evidence
        biz = [
            self._mk_artifact("b1", "BUSINESS_PREMISES_PHOTO", "biz1.jpg"),
            self._mk_artifact("b2", "BUSINESS_PREMISES_PHOTO", "biz2.jpg"),
            self._mk_artifact("b3", "BUSINESS_PREMISES_PHOTO", "biz3.jpg"),
        ]
        out = build_visual_evidence(
            house_arts=[], biz_arts=biz,
            house_imgs_count=0, biz_imgs_count=2,  # one dropped
        )
        assert len(out["business_photos"]) == 3
        assert out["business_photos_evaluated"] == 2
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestBuildVisualEvidence -xvs --no-cov 2>&1 | tail -20
```

Expected: **FAIL** — `ImportError: cannot import name 'build_visual_evidence'`.

- [ ] **Step 3.3: Implement `build_visual_evidence`**

In `backend/app/verification/levels/level_3_vision.py`, add after `build_stock_analysis`:

```python
def build_visual_evidence(
    *,
    house_arts: list[CaseArtifact],
    biz_arts: list[CaseArtifact],
    house_imgs_count: int,
    biz_imgs_count: int,
) -> dict[str, Any]:
    """Return the sub_step_results.visual_evidence dict: per-category
    artifact-id lists + the count the scorer actually evaluated
    (distinct from uploaded, since storage fetches can fail).

    Artifact IDs alone — no download URLs. The FE resolves URLs via
    useCasePhotos(caseId) and filters to this list. See spec §4.2.
    """
    def _pack(a: CaseArtifact, subtype: str) -> dict[str, Any]:
        return {
            "artifact_id": str(a.id),
            "filename": a.filename,
            "subtype": subtype,
        }

    return {
        "house_photos": [
            _pack(a, ArtifactSubtype.HOUSE_VISIT_PHOTO.value)
            for a in house_arts
        ],
        "business_photos": [
            _pack(a, ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value)
            for a in biz_arts
        ],
        "house_photos_evaluated": house_imgs_count,
        "business_photos_evaluated": biz_imgs_count,
    }
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestBuildVisualEvidence -xvs --no-cov 2>&1 | tail -10
```

Expected: **PASS** on all 3 tests.

- [ ] **Step 3.5: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/app/verification/levels/level_3_vision.py backend/tests/unit/test_verification_level_3_vision.py
git commit -m "$(cat <<'EOF'
feat(l3-vision): build_visual_evidence pure helper for the photos gallery

Returns the sub_step_results.visual_evidence dict: house_photos +
business_photos lists (each entry = {artifact_id, filename, subtype})
plus house_photos_evaluated / business_photos_evaluated counts. The
frontend's L3 header panel uses the artifact-id lists to filter the
existing useCasePhotos hook — no second fetch path.

Evaluated counts are the lengths of the image-bytes lists actually
fed to the scorers, which can be less than the uploaded artifact
count when a storage fetch fails. Both surface so the MD can spot a
"1 uploaded, 0 evaluated" case.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `build_pass_evidence` pure helper

**Files:**
- Modify: `backend/app/verification/levels/level_3_vision.py`
- Test: `backend/tests/unit/test_verification_level_3_vision.py`

- [ ] **Step 4.1: Write failing tests**

```python
class TestBuildPassEvidence:
    """build_pass_evidence returns a dict keyed by sub_step_id, with
    each entry populated only when the rule passed (or skipped via
    N/A). Failing rules are excluded — the FE reads LevelIssue.evidence
    for those. See spec §4.1.a."""

    def test_passing_service_biz_all_entries(self) -> None:
        from app.verification.levels.level_3_vision import build_pass_evidence
        house_data = {
            "overall_rating": "ok",
            "space_rating": "good",
            "upkeep_rating": "ok",
            "construction_type": "pakka",
            "positives": ["courtyard spacious", "walls painted"],
            "concerns": [],
        }
        biz_data = {
            "business_type": "service",
            "business_subtype": "barbershop",
            "stock_value_estimate_inr": 5_000,
            "visible_equipment_value_inr": 45_000,
            "cattle_count": 0,
            "cattle_health": "not_applicable",
            "infrastructure_rating": "good",
            "infrastructure_details": ["solid shelter", "water access"],
            "recommended_loan_amount_inr": 50_000,
            "recommended_loan_rationale": "covers equipment",
        }
        fired_rules = set()  # everything passed
        out = build_pass_evidence(
            house_data=house_data,
            biz_data=biz_data,
            loan_amount_inr=50_000,
            house_photos_evaluated=5,
            business_photos_evaluated=5,
            fired_rules=fired_rules,
        )
        assert "house_living_condition" in out
        assert out["house_living_condition"]["overall_rating"] == "ok"
        assert out["house_living_condition"]["photos_evaluated_count"] == 5
        assert "business_infrastructure" in out
        assert out["business_infrastructure"]["infrastructure_rating"] == "good"
        assert "stock_vs_loan" in out
        assert out["stock_vs_loan"]["business_type"] == "service"
        assert out["stock_vs_loan"]["visible_collateral_inr"] == 50_000
        assert "loan_amount_recommendation" in out
        assert out["loan_amount_recommendation"]["cut_pct"] == 0.0
        assert "cattle_health" in out
        assert out["cattle_health"]["skipped_reason"].startswith("not a dairy business")

    def test_failing_stock_rule_absent(self) -> None:
        """When stock_vs_loan fired as a CRITICAL issue, it must not
        appear in pass_evidence. Other rules that passed still show."""
        from app.verification.levels.level_3_vision import build_pass_evidence
        biz_data = {
            "business_type": "product_trading",
            "stock_value_estimate_inr": 20_000,  # vs 100k loan
            "recommended_loan_amount_inr": 20_000,
            "infrastructure_rating": "good",
        }
        out = build_pass_evidence(
            house_data={"overall_rating": "ok"},
            biz_data=biz_data,
            loan_amount_inr=100_000,
            house_photos_evaluated=3,
            business_photos_evaluated=3,
            fired_rules={"stock_vs_loan", "loan_amount_reduction"},
        )
        assert "stock_vs_loan" not in out
        assert "loan_amount_recommendation" not in out
        assert "business_infrastructure" in out
        assert "house_living_condition" in out

    def test_cattle_dairy_passing_fills_real_entry_not_skipped(self) -> None:
        from app.verification.levels.level_3_vision import build_pass_evidence
        biz_data = {
            "business_type": "cattle_dairy",
            "cattle_count": 4,
            "cattle_health": "healthy",
            "stock_value_estimate_inr": 240_000,
            "recommended_loan_amount_inr": 200_000,
            "infrastructure_rating": "good",
        }
        out = build_pass_evidence(
            house_data={"overall_rating": "ok"},
            biz_data=biz_data,
            loan_amount_inr=200_000,
            house_photos_evaluated=4,
            business_photos_evaluated=6,
            fired_rules=set(),
        )
        assert "cattle_health" in out
        assert "skipped_reason" not in out["cattle_health"]
        assert out["cattle_health"]["business_type"] == "cattle_dairy"
        assert out["cattle_health"]["cattle_count"] == 4
        assert out["cattle_health"]["cattle_health"] == "healthy"

    def test_scorer_failed_empty_biz_data(self) -> None:
        """biz_data empty → no business-driven entries. House entry still
        produced if house_data is present."""
        from app.verification.levels.level_3_vision import build_pass_evidence
        out = build_pass_evidence(
            house_data={"overall_rating": "ok"},
            biz_data={},
            loan_amount_inr=50_000,
            house_photos_evaluated=2,
            business_photos_evaluated=0,
            fired_rules=set(),
        )
        assert "house_living_condition" in out
        assert "stock_vs_loan" not in out
        assert "business_infrastructure" not in out
        assert "cattle_health" not in out
        assert "loan_amount_recommendation" not in out
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestBuildPassEvidence -xvs --no-cov 2>&1 | tail -15
```

Expected: **FAIL** — `ImportError: cannot import name 'build_pass_evidence'`.

- [ ] **Step 4.3: Implement `build_pass_evidence`**

In `backend/app/verification/levels/level_3_vision.py`, add after `build_visual_evidence`:

```python
def build_pass_evidence(
    *,
    house_data: dict[str, Any] | None,
    biz_data: dict[str, Any] | None,
    loan_amount_inr: int | None,
    house_photos_evaluated: int,
    business_photos_evaluated: int,
    fired_rules: set[str],
) -> dict[str, Any]:
    """Return the sub_step_results.pass_evidence dict — keyed by
    sub_step_id, one entry per L3 rule that PASSED or was skipped
    (N/A). Rules in ``fired_rules`` are omitted; the FE reads their
    evidence off LevelIssue.evidence for fails.

    Only L3 rules are populated here. Part B will add entries for
    other levels directly in their orchestrators.
    """
    out: dict[str, Any] = {}

    # House living condition — from house scorer data
    if house_data and "house_living_condition" not in fired_rules:
        out["house_living_condition"] = {
            "overall_rating": house_data.get("overall_rating"),
            "space_rating": house_data.get("space_rating"),
            "upkeep_rating": house_data.get("upkeep_rating"),
            "construction_type": house_data.get("construction_type"),
            "positives": house_data.get("positives") or [],
            "concerns": house_data.get("concerns") or [],
            "photos_evaluated_count": house_photos_evaluated,
        }

    # Business-scorer-driven rules — all need biz_data to be non-empty
    if not biz_data:
        return out

    if "business_infrastructure" not in fired_rules:
        out["business_infrastructure"] = {
            "infrastructure_rating": biz_data.get("infrastructure_rating"),
            "infrastructure_details": biz_data.get("infrastructure_details") or [],
            "equipment_visible": bool(biz_data.get("visible_equipment_value_inr")),
            "photos_evaluated_count": business_photos_evaluated,
        }

    if "stock_vs_loan" not in fired_rules:
        analysis = build_stock_analysis(biz_data, loan_amount_inr=loan_amount_inr)
        if analysis:
            out["stock_vs_loan"] = {
                **analysis,
                "photos_evaluated_count": business_photos_evaluated,
            }

    if "loan_amount_reduction" not in fired_rules:
        out["loan_amount_recommendation"] = {
            "loan_amount_inr": loan_amount_inr,
            "recommended_loan_amount_inr": biz_data.get("recommended_loan_amount_inr"),
            "cut_pct": (
                max(0.0, 1 - biz_data["recommended_loan_amount_inr"] / loan_amount_inr)
                if biz_data.get("recommended_loan_amount_inr") and loan_amount_inr
                else None
            ),
            "trigger_pct": _LOAN_REDUCTION_TRIGGER_PCT,
            "rationale": biz_data.get("recommended_loan_rationale"),
            "photos_evaluated_count": business_photos_evaluated,
        }

    if "cattle_health" not in fired_rules:
        biz_type = biz_data.get("business_type")
        if biz_type in ("cattle_dairy", "mixed") and (biz_data.get("cattle_count") or 0) > 0:
            out["cattle_health"] = {
                "business_type": biz_type,
                "cattle_count": biz_data.get("cattle_count"),
                "cattle_health": biz_data.get("cattle_health"),
            }
        else:
            out["cattle_health"] = {
                "skipped_reason": (
                    f"not a dairy business (classified: {biz_type or 'unknown'})"
                ),
            }

    return out
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestBuildPassEvidence -xvs --no-cov 2>&1 | tail -15
```

Expected: **PASS** on all 4 tests.

- [ ] **Step 4.5: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/app/verification/levels/level_3_vision.py backend/tests/unit/test_verification_level_3_vision.py
git commit -m "$(cat <<'EOF'
feat(l3-vision): build_pass_evidence for click-to-expand on passing rules

Pass-evidence for L3's scorer-driven rules. Returns a dict keyed by
sub_step_id; each entry populated only when the rule passed or was
skipped with N/A. Failing rules are excluded so the FE reads
LevelIssue.evidence for those.

L3 entries surfaced:
  - house_living_condition → rating grid + positives/concerns
  - business_infrastructure → rating + details + equipment_visible
  - stock_vs_loan → full stock_analysis shape (13 keys) for the
    side-by-side "stock vs loan" expand card
  - loan_amount_recommendation → proposed vs recommended with cut_pct
  - cattle_health → real entry on dairy biz; {skipped_reason} on
    non-dairy so the FE can say "not a dairy business (classified:
    service)" instead of rendering a blank card

Other levels' pass_evidence is populated later in Part B.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Orchestrator — refactor `cross_check_stock_vs_loan` to use `build_stock_analysis`

**Files:**
- Modify: `backend/app/verification/levels/level_3_vision.py:83-166`
- Test: `backend/tests/unit/test_verification_level_3_vision.py` (existing tests)

- [ ] **Step 5.1: Read the existing `cross_check_stock_vs_loan` implementation**

Run:
```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
```

Read `backend/app/verification/levels/level_3_vision.py` lines 83-166 with the Read tool.

- [ ] **Step 5.2: Confirm existing tests cover the current behaviour**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py -k "stock_vs_loan" --no-cov -q 2>&1 | tail -10
```

Note the existing test names — the refactor must keep them green.

- [ ] **Step 5.3: Refactor the function to delegate number-crunching to the helper**

Replace the body of `cross_check_stock_vs_loan` so the collateral / coverage / floor math flows through `build_stock_analysis`, but the issue description + severity selection stays inside the cross-check (description is human-facing and mixes values + narrative).

Concretely: compute `analysis = build_stock_analysis({...biz fields from the kwargs...}, loan_amount_inr=loan_amount_inr)`, then read `analysis["visible_collateral_inr"]`, `analysis["coverage_pct"]`, `analysis["floor_pct_critical"]`, `analysis["floor_pct_warning"]` for the if-branches instead of recomputing.

Keep the description strings and severity branching identical to the current behaviour — no user-visible change, only DRY.

- [ ] **Step 5.4: Run the existing stock_vs_loan tests**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py -k "stock_vs_loan" --no-cov -q 2>&1 | tail -10
```

Expected: all existing tests still pass. If any fail, the refactor changed behaviour — revert and narrow the scope.

- [ ] **Step 5.5: Run the full L3 suite**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py --no-cov -q 2>&1 | tail -6
```

Expected: all green.

- [ ] **Step 5.6: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/app/verification/levels/level_3_vision.py
git commit -m "$(cat <<'EOF'
refactor(l3-vision): route cross_check_stock_vs_loan through build_stock_analysis

The cross-check was duplicating the collateral-vs-loan math
(visible_collateral, coverage, floor) that build_stock_analysis
already produces. Delegate the number-crunching to the helper; keep
only the issue description + severity branching inside the cross-
check. Makes it impossible for the cross-check's numbers to drift
from the pass-evidence numbers the FE renders above it.

No behavioural change — the same six test cases cover both paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Orchestrator — wire visual_evidence + stock_analysis + pass_evidence

**Files:**
- Modify: `backend/app/verification/levels/level_3_vision.py:410-417`
- Test: `backend/tests/unit/test_verification_level_3_vision.py`

- [ ] **Step 6.1: Write an integration-style test that asserts the new keys are in sub_step_results**

Add to `tests/unit/test_verification_level_3_vision.py` (or reuse an existing `TestRunLevel3Vision`-style class if it exists):

```python
class TestRunLevel3VisionSubStepResults:
    """Smoke tests that the L3 orchestrator populates the new
    sub_step_results keys consumed by the frontend header panel."""

    @pytest.mark.asyncio
    async def test_sub_step_results_has_visual_evidence_and_stock_analysis(
        self, db_session, seeded_case_and_artifacts, mock_claude_vision_scorers
    ):
        # Use the existing test fixtures (mirror whatever setup
        # existing L3 tests use — there's likely a fixture that
        # creates a case, uploads photos, and stubs the scorer).
        from uuid import uuid4
        from app.verification.levels.level_3_vision import run_level_3_vision

        result = await run_level_3_vision(
            db_session,
            seeded_case_and_artifacts.id,
            actor_user_id=uuid4(),
            claude=mock_claude_vision_scorers,
            storage=... ,  # existing fixture
        )
        assert "visual_evidence" in result.sub_step_results
        ve = result.sub_step_results["visual_evidence"]
        assert set(ve.keys()) == {
            "house_photos", "business_photos",
            "house_photos_evaluated", "business_photos_evaluated",
        }

        assert "stock_analysis" in result.sub_step_results
        assert "pass_evidence" in result.sub_step_results
```

If the existing test module doesn't have `mock_claude_vision_scorers` / `seeded_case_and_artifacts` fixtures, **read the existing test module first** and adapt the test to the patterns already in use there — do not invent fixtures that don't exist.

- [ ] **Step 6.2: Run the test to confirm it fails**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestRunLevel3VisionSubStepResults -xvs --no-cov 2>&1 | tail -15
```

Expected: **FAIL** — `KeyError: 'visual_evidence'` or similar.

- [ ] **Step 6.3: Wire into the orchestrator**

In `backend/app/verification/levels/level_3_vision.py`, locate the `result.sub_step_results = {...}` block (around line 410) and extend it:

```python
fired_sub_step_ids = {i["sub_step_id"] for i in issues}
result.sub_step_results = {
    "house": {k: v for k, v in house_data.items() if k != "usage"},
    "business": {k: v for k, v in biz_data.items() if k != "usage"},
    "house_photo_count": len(house_imgs),
    "business_photo_count": len(biz_imgs),
    "issue_count": len(issues),
    "suppressed_rules": suppressed_rules,
    # NEW
    "visual_evidence": build_visual_evidence(
        house_arts=house_arts,
        biz_arts=biz_arts,
        house_imgs_count=len(house_imgs),
        biz_imgs_count=len(biz_imgs),
    ),
    "stock_analysis": build_stock_analysis(
        biz_data,
        loan_amount_inr=int(loan_amount) if loan_amount else None,
    ),
    "pass_evidence": build_pass_evidence(
        house_data=house_data,
        biz_data=biz_data,
        loan_amount_inr=int(loan_amount) if loan_amount else None,
        house_photos_evaluated=len(house_imgs),
        business_photos_evaluated=len(biz_imgs),
        fired_rules=fired_sub_step_ids,
    ),
}
```

Also, on every scorer-driven issue append (house_living_condition, stock_vs_loan, business_infrastructure, cattle_health, loan_amount_reduction), merge `photos_evaluated_count` into `iss["evidence"]`. Around lines 327-337 and 378-387:

```python
# After: iss["evidence"] = {k: v for k, v in h.data.items() if k != "usage"}
iss["evidence"]["photos_evaluated_count"] = len(house_imgs)
# or for biz-driven issues
iss["evidence"]["photos_evaluated_count"] = len(biz_imgs)
```

- [ ] **Step 6.4: Run the new test**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit/test_verification_level_3_vision.py::TestRunLevel3VisionSubStepResults -xvs --no-cov 2>&1 | tail -10
```

Expected: **PASS**.

- [ ] **Step 6.5: Run the full baseline**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q 2>&1 | tail -6
```

Expected: ~615 passed (or existing baseline + however many new tests this plan added).

- [ ] **Step 6.6: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add backend/app/verification/levels/level_3_vision.py backend/tests/unit/test_verification_level_3_vision.py
git commit -m "$(cat <<'EOF'
feat(l3-vision): emit visual_evidence + stock_analysis + pass_evidence on every run

Wire the three new pure helpers into the L3 orchestrator's
sub_step_results. Adds three top-level keys:

  - visual_evidence: per-category artifact IDs + evaluated counts
    (frontend filters the useCasePhotos hook output to this subset
    and displays the evaluated count on the header gallery).
  - stock_analysis: loan vs visible collateral, coverage, recommended
    loan, reasoning — 13 keys total, always present when the
    business scorer produced data.
  - pass_evidence: click-to-expand detail for L3's 5 scorer-driven
    rules; omits entries for rules that fired so the FE reads those
    off LevelIssue.evidence.

Also attaches photos_evaluated_count to every scorer-driven issue's
evidence so the per-concern "What was checked" panel can show the
multi-angle count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Backend deploy + live-case sanity check

- [ ] **Step 7.1: Restart the backend container**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system" && docker restart pfl-backend && sleep 10
```

- [ ] **Step 7.2: Verify new code is in the container**

```bash
docker exec pfl-backend grep -c "build_pass_evidence\|build_visual_evidence\|build_stock_analysis" /app/app/verification/levels/level_3_vision.py
```

Expected: ≥ 8 (three function definitions + one orchestrator call-site each for build_visual_evidence / build_stock_analysis / build_pass_evidence + internal call from cross_check_stock_vs_loan + internal call from build_pass_evidence → build_stock_analysis). If the count is lower, one of the earlier tasks' edits didn't land — `git diff HEAD~7..HEAD level_3_vision.py` and re-inspect.

- [ ] **Step 7.3: Re-run L3 for Ajay's case**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"saksham@pflfinance.com","password":"Saksham123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/trigger/L3_VISION" \
  | python3 -m json.tool | head -30
```

- [ ] **Step 7.4: Inspect the new sub_step_results shape**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L3_VISION" \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
ssr = d.get('sub_step_results') or {}
for key in ('visual_evidence', 'stock_analysis', 'pass_evidence'):
    print(f'=== {key} ===')
    print(json.dumps(ssr.get(key), indent=2)[:800])
"
```

Expected: all three keys present, `visual_evidence` has artifact IDs for Ajay's photos, `stock_analysis` has real numbers, `pass_evidence` has entries for whichever L3 rules passed.

- [ ] **Step 7.5: Verify cattle_health is silenced on Ajay**

Ajay's business type is `service` (barbershop-equivalent). Before the guard, cattle_health was firing falsely. After: the issues list should not contain `cattle_health`.

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/cases/7bdea924-225e-4b70-9c46-2d2387fc884c/verification/L3_VISION" \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
ids = [i['sub_step_id'] for i in d.get('issues') or []]
print('fired:', ids)
assert 'cattle_health' not in ids, 'cattle_health fired on non-dairy biz!'
print('cattle_health silenced ✓')
"
```

If cattle_health still fires: Ajay's business_type in scorer output may be set to something other than `service`. Inspect `sub_step_results.business.business_type` to diagnose; the guard logic itself is covered by unit tests.

---

## Phase 2 — Frontend

### Task 8: Types — extend sub_step_results shape

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 8.1: Find the L3-specific sub_step_results type**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
```

Search the types file with Grep for `L3_VISION` or the existing `sub_step_results` declaration.

- [ ] **Step 8.2: Add the three new shapes**

Add to `frontend/src/lib/types.ts`:

```typescript
// L3 visual-evidence additions (Part A).
export type L3VisualEvidencePhoto = {
  artifact_id: string
  filename: string
  subtype: string
}

export type L3VisualEvidence = {
  house_photos: L3VisualEvidencePhoto[]
  business_photos: L3VisualEvidencePhoto[]
  house_photos_evaluated: number
  business_photos_evaluated: number
}

export type L3StockAnalysis = {
  business_type: string | null
  business_subtype: string | null
  loan_amount_inr: number | null
  stock_value_estimate_inr: number | null
  visible_equipment_value_inr: number | null
  visible_collateral_inr: number | null
  cattle_count: number | null
  cattle_health: string | null
  stock_condition: string | null
  stock_variety: string | null
  coverage_pct: number | null
  floor_pct_critical: number | null
  floor_pct_warning: number | null
  recommended_loan_amount_inr: number | null
  recommended_loan_rationale: string | null
  cut_pct: number | null
  reasoning: string
}

// pass_evidence is keyed by sub_step_id; values are loosely typed
// because each rule's shape differs. The L3 pass cards narrow on
// sub_step_id at render time. Other levels will add keys in Part B.
export type L3PassEvidence = Record<string, Record<string, unknown>>
```

If the existing `sub_step_results` type on L3 is a `Record<string, unknown>`, leave it alone — the new types above are used by the components directly via a typed narrowing. If there's a specific L3 `sub_step_results` interface, extend it with `visual_evidence?`, `stock_analysis?`, `pass_evidence?`.

- [ ] **Step 8.3: Type-check frontend**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/frontend" && npx tsc --noEmit 2>&1 | tail -10
```

Expected: 0 errors. If errors surface in files that depend on `types.ts`, they were likely relying on loose typing that this change tightened — adjust those call-sites.

- [ ] **Step 8.4: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add frontend/src/lib/types.ts
git commit -m "feat(types): L3VisualEvidence / L3StockAnalysis / L3PassEvidence shapes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `frontend/src/components/cases/l3/helpers.ts`

**Files:**
- Create: `frontend/src/components/cases/l3/helpers.ts`

- [ ] **Step 9.1: Create the helpers file**

Create `frontend/src/components/cases/l3/helpers.ts`:

```typescript
// Shared formatters and colour-grade helpers for the L3 panel components.
// Lives next to the components so the number formatting stays consistent
// between the header card and the click-to-expand pass cards.

export function formatInr(n: number | null | undefined): string {
  if (n == null) return '—'
  return `₹${n.toLocaleString('en-IN')}`
}

export function formatPct(n: number | null | undefined, digits = 0): string {
  if (n == null) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

export type CoverageTone = 'emerald' | 'amber' | 'red'

/** Emerald / amber / red based on coverage vs floor thresholds.
 *  Service biz has a single critical floor (no warning tier);
 *  non-service has two tiers. */
export function coverageTone(
  coveragePct: number | null | undefined,
  floorCritical: number | null | undefined,
  floorWarning: number | null | undefined,
): CoverageTone {
  if (coveragePct == null || floorCritical == null) return 'amber'
  if (floorWarning != null) {
    // Two-tier (non-service)
    if (coveragePct >= floorWarning) return 'emerald'
    if (coveragePct >= floorCritical) return 'amber'
    return 'red'
  }
  // Single-tier (service)
  return coveragePct >= floorCritical ? 'emerald' : 'red'
}

export const TONE_PILL_CLASSES: Record<CoverageTone, string> = {
  emerald:
    'bg-emerald-50 text-emerald-800 border-emerald-300',
  amber: 'bg-amber-50 text-amber-800 border-amber-300',
  red: 'bg-red-50 text-red-800 border-red-300',
}
```

- [ ] **Step 9.2: Type-check**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/frontend" && npx tsc --noEmit 2>&1 | tail -5
```

Expected: 0 errors.

- [ ] **Step 9.3: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add frontend/src/components/cases/l3/helpers.ts
git commit -m "feat(l3-fe): shared helpers for INR/pct formatting + coverage tone

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `L3StockAnalysisCard` — header-level card

**Files:**
- Create: `frontend/src/components/cases/l3/L3StockAnalysisCard.tsx`

- [ ] **Step 10.1: Create the component**

Create `frontend/src/components/cases/l3/L3StockAnalysisCard.tsx`:

```tsx
'use client'

import { L3StockAnalysis } from '@/lib/types'
import { cn } from '@/lib/utils'
import {
  formatInr,
  formatPct,
  coverageTone,
  TONE_PILL_CLASSES,
} from './helpers'

/** Always-visible L3 header card.
 *  Renders the stock_analysis dict from sub_step_results. When the
 *  business scorer errored (analysis === null), shows a muted fallback
 *  with a pointer to the scorer-failure concern. */
export function L3StockAnalysisCard({
  analysis,
}: {
  analysis: L3StockAnalysis | null | undefined
}) {
  if (!analysis) {
    return (
      <div className="border border-pfl-slate-200 rounded-md bg-white p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
          Stock analysis
        </div>
        <div className="text-[12.5px] text-pfl-slate-600">
          Unavailable — the business-premises scorer failed. See the{' '}
          <span className="font-mono text-[11.5px] text-pfl-slate-800">
            business_scorer_failed
          </span>{' '}
          concern below.
        </div>
      </div>
    )
  }

  const tone = coverageTone(
    analysis.coverage_pct,
    analysis.floor_pct_critical,
    analysis.floor_pct_warning,
  )
  const isService = analysis.business_type === 'service'

  return (
    <div className="border border-pfl-slate-200 rounded-md bg-white p-3 flex flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
          Stock analysis
        </span>
        <span className="text-[11px] text-pfl-slate-500">·</span>
        <span className="text-[12px] font-medium text-pfl-slate-800">
          {analysis.business_type ?? 'unknown'}
          {analysis.business_subtype ? ` · ${analysis.business_subtype}` : ''}
        </span>
        <span
          className={cn(
            'ml-auto inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide',
            TONE_PILL_CLASSES[tone],
          )}
          title="Visible collateral coverage vs the loan amount"
        >
          coverage {formatPct(analysis.coverage_pct)}
        </span>
      </div>

      <div className="grid grid-cols-[max-content,1fr] gap-x-4 gap-y-1 text-[12.5px]">
        <span className="text-pfl-slate-500">Loan amount</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(analysis.loan_amount_inr)}
        </span>

        <span className="text-pfl-slate-500">Visible collateral</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(analysis.visible_collateral_inr)}
        </span>

        {isService && analysis.visible_equipment_value_inr != null && (
          <>
            <span className="pl-3 text-pfl-slate-500 text-[11.5px]">
              · stock
            </span>
            <span className="text-pfl-slate-700 text-[11.5px]">
              {formatInr(analysis.stock_value_estimate_inr)}
            </span>
            <span className="pl-3 text-pfl-slate-500 text-[11.5px]">
              · equipment
            </span>
            <span className="text-pfl-slate-700 text-[11.5px]">
              {formatInr(analysis.visible_equipment_value_inr)}
            </span>
          </>
        )}

        <span className="text-pfl-slate-500">Floor</span>
        <span className="text-pfl-slate-800">
          {formatPct(analysis.floor_pct_critical)} critical
          {analysis.floor_pct_warning != null
            ? ` · ${formatPct(analysis.floor_pct_warning)} warning`
            : ''}
        </span>

        <span className="text-pfl-slate-500">Recommended loan</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(analysis.recommended_loan_amount_inr)}
          {analysis.cut_pct != null && analysis.cut_pct > 0 && (
            <span className="ml-2 text-red-700 text-[11.5px] font-normal">
              ({formatPct(analysis.cut_pct)} cut)
            </span>
          )}
        </span>
      </div>

      {analysis.reasoning && (
        <p className="text-[12px] text-pfl-slate-700 whitespace-pre-wrap leading-relaxed">
          {analysis.reasoning}
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 10.2: Type-check**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/frontend" && npx tsc --noEmit 2>&1 | tail -5
```

Expected: 0 errors. If `cn` isn't available at that import path, find the existing helper (grep `export function cn` or similar).

- [ ] **Step 10.3: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add frontend/src/components/cases/l3/L3StockAnalysisCard.tsx
git commit -m "feat(l3-fe): L3StockAnalysisCard header component

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: `L3PhotoGallery` — header-level gallery

**Files:**
- Create: `frontend/src/components/cases/l3/L3PhotoGallery.tsx`

- [ ] **Step 11.1: (informational) Real `useCasePhotos` hook signature**

The hook lives at `frontend/src/lib/useVerification.ts:61` and has the signature:

```ts
export function useCasePhotos(
  caseId: string,
  subtype: 'HOUSE_VISIT_PHOTO' | 'BUSINESS_PREMISES_PHOTO',
  enabled = true,
): { data: CasePhotosResponse | undefined, error, isLoading }
```

`data.items` is an array of `{ artifact_id, download_url, filename, subtype }` (and possibly more — inspect `CasePhotosResponse` for the full shape). The existing L3 photo gallery in `VerificationPanel.tsx:2327-2336` makes **two** calls — one per subtype — and that pattern is what the new gallery replicates.

- [ ] **Step 11.2: Create the component**

Create `frontend/src/components/cases/l3/L3PhotoGallery.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { L3VisualEvidence } from '@/lib/types'
import { useCasePhotos } from '@/lib/useVerification'

/** Always-visible photo gallery next to the stock-analysis card.
 *  Filters the existing useCasePhotos hook's output down to the
 *  artifact IDs the L3 scorer actually processed. Shows a low-count
 *  warning when fewer than 2 were evaluated in either category. */
export function L3PhotoGallery({
  caseId,
  visualEvidence,
}: {
  caseId: string
  visualEvidence: L3VisualEvidence | null | undefined
}) {
  // Always call the hooks — React rules-of-hooks. The `enabled` flag
  // is left true so the gallery stays live even if visualEvidence is
  // briefly null during a refetch; the filter below still produces
  // empty arrays so nothing renders until data arrives.
  const { data: housePhotos } = useCasePhotos(caseId, 'HOUSE_VISIT_PHOTO', true)
  const { data: businessPhotos } = useCasePhotos(
    caseId,
    'BUSINESS_PREMISES_PHOTO',
    true,
  )
  const [lightbox, setLightbox] = useState<null | {
    src: string
    filename: string
  }>(null)

  if (!visualEvidence) {
    return (
      <div className="border border-pfl-slate-200 rounded-md bg-white p-3 text-[12px] text-pfl-slate-500">
        Photo gallery unavailable.
      </div>
    )
  }

  const houseIds = new Set(
    visualEvidence.house_photos.map((p) => p.artifact_id),
  )
  const bizIds = new Set(
    visualEvidence.business_photos.map((p) => p.artifact_id),
  )
  const house = (housePhotos?.items ?? []).filter((p) =>
    houseIds.has(p.artifact_id),
  )
  const biz = (businessPhotos?.items ?? []).filter((p) =>
    bizIds.has(p.artifact_id),
  )

  const lowHouse =
    visualEvidence.house_photos.length > 0 &&
    visualEvidence.house_photos_evaluated < 2
  const lowBiz =
    visualEvidence.business_photos.length > 0 &&
    visualEvidence.business_photos_evaluated < 2

  return (
    <>
      <div className="border border-pfl-slate-200 rounded-md bg-white p-3 flex flex-col gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
          Photos
        </div>

        <Section
          title="House visit"
          evaluated={visualEvidence.house_photos_evaluated}
          uploaded={visualEvidence.house_photos.length}
          lowCount={lowHouse}
          photos={house}
          onOpen={(src, filename) => setLightbox({ src, filename })}
          emptyCopy="No house-visit photos uploaded."
        />

        <Section
          title="Business premises"
          evaluated={visualEvidence.business_photos_evaluated}
          uploaded={visualEvidence.business_photos.length}
          lowCount={lowBiz}
          photos={biz}
          onOpen={(src, filename) => setLightbox({ src, filename })}
          emptyCopy="No business-premises photos uploaded."
        />
      </div>

      {lightbox && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          role="dialog"
          aria-label={`Photo preview: ${lightbox.filename}`}
          onClick={() => setLightbox(null)}
        >
          <div className="max-w-5xl max-h-full flex flex-col gap-2">
            <img
              src={lightbox.src}
              alt={lightbox.filename}
              className="max-h-[80vh] w-auto object-contain rounded"
            />
            <div className="text-[12px] text-white/80 flex justify-between items-center">
              <span className="truncate">{lightbox.filename}</span>
              <button
                type="button"
                className="text-white underline"
                onClick={(e) => {
                  e.stopPropagation()
                  setLightbox(null)
                }}
              >
                close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function Section({
  title,
  evaluated,
  uploaded,
  lowCount,
  photos,
  onOpen,
  emptyCopy,
}: {
  title: string
  evaluated: number
  uploaded: number
  lowCount: boolean
  photos: Array<{ artifact_id: string; download_url: string; filename: string }>
  onOpen: (src: string, filename: string) => void
  emptyCopy: string
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[11.5px] font-semibold text-pfl-slate-700">
          {title}
        </span>
        <span className="text-[11px] text-pfl-slate-500">
          {uploaded} uploaded · {evaluated} evaluated
        </span>
      </div>
      {lowCount && (
        <div className="mb-2 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
          Only {evaluated} photo evaluated — consider re-inspection for
          confidence.
        </div>
      )}
      {photos.length === 0 ? (
        <div className="text-[11.5px] text-pfl-slate-500">{emptyCopy}</div>
      ) : (
        <div className="grid grid-cols-3 md:grid-cols-5 gap-2">
          {photos.map((p) => (
            <button
              key={p.artifact_id}
              type="button"
              onClick={() => onOpen(p.download_url, p.filename)}
              className="block border border-pfl-slate-200 rounded bg-white hover:border-pfl-blue-500 transition-colors overflow-hidden aspect-square"
              title={p.filename}
            >
              <img
                src={p.download_url}
                alt={p.filename}
                className="w-full h-full object-cover"
                loading="lazy"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 11.3: Type-check**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/frontend" && npx tsc --noEmit 2>&1 | tail -8
```

Expected: 0 errors. If `CasePhotosResponse.items[i]` is missing a field referenced in the component (filename, download_url, artifact_id), check the actual type definition and adjust — do not invent fields.

- [ ] **Step 11.4: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add frontend/src/components/cases/l3/L3PhotoGallery.tsx
git commit -m "feat(l3-fe): L3PhotoGallery header component with lightbox

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Wire L3 header section into VerificationPanel

**Files:**
- Modify: `frontend/src/components/cases/VerificationPanel.tsx` (L3 detail-view area, roughly around the level-content rendering; find via Grep for `L3_VISION`)
- Also: delete the inline photo gallery at ~line 2410-2460 in the per-concern expanded view

- [ ] **Step 12.1: Find the L3 detail-view render**

Grep for `L3Findings` in `VerificationPanel.tsx` (already imported around line 3418) — that's where level-specific content slots in. The new header section should render *before* the concerns list, not inside the extraction-details panel.

Also find the level detail-view render that owns `expanded[level]` — concerns live inside it, and the new header must sit above the concerns.

- [ ] **Step 12.2: Add the header section**

Inside the L3 branch of the level detail-view (the place that today renders concerns → PassingRulesPanel → ExtractionDetailsPanel), insert a new block at the top:

```tsx
{level === 'L3_VISION' &&
  data.sub_step_results && (
    <div className="flex flex-col xl:flex-row gap-3 mb-3">
      <div className="xl:flex-[55]">
        <L3StockAnalysisCard
          analysis={
            (data.sub_step_results as Record<string, unknown>)
              .stock_analysis as L3StockAnalysis | null | undefined
          }
        />
      </div>
      <div className="xl:flex-[45]">
        <L3PhotoGallery
          caseId={caseId}
          visualEvidence={
            (data.sub_step_results as Record<string, unknown>)
              .visual_evidence as L3VisualEvidence | null | undefined
          }
        />
      </div>
    </div>
)}
```

- [ ] **Step 12.3: Remove the inline photo gallery inside per-concern open view**

Delete the block in `VerificationPanel.tsx` lines ~2410-2460 that renders the inside-issue `{levelNumber === 'L3_VISION' && (housePhotos…businessPhotos…)}` photos. The new header panel subsumes this.

- [ ] **Step 12.4: Add the imports**

At the top of `VerificationPanel.tsx` add:

```tsx
import { L3StockAnalysisCard } from './l3/L3StockAnalysisCard'
import { L3PhotoGallery } from './l3/L3PhotoGallery'
import { L3StockAnalysis, L3VisualEvidence } from '@/lib/types'
```

- [ ] **Step 12.5: Type-check**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/frontend" && npx tsc --noEmit 2>&1 | tail -10
```

Expected: 0 errors.

- [ ] **Step 12.6: Browser smoke test**

With the dev server + backend running:

Use `mcp__Claude_Preview__preview_eval` on the frontend preview server to reload Ajay's case and confirm:
1. L3 expanded view shows the new header section (Stock analysis + Photos gallery)
2. Photos display real thumbnails
3. Clicking a thumbnail opens the lightbox
4. The old inline gallery inside the house_living_condition concern is gone

- [ ] **Step 12.7: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add frontend/src/components/cases/VerificationPanel.tsx
git commit -m "$(cat <<'EOF'
feat(case-view): always-visible L3 stock-analysis + photo-gallery header

Splits the L3 detail view into two rows: a new "Visual evidence &
stock analysis" header (55/45 split — L3StockAnalysisCard +
L3PhotoGallery) followed by the existing concerns / passing-rules /
extraction-details content. The header renders regardless of whether
any L3 concern fires, so the MD can eyeball the stock numbers and
photos on every case.

Removed the inside-issue photo gallery from the concern expand view
— subsumed by the header panel, rendering both would have been
duplicate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: `LogicCheckRow` click-to-expand infrastructure

**Files:**
- Modify: `frontend/src/components/cases/VerificationPanel.tsx` (the `LogicCheckRow` component)

- [ ] **Step 13.1: Find `LogicCheckRow`**

Grep for `function LogicCheckRow` in `VerificationPanel.tsx`.

- [ ] **Step 13.2: Add expansion affordance + placeholder body**

Convert the row's outer element from a plain div to a `role="button"` keyboard-accessible element with `aria-expanded`. Toggle a local `open` state on click / Enter / Space. Add a chevron.

Below the existing one-line content, render a **placeholder body only** — the L3 dispatcher lands in Task 14, not here. This commit (Task 13) just proves the expand affordance works across every level with the placeholder message:

```tsx
{open && (
  <div className="mt-2 ml-6 mr-1 text-[12px]">
    {passEvidence ? (
      <div className="text-pfl-slate-500 italic">
        Pass-detail renderer lands in the next commit. Raw evidence:
        <pre className="whitespace-pre-wrap text-[11px] mt-1 text-pfl-slate-600">
          {JSON.stringify(passEvidence, null, 2)}
        </pre>
      </div>
    ) : (
      <div className="text-pfl-slate-500 italic">
        No additional pass-detail available yet — this will be
        populated when Part B of the evidence audit ships.
      </div>
    )}
  </div>
)}
```

`passEvidence` needs to be threaded down from the VerificationPanel render through `PassingRulesPanel` → `LogicCheckRow`. It equals `sub_step_results.pass_evidence?.[state.entry.sub_step_id]`. A null-safe access keeps non-L3 levels rendering the "Part B" placeholder. Task 14 replaces the raw-JSON branch with the real dispatcher.

- [ ] **Step 13.3: Thread the props**

Update `PassingRulesPanel`'s props to accept a `passEvidenceByRule: Record<string, unknown> | undefined` and a `visualEvidence: L3VisualEvidence | null | undefined` (passed through to `LogicCheckRow`). Update its call-site in the main panel to pass `data.sub_step_results?.pass_evidence` and `data.sub_step_results?.visual_evidence`.

Also if there's a parallel "overridden" / "n/a" section, it uses the same `LogicCheckRow` — props apply there too.

- [ ] **Step 13.4: Type-check**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/frontend" && npx tsc --noEmit 2>&1 | tail -8
```

Expected: 0 errors.

- [ ] **Step 13.5: Browser smoke test**

Reload Ajay's case. Expand L3 → Passing Rules → click any passing rule row. Confirm the row expands and shows the placeholder text. Keyboard: Tab to a row, Enter toggles.

- [ ] **Step 13.6: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add frontend/src/components/cases/VerificationPanel.tsx
git commit -m "$(cat <<'EOF'
feat(case-view): click-to-expand on passing-rule rows with placeholder body

LogicCheckRow is now a keyboard-accessible expandable element
(role="button", Enter/Space toggle, chevron affordance). Expanded
body renders a placeholder "No additional pass-detail available
yet — populated in Part B" for rules without pass_evidence, so the
UX is consistent across levels before Part B fills the dicts in.

Pass-evidence dicts are threaded from sub_step_results.pass_evidence
through PassingRulesPanel into the row; a null-safe lookup means
non-L3 levels just show the placeholder.

L3 rules will dispatch to dedicated detail cards in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: L3 pass-detail components

**Files:**
- Create: `frontend/src/components/cases/l3/L3StockVsLoanPassCard.tsx`
- Create: `frontend/src/components/cases/l3/L3InfraPassCard.tsx`
- Create: `frontend/src/components/cases/l3/L3LoanRecPassCard.tsx`
- Create: `frontend/src/components/cases/l3/L3PassDetailDispatcher.tsx`
- Modify: `frontend/src/components/cases/VerificationPanel.tsx` (hook the dispatcher into the LogicCheckRow expand body)

- [ ] **Step 14.1: `L3StockVsLoanPassCard.tsx`**

Create:

```tsx
'use client'
import { L3StockAnalysis } from '@/lib/types'
import { cn } from '@/lib/utils'
import { formatInr, formatPct, coverageTone, TONE_PILL_CLASSES } from './helpers'

export function L3StockVsLoanPassCard({
  evidence,
}: {
  evidence: L3StockAnalysis & { photos_evaluated_count?: number }
}) {
  const tone = coverageTone(
    evidence.coverage_pct,
    evidence.floor_pct_critical,
    evidence.floor_pct_warning,
  )
  const isService = evidence.business_type === 'service'
  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-3">
        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
            Visible collateral
          </div>
          <table className="w-full text-[12px]">
            <tbody>
              <tr>
                <td className="text-pfl-slate-600">Stock</td>
                <td className="text-right text-pfl-slate-900 font-medium">
                  {formatInr(evidence.stock_value_estimate_inr)}
                </td>
              </tr>
              {isService && (
                <tr>
                  <td className="text-pfl-slate-600">Fixed equipment</td>
                  <td className="text-right text-pfl-slate-900 font-medium">
                    {formatInr(evidence.visible_equipment_value_inr)}
                  </td>
                </tr>
              )}
              <tr className="border-t border-pfl-slate-200">
                <td className="pt-1 text-pfl-slate-700 font-semibold">Total</td>
                <td className="pt-1 text-right text-pfl-slate-900 font-semibold">
                  {formatInr(evidence.visible_collateral_inr)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
            Loan amount
          </div>
          <div className="text-[15px] font-semibold text-pfl-slate-900">
            {formatInr(evidence.loan_amount_inr)}
          </div>
          <div className="mt-2 text-[11.5px] text-pfl-slate-600">
            Floor: {formatPct(evidence.floor_pct_critical)} critical
            {evidence.floor_pct_warning != null
              ? ` · ${formatPct(evidence.floor_pct_warning)} warning`
              : ''}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span
          className={cn(
            'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold',
            TONE_PILL_CLASSES[tone],
          )}
        >
          coverage {formatPct(evidence.coverage_pct)}
        </span>
        {evidence.recommended_loan_amount_inr != null && (
          <span className="text-[11.5px] text-pfl-slate-700">
            · recommended {formatInr(evidence.recommended_loan_amount_inr)}
          </span>
        )}
        {evidence.photos_evaluated_count != null && (
          <span className="ml-auto text-[11px] text-pfl-slate-500">
            {evidence.photos_evaluated_count} photo
            {evidence.photos_evaluated_count === 1 ? '' : 's'} evaluated
          </span>
        )}
      </div>

      {evidence.reasoning && (
        <p className="text-[12px] text-pfl-slate-700 leading-relaxed">
          {evidence.reasoning}
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 14.2: `L3InfraPassCard.tsx`**

Create:

```tsx
'use client'
type Evidence = {
  infrastructure_rating?: string | null
  infrastructure_details?: string[]
  equipment_visible?: boolean
  photos_evaluated_count?: number
}
export function L3InfraPassCard({ evidence }: { evidence: Evidence }) {
  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-pfl-slate-500">Infrastructure rating</span>
        <span className="text-pfl-slate-900 font-semibold">
          {evidence.infrastructure_rating ?? '—'}
        </span>
        {evidence.equipment_visible != null && (
          <span className="ml-3 text-pfl-slate-500">
            Equipment visible: {evidence.equipment_visible ? 'yes' : 'no'}
          </span>
        )}
        {evidence.photos_evaluated_count != null && (
          <span className="ml-auto text-[11px] text-pfl-slate-500">
            {evidence.photos_evaluated_count} photos evaluated
          </span>
        )}
      </div>
      {Array.isArray(evidence.infrastructure_details) &&
        evidence.infrastructure_details.length > 0 && (
          <ul className="list-disc ml-4 text-[12px] text-pfl-slate-700 space-y-0.5">
            {evidence.infrastructure_details.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        )}
    </div>
  )
}
```

- [ ] **Step 14.3: `L3LoanRecPassCard.tsx`**

Create:

```tsx
'use client'
import { formatInr, formatPct } from './helpers'

type Evidence = {
  loan_amount_inr?: number | null
  recommended_loan_amount_inr?: number | null
  cut_pct?: number | null
  trigger_pct?: number
  rationale?: string | null
  photos_evaluated_count?: number
}

export function L3LoanRecPassCard({ evidence }: { evidence: Evidence }) {
  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-3 text-[12.5px]">
        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-0.5">
            Proposed
          </div>
          <div className="text-pfl-slate-900 font-semibold">
            {formatInr(evidence.loan_amount_inr)}
          </div>
        </div>
        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-0.5">
            Recommended
          </div>
          <div className="text-pfl-slate-900 font-semibold">
            {formatInr(evidence.recommended_loan_amount_inr)}
            {evidence.cut_pct != null && evidence.cut_pct > 0 && (
              <span className="ml-2 text-red-700 text-[11.5px]">
                ({formatPct(evidence.cut_pct)} cut)
              </span>
            )}
          </div>
        </div>
      </div>
      {evidence.rationale && (
        <p className="text-[12px] text-pfl-slate-700 leading-relaxed">
          {evidence.rationale}
        </p>
      )}
      {evidence.photos_evaluated_count != null && (
        <div className="text-[11px] text-pfl-slate-500">
          {evidence.photos_evaluated_count} photos evaluated · trigger floor{' '}
          {formatPct(evidence.trigger_pct ?? 0.8)}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 14.4: `L3PassDetailDispatcher.tsx`**

Create:

```tsx
'use client'
import { L3StockAnalysis } from '@/lib/types'
import { L3StockVsLoanPassCard } from './L3StockVsLoanPassCard'
import { L3InfraPassCard } from './L3InfraPassCard'
import { L3LoanRecPassCard } from './L3LoanRecPassCard'

export function L3PassDetailDispatcher({
  subStepId,
  evidence,
}: {
  subStepId: string
  evidence: Record<string, unknown>
}) {
  switch (subStepId) {
    case 'stock_vs_loan':
      return (
        <L3StockVsLoanPassCard
          evidence={evidence as L3StockAnalysis & { photos_evaluated_count?: number }}
        />
      )
    case 'business_infrastructure':
      return <L3InfraPassCard evidence={evidence} />
    case 'loan_amount_recommendation':
      return <L3LoanRecPassCard evidence={evidence} />
    case 'cattle_health':
      if ('skipped_reason' in evidence) {
        return (
          <div className="text-[12px] text-pfl-slate-600 italic">
            Skipped — {String(evidence.skipped_reason)}. Does not count toward
            the match %.
          </div>
        )
      }
      return (
        <div className="text-[12px] text-pfl-slate-700">
          Cattle health rated{' '}
          <span className="font-semibold">
            {String(evidence.cattle_health ?? '—')}
          </span>{' '}
          across {String(evidence.cattle_count ?? '—')} animal(s).
        </div>
      )
    case 'house_living_condition':
      // Reuse the generic key-value grid pattern — the existing
      // IssueEvidencePanel rendering already handles this shape.
      return (
        <div className="text-[12px]">
          <pre className="whitespace-pre-wrap text-pfl-slate-700">
            {JSON.stringify(evidence, null, 2)}
          </pre>
        </div>
      )
    default:
      return (
        <div className="text-[12px] text-pfl-slate-500 italic">
          No additional pass-detail available yet.
        </div>
      )
  }
}
```

(The `house_living_condition` branch is a minimum-viable pretty-print. A proper ratings grid is **deferred** — see "Out of scope" below. If you have ~30 min of budget at the end of Task 14 and want to land it here instead, it's five labeled rows: space / upkeep / overall / construction / furnishing ratings plus positives/concerns bullet lists. Not required for Part A sign-off.)

- [ ] **Step 14.5: Wire the dispatcher into LogicCheckRow**

In `VerificationPanel.tsx`, replace the Task-13 placeholder (`{passEvidence ? (<L3PassDetailDispatcher … />) : (…placeholder…)}`) with the actual import + invocation of `L3PassDetailDispatcher`.

- [ ] **Step 14.6: Type-check**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/frontend" && npx tsc --noEmit 2>&1 | tail -8
```

Expected: 0 errors.

- [ ] **Step 14.7: Browser smoke test**

Reload Ajay's case:

1. Expand L3 → PASSING RULES pill → expand.
2. Click "Stock / collateral vs loan" row → expands to a side-by-side table: Visible collateral (left, stock + equipment + total) vs Loan amount (right) + coverage pill + reasoning paragraph.
3. Click "Business infrastructure" → rating line + bullet list.
4. Click "Loan amount recommendation" → proposed vs recommended side by side.
5. Click "Cattle health" (currently N/A for Ajay) → "Skipped — not a dairy business (classified: service). Does not count toward the match %."

- [ ] **Step 14.8: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add frontend/src/components/cases/l3/ frontend/src/components/cases/VerificationPanel.tsx
git commit -m "$(cat <<'EOF'
feat(l3-fe): dedicated pass-detail cards for stock_vs_loan + infra + loan-rec + cattle

Click-to-expand on L3 passing rules now renders structured detail
cards backed by sub_step_results.pass_evidence:

  - stock_vs_loan → side-by-side "Visible collateral" (stock +
    equipment + total) vs "Loan amount" table + coverage pill +
    reasoning paragraph. The MD can verify the scorer's
    ₹-conclusion against the photos in the header gallery directly
    above.
  - business_infrastructure → rating line + bullet list of details.
  - loan_amount_recommendation → proposed vs recommended side-by-
    side with cut-% pill.
  - cattle_health → "Skipped — not a dairy business" line on non-
    dairy cases, real cattle detail on dairy cases.
  - house_living_condition → minimum-viable JSON pretty-print for
    now; ratings grid is a follow-up.

Other sub_step_ids still render the placeholder from Part A.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Integration verification

### Task 15: End-to-end smoke on Ajay

- [ ] **Step 15.1: Green-baseline backend**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system/backend" && poetry run pytest tests/unit tests/integration/test_cases_service.py --no-cov -q 2>&1 | tail -6
```

Expected: existing baseline count + new tests from this plan, all green.

- [ ] **Step 15.2: Restart backend + re-run L3 for Ajay**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system" && docker restart pfl-backend && sleep 10
```

Re-run L3 via the API (Step 7.3 recipe).

- [ ] **Step 15.3: Browser screenshots**

Note: `mcp__Claude_Preview__preview_screenshot` is a deferred tool; load its schema first via `ToolSearch(query: "select:mcp__Claude_Preview__preview_screenshot,mcp__Claude_Preview__preview_eval,mcp__Claude_Preview__preview_list")`. Then:

1. L3 header section — stock-analysis card + photo gallery, expanded.
2. Passing-rule expand — `stock_vs_loan` opened with the side-by-side table.
3. Cattle-health row — skipped copy visible.

Attach to the PR description.

- [ ] **Step 15.4: Confirm cattle_health doesn't fire on Ajay's service biz**

Use the Step 7.5 script.

---

### Task 16: Update the resume doc

**Files:**
- Create: `docs/superpowers/RESUME_2026_04_25_NEXT_SESSION.md` (or similar date-stamped name when the work actually lands)

- [ ] **Step 16.1: Document what shipped**

Record the Part A commits, the cattle-guard semantic change, the new `sub_step_results` shape, and the remaining Part B backlog (cross-level evidence audit + per-item stock itemization + other open questions parked in §12 of the spec).

- [ ] **Step 16.2: Commit**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system"
git add docs/superpowers/RESUME_*.md
git commit -m "docs: resume notes — L3 visual-evidence Part A shipped

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Rollout

- [ ] **Push the branch**

```bash
cd "/Users/sakshamgupta/Desktop/PFL credit system" && git push -u origin 4level-l1
```

- [ ] **Open / update PR #1**

If the existing [PR #1](https://github.com/saksham7g1/pfl-credit-system/pull/1) is still the single open PR on this branch, the new commits will roll into it automatically. Otherwise `gh pr create` per CLAUDE.md.

---

## Out of scope (parking lot — do NOT implement here)

Per spec §12, these belong to Part B or follow-up work:

- Proper ratings-grid for the `house_living_condition` pass card
  (currently JSON-pretty-printed in Task 14).
- Cross-level evidence audit for L1 / L1.5 / L2 / L4 concerns.
- Cross-level `pass_evidence` population beyond L3.
- Smart-layout additions in `IssueEvidencePanel` (stock_vs_loan mini-card, avg_balance_vs_emi bar, loan_amount_reduction card, commute-route view, bureau status-account card).
- Corrected `house_business_commute` keys (`travel_minutes`, `dm_status`, `judge_verdict`, `judge_attempted`, origin/destination lat/lng).
- `business_visit_gps` actually computing distance-from-house.
- `aadhaar_vs_bureau_address` numeric-score refactor.
- Scorer-prompt revision for per-item stock itemization (`[{item_type, count, unit_price_inr, subtotal_inr}]`).
- Map pin + geocoded place-name subtitle on the lightbox.
- Scorer-level `business_type` confidence threshold.
- Centralise the 24% flat-rate EMI assumption in L2.
