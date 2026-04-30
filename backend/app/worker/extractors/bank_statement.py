"""BankStatementExtractor — extracts key fields from a bank statement PDF."""

from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from typing import Any

import pdfplumber

from app.enums import ExtractionStatus
from app.worker.extractors.base import BaseExtractor, ExtractionResult

# Patterns use \s* around the colon so they tolerate "Label:value", "Label: value",
# "Label : value" (real SBI format) and mixed whitespace.
_RE_ACCOUNT_NUMBER = re.compile(
    r"(?:Account|A/?C|Acct)[ \t]*(?:No\.?|Number)?[ \t]*:[ \t]*(\d{8,20})", re.IGNORECASE
)
# Inline-whitespace only after colon — prevents "Welcome:\n<next line>" from
# pulling in the next header line as the holder value.
_RE_ACCOUNT_HOLDER = re.compile(
    r"(?:Account[ \t]*Holder|Customer[ \t]*Name)[ \t]*:[ \t]+([^\n\r]+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_IFSC = re.compile(
    r"IFSC(?:[ \t]*Code)?[ \t]*:?[ \t]*([A-Z]{4}0[A-Z0-9]{6})", re.IGNORECASE
)
_RE_OPENING_BALANCE = re.compile(
    r"Opening[ \t]*Balance[ \t]*:?[ \t]*([\d,]+(?:\.\d{2})?)", re.IGNORECASE
)
_RE_CLOSING_BALANCE = re.compile(
    r"(?:Closing[ \t]*Balance|Clear[ \t]*Balance)[ \t]*:?[ \t]*([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)
_RE_PERIOD = re.compile(
    r"(?:Period|Statement[ \t]*From)[ \t]*:?[ \t]*([^\n\r]+)", re.IGNORECASE
)
# Transaction lines: real-world Indian bank statements use:
#   - "01.10.2025  INF/...  727.00  2119.48"               (ICICI dotted)
#   - "1   01.10.2025  INF/...  727.00  2119.48"           (ICICI w/ S.No prefix)
#   - "04/09/2025 ..." or "2025-09-04 ..."                 (HDFC/SBI hyphen/slash)
# Tolerate optional leading S.No (1-4 digits + whitespace), 1-2 digit day/month
# components, and ``.`` / ``-`` / ``/`` separators. Capture group 1 is the date
# token so callers can parse it for coverage-period analysis.
_RE_TRANSACTION_LINE = re.compile(
    r"^\s*(?:\d{1,4}\s+)?(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})\b"
)
# Fallback: a standalone name line near the top of the statement (e.g. "Mr. Ajay Singh").
_RE_NAME_LINE = re.compile(
    r"^\s*(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+([A-Z][A-Za-z\s]{2,60}?)\s*$"
)


def _parse_tx_date(token: str) -> date | None:
    """Parse a transaction-line date token in DMY, YMD, or MDY order.

    Indian bank statements predominantly use DMY (``01.10.2025`` = 1 Oct 2025);
    SBI/HDFC e-statements occasionally emit YMD (``2025-10-01``). MDY is rare
    but accepted as a tertiary fallback so a stray US-formatted statement
    doesn't silently drop dates.

    Returns ``None`` if no permutation produces a real calendar date.
    """
    parts = re.split(r"[-/.]", token)
    if len(parts) != 3:
        return None
    try:
        a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None

    def _y(yr: int) -> int:
        # 2-digit year heuristic: 00-79 → 20xx, 80-99 → 19xx. Indian bank
        # statements rarely span 1980-1999 so the bias is safe.
        if yr < 100:
            return 2000 + yr if yr < 80 else 1900 + yr
        return yr

    candidates: list[tuple[int, int, int]] = []
    # DMY (most common Indian format)
    if 1 <= a <= 31 and 1 <= b <= 12:
        candidates.append((_y(c), b, a))
    # YMD (ISO)
    if a > 31 and 1 <= b <= 12 and 1 <= c <= 31:
        candidates.append((_y(a), b, c))
    # MDY (rare US format)
    if 1 <= a <= 12 and 1 <= b <= 31:
        candidates.append((_y(c), a, b))

    for y, m, d in candidates:
        try:
            return date(y, m, d)
        except ValueError:
            continue
    return None


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


class BankStatementExtractor(BaseExtractor):
    extractor_name = "bank_statement"
    schema_version = "1.0"

    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult:
        try:
            with pdfplumber.open(BytesIO(body_bytes)) as pdf:
                total_pages = len(pdf.pages)
                pages_text = [page.extract_text() or "" for page in pdf.pages]
        except Exception as exc:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=type(self).schema_version,
                data={},
                error_message=f"pdfplumber failed to open {filename!r}: {exc}",
            )

        full_text = "\n".join(pages_text)

        if not full_text.strip():
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=type(self).schema_version,
                data={},
                error_message=f"No text extracted from {filename!r}.",
            )

        account_number = _first_match(_RE_ACCOUNT_NUMBER, full_text)
        account_holder = _first_match(_RE_ACCOUNT_HOLDER, full_text)
        # Fallback: scan the first 20 lines for a "Mr./Ms. <Name>" line.
        if not account_holder:
            for line in full_text.splitlines()[:20]:
                m = _RE_NAME_LINE.match(line)
                if m:
                    account_holder = m.group(1).strip()
                    break
        ifsc = _first_match(_RE_IFSC, full_text)
        period = _first_match(_RE_PERIOD, full_text)
        opening_balance = _first_match(_RE_OPENING_BALANCE, full_text)
        closing_balance = _first_match(_RE_CLOSING_BALANCE, full_text)

        transaction_lines: list[str] = []
        tx_dates: list[date] = []
        for raw_line in full_text.splitlines():
            stripped = raw_line.strip()
            m = _RE_TRANSACTION_LINE.match(stripped)
            if not m:
                continue
            transaction_lines.append(stripped)
            parsed = _parse_tx_date(m.group(1))
            if parsed is not None:
                tx_dates.append(parsed)

        # Coverage period: span of the parsed transaction dates. Used by L2
        # to enforce the 6-month statement minimum (and by the FE to prompt
        # the user with "X months available, Y more needed").
        period_start: str | None = None
        period_end: str | None = None
        months_of_coverage: float | None = None
        if tx_dates:
            d_min, d_max = min(tx_dates), max(tx_dates)
            period_start = d_min.isoformat()
            period_end = d_max.isoformat()
            months_of_coverage = round((d_max - d_min).days / 30.4375, 1)

        data: dict[str, Any] = {
            "account_holder": account_holder,
            "account_number": account_number,
            "ifsc": ifsc,
            "period": period,
            "period_start": period_start,
            "period_end": period_end,
            "months_of_coverage": months_of_coverage,
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "transaction_lines": transaction_lines,
            "total_pages": total_pages,
            "full_text_length": len(full_text),
        }

        warnings: list[str] = []
        if not account_number and not account_holder:
            warnings.append("no_account_header_detected")
            status = ExtractionStatus.PARTIAL
        else:
            status = ExtractionStatus.SUCCESS

        return ExtractionResult(
            status=status,
            schema_version=type(self).schema_version,
            data=data,
            warnings=warnings,
        )
