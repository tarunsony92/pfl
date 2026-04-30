"""L3 Phase 2: build_stock_analysis forwards items to FE shape."""
from app.verification.levels.level_3_vision import build_stock_analysis


def test_build_stock_analysis_forwards_items():
    biz_data = {
        "business_type": "service",
        "business_subtype": "barbershop",
        "stock_value_estimate_inr": 1500,
        "visible_equipment_value_inr": 20000,
        "items": [
            {"description": "barber chair", "qty": 2, "category": "equipment",
             "mrp_estimate_inr": 8500, "mrp_confidence": "medium"},
            {"description": "shampoo bottle", "qty": 6, "category": "consumable",
             "mrp_estimate_inr": 250, "mrp_confidence": "low"},
        ],
        "concerns": [],
        "positives": [],
    }
    out = build_stock_analysis(biz_data, loan_amount_inr=100_000)
    assert out is not None
    assert "items" in out
    assert len(out["items"]) == 2
    assert out["items"][0]["description"] == "barber chair"


def test_build_stock_analysis_defaults_items_to_empty_list_when_missing():
    """biz_data without an 'items' key must produce items=[] rather than KeyError."""
    biz_data = {
        "business_type": "service",
        "business_subtype": "barbershop",
        "stock_value_estimate_inr": 1500,
        "visible_equipment_value_inr": 20000,
        "concerns": [],
        "positives": [],
    }
    out = build_stock_analysis(biz_data, loan_amount_inr=100_000)
    assert out is not None
    assert out["items"] == []
