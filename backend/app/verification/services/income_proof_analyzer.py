"""IncomeProofAnalyzer — Opus-4.7 vision read of the borrower's income-proof
artifacts.

Why this exists
---------------
PFL's L5 rubric used to "verify" Applicant Income Proof and Additional Income
purely on artifact-presence: bank statement uploaded ⇒ row #16 PASS, no second
proof ⇒ row #18 PENDING. The BCM-declared CAM income was never cross-checked
against the actual evidence on file. In practice the income-proof folder for
a rural microfinance case is a stack of consignment notes, transport slips,
shop invoices, salary stubs, agricultural-mandi receipts — heterogeneous
artefacts that need a real read, not a subtype check.

This service runs Opus-4.7 over the proof images and returns:

- ``forecasted_monthly_income_inr`` — what the proof actually justifies
- ``accuracy_pct``                 — forecasted / declared
- ``distinct_income_sources``     — how many independent earning streams
  appear across the artefacts (powers row #18 "Additional Income")
- a structured ``verdict`` (clean / caution / adverse) the resolvers consume

Cost is bounded (Opus vision, ~5-8 images × ~0.5k input tokens each, <1k
output) — runs at most once per L5 trigger and the result is cached on the
``VerificationResult.sub_step_results`` so re-renders don't re-pay.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.enums import ExtractionStatus
from app.worker.extractors.base import ExtractionResult

_log = logging.getLogger(__name__)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


_SYSTEM_PROMPT = """You are a senior credit officer at PFL Finance, a rural
microfinance lender in Haryana / Punjab / western UP. You receive the income
proof a Branch Credit Manager (BCM) has attached to a loan file — usually a
mix of: consignment notes / transport slips for transport businesses, mandi
receipts for agri traders, shop invoices / GSTR-style summaries for retail,
salary stubs for the rare salaried borrower, milk-collection booklets, etc.

Your job: cross-verify the BCM's DECLARED monthly household income against
what the proofs actually justify, AND count how many INDEPENDENT income
sources are visible in the proofs.

You are STRICT. A microfinance book has no room for over-stated income.
Forecast on the conservative side — if a transport slip shows ₹300 / parcel
and you can see ~10 parcels per slip on a typical day, do NOT extrapolate to
a full month without evidence of frequency; instead, state your assumption
explicitly and produce a low-confidence forecast.

=== FORECASTING RULES ===

1. Identify each proof's type. Examples: "transport_consignment",
   "shop_invoice", "salary_slip", "agri_mandi_receipt", "milk_booklet",
   "rent_receipt", "freelance_invoice".
2. For each proof, extract the dated transaction value(s) and any volume
   signals (number of parcels, weight, head count, days worked).
3. Aggregate by SOURCE — multiple slips for the same business on different
   dates collapse to one source; a salary slip + a separate shop invoice =
   two distinct sources.
4. Forecast a MONTHLY income per source from the dated values you can see.
   If you only have a single dated slip, multiply by a conservative
   frequency (e.g. ×4 for weekly, ×30 for daily) and SAY SO in your
   narrative.
5. Sum the per-source forecasts to get ``forecasted_monthly_income_inr``.

=== ACCURACY VERDICT ===

Compare ``forecasted_monthly_income_inr`` against ``declared_monthly_income_inr``:

- ``clean``   — forecast is within ±25 % of declared, AND every proof is
                legible / signed / clearly belongs to a loan party
- ``caution`` — forecast is 50–75 % of declared, OR proofs are partially
                illegible / outdated / from a third party not declared on
                the loan
- ``adverse`` — forecast is < 50 % of declared, OR proofs are unrelated /
                fabricated / heavily inflated

A material gap (`adverse`) MUST route to MD approval — the resolver will
do that automatically when you return verdict=adverse.

=== DISTINCT INCOME SOURCES ===

Count of independent earning streams supported by the proofs. Two
consignment slips from the same transport company = ONE source. A
consignment slip + an unrelated agri receipt = TWO sources. Always >= 0,
NEVER counts an unsupported declaration (CAM line saying "wife earns
₹X" without a single proof slip is NOT a source).

=== OUTPUT FORMAT ===

Return ONLY valid JSON matching this schema:

{
  "forecasted_monthly_income_inr": <int or null if you cannot forecast>,
  "accuracy_pct": <float 0..200, forecast / declared × 100; null if either side missing>,
  "verdict": "clean | caution | adverse",
  "confidence": <0..100 — your confidence in the forecast>,
  "distinct_income_sources": <int>,
  "proof_types_detected": ["<short label per artefact>"],
  "per_source_forecast_inr": {"<source label>": <int monthly INR>},
  "narrative": "<2-4 sentences explaining the forecast and the gap>",
  "concerns": ["<short string per material concern>"],
  "assumptions": ["<short string per frequency / volume assumption made>"]
}

Rules:
- Never fabricate amounts. If the slip is illegible, say so in `concerns`.
- If declared_monthly_income_inr is 0 or missing, set `accuracy_pct=null`
  but still forecast and count sources.
- Respond with JSON only, no prose.
"""


@dataclass
class IncomeProofAnalysis:
    """Structured result the L5 resolvers consume."""

    forecasted_monthly_income_inr: int | None
    declared_monthly_income_inr: int | None
    accuracy_pct: float | None
    verdict: str  # clean / caution / adverse / unknown
    confidence: int
    distinct_income_sources: int
    proof_types_detected: list[str] = field(default_factory=list)
    per_source_forecast_inr: dict[str, int] = field(default_factory=dict)
    narrative: str = ""
    concerns: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    images_examined: int = 0
    cost_usd: float = 0.0
    model: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecasted_monthly_income_inr": self.forecasted_monthly_income_inr,
            "declared_monthly_income_inr": self.declared_monthly_income_inr,
            "accuracy_pct": self.accuracy_pct,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "distinct_income_sources": self.distinct_income_sources,
            "proof_types_detected": self.proof_types_detected,
            "per_source_forecast_inr": self.per_source_forecast_inr,
            "narrative": self.narrative,
            "concerns": self.concerns,
            "assumptions": self.assumptions,
            "images_examined": self.images_examined,
            "cost_usd": self.cost_usd,
            "model": self.model,
            "error": self.error,
        }


def _detect_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "webp": "image/webp",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "pdf": "application/pdf",
    }.get(ext, "image/jpeg")


def _empty(*, error: str, declared: int | None = None) -> IncomeProofAnalysis:
    return IncomeProofAnalysis(
        forecasted_monthly_income_inr=None,
        declared_monthly_income_inr=declared,
        accuracy_pct=None,
        verdict="unknown",
        confidence=0,
        distinct_income_sources=0,
        error=error,
    )


async def analyse_income_proofs(
    *,
    proofs: list[tuple[str, bytes]],
    declared_monthly_income_inr: int | None,
    applicant_name: str | None = None,
    co_applicant_name: str | None = None,
    business_type: str | None = None,
    claude: Any | None = None,
) -> IncomeProofAnalysis:
    """Run a single Opus-4.7 vision call across all income-proof images.

    Returns a structured analysis. The function never raises on Claude /
    JSON failures — instead it returns an empty analysis with `error` set so
    the L5 orchestrator can record the failure mode without 500-ing the
    whole verification level.
    """
    if not proofs:
        return _empty(error="no_proof_artifacts", declared=declared_monthly_income_inr)

    # Drop unsupported PDFs — Claude vision needs raster image blocks.
    image_blocks: list[dict[str, Any]] = []
    skipped: list[str] = []
    for filename, data in proofs:
        mt = _detect_media_type(filename)
        if mt == "application/pdf" or not data:
            skipped.append(filename)
            continue
        image_blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mt,
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            }
        )

    if not image_blocks:
        return _empty(
            error=f"no_image_blocks_after_filtering (skipped={','.join(skipped) or 'none'})",
            declared=declared_monthly_income_inr,
        )

    if claude is None:
        from app.services.claude import get_claude_service

        claude = get_claude_service()

    context_lines = [
        f"Applicant: {applicant_name or '—'}",
        f"Co-applicant: {co_applicant_name or '—'}",
        f"Business type per CAM: {business_type or '—'}",
        f"Declared monthly household income (BCM): "
        f"₹{declared_monthly_income_inr:,}"
        if declared_monthly_income_inr
        else "Declared monthly household income (BCM): NOT PROVIDED",
        f"Number of proof artifacts attached: {len(image_blocks)}"
        + (f" (skipped {len(skipped)} non-image: {', '.join(skipped)})" if skipped else ""),
        "",
        "Forecast monthly income from the proofs and produce the JSON verdict.",
    ]
    text_block = {"type": "text", "text": "\n".join(context_lines)}

    try:
        message = await claude.invoke(
            tier="opus",
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": [*image_blocks, text_block]}],
            cache_system=True,
            max_tokens=1500,
        )
    except Exception as exc:  # noqa: BLE001 — vision API errors must not 500 the level
        _log.exception("income_proof_analyzer Opus call failed")
        return _empty(
            error=f"opus_call_failed: {exc}",
            declared=declared_monthly_income_inr,
        )

    raw = claude.extract_text(message)
    m = _JSON_RE.search(raw)
    if not m:
        return _empty(
            error=f"json_parse_failed_no_match: {raw[:200]!r}",
            declared=declared_monthly_income_inr,
        )
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return _empty(
            error=f"json_parse_failed: {exc} :: {raw[:200]!r}",
            declared=declared_monthly_income_inr,
        )

    from app.services.claude import MODELS

    model = MODELS.get("opus", "opus")
    usage = claude.usage_dict(message)
    cost = float(claude.cost_usd(model, usage))

    def _maybe_int(v: Any) -> int | None:
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _maybe_float(v: Any) -> float | None:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return IncomeProofAnalysis(
        forecasted_monthly_income_inr=_maybe_int(parsed.get("forecasted_monthly_income_inr")),
        declared_monthly_income_inr=declared_monthly_income_inr,
        accuracy_pct=_maybe_float(parsed.get("accuracy_pct")),
        verdict=str(parsed.get("verdict") or "unknown"),
        confidence=_maybe_int(parsed.get("confidence")) or 0,
        distinct_income_sources=_maybe_int(parsed.get("distinct_income_sources")) or 0,
        proof_types_detected=[
            str(t) for t in (parsed.get("proof_types_detected") or [])
        ],
        per_source_forecast_inr={
            str(k): _maybe_int(v) or 0
            for k, v in (parsed.get("per_source_forecast_inr") or {}).items()
        },
        narrative=str(parsed.get("narrative") or ""),
        concerns=[str(c) for c in (parsed.get("concerns") or [])],
        assumptions=[str(a) for a in (parsed.get("assumptions") or [])],
        images_examined=len(image_blocks),
        cost_usd=cost,
        model=model,
    )


def make_extraction_result(analysis: IncomeProofAnalysis) -> ExtractionResult:
    """Wrap the structured analysis as an ExtractionResult so the L5
    orchestrator can persist it on the same code path it uses for other
    extractor outputs."""
    return ExtractionResult(
        status=(
            ExtractionStatus.FAILED
            if analysis.error and not analysis.proof_types_detected
            else ExtractionStatus.SUCCESS
        ),
        schema_version="1.0",
        data=analysis.to_dict(),
        error_message=analysis.error,
    )
