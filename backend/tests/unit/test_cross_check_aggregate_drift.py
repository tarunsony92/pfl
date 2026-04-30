"""Unit tests for cross_check_aggregate_drift — surfaces a WARNING when the
scorer's per-item line totals disagree with its own aggregate by >20%."""
from app.verification.levels.level_3_vision import cross_check_aggregate_drift


def test_returns_none_when_aggregate_consistency_is_none():
    assert cross_check_aggregate_drift(aggregate_consistency=None) is None


def test_returns_none_when_aggregate_consistency_is_empty_dict():
    assert cross_check_aggregate_drift(aggregate_consistency={}) is None


def test_returns_none_when_neither_warning_set():
    ac = {
        "stock_aggregate": 1000,
        "stock_items_sum": 1000,
        "stock_drift_pct": 0.0,
        "equipment_aggregate": 5000,
        "equipment_items_sum": 5000,
        "equipment_drift_pct": 0.0,
        "warning_threshold_pct": 0.20,
        "stock_warning": False,
        "equipment_warning": False,
    }
    assert cross_check_aggregate_drift(aggregate_consistency=ac) is None


def test_fires_when_stock_warning_set():
    ac = {
        "stock_aggregate": 10_000,
        "stock_items_sum": 4_000,
        "stock_drift_pct": 0.6,
        "equipment_aggregate": 0,
        "equipment_items_sum": 0,
        "equipment_drift_pct": None,
        "warning_threshold_pct": 0.20,
        "stock_warning": True,
        "equipment_warning": False,
    }
    out = cross_check_aggregate_drift(aggregate_consistency=ac)
    assert out is not None
    assert out["sub_step_id"] == "stock_aggregate_drift"
    assert out["severity"] == "WARNING"
    assert "60%" in out["description"]
    assert ">20%" in out["description"]
    assert "stock aggregate" in out["description"]


def test_fires_when_equipment_warning_set():
    ac = {
        "stock_aggregate": 0,
        "stock_items_sum": 0,
        "stock_drift_pct": None,
        "equipment_aggregate": 20_000,
        "equipment_items_sum": 10_000,
        "equipment_drift_pct": 0.5,
        "warning_threshold_pct": 0.20,
        "stock_warning": False,
        "equipment_warning": True,
    }
    out = cross_check_aggregate_drift(aggregate_consistency=ac)
    assert out is not None
    assert out["sub_step_id"] == "stock_aggregate_drift"
    assert "50%" in out["description"]
    assert "equipment aggregate" in out["description"]


def test_fires_when_both_warnings_set_includes_both_in_description():
    ac = {
        "stock_aggregate": 8_000,
        "stock_items_sum": 4_000,
        "stock_drift_pct": 0.5,
        "equipment_aggregate": 30_000,
        "equipment_items_sum": 12_000,
        "equipment_drift_pct": 0.6,
        "warning_threshold_pct": 0.20,
        "stock_warning": True,
        "equipment_warning": True,
    }
    out = cross_check_aggregate_drift(aggregate_consistency=ac)
    assert out is not None
    desc = out["description"]
    assert "stock aggregate" in desc
    assert "equipment aggregate" in desc
    assert "50%" in desc
    assert "60%" in desc
