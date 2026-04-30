"""EquifaxHtmlExtractor — parses an Equifax-style HTML credit report.

Supports two schemas in the wild:

1. **Fixture/test schema**: elements with classes `.CreditScore`, `.Name`,
   `.DOB`, `.PAN`, and tables with ids `AccountsTable` / `InquiriesTable` /
   `AddressTable`. Simple row-per-account layout.

2. **Real V2.0 bureau output** (e.g. `EQUIFAX_CREDIT_REPORT*.html`):
   - `<h4 class="displayscore">834</h4>` (or "-1" for consumer-not-found)
   - `<h4>Consumer Name: AJAY SINGH</h4>` plain text
   - `<table id="accountTable">` (lower-case a) with multi-row account blocks
   - `<table id="summaryTable">` with OVERALL + "Number of Open Accounts"
   - PAN/DOB embedded as text `PAN:OWLPS6441C`, `DOB:17-11-2001`
   - HIT CODE 00 / "Consumer record not found" for no-match runs

Extractor tries the real schema first (superset) then falls back to the
fixture selectors so existing tests continue to pass.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.enums import ExtractionStatus
from app.worker.extractors.base import BaseExtractor, ExtractionResult

_RE_PAN = re.compile(r"PAN\s*:\s*([A-Z]{5}[0-9]{4}[A-Z])", re.IGNORECASE)
_RE_DOB = re.compile(r"DOB\s*:\s*(\d{2}[-/]\d{2}[-/]\d{4})")
_RE_CONSUMER_NAME = re.compile(
    r"Consumer(?:'s)?\s*(?:Full\s*)?Name\s*:\s*"
    r"([A-Z][A-Z.]*(?:\s+[A-Z][A-Z.]*)*?)"
    r"(?=\s*(?:null|PAN:|DOB:|Previous|Alias|Personal|</|$))",
    re.IGNORECASE,
)
_RE_OPEN_ACCOUNTS = re.compile(
    r"Number\s*of\s*Open\s*Accounts\s*:?\s*(\d+)", re.IGNORECASE
)
_RE_PAST_DUE_ACCOUNTS = re.compile(
    r"Number\s*of\s*Past\s*Due\s*Accounts\s*:?\s*(\d+)", re.IGNORECASE
)
# MUST require a colon directly after "Balance" — the bureau report has a
# second header column "Total Outstanding Balance 60+ DPD Accounts:" (no
# colon between "Balance" and "60+") which the prior optional-colon pattern
# happily captured as ``60``, masking the real Rs. 2,64,230 outstanding
# balance and producing nonsense PASS verdicts on Section A #5. The colon
# anchor + optional ``Rs.`` prefix lets us match every observed format
# ("Total Outstanding Balance: Rs. 2,64,230" / "...: 264230" / "...: 264230.00")
# while skipping the header-collision line cleanly.
_RE_TOTAL_BALANCE = re.compile(
    r"Total\s+Outstanding\s+Balance\s*:\s*(?:Rs\.?\s*)?([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)


def _text(tag: Any) -> str:
    return tag.get_text(strip=True) if tag else ""


def _try_int(value: str) -> int | str:
    cleaned = value.replace(",", "").strip()
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return value


def _pick_display_score(soup: Any) -> int | None:
    """Pick the most meaningful displayscore value.

    Real Equifax reports emit multiple score tags (Microfinance Risk Score,
    Equifax Risk Score 4.0). Positive values are actual credit scores.
    -1 is the bureau's explicit "no record on file" sentinel (NTC / consumer
    not found) — itself a meaningful signal that should NOT be silently
    dropped; downstream decisioning needs to see it.

    Rule: prefer any positive score (max) if present; otherwise return the
    highest sentinel value (typically -1). Only return None when no parseable
    score tags exist at all.
    """
    positive: int | None = None
    sentinel: int | None = None
    for tag in soup.find_all(class_="displayscore"):
        raw = _text(tag)
        try:
            value = int(raw)
        except (ValueError, TypeError):
            continue
        if value >= 0:
            if positive is None or value > positive:
                positive = value
        else:
            if sentinel is None or value > sentinel:
                sentinel = value
    return positive if positive is not None else sentinel


def _parse_table_rows(table: Any, columns: list[str]) -> list[dict[str, Any]]:
    """Parse tbody rows of *table* into a list of dicts keyed by *columns*."""
    rows: list[dict[str, Any]] = []
    if table is None:
        return rows
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < len(columns):
            continue
        rows.append(dict(zip(columns, cells, strict=False)))
    return rows


def _parse_real_account_table(table: Any) -> list[dict[str, Any]]:
    """Real accountTable parser.

    Each account block starts with a single-cell TR holding the product type
    (e.g. "RETAIL", "CREDIT CARD", "AGRICULTURE AND ALLIED"). We group rows
    under that header and pull key fields from the concatenated block text
    using simple "Label : Value" regex. We *do* include blocks with only
    product_type so the caller can count open accounts reliably.
    """
    accounts: list[dict[str, Any]] = []
    if table is None:
        return accounts

    rows = table.find_all("tr")

    def _finalise(header: str | None, buf: list[str]) -> None:
        if header is None and not buf:
            return
        block_text = " ".join(buf)
        acc: dict[str, Any] = {"product_type": header}
        for label, key, pattern in (
            ("institution", "institution", r"Institution\s*:\s*([A-Za-z0-9& .,\-]+?)(?=\s+[A-Z][A-Za-z ]{2,30}?\s*:|$)"),
            ("type", "type", r"\bType\s*:\s*([A-Za-z][A-Za-z ]{2,40}?)(?=\s+[A-Z][A-Za-z ]{2,30}?\s*:|$)"),
            ("balance", "balance", r"Balance\s*:\s*([\d,.]+)"),
            ("status", "status", r"Account\s*status\s*:\s*([A-Za-z ]+?)(?=\s+[A-Z][A-Za-z ]{2,30}?\s*:|$)"),
            ("date_opened", "date_opened", r"Date\s*Opened\s*:\s*(\d{2}[-/]\d{2}[-/]\d{4})"),
            ("date_reported", "date_reported", r"Date\s*Reported\s*:\s*(\d{2}[-/]\d{2}[-/]\d{4})"),
        ):
            m = re.search(pattern, block_text, re.IGNORECASE)
            if m:
                acc[key] = m.group(1).strip()
        if "balance" in acc:
            acc["balance"] = _try_int(acc["balance"])
        accounts.append(acc)

    header: str | None = None
    buf: list[str] = []
    for tr in rows:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        if len(cells) == 1 and len(cells[0]) < 60 and cells[0].isupper():
            # New product-type header — close out previous block.
            _finalise(header, buf)
            header = cells[0]
            buf = []
        else:
            buf.extend(cells)
    _finalise(header, buf)
    # Drop stub entries with no fields beyond product_type (likely history rows).
    return [a for a in accounts if a.get("product_type") and len(a) >= 2 or a.get("institution")]


class EquifaxHtmlExtractor(BaseExtractor):
    extractor_name = "equifax"
    schema_version = "1.0"

    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult:
        if not body_bytes:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=type(self).schema_version,
                data={},
                error_message=f"Empty body for {filename!r}.",
            )

        try:
            soup = BeautifulSoup(body_bytes, "lxml")
        except Exception as exc:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=type(self).schema_version,
                data={},
                error_message=f"BeautifulSoup failed to parse {filename!r}: {exc}",
            )

        full_text = soup.get_text(" ", strip=True)

        # --- Personal info ---
        # Fixture schema first (class-based).
        name_tag = soup.select_one("#PersonalInfo .Name") or soup.find(class_="Name")
        dob_tag = soup.select_one("#PersonalInfo .DOB") or soup.find(class_="DOB")
        pan_tag = soup.select_one("#PersonalInfo .PAN") or soup.find(class_="PAN")

        name = _text(name_tag) or None
        dob = _text(dob_tag) or None
        pan = _text(pan_tag) or None

        # Real-schema fallback: regex scan on the flattened text.
        if not name:
            m = _RE_CONSUMER_NAME.search(full_text)
            if m:
                name = m.group(1).strip()
        if not pan:
            m = _RE_PAN.search(full_text)
            if m:
                pan = m.group(1).strip().upper()
        if not dob:
            m = _RE_DOB.search(full_text)
            if m:
                dob = m.group(1).strip()

        customer_info: dict[str, str | None] = {"name": name, "dob": dob, "pan": pan}

        # --- Credit score ---
        # Fixture: .CreditScore / #CreditScore. Real: .displayscore (pick max non-neg).
        score_tag = (
            soup.select_one(".CreditScore")
            or soup.find(class_="creditscore")
            or soup.find(id="CreditScore")
        )
        credit_score: int | None = None
        if score_tag:
            try:
                credit_score = int(_text(score_tag))
            except (ValueError, TypeError):
                credit_score = None
        if credit_score is None:
            credit_score = _pick_display_score(soup)

        # --- Accounts ---
        # Fixture: <table id="AccountsTable">. Real: <table id="accountTable">.
        accounts_table = soup.find("table", id="AccountsTable")
        accounts: list[dict[str, Any]] = []
        if accounts_table is not None:
            raw = _parse_table_rows(
                accounts_table, ["lender", "type", "opened", "balance", "status"]
            )
            for row in raw:
                row["balance"] = _try_int(row.get("balance", ""))
                accounts.append(row)
        else:
            real_table = soup.find("table", id="accountTable")
            accounts = _parse_real_account_table(real_table)

        # --- Inquiries / Enquiries ---
        # Test fixtures use ``<table id="InquiriesTable">``; real Equifax CIRs
        # have NO id on the enquiries table — they label the section with a
        # plain "Enquiries :" header text and put the data into the next
        # ``<table class="dashTable">``. Try the fixture path first, then
        # fall back to text-anchored discovery so production reports score
        # the rule correctly. Columns in the real format are
        # [institution, date, time, purpose] (per observed Equifax export);
        # we map ``lender`` ← institution to keep downstream resolvers happy.
        inquiries_table = soup.find("table", id="InquiriesTable")
        if inquiries_table is not None:
            inquiries = _parse_table_rows(
                inquiries_table, ["date", "lender", "purpose"]
            )
        else:
            inquiries = []
            enq_anchor = soup.find(
                string=lambda s: s and "enquiries" in s.lower() and ":" in s
            )
            if enq_anchor is not None:
                # Walk forward and pick up consecutive dashTable rows whose
                # second column parses as a date — stop when we leave the
                # enquiries block.
                node: Any = enq_anchor
                while True:
                    table = node.find_next("table") if hasattr(node, "find_next") else None
                    if table is None:
                        break
                    cls = table.get("class") or []
                    if "dashTable" in cls:
                        for tr in table.find_all("tr"):
                            cells = [
                                td.get_text(strip=True)
                                for td in tr.find_all(["td", "th"])
                            ]
                            # Skip header / pad rows; need at least
                            # institution + date + time/purpose.
                            if len(cells) < 3:
                                continue
                            inst, dt, *rest = cells
                            if not inst or not dt:
                                continue
                            # Date sniff: ``dd-mm-yyyy`` / ``dd/mm/yyyy`` /
                            # ``yyyy-mm-dd``. Stop if no date pattern, the
                            # table is something else.
                            if not re.match(
                                r"^\s*(?:\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})", dt
                            ):
                                # Probably hit a different section table —
                                # bail out of the enquiries walk.
                                inquiries = inquiries or []
                                break
                            entry: dict[str, Any] = {
                                "lender": inst,
                                "date": dt,
                            }
                            if rest:
                                # rest[0] is time, rest[1] is purpose
                                if len(rest) > 1:
                                    entry["purpose"] = rest[1]
                                else:
                                    entry["purpose"] = rest[0]
                            inquiries.append(entry)
                        # Continue walking — there may be more dashTables in
                        # the enquiries block (rare, but defensive).
                    # Stop when we run far past the enquiries section.
                    node = table
                    # Heuristic stop: if we've walked 6 tables without
                    # finding a dashTable that has a date row, we're past
                    # the section. Avoid infinite loops on malformed HTML.
                    if len(inquiries) > 0 and "dashTable" not in cls:
                        break

        # --- Addresses ---
        address_table = soup.find("table", id="AddressTable")
        addresses = _parse_table_rows(address_table, ["address", "city", "pin", "type"])

        # --- Summary ---
        # Fixture counts directly; real schema pulls from summaryTable text.
        if accounts and isinstance(accounts[0], dict) and "status" in accounts[0]:
            open_count = sum(1 for a in accounts if a.get("status") == "Active")
            closed_count = sum(1 for a in accounts if a.get("status") == "Closed")
            total = len(accounts)
        else:
            m_open = _RE_OPEN_ACCOUNTS.search(full_text)
            open_count = int(m_open.group(1)) if m_open else 0
            closed_count = 0
            total = len(accounts)
        summary: dict[str, int] = {
            "total_accounts": total,
            "open_accounts": open_count,
            "closed_accounts": closed_count,
        }
        m_past_due = _RE_PAST_DUE_ACCOUNTS.search(full_text)
        if m_past_due:
            summary["past_due_accounts"] = int(m_past_due.group(1))
        m_total_bal = _RE_TOTAL_BALANCE.search(full_text)
        if m_total_bal:
            summary["total_outstanding_balance"] = m_total_bal.group(1)

        # Detect "bureau returned no record" — any of:
        #  - HIT CODE 00 in text
        #  - "Consumer record not found" in text
        #  - displayscore <= 0 (explicit NTC sentinel; real files use -1)
        # This is a COMPLETE bureau response (the applicant is NTC / new-to-
        # credit or not in the bureau), not an extraction failure. The raw
        # sentinel score (e.g. -1) is preserved in data.credit_score so
        # downstream decisioning can distinguish "bureau said no record" (-1)
        # from "we couldn't find a score in the HTML" (null). bureau_hit
        # reflects the same signal.
        full_text_lower = full_text.lower()
        bureau_no_record = (
            "consumer record not found" in full_text_lower
            or re.search(r"hit\s*code\s*:\s*0+\b", full_text_lower) is not None
            or (credit_score is not None and credit_score <= 0)
        )

        # Surface both ``inquiries`` (US spelling, kept for back-compat with
        # any existing consumers / tests) and ``enquiries`` (British, what
        # ``scoring_model.r_a08_enquiries_3m`` reads). The two were drifting
        # — extractor wrote one, resolver read the other, and rule #8 was
        # silently passing every applicant as "no enquiries logged" no
        # matter how many recent hits the bureau actually had.
        data: dict[str, Any] = {
            "customer_info": customer_info,
            "credit_score": credit_score,
            "accounts": accounts,
            "inquiries": inquiries,
            "enquiries": inquiries,
            "addresses": addresses,
            "summary": summary,
            "bureau_hit": not bureau_no_record,
        }

        # --- Status ---
        warnings: list[str] = []
        if bureau_no_record:
            # Bureau returned a complete "no match" response. The no-record
            # signal is carried by data.bureau_hit=False and the preserved
            # -1 credit_score — no warning is emitted, because "bureau
            # replied cleanly" is not a problem for the reviewer to act on.
            status = ExtractionStatus.SUCCESS
        else:
            # Bureau returned a report. Primary output = credit_score + ≥1
            # account. Non-critical issues stay in warnings[] without
            # flipping SUCCESS to PARTIAL.
            if credit_score is None:
                warnings.append("missing_credit_score")
            if not accounts:
                warnings.append("no_accounts")
            has_primary = credit_score is not None and bool(accounts)
            status = ExtractionStatus.SUCCESS if has_primary else ExtractionStatus.PARTIAL

        return ExtractionResult(
            status=status,
            schema_version=type(self).schema_version,
            data=data,
            warnings=warnings,
        )
