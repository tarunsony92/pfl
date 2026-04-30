"""Builder for Equifax HTML fixture."""

from pathlib import Path

_DEFAULT_ACCOUNTS = [
    {
        "lender": "ABC Bank",
        "type": "Personal Loan",
        "opened": "2020-06",
        "balance": 45000,
        "status": "Active",
    },
    {
        "lender": "XYZ Finance",
        "type": "Credit Card",
        "opened": "2019-01",
        "balance": 0,
        "status": "Closed",
    },
]

_DEFAULT_INQUIRIES = [
    {"date": "2024-11-10", "lender": "PFL Finance", "purpose": "Personal Loan"},
]

_DEFAULT_ADDRESSES = [
    {"line1": "123 MG Road", "city": "Delhi", "pin": "110001", "type": "Current"},
]


def build_equifax_html(
    path: Path,
    score: int = 769,
    accounts: list[dict] | None = None,
    inquiries: list[dict] | None = None,
    addresses: list[dict] | None = None,
) -> Path:
    """Generate a minimal HTML document with Equifax-style structure.

    Includes a .CreditScore element and tables for accounts, inquiries, addresses.
    Returns path.
    """
    accounts = accounts if accounts is not None else _DEFAULT_ACCOUNTS
    inquiries = inquiries if inquiries is not None else _DEFAULT_INQUIRIES
    addresses = addresses if addresses is not None else _DEFAULT_ADDRESSES

    account_rows = "\n".join(
        f"<tr><td>{a['lender']}</td><td>{a['type']}</td>"
        f"<td>{a['opened']}</td><td>{a['balance']}</td><td>{a['status']}</td></tr>"
        for a in accounts
    )

    inquiry_rows = "\n".join(
        f"<tr><td>{i['date']}</td><td>{i['lender']}</td><td>{i['purpose']}</td></tr>"
        for i in inquiries
    )

    address_rows = "\n".join(
        f"<tr><td>{a['line1']}</td><td>{a['city']}</td>"
        f"<td>{a['pin']}</td><td>{a['type']}</td></tr>"
        for a in addresses
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Equifax Credit Report</title></head>
<body>
<div id="CreditReportHeader">
  <h1>Equifax Credit Report</h1>
  <div id="PersonalInfo">
    <span class="Name">SEEMA DEVI</span>
    <span class="DOB">15/03/1985</span>
    <span class="PAN">ABCDE1234F</span>
  </div>
  <div id="ScoreSection">
    <span class="CreditScore">{score}</span>
    <span class="ScoreLabel">Equifax Credit Score</span>
  </div>
</div>

<div id="AccountSummary">
  <h2>Account Summary</h2>
  <table id="AccountsTable" class="AccountTable">
    <thead>
      <tr><th>Lender</th><th>Type</th><th>Opened</th><th>Balance</th><th>Status</th></tr>
    </thead>
    <tbody>
{account_rows}
    </tbody>
  </table>
</div>

<div id="InquirySummary">
  <h2>Recent Inquiries</h2>
  <table id="InquiriesTable" class="InquiryTable">
    <thead>
      <tr><th>Date</th><th>Lender</th><th>Purpose</th></tr>
    </thead>
    <tbody>
{inquiry_rows}
    </tbody>
  </table>
</div>

<div id="AddressSection">
  <h2>Addresses</h2>
  <table id="AddressTable" class="AddressTable">
    <thead>
      <tr><th>Address</th><th>City</th><th>PIN</th><th>Type</th></tr>
    </thead>
    <tbody>
{address_rows}
    </tbody>
  </table>
</div>
</body>
</html>"""

    path.write_text(html, encoding="utf-8")
    return path
