"""Tests for EquifaxHtmlExtractor — happy path and degraded paths."""

from pathlib import Path

from app.enums import ExtractionStatus
from app.worker.extractors.equifax import EquifaxHtmlExtractor
from tests.fixtures.builders.equifax_builder import build_equifax_html

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_equifax_extracts_all_sections_happy_path(tmp_path: Path):
    p = build_equifax_html(tmp_path / "eq.html")
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    assert result.status == ExtractionStatus.SUCCESS
    assert result.schema_version == "1.0"
    assert result.warnings == []
    assert result.error_message is None


async def test_equifax_credit_score_is_int(tmp_path: Path):
    p = build_equifax_html(tmp_path / "eq.html", score=769)
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    assert result.data["credit_score"] == 769
    assert isinstance(result.data["credit_score"], int)


async def test_equifax_customer_info(tmp_path: Path):
    p = build_equifax_html(tmp_path / "eq.html")
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    ci = result.data["customer_info"]
    assert ci["name"] == "SEEMA DEVI"
    assert ci["dob"] == "15/03/1985"
    assert ci["pan"] == "ABCDE1234F"


async def test_equifax_accounts_parsed(tmp_path: Path):
    p = build_equifax_html(tmp_path / "eq.html")
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    accounts = result.data["accounts"]
    assert len(accounts) == 2
    assert accounts[0]["lender"] == "ABC Bank"
    assert accounts[0]["status"] == "Active"
    assert accounts[1]["status"] == "Closed"


async def test_equifax_balance_cast_to_int(tmp_path: Path):
    p = build_equifax_html(
        tmp_path / "eq.html",
        accounts=[
            {
                "lender": "Bank A",
                "type": "PL",
                "opened": "2021-01",
                "balance": 30000,
                "status": "Active",
            }
        ],
    )
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    assert result.data["accounts"][0]["balance"] == 30000
    assert isinstance(result.data["accounts"][0]["balance"], int)


async def test_equifax_summary_counts(tmp_path: Path):
    p = build_equifax_html(tmp_path / "eq.html")
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    summary = result.data["summary"]
    assert summary["total_accounts"] == 2
    assert summary["open_accounts"] == 1
    assert summary["closed_accounts"] == 1


async def test_equifax_inquiries_and_addresses(tmp_path: Path):
    p = build_equifax_html(tmp_path / "eq.html")
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    assert len(result.data["inquiries"]) == 1
    assert result.data["inquiries"][0]["lender"] == "PFL Finance"

    assert len(result.data["addresses"]) == 1
    assert result.data["addresses"][0]["city"] == "Delhi"


async def test_equifax_extractor_name_and_schema_version():
    extractor = EquifaxHtmlExtractor()
    assert extractor.extractor_name == "equifax"
    assert extractor.schema_version == "1.0"


# ---------------------------------------------------------------------------
# Degraded: empty body → FAILED
# ---------------------------------------------------------------------------


async def test_equifax_failed_on_empty_body():
    result = await EquifaxHtmlExtractor().extract("empty.html", b"")

    assert result.status == ExtractionStatus.FAILED
    assert result.error_message is not None


# ---------------------------------------------------------------------------
# Degraded: missing credit score → PARTIAL
# ---------------------------------------------------------------------------


async def test_equifax_partial_when_missing_credit_score(tmp_path: Path):
    html = b"""<!DOCTYPE html><html><body>
    <div id="AccountSummary">
      <table id="AccountsTable"><thead><tr><th>Lender</th><th>Type</th>
        <th>Opened</th><th>Balance</th><th>Status</th></tr></thead>
      <tbody><tr><td>Bank X</td><td>PL</td><td>2020</td>
        <td>10000</td><td>Active</td></tr></tbody></table>
    </div></body></html>"""
    result = await EquifaxHtmlExtractor().extract("noscore.html", html)

    assert result.status == ExtractionStatus.PARTIAL
    assert "missing_credit_score" in result.warnings
    assert result.data["credit_score"] is None


# ---------------------------------------------------------------------------
# Degraded: no accounts → PARTIAL
# ---------------------------------------------------------------------------


async def test_equifax_partial_when_no_accounts(tmp_path: Path):
    html = b"""<!DOCTYPE html><html><body>
    <div id="ScoreSection"><span class="CreditScore">700</span></div>
    <table id="AccountsTable"><thead><tr><th>Lender</th><th>Type</th>
      <th>Opened</th><th>Balance</th><th>Status</th></tr></thead>
    <tbody></tbody></table>
    </body></html>"""
    result = await EquifaxHtmlExtractor().extract("noaccounts.html", html)

    assert result.status == ExtractionStatus.PARTIAL
    assert "no_accounts" in result.warnings
    assert result.data["accounts"] == []


# ---------------------------------------------------------------------------
# Edge: empty inquiries list — no warning expected
# ---------------------------------------------------------------------------


async def test_equifax_empty_inquiries_no_warning(tmp_path: Path):
    p = build_equifax_html(tmp_path / "eq.html", inquiries=[])
    result = await EquifaxHtmlExtractor().extract("eq.html", p.read_bytes())

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["inquiries"] == []


# ---------------------------------------------------------------------------
# Bureau "no record" response — valid, complete, not an extraction failure
# ---------------------------------------------------------------------------


async def test_equifax_bureau_no_record_is_success():
    """HIT CODE :00 / Consumer record not found → SUCCESS with NO warnings.
    The no-record signal is carried by data.bureau_hit=False; a warning
    would be noise on a reviewer's screen for a clean bureau response."""
    html = b"""<!DOCTYPE html><html><body>
    <table><tr><td>HIT CODE :</td><td>00</td></tr>
    <tr><td>DESCRIPTION :Consumer record not found.</td></tr></table>
    </body></html>"""
    result = await EquifaxHtmlExtractor().extract("ntc.html", html)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.warnings == []
    assert result.data["bureau_hit"] is False
    assert result.data["credit_score"] is None
    assert result.data["accounts"] == []


async def test_equifax_non_record_variants_still_trigger_no_record():
    """Plain 'Consumer record not found' text (no HIT CODE pattern) also works."""
    html = b"""<html><body><p>Consumer record not found for this applicant.</p></body></html>"""
    result = await EquifaxHtmlExtractor().extract("ntc2.html", html)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.warnings == []
    assert result.data["bureau_hit"] is False


async def test_equifax_preserves_negative_display_score_as_ntc_sentinel():
    """Real files use `<h4 class="displayscore">-1</h4>` for NTC applicants.
    The -1 must reach data.credit_score verbatim (not null) so downstream
    decisioning can distinguish 'bureau said no record' from 'HTML had no
    score tag'. Identity data (name, PAN, DOB) must still flow through,
    and no warning should be emitted (clean bureau reply).
    """
    html = b"""<!DOCTYPE html><html><body>
    <h4>Consumer Name: GORDHAN</h4>
    <p>PAN:CQIPG4434Q DOB:07-11-1998</p>
    <h4 class="displayscore">-1</h4>
    <h4 class="displayscore">-1</h4>
    </body></html>"""
    result = await EquifaxHtmlExtractor().extract("ntc_gordhan.html", html)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.warnings == []
    assert result.data["credit_score"] == -1        # preserved, NOT null
    assert result.data["bureau_hit"] is False
    assert result.data["customer_info"]["name"] == "GORDHAN"
    assert result.data["customer_info"]["pan"] == "CQIPG4434Q"
    assert result.data["customer_info"]["dob"] == "07-11-1998"


async def test_equifax_prefers_positive_score_over_negative_sentinel():
    """When a report has both Microfinance (-1) and Equifax Risk (834) scores,
    the positive score wins."""
    html = b"""<html><body>
    <h4 class="displayscore">-1</h4>
    <h4 class="displayscore">834</h4>
    <table id="accountTable"><tr><td>RETAIL</td></tr>
    <tr><td>Institution : ABC Bank</td><td>Type : Consumer Loan</td></tr></table>
    </body></html>"""
    result = await EquifaxHtmlExtractor().extract("mixed.html", html)
    assert result.data["credit_score"] == 834
    assert result.data["bureau_hit"] is True
