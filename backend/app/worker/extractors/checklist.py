"""ChecklistExtractor — parses a one-sheet checklist xlsx."""

from __future__ import annotations

import io
from typing import Any

import openpyxl

from app.enums import ExtractionStatus
from app.worker.extractors.base import BaseExtractor, ExtractionResult

_FEW_ITEMS_THRESHOLD = 3


class ChecklistExtractor(BaseExtractor):
    extractor_name = "checklist"
    schema_version = "1.0"

    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(body_bytes), data_only=True)
        except Exception as exc:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=type(self).schema_version,
                data={},
                error_message=f"openpyxl failed to open {filename!r}: {exc}",
            )

        ws = wb.active or wb.worksheets[0]

        sections: dict[str, Any] = {}
        current_section: str | None = None
        yes_count = no_count = na_count = 0

        # Row 1 is the header — start from row 2
        for row in ws.iter_rows(min_row=2, values_only=True):
            col_a = row[0] if len(row) > 0 else None
            col_b = row[1] if len(row) > 1 else None
            col_c = row[2] if len(row) > 2 else None
            col_d = row[3] if len(row) > 3 else None

            if col_a is None:
                continue

            col_a_str = str(col_a).strip()
            if not col_a_str:
                continue

            # Section header: col A has value, col B is empty/None
            if not col_b or not str(col_b).strip():
                current_section = col_a_str
                if current_section not in sections:
                    sections[current_section] = {}
                continue

            # Item row: col A + col B both present
            if current_section is None:
                # Item without a section header — use a default bucket
                current_section = "General"
                if current_section not in sections:
                    sections[current_section] = {}

            item_name = str(col_b).strip()
            status_raw = str(col_c).strip().upper() if col_c else "NA"
            remarks = str(col_d).strip() if col_d else None

            sections[current_section][item_name] = {
                "value": status_raw,
                "remarks": remarks,
            }

            if status_raw == "YES":
                yes_count += 1
            elif status_raw == "NO":
                no_count += 1
            else:
                na_count += 1

        total_items = yes_count + no_count + na_count

        if total_items == 0:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=type(self).schema_version,
                data={},
                error_message="Checklist sheet is empty or unrecognisable.",
            )

        data: dict[str, Any] = {
            "sections": sections,
            "yes_count": yes_count,
            "no_count": no_count,
            "na_count": na_count,
            "total_items": total_items,
        }

        warnings: list[str] = []
        if total_items < _FEW_ITEMS_THRESHOLD:
            warnings.append("very_few_items")
            status = ExtractionStatus.PARTIAL
        else:
            status = ExtractionStatus.SUCCESS

        return ExtractionResult(
            status=status,
            schema_version=type(self).schema_version,
            data=data,
            warnings=warnings,
        )
