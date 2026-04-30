"""Builder for Bank Statement PDF fixture."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_DEFAULT_TRANSACTIONS = [
    {
        "date": "2024-10-01",
        "description": "Opening Balance",
        "debit": "",
        "credit": "",
        "balance": 12500,
    },
    {
        "date": "2024-10-03",
        "description": "NEFT - Salary Credit",
        "debit": "",
        "credit": 35000,
        "balance": 47500,
    },
    {
        "date": "2024-10-05",
        "description": "ATM Withdrawal",
        "debit": 5000,
        "credit": "",
        "balance": 42500,
    },
    {
        "date": "2024-10-12",
        "description": "UPI - Grocery",
        "debit": 1200,
        "credit": "",
        "balance": 41300,
    },
    {
        "date": "2024-10-18",
        "description": "EMI - ABC Bank",
        "debit": 8500,
        "credit": "",
        "balance": 32800,
    },
    {
        "date": "2024-10-31",
        "description": "Closing Balance",
        "debit": "",
        "credit": "",
        "balance": 32800,
    },
]


def build_bank_statement_pdf(
    path: Path,
    account_holder: str = "SEEMA DEVI",
    transactions: list[dict] | None = None,
) -> Path:
    """Produce a PDF with account header + transaction table.

    Header: Account Holder, Account Number, Period, Opening/Closing Balance.
    Returns path.
    """
    if transactions is None:
        transactions = _DEFAULT_TRANSACTIONS

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    elements = []

    elements.append(Paragraph("Bank Account Statement", styles["Title"]))
    elements.append(Spacer(1, 0.3 * cm))

    # Header info
    header_data = [
        ["Account Holder:", account_holder],
        ["Account Number:", "0012345678901"],
        ["IFSC:", "SBIN0001234"],
        ["Period:", "01-Oct-2024 to 31-Oct-2024"],
        ["Opening Balance:", "12,500.00"],
        ["Closing Balance:", f"{transactions[-1]['balance']:,.2f}"],
    ]
    header_table = Table(header_data, colWidths=[5 * cm, 10 * cm])
    header_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 0.5 * cm))

    # Transactions table
    tx_header = ["Date", "Description", "Debit", "Credit", "Balance"]
    tx_rows = [tx_header]
    for tx in transactions:
        tx_rows.append(
            [
                tx.get("date", ""),
                tx.get("description", ""),
                str(tx.get("debit", "")) if tx.get("debit", "") != "" else "-",
                str(tx.get("credit", "")) if tx.get("credit", "") != "" else "-",
                f"{tx.get('balance', 0):,.2f}",
            ]
        )

    tx_table = Table(tx_rows, colWidths=[2.5 * cm, 8 * cm, 2.5 * cm, 2.5 * cm, 3 * cm])
    tx_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    elements.append(tx_table)

    doc.build(elements)
    return path
