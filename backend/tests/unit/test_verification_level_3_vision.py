"""Unit tests for Level 3 pure cross-check helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.enums import (
    ArtifactSubtype,
    ArtifactType,
    ExtractionStatus,
    LevelIssueSeverity,
    UserRole,
)
from app.verification.levels.level_3_vision import (
    build_pass_evidence,
    build_stock_analysis,
    build_visual_evidence,
    cross_check_house_rating,
    cross_check_stock_vs_loan,
    cross_check_cattle_health,
    cross_check_infrastructure_rating,
    cross_check_loan_amount_reduction,
)
from app.worker.extractors.base import ExtractionResult


def test_house_ok_passes():
    assert cross_check_house_rating("ok") is None
    assert cross_check_house_rating("good") is None
    assert cross_check_house_rating("excellent") is None


def test_house_bad_or_worst_is_critical():
    assert cross_check_house_rating("bad")["severity"] == LevelIssueSeverity.CRITICAL.value
    assert cross_check_house_rating("worst")["severity"] == LevelIssueSeverity.CRITICAL.value


def test_house_unknown_is_warning():
    iss = cross_check_house_rating(None)
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_stock_meets_loan_passes():
    assert cross_check_stock_vs_loan(
        stock_value_estimate_inr=110_000, loan_amount_inr=100_000
    ) is None


def test_stock_below_half_loan_is_critical():
    iss = cross_check_stock_vs_loan(
        stock_value_estimate_inr=20_000, loan_amount_inr=100_000
    )
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value


def test_stock_between_50_and_100_is_warning():
    iss = cross_check_stock_vs_loan(
        stock_value_estimate_inr=65_000, loan_amount_inr=100_000
    )
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_stock_check_skipped_when_loan_amount_unknown():
    assert cross_check_stock_vs_loan(
        stock_value_estimate_inr=50_000, loan_amount_inr=None
    ) is None


def test_stock_check_skipped_when_stock_unknown():
    assert cross_check_stock_vs_loan(
        stock_value_estimate_inr=None, loan_amount_inr=100_000
    ) is None


def test_cattle_unhealthy_is_critical():
    iss = cross_check_cattle_health(
        "unhealthy",
        business_type="cattle_dairy",
        cattle_count=3,
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value


def test_cattle_healthy_passes():
    assert cross_check_cattle_health("healthy") is None
    assert cross_check_cattle_health("not_applicable") is None
    assert cross_check_cattle_health(None) is None


def test_infrastructure_bad_is_warning():
    iss = cross_check_infrastructure_rating("bad")
    assert iss["severity"] == LevelIssueSeverity.WARNING.value


def test_infrastructure_worst_is_critical():
    iss = cross_check_infrastructure_rating("worst")
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value


def test_infrastructure_ok_or_better_passes():
    for r in ("ok", "good", "excellent"):
        assert cross_check_infrastructure_rating(r) is None


# ───────────────── service-business branch & loan reduction ──────────────────


def test_service_collateral_above_40pct_passes():
    # stock + equipment = 45,000 on a 100,000 loan = 45% → above 40% floor.
    assert (
        cross_check_stock_vs_loan(
            business_type="service",
            stock_value_estimate_inr=5_000,
            visible_equipment_value_inr=40_000,
            loan_amount_inr=100_000,
        )
        is None
    )


def test_service_collateral_below_40pct_is_critical():
    # 15,000 + 10,000 = 25,000 on 100,000 = 25% → CRITICAL.
    iss = cross_check_stock_vs_loan(
        business_type="service",
        stock_value_estimate_inr=15_000,
        visible_equipment_value_inr=10_000,
        loan_amount_inr=100_000,
        recommended_loan_amount_inr=35_000,
        recommended_loan_rationale="chair + mirror only",
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value
    assert "Service business" in iss["description"]
    assert "₹35,000" in iss["description"]
    assert "chair + mirror only" in iss["description"]


def test_product_trading_keeps_legacy_50pct_threshold():
    # product_trading with 30% stock coverage → CRITICAL (legacy path).
    iss = cross_check_stock_vs_loan(
        business_type="product_trading",
        stock_value_estimate_inr=30_000,
        visible_equipment_value_inr=200_000,  # irrelevant for product_trading
        loan_amount_inr=100_000,
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.CRITICAL.value


def test_loan_reduction_skipped_when_within_20pct():
    # recommended is within 20% of proposed → no issue.
    assert (
        cross_check_loan_amount_reduction(
            recommended_loan_amount_inr=85_000,
            loan_amount_inr=100_000,
            rationale="adequate collateral",
        )
        is None
    )


def test_loan_reduction_warns_when_cut_exceeds_20pct():
    iss = cross_check_loan_amount_reduction(
        recommended_loan_amount_inr=40_000,
        loan_amount_inr=100_000,
        rationale="barbershop — equipment only",
        business_type="service",
        business_subtype="barbershop",
    )
    assert iss is not None
    assert iss["severity"] == LevelIssueSeverity.WARNING.value
    assert "barbershop" in iss["description"]
    assert "60% cut" in iss["description"]


def test_loan_reduction_skipped_when_recommended_missing():
    assert (
        cross_check_loan_amount_reduction(
            recommended_loan_amount_inr=None,
            loan_amount_inr=100_000,
            rationale=None,
        )
        is None
    )


class TestCattleHealthGuard:
    """cross_check_cattle_health must only fire for cattle_dairy / mixed
    businesses with an actual cattle count. Protects against Opus
    wrongly emitting cattle_health="unhealthy" on non-dairy cases."""

    def test_service_biz_unhealthy_cattle_no_fire(self) -> None:
        result = cross_check_cattle_health(
            "unhealthy",
            business_type="service",
            cattle_count=0,
        )
        assert result is None

    def test_product_trading_unhealthy_no_fire(self) -> None:
        result = cross_check_cattle_health(
            "unhealthy",
            business_type="product_trading",
            cattle_count=None,
        )
        assert result is None

    def test_cattle_dairy_unhealthy_count_3_fires(self) -> None:
        result = cross_check_cattle_health(
            "unhealthy",
            business_type="cattle_dairy",
            cattle_count=3,
        )
        assert result is not None
        assert result["sub_step_id"] == "cattle_health"
        assert result["severity"] == LevelIssueSeverity.CRITICAL.value

    def test_cattle_dairy_unhealthy_count_0_no_fire(self) -> None:
        result = cross_check_cattle_health(
            "unhealthy",
            business_type="cattle_dairy",
            cattle_count=0,
        )
        assert result is None

    def test_cattle_dairy_healthy_no_fire(self) -> None:
        result = cross_check_cattle_health(
            "healthy",
            business_type="cattle_dairy",
            cattle_count=3,
        )
        assert result is None

    def test_mixed_biz_unhealthy_count_2_fires(self) -> None:
        result = cross_check_cattle_health(
            "unhealthy",
            business_type="mixed",
            cattle_count=2,
        )
        assert result is not None
        assert result["sub_step_id"] == "cattle_health"
        assert result["severity"] == LevelIssueSeverity.CRITICAL.value

    def test_unhealthy_without_business_type_kwarg_no_fire(self) -> None:
        """The exact regression case this commit guards against:
        calling with only ``health`` (business_type defaults to None)
        must return None after the guard, even though it would have
        fired under the pre-guard signature."""
        assert cross_check_cattle_health("unhealthy") is None


class TestBuildStockAnalysis:
    """build_stock_analysis is a pure function that packages the business
    scorer's output plus the case loan amount into the
    sub_step_results.stock_analysis dict shape. Always produces a
    well-formed dict when given scorer data; returns None only when
    the scorer errored. The frontend renders specific keys from this
    dict — a schema-drift guard test locks the contract."""

    EXPECTED_KEYS = {
        "business_type", "business_subtype", "loan_amount_inr",
        "stock_value_estimate_inr", "visible_equipment_value_inr",
        "visible_collateral_inr", "cattle_count", "cattle_health",
        "coverage_pct", "floor_pct_critical", "floor_pct_warning",
        "recommended_loan_amount_inr", "recommended_loan_rationale",
        "cut_pct", "reasoning", "stock_condition", "stock_variety",
        "items", "aggregate_consistency",
    }

    def test_service_biz_all_keys_present(self) -> None:
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
        assert "service" in out["reasoning"].lower()

    def test_product_trading_non_service(self) -> None:
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
        biz_data = {
            "business_type": "cattle_dairy",
            "business_subtype": "buffalo dairy",
            "stock_value_estimate_inr": 240_000,  # 4 × 60k
            "cattle_count": 4,
            "cattle_health": "healthy",
            "recommended_loan_amount_inr": 200_000,
            "recommended_loan_rationale": "4 cattle at 60k each",
        }
        out = build_stock_analysis(biz_data, loan_amount_inr=200_000)
        assert out["visible_collateral_inr"] == 240_000
        assert out["cattle_count"] == 4
        assert out["coverage_pct"] == pytest.approx(1.20)

    def test_scorer_error_returns_none(self) -> None:
        """Empty / error-path scorer data → None so the orchestrator
        simply omits the key."""
        assert build_stock_analysis({}, loan_amount_inr=50_000) is None
        assert build_stock_analysis(None, loan_amount_inr=50_000) is None

    def test_missing_loan_amount_still_produces_partial_output(self) -> None:
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


class TestBuildVisualEvidence:
    """build_visual_evidence returns a dict with artifact-id lists the
    frontend uses to filter the useCasePhotos hook output. Counts
    (photos_evaluated) are the lengths of the image bytes lists fed
    to the scorers — distinct from the uploaded artifact counts,
    since the scorer may skip an artifact that failed to download."""

    def _mk_artifact(self, aid: str, subtype: str, filename: str):
        """Build a minimal CaseArtifact-shaped object for the test."""
        class _A:
            pass
        a = _A()
        a.id = aid
        a.filename = filename
        a.metadata_json = {"subtype": subtype}
        return a

    def test_empty_lists(self) -> None:
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


class TestBuildPassEvidence:
    """build_pass_evidence returns a dict keyed by sub_step_id, with
    each entry populated only when the rule passed (or skipped with
    N/A). Failing rules are excluded — the FE reads their evidence
    off LevelIssue.evidence."""

    def test_passing_service_biz_all_entries(self) -> None:
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
        out = build_pass_evidence(
            house_data=house_data,
            biz_data=biz_data,
            loan_amount_inr=50_000,
            house_photos_evaluated=5,
            business_photos_evaluated=5,
            fired_rules=set(),
        )
        assert "house_living_condition" in out
        assert out["house_living_condition"]["overall_rating"] == "ok"
        assert out["house_living_condition"]["photos_evaluated_count"] == 5
        assert "business_infrastructure" in out
        assert out["business_infrastructure"]["infrastructure_rating"] == "good"
        assert "stock_vs_loan" in out
        assert out["stock_vs_loan"]["business_type"] == "service"
        assert out["stock_vs_loan"]["visible_collateral_inr"] == 50_000
        assert "loan_amount_reduction" in out
        assert out["loan_amount_reduction"]["cut_pct"] == 0.0
        assert "cattle_health" in out
        assert out["cattle_health"]["skipped_reason"].startswith(
            "not a dairy business"
        )

    def test_failing_stock_rule_absent(self) -> None:
        """When stock_vs_loan fired as a CRITICAL issue, it must not
        appear in pass_evidence. Other rules that passed still show."""
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
        assert "loan_amount_reduction" not in out
        assert "business_infrastructure" in out
        assert "house_living_condition" in out

    def test_cattle_dairy_passing_fills_real_entry_not_skipped(self) -> None:
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
        assert "loan_amount_reduction" not in out


# ─────────────────────── Orchestrator integration test ────────────────────────


async def _seed_l3_fixture(
    db,
    *,
    house_count: int = 2,
    biz_count: int = 3,
    loan_amount: int | None = 100_000,
):
    """Seed a case + N house + M business photo artifacts on the test DB
    and return ``(case_id, actor_user_id)``. Used by the orchestrator
    integration test below. Keeps the artifact metadata_json shape the
    orchestrator's ``_sub`` helper reads from."""
    from app.enums import UserRole
    from app.models.case import Case
    from app.models.case_artifact import CaseArtifact
    from app.services import users as users_svc

    user = await users_svc.create_user(
        db,
        email="l3-int@pfl.com",
        password="Pass123!",
        full_name="L3 Int",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()

    case = Case(
        loan_id="L3INT0001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="l3int/case.zip",
        loan_amount=loan_amount,
    )
    db.add(case)
    await db.flush()

    for i in range(house_count):
        db.add(
            CaseArtifact(
                case_id=case.id,
                filename=f"house_{i}.jpg",
                artifact_type=ArtifactType.ADDITIONAL_FILE,
                s3_key=f"l3int/{case.id}/house_{i}.jpg",
                uploaded_by=user.id,
                uploaded_at=datetime.now(UTC),
                metadata_json={"subtype": ArtifactSubtype.HOUSE_VISIT_PHOTO.value},
            )
        )
    for i in range(biz_count):
        db.add(
            CaseArtifact(
                case_id=case.id,
                filename=f"biz_{i}.jpg",
                artifact_type=ArtifactType.ADDITIONAL_FILE,
                s3_key=f"l3int/{case.id}/biz_{i}.jpg",
                uploaded_by=user.id,
                uploaded_at=datetime.now(UTC),
                metadata_json={"subtype": ArtifactSubtype.BUSINESS_PREMISES_PHOTO.value},
            )
        )
    await db.flush()
    return case.id, user.id


class _StubStorage:
    """Minimal storage stub that returns canned bytes from download_object."""

    def __init__(self) -> None:
        self.download_object = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake_jpeg_bytes")


class TestRunLevel3VisionSubStepResults:
    """Integration-ish test for the full ``run_level_3_vision`` orchestrator.

    Mocks the two Claude-vision scorers to avoid any network / API calls,
    then verifies that ``sub_step_results`` contains the three new keys
    (``visual_evidence``, ``stock_analysis``, ``pass_evidence``) along
    with the pre-existing six, and that scorer-driven issues carry the
    new ``photos_evaluated_count`` field in their evidence."""

    async def _run(
        self,
        db,
        *,
        house_payload: dict,
        biz_payload: dict,
        house_count: int = 2,
        biz_count: int = 3,
        loan_amount: int | None = 100_000,
    ):
        from app.verification.levels import level_3_vision as l3_mod

        case_id, actor_user_id = await _seed_l3_fixture(
            db,
            house_count=house_count,
            biz_count=biz_count,
            loan_amount=loan_amount,
        )

        house_result = ExtractionResult(
            status=ExtractionStatus.SUCCESS,
            schema_version="1.0",
            data=house_payload,
        )
        biz_result = ExtractionResult(
            status=ExtractionStatus.SUCCESS,
            schema_version="1.0",
            data=biz_payload,
        )

        class _StubHouseScorer:
            def __init__(self, claude=None) -> None:
                pass

            async def score(self, imgs):
                return house_result

        class _StubBusinessScorer:
            def __init__(self, claude=None) -> None:
                pass

            async def score(self, imgs, *, loan_amount_inr=None):
                return biz_result

        # The orchestrator imports the scorers lazily inside the function,
        # so patch them on the module they come from.
        with (
            patch(
                "app.verification.services.vision_scorers.HousePremisesScorer",
                _StubHouseScorer,
            ),
            patch(
                "app.verification.services.vision_scorers.BusinessPremisesScorer",
                _StubBusinessScorer,
            ),
        ):
            result = await l3_mod.run_level_3_vision(
                db,
                case_id,
                actor_user_id=actor_user_id,
                claude=object(),
                storage=_StubStorage(),
            )
        return result

    async def test_sub_step_results_has_three_new_keys(self, db) -> None:
        """Passing service biz → all three new keys present, none of the
        5 scorer rules fired, pass_evidence entries for all of them."""
        house_payload = {
            "overall_rating": "good",
            "space_rating": "good",
            "upkeep_rating": "ok",
            "construction_type": "pakka",
            "positives": ["courtyard spacious"],
            "concerns": [],
            "cost_usd": 0.03,
        }
        biz_payload = {
            "business_type": "service",
            "business_subtype": "barbershop",
            "stock_value_estimate_inr": 5_000,
            "visible_equipment_value_inr": 45_000,  # 50k on 100k loan = 50%
            "cattle_count": 0,
            "cattle_health": "not_applicable",
            "infrastructure_rating": "good",
            "infrastructure_details": ["solid shelter"],
            "recommended_loan_amount_inr": 100_000,
            "recommended_loan_rationale": "covers equipment fully",
            "cost_usd": 0.04,
        }
        result = await self._run(db, house_payload=house_payload, biz_payload=biz_payload)
        ssr = result.sub_step_results
        # Pre-existing keys are still there.
        for k in (
            "house",
            "business",
            "house_photo_count",
            "business_photo_count",
            "issue_count",
            "suppressed_rules",
        ):
            assert k in ssr, f"missing pre-existing key: {k}"
        # Three new keys are present.
        assert "visual_evidence" in ssr
        assert "stock_analysis" in ssr
        assert "pass_evidence" in ssr
        # visual_evidence shape.
        ve = ssr["visual_evidence"]
        assert set(ve.keys()) == {
            "house_photos",
            "business_photos",
            "house_photos_evaluated",
            "business_photos_evaluated",
        }
        assert ve["house_photos_evaluated"] == 2
        assert ve["business_photos_evaluated"] == 3
        assert len(ve["house_photos"]) == 2
        assert len(ve["business_photos"]) == 3
        # stock_analysis shape — packaged by build_stock_analysis.
        sa = ssr["stock_analysis"]
        assert sa is not None
        assert sa["business_type"] == "service"
        assert sa["visible_collateral_inr"] == 50_000
        assert sa["coverage_pct"] == pytest.approx(0.50)
        # pass_evidence: no rules fired → all 5 scorer entries present.
        pe = ssr["pass_evidence"]
        assert "house_living_condition" in pe
        assert "business_infrastructure" in pe
        assert "stock_vs_loan" in pe
        assert "loan_amount_reduction" in pe
        assert "cattle_health" in pe
        # photos_evaluated_count threaded through every entry.
        assert pe["house_living_condition"]["photos_evaluated_count"] == 2
        assert pe["business_infrastructure"]["photos_evaluated_count"] == 3
        assert pe["stock_vs_loan"]["photos_evaluated_count"] == 3

    async def test_fired_rule_absent_from_pass_evidence_and_photos_count_on_issue(
        self, db
    ) -> None:
        """When a scorer-driven rule fires (stock_vs_loan CRITICAL), that
        rule's entry is omitted from pass_evidence and the corresponding
        LevelIssue evidence carries photos_evaluated_count."""
        house_payload = {
            "overall_rating": "ok",  # passes
            "space_rating": "ok",
            "upkeep_rating": "ok",
            "construction_type": "pakka",
            "positives": [],
            "concerns": [],
            "cost_usd": 0.03,
        }
        # product_trading + 20k stock / 100k loan = 20% → CRITICAL stock_vs_loan.
        biz_payload = {
            "business_type": "product_trading",
            "business_subtype": "kirana",
            "stock_value_estimate_inr": 20_000,
            "visible_equipment_value_inr": 0,
            "cattle_count": 0,
            "cattle_health": "not_applicable",
            "infrastructure_rating": "good",
            "infrastructure_details": [],
            "recommended_loan_amount_inr": 25_000,
            "recommended_loan_rationale": "stock only supports this much",
            "cost_usd": 0.04,
        }
        result = await self._run(db, house_payload=house_payload, biz_payload=biz_payload)
        ssr = result.sub_step_results
        pe = ssr["pass_evidence"]
        # stock_vs_loan fired → absent from pass_evidence.
        assert "stock_vs_loan" not in pe
        # loan_amount_reduction also fires (25k vs 100k = 75% cut > 20% trigger).
        assert "loan_amount_reduction" not in pe
        # The other three still passed → present.
        assert "house_living_condition" in pe
        assert "business_infrastructure" in pe
        assert "cattle_health" in pe
        # Check LevelIssue evidence on the persisted issues carries the
        # new photos_evaluated_count field.
        from sqlalchemy import select
        from app.models.level_issue import LevelIssue

        rows = (
            await db.execute(
                select(LevelIssue).where(
                    LevelIssue.verification_result_id == result.id
                )
            )
        ).scalars().all()
        biz_issues = [r for r in rows if r.sub_step_id in {
            "stock_vs_loan",
            "loan_amount_reduction",
            "business_infrastructure",
            "cattle_health",
        }]
        assert biz_issues, "expected at least one business-driven issue"
        for r in biz_issues:
            assert r.evidence is not None
            assert r.evidence.get("photos_evaluated_count") == 3

    async def test_no_loan_amount_stock_analysis_still_present(self, db) -> None:
        """loan_amount None → stock_analysis has coverage_pct=None but is
        still a well-formed dict (not None) because biz_data is non-empty."""
        house_payload = {
            "overall_rating": "ok",
            "positives": [],
            "concerns": [],
            "cost_usd": 0.02,
        }
        biz_payload = {
            "business_type": "service",
            "stock_value_estimate_inr": 5_000,
            "visible_equipment_value_inr": 45_000,
            "infrastructure_rating": "good",
            "cost_usd": 0.02,
        }
        result = await self._run(
            db,
            house_payload=house_payload,
            biz_payload=biz_payload,
            loan_amount=None,
        )
        ssr = result.sub_step_results
        sa = ssr["stock_analysis"]
        assert sa is not None
        assert sa["loan_amount_inr"] is None
        assert sa["coverage_pct"] is None
        assert sa["visible_collateral_inr"] == 50_000
