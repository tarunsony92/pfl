# Test Fixture Builders

This directory contains **programmatic fixture builders** that produce minimal, realistic
synthetic files for testing the ingestion pipeline extractors.

## Important: No Real Customer Data

All fixtures use entirely synthetic data. No real customer names, PAN numbers, Aadhaar
numbers, or financial data are committed to this repository. Default values resemble a
generic "SEEMA" case (a common placeholder in PFL test scenarios) but are not tied to
any real individual.

## Why Programmatic Builders?

Binary test fixtures (xlsx, pdf, docx, html) tend to rot silently — they can't be
diffed, they inflate repo size, and they may accidentally contain real data. Instead,
every fixture file is regenerated at test time from Python code. If a builder is
updated, all dependent tests immediately reflect the change.

## Available Builders

| Builder module | Function | Output |
|---|---|---|
| `auto_cam_builder.py` | `build_auto_cam_xlsx(path, **overrides)` | xlsx with 4 sheets |
| `checklist_builder.py` | `build_checklist_xlsx(path, yes_keys, no_keys, na_keys)` | checklist xlsx |
| `pd_sheet_builder.py` | `build_pd_sheet_docx(path, fields)` | PD Sheet docx |
| `equifax_builder.py` | `build_equifax_html(path, score, accounts, inquiries, addresses)` | Equifax HTML |
| `bank_statement_builder.py` | `build_bank_statement_pdf(path, account_holder, transactions)` | bank statement PDF |
| `dedupe_builder.py` | `build_dedupe_xlsx(path, customers)` | Customer_Dedupe xlsx |
| `case_zip_builder.py` | `build_case_zip(path, **kwargs)` | full case ZIP |

## Usage in Tests

```python
from tests.fixtures.builders import build_auto_cam_xlsx, build_case_zip

def test_something(tmp_path):
    xlsx = build_auto_cam_xlsx(tmp_path / "cam.xlsx", cibil_score=750)
    # pass xlsx to extractor under test
```

Pass `tmp_path` (pytest's built-in fixture) as the path argument. Each builder returns
the path it wrote to, so you can chain calls.

## Default Synthetic Values

- Applicant Name: `SEEMA DEVI`
- PAN: `ABCDE1234F`
- DOB: `15/03/1985`
- CIBIL Score: `769`
- Loan Amount: `150,000`
- Loan ID (ZIP): `10006484`
