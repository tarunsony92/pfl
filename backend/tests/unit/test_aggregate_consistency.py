"""L3 Phase 2.5: aggregate_consistency diagnostic in build_stock_analysis."""
from app.verification.levels.level_3_vision import build_stock_analysis


def _biz(items, stock=0, equipment=0):
    return {
        "business_type": "service",
        "business_subtype": "barbershop",
        "stock_value_estimate_inr": stock,
        "visible_equipment_value_inr": equipment,
        "items": items,
        "concerns": [],
        "positives": [],
    }


def test_consistency_perfect():
    items = [
        {"description": "chair", "qty": 2, "category": "equipment",
         "mrp_estimate_inr": 5000, "mrp_confidence": "high"},
        {"description": "shampoo", "qty": 4, "category": "consumable",
         "mrp_estimate_inr": 200, "mrp_confidence": "high"},
    ]
    out = build_stock_analysis(_biz(items, stock=800, equipment=10000),
                                loan_amount_inr=50_000)
    assert out is not None
    ac = out["aggregate_consistency"]
    assert ac["stock_items_sum"] == 800
    assert ac["equipment_items_sum"] == 10000
    assert ac["stock_drift_pct"] == 0.0
    assert ac["equipment_drift_pct"] == 0.0
    assert ac["stock_warning"] is False
    assert ac["equipment_warning"] is False


def test_consistency_drift_above_threshold_sets_warning():
    items = [
        {"description": "chair", "qty": 2, "category": "equipment",
         "mrp_estimate_inr": 5000, "mrp_confidence": "high"},
    ]
    # Aggregate claims 20000, items sum 10000 -> 50% drift -> warning
    out = build_stock_analysis(_biz(items, stock=0, equipment=20000),
                                loan_amount_inr=50_000)
    ac = out["aggregate_consistency"]
    assert ac["equipment_items_sum"] == 10000
    assert ac["equipment_aggregate"] == 20000
    assert ac["equipment_drift_pct"] == 0.5
    assert ac["equipment_warning"] is True


def test_consistency_handles_null_mrp_gracefully():
    """Items with mrp_estimate_inr=null contribute 0 to the sum."""
    items = [
        {"description": "chair", "qty": 2, "category": "equipment",
         "mrp_estimate_inr": 5000, "mrp_confidence": "medium"},
        {"description": "mystery", "qty": 1, "category": "equipment",
         "mrp_estimate_inr": None, "mrp_confidence": "low"},
    ]
    out = build_stock_analysis(_biz(items, equipment=10000),
                                loan_amount_inr=50_000)
    ac = out["aggregate_consistency"]
    assert ac["equipment_items_sum"] == 10000
    assert ac["equipment_drift_pct"] == 0.0


def test_consistency_zero_zero_returns_none_drift():
    """No items + zero aggregate -> drift_pct is None (vacuously consistent)."""
    out = build_stock_analysis(_biz([], stock=0, equipment=0),
                                loan_amount_inr=50_000)
    ac = out["aggregate_consistency"]
    assert ac["stock_drift_pct"] is None
    assert ac["equipment_drift_pct"] is None
    assert ac["stock_warning"] is False
    assert ac["equipment_warning"] is False
