"""Unit tests for the CAM discrepancy detector."""

from __future__ import annotations

from app.worker.extractors.autocam_discrepancies import (
    FIELD_APPLICANT_NAME,
    FIELD_CIBIL,
    FIELD_DATE_OF_BIRTH,
    FIELD_FOIR,
    FIELD_LOAN_AMOUNT,
    FIELD_PAN,
    FIELD_TENURE,
    FIELD_TOTAL_MONTHLY_INCOME,
    detect_discrepancies,
    serialise,
)


# ---------------------------------------------------------------------------
# Happy path — no discrepancies
# ---------------------------------------------------------------------------


def test_detector_returns_empty_when_both_sheets_agree():
    data = {
        "system_cam": {
            "applicant_name": "AJAY SINGH",
            "pan": "OWLPS6441C",
            "date_of_birth": "17-11-2001",
            "loan_amount": 100000,
            "foir_overall": 25.35,
            "tenure": 20,
        },
        "eligibility": {"cibil_score": 750},
        "cm_cam_il": {
            "borrower_name": "AJAY SINGH",
            "pan_number": "OWLPS6441C",
            "date_of_birth": "17-11-2001",
            "loan_required": 100000,
            "foir": 0.2535,   # same value expressed as fraction
            "cibil": 750,
            "total_monthly_income": 36000,
            "tenure": 20,
        },
        "health_sheet": {"total_monthly_income": 36000},
    }
    assert detect_discrepancies(data) == []


def test_detector_ignores_missing_side():
    """If a field is missing from one sheet entirely it's NOT a discrepancy;
    that's a 'missing_field' concern handled elsewhere."""
    data = {
        "system_cam": {"applicant_name": "AJAY SINGH"},
        "cm_cam_il": {},   # empty — no conflict, just missing
    }
    assert detect_discrepancies(data) == []


# ---------------------------------------------------------------------------
# String fields
# ---------------------------------------------------------------------------


def test_name_mismatch_critical():
    data = {
        "system_cam": {"applicant_name": "AJAY SINGH"},
        "cm_cam_il": {"borrower_name": "AJAY KUMAR SINGH"},
    }
    discs = detect_discrepancies(data)
    assert len(discs) == 1
    d = discs[0]
    assert d.field_key == FIELD_APPLICANT_NAME
    assert d.severity == "CRITICAL"
    assert "AJAY SINGH" in (d.system_cam_value or "")


def test_name_case_and_token_order_insensitive():
    data = {
        "system_cam": {"applicant_name": "ajay SINGH"},
        "cm_cam_il": {"borrower_name": "Singh Ajay"},
    }
    assert detect_discrepancies(data) == []


def test_pan_mismatch():
    data = {
        "system_cam": {"pan": "OWLPS6441C"},
        "cm_cam_il": {"pan_number": "ABCDE1234F"},
    }
    discs = detect_discrepancies(data)
    assert any(d.field_key == FIELD_PAN and d.severity == "CRITICAL" for d in discs)


def test_dob_date_format_equivalence():
    """17-11-2001 == 17/11/2001 == 2001-11-17 — all the same calendar day."""
    data = {
        "system_cam": {"date_of_birth": "17-11-2001"},
        "cm_cam_il": {"date_of_birth": "17/11/2001"},
    }
    assert detect_discrepancies(data) == []

    data["cm_cam_il"]["date_of_birth"] = "2001-11-17"
    assert detect_discrepancies(data) == []


def test_dob_different_date_is_critical():
    data = {
        "system_cam": {"date_of_birth": "17-11-2001"},
        "cm_cam_il": {"date_of_birth": "16-11-2001"},
    }
    discs = detect_discrepancies(data)
    assert any(d.field_key == FIELD_DATE_OF_BIRTH and d.severity == "CRITICAL" for d in discs)


# ---------------------------------------------------------------------------
# Numeric fields — tolerances
# ---------------------------------------------------------------------------


def test_loan_amount_small_diff_within_tolerance():
    """≤ ₹500 absolute tolerance — 100_000 vs 100_250 is fine."""
    data = {
        "system_cam": {"loan_amount": 100000},
        "cm_cam_il": {"loan_required": 100250},
    }
    assert detect_discrepancies(data) == []


def test_loan_amount_big_diff_flagged_critical():
    data = {
        "system_cam": {"loan_amount": 100000},
        "cm_cam_il": {"loan_required": 110000},
    }
    discs = detect_discrepancies(data)
    flagged = next(d for d in discs if d.field_key == FIELD_LOAN_AMOUNT)
    assert flagged.severity == "CRITICAL"
    assert flagged.diff_abs == 10000.0
    # 10k on max(110k,100k)=110k → ~9.09%
    assert 9.0 < (flagged.diff_pct or 0) < 9.2


def test_foir_within_one_percentage_point():
    data = {
        "system_cam": {"foir_overall": 25.35},
        "cm_cam_il": {"foir": 24.5},
    }
    # |25.35 - 24.5| = 0.85 pp — within tolerance → not flagged
    assert detect_discrepancies(data) == []


def test_foir_big_gap_flagged_warning():
    """Real Ajay case: SystemCam 25.35% vs CM CAM IL 18.1%."""
    data = {
        "system_cam": {"foir_overall": 25.35},
        "cm_cam_il": {"foir": 0.181},   # stored as fraction
    }
    discs = detect_discrepancies(data)
    flagged = next(d for d in discs if d.field_key == FIELD_FOIR)
    assert flagged.severity == "WARNING"
    assert flagged.diff_abs is not None and flagged.diff_abs > 7
    assert "25.35" in (flagged.system_cam_value or "")


def test_foir_fraction_and_percentage_are_treated_same():
    """0.25 and 25 should compare as equivalent."""
    data = {
        "system_cam": {"foir_overall": 0.25},
        "cm_cam_il": {"foir": 25},
    }
    assert detect_discrepancies(data) == []


def test_cibil_any_diff_is_critical():
    data = {
        "system_cam": {},
        "eligibility": {"cibil_score": 750},
        "cm_cam_il": {"cibil": 749},
    }
    discs = detect_discrepancies(data)
    assert any(d.field_key == FIELD_CIBIL and d.severity == "CRITICAL" for d in discs)


def test_monthly_income_within_two_percent():
    data = {
        "system_cam": {},
        "health_sheet": {"total_monthly_income": 36000},
        "cm_cam_il": {"total_monthly_income": 36500},   # ~1.37% off
    }
    assert detect_discrepancies(data) == []


def test_monthly_income_over_two_percent_flagged():
    data = {
        "system_cam": {},
        "health_sheet": {"total_monthly_income": 36000},
        "cm_cam_il": {"total_monthly_income": 40000},   # 10% off
    }
    discs = detect_discrepancies(data)
    assert any(
        d.field_key == FIELD_TOTAL_MONTHLY_INCOME and d.severity == "WARNING"
        for d in discs
    )


def test_tenure_exact_match_required():
    data = {
        "system_cam": {"tenure": 20},
        "cm_cam_il": {"tenure": 24},
    }
    discs = detect_discrepancies(data)
    assert any(d.field_key == FIELD_TENURE for d in discs)


# ---------------------------------------------------------------------------
# Coercion edge cases
# ---------------------------------------------------------------------------


def test_dash_values_treated_as_missing():
    data = {
        "system_cam": {"tenure": 20},
        "cm_cam_il": {"tenure": "-"},
    }
    # '-' → missing, not a discrepancy
    assert detect_discrepancies(data) == []


def test_currency_symbols_stripped():
    data = {
        "system_cam": {"loan_amount": "₹ 1,00,000"},
        "cm_cam_il": {"loan_required": 100000},
    }
    # Commas + ₹ stripped → 100000 both sides
    assert detect_discrepancies(data) == []


def test_serialise_shape():
    data = {
        "system_cam": {"applicant_name": "A"},
        "cm_cam_il": {"borrower_name": "B"},
    }
    out = serialise(detect_discrepancies(data))
    assert len(out) == 1
    assert set(out[0].keys()) == {
        "field_key",
        "field_label",
        "system_cam_value",
        "cm_cam_il_value",
        "diff_abs",
        "diff_pct",
        "severity",
        "tolerance_description",
        "note",
    }


def test_non_dict_input_returns_empty_list():
    assert detect_discrepancies(None) == []  # type: ignore[arg-type]
    assert detect_discrepancies("foo") == []  # type: ignore[arg-type]
