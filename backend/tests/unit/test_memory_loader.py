"""Unit tests for app.memory.loader."""

from __future__ import annotations

import pytest

from app.memory.loader import load_heuristics, load_policy, reset_caches


@pytest.fixture(autouse=True)
def _clear_caches():
    """Ensure each test starts with fresh caches."""
    reset_caches()
    yield
    reset_caches()


class TestLoadPolicy:
    def test_returns_dict(self):
        policy = load_policy()
        assert isinstance(policy, dict)

    def test_hard_rules_present(self):
        policy = load_policy()
        assert "hard_rules" in policy

    def test_cibil_min_is_700(self):
        policy = load_policy()
        assert policy["hard_rules"]["cibil_min"] == 700

    def test_foir_cap_present(self):
        policy = load_policy()
        assert "foir_cap" in policy
        assert policy["foir_cap"] == 0.50

    def test_ticket_grid_is_list(self):
        policy = load_policy()
        assert isinstance(policy["ticket_grid"], list)
        assert len(policy["ticket_grid"]) > 0

    def test_max_business_distance(self):
        policy = load_policy()
        assert policy["hard_rules"]["max_business_distance_km"] == 25

    def test_negative_statuses_list(self):
        policy = load_policy()
        neg = policy["hard_rules"]["negative_statuses"]
        assert "WRITTEN_OFF" in neg
        assert "SUIT_FILED" in neg
        assert "LSS" in neg

    def test_cached_on_second_call(self):
        p1 = load_policy()
        p2 = load_policy()
        assert p1 is p2, "Should return the same cached object"

    def test_reset_caches_forces_reload(self):
        load_policy()
        reset_caches()
        # After reset the cache is empty; calling again populates it
        info_after_reset = load_policy.cache_info()
        assert info_after_reset.currsize == 0
        p2 = load_policy()
        assert isinstance(p2, dict)
        assert load_policy.cache_info().currsize == 1


class TestLoadHeuristics:
    def test_returns_string(self):
        h = load_heuristics()
        assert isinstance(h, str)

    def test_not_empty(self):
        h = load_heuristics()
        assert len(h) > 0

    def test_contains_npa_patterns(self):
        h = load_heuristics()
        assert "NPA Patterns" in h

    def test_contains_cibil_rule(self):
        h = load_heuristics()
        assert "CIBIL" in h.upper()

    def test_cached_on_second_call(self):
        h1 = load_heuristics()
        h2 = load_heuristics()
        assert h1 is h2

    def test_reset_clears_heuristics_cache(self):
        load_heuristics()
        reset_caches()
        # After reset the cache should be empty
        info_after_reset = load_heuristics.cache_info()
        assert info_after_reset.currsize == 0
