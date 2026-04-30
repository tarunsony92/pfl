"""Case library — pgvector similarity search + feature vector construction.

M5 uses an 8-dimensional numerical feature vector for basic similarity.
Full sentence-embedding via Voyage is deferred to M7.

Feature vector dimensions (indices 0–7):
  0 – loan_amount_normalized      (0–500 000 INR → 0.0–1.0)
  1 – cibil_score_normalized      (300–900 → 0.0–1.0)
  2 – foir_pct                    (0–1.0; already fractional)
  3 – business_type_hash          (lookup table → 0.0–1.0)
  4 – district_hash               (lookup table → 0.0–1.0)
  5 – income_inr_normalized       (0–200 000 monthly INR → 0.0–1.0)
  6 – abb_inr_normalized          (0–200 000 monthly INR → 0.0–1.0)
  7 – tenure_months_normalized    (0–60 months → 0.0–1.0)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

# ── Normalization constants ──────────────────────────────────────────────────

_LOAN_MAX = 500_000.0       # INR
_CIBIL_MIN = 300.0
_CIBIL_MAX = 900.0
_INCOME_MAX = 200_000.0     # monthly INR
_ABB_MAX = 200_000.0        # monthly INR
_TENURE_MAX = 60.0          # months

# Simple lookup dicts for categorical → numeric hashes.
# Unknown categories fall back to 0.5 (mid-range).

_BUSINESS_TYPE_MAP: dict[str, float] = {
    "KIRANA": 0.1,
    "GROCERY": 0.1,
    "COSMETICS": 0.2,
    "PHARMACY": 0.3,
    "HARDWARE": 0.4,
    "ELECTRONICS": 0.5,
    "TEXTILES": 0.6,
    "FOOD": 0.7,
    "SERVICES": 0.8,
    "OTHER": 0.9,
}

_DISTRICT_MAP: dict[str, float] = {
    "MUMBAI": 0.05,
    "DELHI": 0.10,
    "BENGALURU": 0.15,
    "HYDERABAD": 0.20,
    "PUNE": 0.25,
    "CHENNAI": 0.30,
    "KOLKATA": 0.35,
    "AHMEDABAD": 0.40,
    "SURAT": 0.45,
    "NAGPUR": 0.50,
}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute_feature_vector(
    loan_amount: float = 0.0,
    cibil_score: float = 700.0,
    foir_pct: float = 0.0,
    business_type: str = "OTHER",
    district: str = "",
    monthly_income_inr: float = 0.0,
    abb_inr: float = 0.0,
    tenure_months: float = 24.0,
) -> list[float]:
    """Compute a normalised 8-dim feature vector from case parameters.

    All output values are in [0, 1].
    """
    loan_norm = _clamp(loan_amount / _LOAN_MAX)
    cibil_norm = _clamp((cibil_score - _CIBIL_MIN) / (_CIBIL_MAX - _CIBIL_MIN))
    foir_norm = _clamp(foir_pct)
    btype_hash = _BUSINESS_TYPE_MAP.get(business_type.upper().strip(), 0.5)
    district_hash = _DISTRICT_MAP.get(district.upper().strip(), 0.5)
    income_norm = _clamp(monthly_income_inr / _INCOME_MAX)
    abb_norm = _clamp(abb_inr / _ABB_MAX)
    tenure_norm = _clamp(tenure_months / _TENURE_MAX)

    return [
        round(loan_norm, 6),
        round(cibil_norm, 6),
        round(foir_norm, 6),
        round(btype_hash, 6),
        round(district_hash, 6),
        round(income_norm, 6),
        round(abb_norm, 6),
        round(tenure_norm, 6),
    ]


async def similarity_search(
    session: AsyncSession,
    vector: list[float],
    k: int = 10,
    threshold: float = 0.70,
) -> list[dict[str, Any]]:
    """Query completed DecisionResults by cosine similarity to ``vector``.

    Uses the pgvector ``<=>`` cosine distance operator. Returns an empty list
    when the pgvector extension is not installed or no qualifying rows exist.

    Args:
        session: Async SQLAlchemy session.
        vector: 8-dim normalised feature vector.
        k: Maximum number of results to return.
        threshold: Minimum cosine similarity (1 − cosine_distance) threshold.

    Returns:
        List of dicts with keys: ``id``, ``case_id``, ``final_decision``,
        ``confidence_score``, ``reasoning_markdown`` (first 500 chars),
        ``similarity``.
    """
    vec_str = "[" + ",".join(str(v) for v in vector) + "]"
    sql = text(
        """
        SELECT
            id,
            case_id,
            final_decision,
            confidence_score,
            LEFT(reasoning_markdown, 500) AS reasoning_snippet,
            1 - (feature_vector <=> CAST(:vec AS vector)) AS similarity
        FROM decision_results
        WHERE status = 'COMPLETED'
          AND feature_vector IS NOT NULL
          AND 1 - (feature_vector <=> CAST(:vec AS vector)) >= :threshold
        ORDER BY feature_vector <=> CAST(:vec AS vector)
        LIMIT :k
        """
    )
    # Run inside a SAVEPOINT so a pgvector-missing error (or any other SQL
    # failure here) doesn't poison the outer transaction and cause every
    # subsequent query in the decisioning pipeline to fail with
    # `current transaction is aborted`.
    try:
        async with session.begin_nested():
            result = await session.execute(
                sql, {"vec": vec_str, "k": k, "threshold": threshold}
            )
            rows = result.mappings().all()
        return [
            {
                "id": str(row["id"]),
                "case_id": str(row["case_id"]),
                "final_decision": row["final_decision"],
                "confidence_score": row["confidence_score"],
                "reasoning_markdown": row["reasoning_snippet"],
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        # pgvector extension not available or column is JSONB fallback.
        # The savepoint has rolled back; the caller's transaction is intact.
        _log.warning("Case library similarity search unavailable: %s", exc)
        return []
