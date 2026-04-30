"""Unit tests for the Phase-1 gate helper (``_gate_open``).

The gate must require *every* ``VerificationLevelNumber`` to be present in
the latest results AND in a pass state. A partial set of levels (e.g. L1
through L4 only, with L1.5 + L5 missing) must NOT open the gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.api.routers.verification import _gate_open
from app.enums import VerificationLevelNumber, VerificationLevelStatus


@dataclass
class _StubResult:
    level_number: VerificationLevelNumber
    status: VerificationLevelStatus


def _all_passed() -> list[_StubResult]:
    return [
        _StubResult(lv, VerificationLevelStatus.PASSED)
        for lv in VerificationLevelNumber
    ]


def test_gate_open_with_every_level_passed() -> None:
    assert _gate_open(_all_passed()) is True


def test_gate_closed_when_l1_5_missing() -> None:
    """Four out of six levels passing must not open the gate — L1.5 + L5 gap."""
    results = [
        _StubResult(VerificationLevelNumber.L1_ADDRESS, VerificationLevelStatus.PASSED),
        _StubResult(VerificationLevelNumber.L2_BANKING, VerificationLevelStatus.PASSED),
        _StubResult(VerificationLevelNumber.L3_VISION, VerificationLevelStatus.PASSED),
        _StubResult(VerificationLevelNumber.L4_AGREEMENT, VerificationLevelStatus.PASSED),
    ]
    assert _gate_open(results) is False


def test_gate_closed_when_any_level_missing() -> None:
    """Drop one level — gate must close, even if the other five passed."""
    for missing in VerificationLevelNumber:
        partial = [
            _StubResult(lv, VerificationLevelStatus.PASSED)
            for lv in VerificationLevelNumber
            if lv is not missing
        ]
        assert _gate_open(partial) is False, f"gate incorrectly opened when {missing} missing"


def test_gate_closed_when_any_level_blocked() -> None:
    results = _all_passed()
    results[2] = _StubResult(results[2].level_number, VerificationLevelStatus.BLOCKED)
    assert _gate_open(results) is False


def test_gate_open_with_md_override_on_any_level() -> None:
    results = _all_passed()
    results[0] = _StubResult(
        results[0].level_number, VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE
    )
    assert _gate_open(results) is True


def test_gate_closed_when_level_pending() -> None:
    results = _all_passed()
    results[-1] = _StubResult(
        results[-1].level_number, VerificationLevelStatus.PENDING
    )
    assert _gate_open(results) is False


def test_gate_closed_when_level_failed() -> None:
    results = _all_passed()
    results[3] = _StubResult(
        results[3].level_number, VerificationLevelStatus.FAILED
    )
    assert _gate_open(results) is False


def test_gate_closed_empty_results() -> None:
    assert _gate_open([]) is False
