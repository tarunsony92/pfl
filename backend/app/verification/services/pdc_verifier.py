"""Claude vision verifier for the PDC (post-dated cheque) artifact at L5.5.

The borrower hands over a post-dated cheque alongside the NACH e-mandate as a
back-up EMI-recovery instrument. L5.5 needs to confirm:

1. An artifact tagged ``PDC_CHEQUE`` is on file
2. The image actually depicts a bank cheque (not a random photo or scan)

A single Claude Sonnet vision call gives both signals plus side-extracted
fields (bank, IFSC, account number, account-holder name, signature presence)
that the FE / report can surface without an OCR pipeline.

Cost: ~$0.003-$0.006 per case (one image, ~100 input tokens, <300 output
tokens). Cheap enough to run unconditionally on every L5.5 trigger when a
PDC artifact is present.

Failures are non-fatal — if the vision call errors, we return a degraded
result with ``vision_error`` set so the L5.5 engine can downgrade the
``pdc_present`` issue to WARNING (not CRITICAL) and let the case proceed.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


_PDC_SYSTEM = """You are a PFL Finance underwriting assistant verifying that
an uploaded artifact is a valid bank cheque suitable for use as a post-dated
cheque (PDC) — a back-up EMI-recovery instrument the borrower hands over with
their NACH e-mandate.

Look for: bank logo, MICR code line at the bottom, "Pay" / "Rupees" /
"Or Bearer" labels, account-holder signature line, IFSC code, account number,
chequebook serial number. The image may be a phone photo (often with a GPS
overlay) or a scanned image.

Return ONLY valid JSON matching this schema, no prose, no markdown:

{
  "is_cheque": <bool>,
  "confidence": <0..100 integer — your confidence the image is a valid cheque>,
  "bank_name": <string or null>,
  "ifsc": <string or null — 11-char IFSC code if visible>,
  "account_number": <string or null — full or masked account number printed on the cheque>,
  "account_holder": <string or null — printed name on the cheque>,
  "cheque_number": <string or null — leading 6-digit number from the MICR line>,
  "signature_present": <bool — true if the signature line shows ink>,
  "is_cancelled": <bool — true if "CANCELLED" / "CANCELED" is stamped or written across the cheque>,
  "concerns": [<short string list — anything that should disqualify this as a PDC, e.g. "no MICR line", "image is blurry", "looks like a deposit slip not a cheque">]
}
"""

_PDC_USER_INSTRUCTION = (
    "Verify whether this uploaded artifact is a bank cheque the borrower "
    "could lodge as a PDC. Extract the printed fields you can see. Be "
    "conservative — if you cannot clearly identify it as a cheque, set "
    "is_cheque=false and explain in concerns."
)


@dataclass
class PDCVerifyResult:
    """Outcome of one PDC vision verification."""

    is_cheque: bool
    confidence: int  # 0..100
    bank_name: str | None
    ifsc: str | None
    account_number: str | None
    account_holder: str | None
    cheque_number: str | None
    signature_present: bool
    is_cancelled: bool
    concerns: list[str]
    cost_usd: float
    model: str
    raw: dict[str, Any]
    vision_error: str | None = None

    def to_evidence(self) -> dict[str, Any]:
        """Serialise into a LevelIssue evidence dict."""
        return {
            "is_cheque": self.is_cheque,
            "confidence": self.confidence,
            "bank_name": self.bank_name,
            "ifsc": self.ifsc,
            "account_number": self.account_number,
            "account_holder": self.account_holder,
            "cheque_number": self.cheque_number,
            "signature_present": self.signature_present,
            "is_cancelled": self.is_cancelled,
            "concerns": self.concerns,
            "vision_error": self.vision_error,
            "model": self.model,
            "cost_usd": self.cost_usd,
        }


def _detect_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "webp": "image/webp",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "pdf": "application/pdf",
    }.get(ext, "image/jpeg")


def _extract_json(text: str) -> dict[str, Any]:
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"no JSON in response: {text[:200]!r}")
    return json.loads(m.group(0))


def _empty_result(*, vision_error: str | None = None, model: str = "") -> PDCVerifyResult:
    return PDCVerifyResult(
        is_cheque=False,
        confidence=0,
        bank_name=None,
        ifsc=None,
        account_number=None,
        account_holder=None,
        cheque_number=None,
        signature_present=False,
        is_cancelled=False,
        concerns=[],
        cost_usd=0.0,
        model=model,
        raw={},
        vision_error=vision_error,
    )


async def verify_pdc_cheque(
    *,
    filename: str,
    image_bytes: bytes,
    claude: Any | None = None,
) -> PDCVerifyResult:
    """Run a single Claude Sonnet vision call against the PDC artifact.

    Returns a degraded ``PDCVerifyResult`` (with ``vision_error`` set) on any
    Claude/JSON failure so the L5.5 engine never crashes the verification
    level on a transient API hiccup.
    """
    if not image_bytes:
        return _empty_result(vision_error="empty_image_bytes")

    media_type = _detect_media_type(filename)
    if media_type == "application/pdf":
        # Claude vision doesn't accept PDFs as image blocks. The L5.5 engine
        # will treat a PDF-format PDC as "present but not vision-verified" —
        # WARNING severity rather than CRITICAL, MD can still waive.
        return _empty_result(vision_error="pdf_not_supported_by_vision")

    if claude is None:
        from app.services.claude import get_claude_service

        claude = get_claude_service()

    image_block = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(image_bytes).decode("ascii"),
        },
    }
    content = [image_block, {"type": "text", "text": _PDC_USER_INSTRUCTION}]

    try:
        message = await claude.invoke(
            tier="sonnet",
            system=_PDC_SYSTEM,
            messages=[{"role": "user", "content": content}],
            cache_system=True,
            max_tokens=512,
        )
    except Exception as exc:  # noqa: BLE001 — vision API errors must not 500 the level
        _log.exception("pdc_verifier vision call failed for %s", filename)
        return _empty_result(vision_error=f"vision_call_failed: {exc}")

    raw_text = claude.extract_text(message)
    try:
        parsed = _extract_json(raw_text)
    except (ValueError, json.JSONDecodeError) as exc:
        return _empty_result(
            vision_error=f"json_parse_failed: {exc} :: {raw_text[:200]!r}"
        )

    from app.services.claude import MODELS

    model = MODELS.get("sonnet", "sonnet")
    usage = claude.usage_dict(message)
    cost = float(claude.cost_usd(model, usage))

    def _str_or_none(v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    concerns_raw = parsed.get("concerns") or []
    concerns = [str(c) for c in concerns_raw if c] if isinstance(concerns_raw, list) else []

    return PDCVerifyResult(
        is_cheque=bool(parsed.get("is_cheque")),
        confidence=int(parsed.get("confidence") or 0),
        bank_name=_str_or_none(parsed.get("bank_name")),
        ifsc=_str_or_none(parsed.get("ifsc")),
        account_number=_str_or_none(parsed.get("account_number")),
        account_holder=_str_or_none(parsed.get("account_holder")),
        cheque_number=_str_or_none(parsed.get("cheque_number")),
        signature_present=bool(parsed.get("signature_present")),
        is_cancelled=bool(parsed.get("is_cancelled")),
        concerns=concerns,
        cost_usd=cost,
        model=model,
        raw=parsed,
    )


# ---------------------------------------------------------------------------
# PDC ↔ bank statement cross-validation
# ---------------------------------------------------------------------------


def _normalize_account(s: str | None) -> str:
    """Strip non-digits + uppercase masking chars so masked ('******2084') and
    full ('1348002084') account numbers can be compared on the visible tail."""
    if not s:
        return ""
    return "".join(ch for ch in str(s) if ch.isdigit() or ch in "*Xx")


def _account_tails_match(a: str | None, b: str | None, tail: int = 4) -> bool:
    """True if the last ``tail`` digits of both account numbers are identical
    (ignoring masking characters). Used because cheque MICR usually shows the
    full number while a bank statement may print a masked variant (or vice
    versa) — but the trailing 4 digits are nearly always visible in both."""
    na = _normalize_account(a).rstrip("*Xx")
    nb = _normalize_account(b).rstrip("*Xx")
    if not na or not nb:
        return False
    # Take only the trailing digits of each.
    da = "".join(ch for ch in na if ch.isdigit())[-tail:]
    db = "".join(ch for ch in nb if ch.isdigit())[-tail:]
    return bool(da) and bool(db) and da == db


def _normalize_ifsc(s: str | None) -> str:
    if not s:
        return ""
    return str(s).strip().upper().replace(" ", "")


def _name_similarity(a: str | None, b: str | None) -> int:
    """Fuzzy similarity 0..100 between two names. Lazy-imports rapidfuzz so
    this module stays cheap when cross-validation is skipped."""
    if not a or not b:
        return 0
    try:
        from rapidfuzz import fuzz

        return int(fuzz.token_set_ratio(str(a), str(b)))
    except Exception:  # noqa: BLE001
        return 0


@dataclass
class PDCMatchResult:
    """Outcome of cross-validating the PDC vision read against the bank
    statement extraction. The L5.5 engine uses ``severity`` to decide whether
    to raise a CRITICAL (hard mismatch on IFSC / account) or WARNING (name
    fuzz, or one side is missing the field)."""

    severity: str  # 'pass' | 'warning' | 'critical' | 'skipped'
    mismatches: list[str]  # one human-readable line per disagreement
    cheque_ifsc: str | None
    statement_ifsc: str | None
    cheque_account_tail: str | None
    statement_account_tail: str | None
    cheque_holder: str | None
    statement_holder: str | None
    name_similarity: int  # 0..100, 0 if either side missing
    skip_reason: str | None = None

    def to_evidence(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "mismatches": self.mismatches,
            "cheque_ifsc": self.cheque_ifsc,
            "statement_ifsc": self.statement_ifsc,
            "cheque_account_tail": self.cheque_account_tail,
            "statement_account_tail": self.statement_account_tail,
            "cheque_holder": self.cheque_holder,
            "statement_holder": self.statement_holder,
            "name_similarity": self.name_similarity,
            "skip_reason": self.skip_reason,
        }


def cross_validate_pdc_vs_bank_statement(
    pdc: PDCVerifyResult,
    bank_extraction_data: dict[str, Any] | None,
) -> PDCMatchResult:
    """Compare the cheque (PDC vision read) against the bank statement
    extraction. Catches the operator-error case where the borrower hands in a
    cheque from a different bank account than the one their EMIs will actually
    be debited from — which makes the PDC useless as a recovery instrument.

    Severity rules:
      * IFSC mismatch (both populated, different)              → CRITICAL
      * Account-tail mismatch (both populated, last 4 differ)  → CRITICAL
      * Account-holder name fuzz < 70 (both populated)         → WARNING
      * Either side missing the field                          → SKIPPED with reason
      * Everything matches                                     → PASS
    """

    def _last4(num: str | None) -> str | None:
        if not num:
            return None
        digits = "".join(ch for ch in str(num) if ch.isdigit())
        return digits[-4:] if digits else None

    cheque_ifsc = _normalize_ifsc(pdc.ifsc) or None
    cheque_acc_tail = _last4(pdc.account_number)
    cheque_holder = pdc.account_holder

    if not isinstance(bank_extraction_data, dict):
        return PDCMatchResult(
            severity="skipped",
            mismatches=[],
            cheque_ifsc=cheque_ifsc,
            statement_ifsc=None,
            cheque_account_tail=cheque_acc_tail,
            statement_account_tail=None,
            cheque_holder=cheque_holder,
            statement_holder=None,
            name_similarity=0,
            skip_reason="bank_statement_extraction_unavailable",
        )

    statement_ifsc = _normalize_ifsc(bank_extraction_data.get("ifsc")) or None
    statement_acc_tail = _last4(bank_extraction_data.get("account_number"))
    statement_holder = bank_extraction_data.get("account_holder") or None

    mismatches: list[str] = []
    severity = "pass"

    # IFSC check
    if cheque_ifsc and statement_ifsc:
        if cheque_ifsc != statement_ifsc:
            mismatches.append(
                f"IFSC mismatch: cheque {cheque_ifsc} vs bank statement {statement_ifsc}"
            )
            severity = "critical"
    elif not cheque_ifsc and not statement_ifsc:
        mismatches.append("IFSC not present on either cheque or bank statement")
    # Else: only one side has it — recorded but not flagged

    # Account-tail check
    if cheque_acc_tail and statement_acc_tail:
        if cheque_acc_tail != statement_acc_tail:
            mismatches.append(
                f"Account number mismatch: cheque ends in {cheque_acc_tail}, "
                f"bank statement ends in {statement_acc_tail}"
            )
            severity = "critical"

    # Name fuzz (only WARNING — names on cheques are often initials / nicknames)
    sim = _name_similarity(cheque_holder, statement_holder)
    if cheque_holder and statement_holder and sim < 70:
        mismatches.append(
            f"Account-holder name only {sim}% similar: cheque "
            f"'{cheque_holder}' vs bank statement '{statement_holder}'"
        )
        if severity != "critical":
            severity = "warning"

    # Skipped if BOTH key fields (IFSC + account_tail) couldn't be compared.
    skip_reason: str | None = None
    if (
        not (cheque_ifsc and statement_ifsc)
        and not (cheque_acc_tail and statement_acc_tail)
        and severity == "pass"
    ):
        severity = "skipped"
        skip_reason = "no_overlapping_fields"

    return PDCMatchResult(
        severity=severity,
        mismatches=mismatches,
        cheque_ifsc=cheque_ifsc,
        statement_ifsc=statement_ifsc,
        cheque_account_tail=cheque_acc_tail,
        statement_account_tail=statement_acc_tail,
        cheque_holder=cheque_holder,
        statement_holder=statement_holder,
        name_similarity=sim,
        skip_reason=skip_reason,
    )
