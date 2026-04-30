"""Unit tests for app.decisioning.case_library."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.decisioning.case_library import compute_feature_vector, similarity_search


class TestComputeFeatureVector:
    def test_returns_8_elements(self):
        vec = compute_feature_vector()
        assert len(vec) == 8

    def test_all_values_in_0_1(self):
        vec = compute_feature_vector(
            loan_amount=250_000,
            cibil_score=750,
            foir_pct=0.35,
            business_type="Kirana",
            district="Mumbai",
            monthly_income_inr=50_000,
            abb_inr=40_000,
            tenure_months=24,
        )
        for v in vec:
            assert 0.0 <= v <= 1.0, f"Value {v} is out of [0, 1]"

    def test_zero_loan_amount_normalizes_to_zero(self):
        vec = compute_feature_vector(loan_amount=0)
        assert vec[0] == 0.0

    def test_max_loan_amount_normalizes_to_one(self):
        vec = compute_feature_vector(loan_amount=500_000)
        assert vec[0] == 1.0

    def test_loan_above_max_clamped(self):
        vec = compute_feature_vector(loan_amount=1_000_000)
        assert vec[0] == 1.0

    def test_cibil_300_normalizes_to_zero(self):
        vec = compute_feature_vector(cibil_score=300)
        assert vec[1] == 0.0

    def test_cibil_900_normalizes_to_one(self):
        vec = compute_feature_vector(cibil_score=900)
        assert vec[1] == 1.0

    def test_cibil_700_is_roughly_two_thirds(self):
        vec = compute_feature_vector(cibil_score=700)
        # (700 - 300) / (900 - 300) = 400/600 ≈ 0.667
        assert abs(vec[1] - 2 / 3) < 0.01

    def test_known_business_type_maps_to_expected_hash(self):
        vec_kirana = compute_feature_vector(business_type="KIRANA")
        vec_services = compute_feature_vector(business_type="SERVICES")
        assert vec_kirana[3] < vec_services[3]

    def test_unknown_business_type_uses_midpoint(self):
        vec = compute_feature_vector(business_type="UNKNOWN_TYPE")
        assert vec[3] == 0.5

    def test_unknown_district_uses_midpoint(self):
        vec = compute_feature_vector(district="UNKNOWN_DISTRICT")
        assert vec[4] == 0.5

    def test_tenure_normalized(self):
        vec = compute_feature_vector(tenure_months=30)
        # 30/60 = 0.5
        assert abs(vec[7] - 0.5) < 0.01

    def test_deterministic(self):
        kwargs = {
            "loan_amount": 100_000,
            "cibil_score": 750,
            "foir_pct": 0.38,
            "business_type": "COSMETICS",
            "district": "DELHI",
            "monthly_income_inr": 60_000,
            "abb_inr": 25_000,
            "tenure_months": 18,
        }
        assert compute_feature_vector(**kwargs) == compute_feature_vector(**kwargs)


class TestSimilaritySearch:
    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self):
        mock_session = MagicMock()
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "id": "abc",
            "case_id": "def",
            "final_decision": "APPROVE",
            "confidence_score": 80,
            "reasoning_snippet": "Good case",
            "similarity": 0.92,
        }[key]
        mapping = MagicMock()
        mapping.all.return_value = [row]
        result_mock = MagicMock()
        result_mock.mappings.return_value = mapping
        mock_session.execute = AsyncMock(return_value=result_mock)

        results = await similarity_search(
            mock_session,
            [0.5] * 8,
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        """If pgvector is not available the query raises; returns empty list."""
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(
            side_effect=Exception("type 'vector' does not exist")
        )

        results = await similarity_search(mock_session, [0.5] * 8)
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self):
        mock_session = MagicMock()
        mapping = MagicMock()
        mapping.all.return_value = []
        result_mock = MagicMock()
        result_mock.mappings.return_value = mapping
        mock_session.execute = AsyncMock(return_value=result_mock)

        results = await similarity_search(mock_session, [0.5] * 8)
        assert results == []

    @pytest.mark.asyncio
    async def test_result_dict_has_expected_keys(self):
        mock_session = MagicMock()
        row = {
            "id": "uuid-1",
            "case_id": "uuid-2",
            "final_decision": "REJECT",
            "confidence_score": 55,
            "reasoning_snippet": "Failed CIBIL",
            "similarity": 0.85,
        }
        row_mock = MagicMock()
        row_mock.__getitem__ = lambda self, key: row[key]
        mapping = MagicMock()
        mapping.all.return_value = [row_mock]
        result_mock = MagicMock()
        result_mock.mappings.return_value = mapping
        mock_session.execute = AsyncMock(return_value=result_mock)

        results = await similarity_search(mock_session, [0.5] * 8)
        assert len(results) == 1
        r = results[0]
        expected_keys = (
            "id", "case_id", "final_decision", "confidence_score",
            "reasoning_markdown", "similarity",
        )
        for key in expected_keys:
            assert key in r, f"Key {key!r} missing from result"
