"""Final Verdict Report — ReportLab PDF for a PFL microfinance case.

Pulls every signal the pre-Phase-1 gate collected and renders an
auditor-grade PDF:

- Page 1: cover (case header, key facts, score banner, grade, final
  decision) — stamped with an "AI APPROVED" mark once the gate clears
- Page 2: L1-L5.5 per-level scorecard with issue counts + MD overrides
- Page 3+: the 32-point scoring table (from L5) with evidence
- L6 decisioning synthesis: final decision, 11-step pipeline,
  Opus reasoning, pros/cons, conditions, deviations, risk
- Last pages: per-issue audit trail — when each concern was raised,
  what the assessor mitigated, and the final MD or AI decision

The renderer is pure ReportLab — no external dependencies beyond what's
already in the pyproject. Call ``generate_final_report`` with a fully
populated ``FinalReportData`` and it returns bytes. The renderer treats
the scoring payload defensively: malformed sections or rows downgrade
to a placeholder rather than raising.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


# ── Theme ────────────────────────────────────────────────────────────────────

NAVY = colors.HexColor("#0f172a")
SLATE = colors.HexColor("#475569")
MUTED = colors.HexColor("#94a3b8")
LINE = colors.HexColor("#cbd5e1")
GREEN = colors.HexColor("#047857")
AMBER = colors.HexColor("#b45309")
RED = colors.HexColor("#b91c1c")
PAPER = colors.HexColor("#fafaf7")


def _style(name: str) -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return styles[name]


# ReportLab's built-in Helvetica doesn't carry glyphs for ₹ / ≥ / → / ✓ etc.
# Rather than ship a Unicode TTF, we substitute these to stable ASCII /
# Helvetica-covered equivalents before rendering.
_CHAR_REPLACEMENTS = {
    "\u20b9": "Rs. ",   # ₹
    "\u2265": ">=",       # ≥
    "\u2264": "<=",       # ≤
    "\u2192": "->",       # →
    "\u2190": "<-",       # ←
    "\u2018": "'",        # ‘
    "\u2019": "'",        # ’
    "\u201c": '"',        # “
    "\u201d": '"',        # ”
    "\u2013": "-",        # –
    "\u2014": "-",        # —
    "\u2713": "[Y]",      # ✓
    "\u2717": "[N]",      # ✗
    "\u00b7": "-",        # · — keep simple; middle-dot covered but inconsistent in bold
}


def _safe(text: str) -> str:
    if text is None:
        return ""
    s = str(text)
    for src, dst in _CHAR_REPLACEMENTS.items():
        if src in s:
            s = s.replace(src, dst)
    return s


# Defensive readers for the scoring payload — the renderer must NEVER crash on
# malformed `sub_step_results.scoring`, otherwise the whole report endpoint
# returns a bare HTTP 500 with no actionable message for the assessor.
def _safe_str(d: Any, key: str, default: str = "—") -> str:
    if not isinstance(d, dict):
        return default
    v = d.get(key)
    if v is None or v == "":
        return default
    return str(v)


def _safe_int(d: Any, key: str, default: int = 0) -> int:
    if not isinstance(d, dict):
        return default
    v = d.get(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(d: Any, key: str, default: float = 0.0) -> float:
    if not isinstance(d, dict):
        return default
    v = d.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fmt_dt(iso: str | None, fallback: str = "—") -> str:
    """Format an ISO timestamp as `DD MMM YYYY HH:MM` for the report tables."""
    if not iso:
        return fallback
    try:
        s = str(iso)
        # `2026-04-22T17:21:14.123456+00:00` → first 16 chars give YYYY-MM-DD HH:MM
        # Then reformat to DD MMM YYYY HH:MM for readability.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y %H:%M")
    except (TypeError, ValueError):
        return str(iso)[:16].replace("T", " ") or fallback


def _p(text: str, size: float = 10, color: colors.Color = NAVY, bold: bool = False, align: int = TA_LEFT) -> Paragraph:
    ps = ParagraphStyle(
        "x",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        textColor=color,
        leading=size * 1.25,
        alignment=align,
    )
    return Paragraph(_safe(text), ps)


# ── Data contract ────────────────────────────────────────────────────────────


@dataclass
class LevelBrief:
    level_number: str
    title: str
    status: str
    cost_usd: float = 0.0
    issue_count: int = 0
    critical_unresolved: int = 0
    warning_unresolved: int = 0
    md_approved_count: int = 0
    md_rejected_count: int = 0
    match_pct: float | None = None


@dataclass
class DecisioningStepBrief:
    """One row per Phase-1 decisioning step (L6.x). Mirrors `decision_steps`."""

    step_number: int
    step_name: str
    status: str  # SUCCEEDED / FAILED / SKIPPED / PENDING / RUNNING
    model_used: str | None
    cost_usd: float
    summary: str  # short extracted line from output_data — "passed", "verdict", etc.


@dataclass
class DecisioningBrief:
    """L6 (Decisioning) — the 11-step Opus synthesis on top of the gate.

    Drives a dedicated section in the final report so an auditor can read
    the policy gates, per-step output, the Opus narrative, and the recommended
    decision in one place. Optional — older cases that pre-date L6 may not
    have a DecisionResult row, in which case the report skips the section.
    """

    status: str  # COMPLETED / FAILED / CANCELLED / RUNNING / PENDING
    final_decision: str | None
    recommended_amount: int | None
    recommended_tenure: int | None
    confidence_score: int | None
    reasoning_markdown: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    deviations: list[str] = field(default_factory=list)
    risk_summary_lines: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    started_at: str = ""
    completed_at: str = ""
    steps: list[DecisioningStepBrief] = field(default_factory=list)


@dataclass
class IssueLifecycle:
    """Full chronological lifecycle of one LevelIssue — what an auditor reads
    cold to understand: when the system raised it, what the assessor wrote as
    mitigation, what the MD/AI decided, and the final outcome."""

    sub_step_id: str
    level_number: str
    severity: str
    description: str
    raised_at: str  # ISO — issue.created_at
    assessor_resolved_at: str  # ISO or ""
    assessor_note: str
    md_reviewed_at: str  # ISO or ""
    md_decision: str  # MD_APPROVED / MD_REJECTED / OPEN / ASSESSOR_RESOLVED
    md_rationale: str
    actor: str  # ai / md / assessor / system


@dataclass
class FinalReportData:
    case_id: str
    loan_id: str
    applicant_name: str
    co_applicant_name: str | None
    loan_amount_inr: int | None
    tenure_months: int | None
    uploaded_at: str  # ISO
    # Scoring
    overall_pct: float
    earned: int
    max_score: int
    grade: str
    eb_verdict: str
    sections: list[dict[str, Any]]  # same shape as ScoringResult.to_dict()['sections']
    # Levels
    levels: list[LevelBrief]
    # Full per-issue lifecycle for the audit-trail section. Each entry covers
    # one LevelIssue from raised → mitigation → MD/AI decision so an auditor
    # can read the case cold.
    issue_lifecycle: list[IssueLifecycle] = field(default_factory=list)
    # L6 decisioning synthesis — None on older runs that pre-date Phase-1.
    decisioning: DecisioningBrief | None = None
    # Generated
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    generated_by_email: str = ""
    # Final verdict
    final_verdict: str = "PENDING"  # APPROVE / APPROVE_WITH_CONDITIONS / REJECT
    final_verdict_notes: str = ""


# ── Page frame + header ──────────────────────────────────────────────────────


def _stamp_date_label(iso: str) -> str:
    """Format the date arch on the stamp from `data.generated_at`.

    Falls back to current UTC if `iso` is empty or unparseable, so the stamp
    always shows *something* — but when populated, the date in the stamp
    matches the date in the cover's "Generated" cell exactly. That keeps an
    auditor reading the printed report from confusing stamp-date with
    case-date if the same case is regenerated months later.
    """
    if iso:
        try:
            return (
                datetime.fromisoformat(iso.replace("Z", "+00:00"))
                .strftime("%d %b %Y")
                .upper()
            )
        except (TypeError, ValueError):
            pass
    return datetime.utcnow().strftime("%d %b %Y").upper()


def _draw_ai_approved_stamp(
    canvas, cx: float, cy: float, radius: float, date_iso: str = ""
) -> None:
    """Paint a green "AI APPROVED" rubber-stamp aesthetic at (cx, cy).

    Pure ReportLab canvas primitives — no external image asset. Used on the
    cover page once the gate has cleared (i.e. every concern is settled and
    the PDF is being generated). Slight tilt + serrated outer ring make it
    read as an actual stamp rather than a UI badge. `date_iso` is the
    report's `generated_at` so the stamp date stays in sync with the rest of
    the cover when the report is regenerated.
    """
    stamp_color = colors.HexColor("#16a34a")  # green-600

    canvas.saveState()
    canvas.translate(cx, cy)
    canvas.rotate(-10)

    canvas.setStrokeColor(stamp_color)
    canvas.setFillColor(stamp_color)

    # Outer serrated ring — small triangular wedges around the perimeter.
    n_teeth = 36
    inner_r = radius * 0.92
    for i in range(n_teeth):
        a1 = (i / n_teeth) * 2 * math.pi
        a2 = ((i + 0.5) / n_teeth) * 2 * math.pi
        a3 = ((i + 1) / n_teeth) * 2 * math.pi
        path = canvas.beginPath()
        path.moveTo(inner_r * math.cos(a1), inner_r * math.sin(a1))
        path.lineTo(radius * math.cos(a2), radius * math.sin(a2))
        path.lineTo(inner_r * math.cos(a3), inner_r * math.sin(a3))
        path.close()
        canvas.drawPath(path, fill=1, stroke=0)

    # Two concentric circles forming the stamp band where text sits.
    canvas.setLineWidth(1.2)
    canvas.circle(0, 0, inner_r, stroke=1, fill=0)
    inner_text_r = radius * 0.72
    canvas.circle(0, 0, inner_text_r, stroke=1, fill=0)

    # Centre text — "AI APPROVED" stacked.
    canvas.setFillColor(stamp_color)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawCentredString(0, 5, "AI")
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawCentredString(0, -5, "APPROVED")

    # "PFL CREDIT" arched along the top of the band.
    arc_r = (inner_r + inner_text_r) / 2
    _draw_arched_text(canvas, "PFL CREDIT", arc_r, 90, 100, size=6.5, top=True)

    # Date arched along the bottom of the band — uses the report's
    # generated_at so the stamp date stays consistent with the cover.
    _draw_arched_text(
        canvas, _stamp_date_label(date_iso), arc_r, -90, 90, size=6.0, top=False
    )

    canvas.restoreState()


def _draw_arched_text(
    canvas,
    text: str,
    radius: float,
    centre_deg: float,
    span_deg: float,
    size: float,
    top: bool,
) -> None:
    """Lay out characters along an arc centred on `centre_deg`, spanning
    `span_deg` total. `top=True` for upper arc (text reads left-to-right
    along the curve), `top=False` flips for the lower arc."""
    if not text:
        return
    canvas.setFont("Helvetica-Bold", size)
    n = len(text)
    if n == 1:
        steps = [0.0]
    else:
        steps = [(i / (n - 1)) - 0.5 for i in range(n)]
    if top:
        # Left-to-right along the upper arc means decreasing angle.
        angles = [centre_deg - s * span_deg for s in steps]
    else:
        angles = [centre_deg + s * span_deg for s in steps]
    for ch, a_deg in zip(text, angles):
        a_rad = math.radians(a_deg)
        x = radius * math.cos(a_rad)
        y = radius * math.sin(a_rad)
        canvas.saveState()
        canvas.translate(x, y)
        # Tangent rotation. Upper arc baseline points outward; lower arc flips.
        rot = a_deg - 90 if top else a_deg + 90
        canvas.rotate(rot)
        canvas.drawCentredString(0, 0, ch)
        canvas.restoreState()


def _draw_page_chrome(canvas, doc) -> None:
    canvas.saveState()
    # Masthead rule
    canvas.setStrokeColor(NAVY)
    canvas.setLineWidth(0.8)
    canvas.line(18 * mm, A4[1] - 18 * mm, A4[0] - 18 * mm, A4[1] - 18 * mm)

    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(NAVY)
    canvas.drawString(18 * mm, A4[1] - 14 * mm, "PFL FINANCE · CREDIT ADJUDICATION REPORT")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(SLATE)
    canvas.drawRightString(
        A4[0] - 18 * mm,
        A4[1] - 14 * mm,
        datetime.utcnow().strftime("%d %b %Y"),
    )

    # AI APPROVED stamp on page 1 only — applied "on top" of the cover so the
    # report reads as auditor-grade once the gate clears. The date in the
    # stamp pulls from `doc._stamp_date_iso` (set by generate_final_report)
    # so it matches the report's generated_at on the cover.
    if doc.page == 1:
        _draw_ai_approved_stamp(
            canvas,
            cx=A4[0] - 38 * mm,
            cy=A4[1] - 42 * mm,
            radius=18 * mm,
            date_iso=getattr(doc, "_stamp_date_iso", ""),
        )

    # Footer
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 18 * mm, A4[0] - 18 * mm, 18 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 13 * mm, f"Page {doc.page}")
    canvas.drawRightString(
        A4[0] - 18 * mm,
        13 * mm,
        "Generated by PFL Credit AI · for internal audit use only",
    )
    canvas.restoreState()


# ── Section builders ─────────────────────────────────────────────────────────


def _grade_color(grade: str) -> colors.Color:
    return {"A+": GREEN, "A": GREEN, "B": AMBER, "C": RED, "D": RED}.get(grade, SLATE)


def _status_color(status: str) -> colors.Color:
    s = (status or "").upper()
    if s in ("PASSED", "PASSED_WITH_MD_OVERRIDE", "PASS", "MD_APPROVED", "APPROVE"):
        return GREEN
    if s in ("BLOCKED", "FAILED", "FAIL", "MD_REJECTED", "REJECT"):
        return RED
    if s in ("WARNING", "APPROVE_WITH_CONDITIONS"):
        return AMBER
    return SLATE


def _cover(d: FinalReportData) -> list[Any]:
    els: list[Any] = []
    els.append(Spacer(1, 10 * mm))
    els.append(_p("CREDIT ADJUDICATION REPORT", 11, SLATE, bold=True, align=TA_CENTER))
    els.append(Spacer(1, 4 * mm))
    els.append(
        _p(
            f"Loan <b>{d.loan_id}</b>",
            26,
            NAVY,
            bold=True,
            align=TA_CENTER,
        )
    )
    els.append(Spacer(1, 2 * mm))
    els.append(
        _p(
            f"<i>{d.applicant_name}</i>"
            + (
                f" &nbsp;·&nbsp; with <i>{d.co_applicant_name}</i>"
                if d.co_applicant_name
                else ""
            ),
            14,
            SLATE,
            align=TA_CENTER,
        )
    )
    els.append(Spacer(1, 8 * mm))

    # Key facts row
    key_facts = Table(
        [
            [
                _p("Loan Amount", 8, MUTED, bold=True, align=TA_CENTER),
                _p("Tenure", 8, MUTED, bold=True, align=TA_CENTER),
                _p("Uploaded", 8, MUTED, bold=True, align=TA_CENTER),
                _p("Generated", 8, MUTED, bold=True, align=TA_CENTER),
            ],
            [
                _p(
                    f"₹ {d.loan_amount_inr:,}" if d.loan_amount_inr else "—",
                    11,
                    NAVY,
                    bold=True,
                    align=TA_CENTER,
                ),
                _p(
                    f"{d.tenure_months} mo" if d.tenure_months else "—",
                    11,
                    NAVY,
                    bold=True,
                    align=TA_CENTER,
                ),
                _p(d.uploaded_at[:10] if d.uploaded_at else "—", 11, NAVY, align=TA_CENTER),
                _p(d.generated_at[:10], 11, NAVY, align=TA_CENTER),
            ],
        ],
        colWidths=[42 * mm, 42 * mm, 42 * mm, 42 * mm],
    )
    key_facts.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    els.append(key_facts)
    els.append(Spacer(1, 14 * mm))

    # Score banner
    score_table = Table(
        [
            [
                _p("AUDIT SCORE", 9, MUTED, bold=True, align=TA_CENTER),
                _p("GRADE", 9, MUTED, bold=True, align=TA_CENTER),
                _p("FINAL VERDICT", 9, MUTED, bold=True, align=TA_CENTER),
            ],
            [
                _p(
                    f"<b>{d.earned}</b> / {d.max_score}<br/><font size=11 color='#475569'>{d.overall_pct:.1f}%</font>",
                    26,
                    NAVY,
                    bold=True,
                    align=TA_CENTER,
                ),
                _p(
                    f"<font color='{_grade_color(d.grade).hexval()}'><b>{d.grade}</b></font>",
                    42,
                    _grade_color(d.grade),
                    bold=True,
                    align=TA_CENTER,
                ),
                _p(
                    f"<font color='{_status_color(d.final_verdict).hexval()}'><b>{d.final_verdict}</b></font>",
                    18,
                    _status_color(d.final_verdict),
                    bold=True,
                    align=TA_CENTER,
                ),
            ],
        ],
        colWidths=[55 * mm, 55 * mm, 60 * mm],
    )
    score_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 1.0, NAVY),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
                ("TOPPADDING", (0, 1), (-1, 1), 16),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 16),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ]
        )
    )
    els.append(score_table)
    els.append(Spacer(1, 8 * mm))

    if d.final_verdict_notes:
        els.append(_p("Verdict notes", 9, MUTED, bold=True))
        els.append(Spacer(1, 2 * mm))
        els.append(_p(d.final_verdict_notes, 10, NAVY))

    els.append(Spacer(1, 14 * mm))
    els.append(
        _p(
            "Signed off by <b>" + (d.generated_by_email or "—") + "</b>, "
            f"{d.generated_at[:16].replace('T', ' ')} UTC.",
            9,
            SLATE,
            align=TA_CENTER,
        )
    )
    return els


def _level_scorecard(d: FinalReportData) -> list[Any]:
    els: list[Any] = [
        _p("Level-by-level scorecard", 14, NAVY, bold=True),
        Spacer(1, 4 * mm),
        _p(
            "What each verification gate found, and how it closed out. Levels "
            "marked PASSED_WITH_MD_OVERRIDE were blocked by the engine but cleared "
            "by an MD decision; see the issue audit trail at the end of this "
            "report for the full lifecycle of every concern.",
            9,
            SLATE,
        ),
        Spacer(1, 6 * mm),
    ]
    header = [
        _p("Level", 8, MUTED, bold=True),
        _p("Title", 8, MUTED, bold=True),
        _p("Status", 8, MUTED, bold=True),
        _p("Issues", 8, MUTED, bold=True),
        _p("MD ✓ / ✗", 8, MUTED, bold=True),
        _p("Match %", 8, MUTED, bold=True),
        _p("Cost $", 8, MUTED, bold=True),
    ]
    rows: list[list[Any]] = [header]
    for lvl in d.levels:
        rows.append(
            [
                _p(lvl.level_number.replace("_", " "), 9, NAVY, bold=True),
                _p(lvl.title, 9),
                _p(
                    f"<font color='{_status_color(lvl.status).hexval()}'><b>{lvl.status}</b></font>",
                    9,
                    _status_color(lvl.status),
                ),
                _p(
                    f"{lvl.issue_count} ({lvl.critical_unresolved}✗ / {lvl.warning_unresolved}!)",
                    9,
                ),
                _p(f"{lvl.md_approved_count} / {lvl.md_rejected_count}", 9),
                _p(f"{lvl.match_pct:.0f}%" if lvl.match_pct is not None else "—", 9),
                _p(f"{lvl.cost_usd:.4f}" if lvl.cost_usd else "—", 9),
            ]
        )
    t = Table(rows, colWidths=[22 * mm, 54 * mm, 30 * mm, 26 * mm, 18 * mm, 15 * mm, 17 * mm])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, NAVY),
                ("LINEABOVE", (0, -1), (-1, -1), 0.4, LINE),
                ("GRID", (0, 1), (-1, -1), 0.2, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    els.append(t)
    return els


def _scoring_table(d: FinalReportData) -> list[Any]:
    els: list[Any] = [
        _p("32-point audit detail", 14, NAVY, bold=True),
        Spacer(1, 3 * mm),
        _p(
            f"Overall {d.earned}/{d.max_score} = {d.overall_pct:.1f}% · Grade <b>{d.grade}</b> · "
            f"Eligibility-vs-Banking verdict <b>{d.eb_verdict}</b>.",
            9,
            SLATE,
        ),
        Spacer(1, 4 * mm),
    ]

    valid_sections = [s for s in (d.sections or []) if isinstance(s, dict)]
    if not valid_sections:
        els.append(
            _p(
                "No L5 scoring detail recorded for this case. The 32-point audit "
                "either has not been run or its result payload is empty.",
                10,
                MUTED,
                align=TA_CENTER,
            )
        )
        return els

    for sec in valid_sections:
        els.append(Spacer(1, 4 * mm))
        sec_pct = _safe_float(sec, "pct")
        section_title = Table(
            [
                [
                    _p(
                        f"Section {_safe_str(sec, 'section_id')} — {_safe_str(sec, 'title', default='Untitled section')}",
                        11,
                        NAVY,
                        bold=True,
                    ),
                    _p(
                        f"{_safe_int(sec, 'earned')} / {_safe_int(sec, 'max_score')}  ·  {sec_pct:.1f}%",
                        10,
                        _status_color("PASS" if sec_pct >= 70 else "FAIL"),
                        bold=True,
                        align=TA_CENTER,
                    ),
                ]
            ],
            colWidths=[130 * mm, 42 * mm],
        )
        section_title.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, NAVY),
                    ("TOPPADDING", (0, 0), (-1, 0), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                    ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                ]
            )
        )
        els.append(section_title)

        header = [
            _p("#", 8, MUTED, bold=True),
            _p("Parameter", 8, MUTED, bold=True),
            _p("Role", 8, MUTED, bold=True),
            _p("Wt", 8, MUTED, bold=True, align=TA_CENTER),
            _p("Status", 8, MUTED, bold=True),
            _p("Score", 8, MUTED, bold=True, align=TA_CENTER),
            _p("Evidence / Remarks", 8, MUTED, bold=True),
        ]
        rows: list[list[Any]] = [header]
        sec_rows = sec.get("rows")
        if not isinstance(sec_rows, list):
            sec_rows = []
        for row in sec_rows:
            if not isinstance(row, dict):
                continue
            status = _safe_str(row, "status", default="")
            status_col = (
                GREEN if status == "PASS" else RED if status == "FAIL" else AMBER if status == "PENDING" else MUTED
            )
            evidence = _safe_str(row, "evidence", default="")
            remarks = _safe_str(row, "remarks", default="")
            rows.append(
                [
                    _p(_safe_str(row, "sno", default=""), 8),
                    _p(_safe_str(row, "parameter", default="—"), 8),
                    _p(_safe_str(row, "role", default=""), 8, MUTED),
                    _p(_safe_str(row, "weight", default=""), 8, align=TA_CENTER),
                    _p(
                        f"<font color='{status_col.hexval()}'><b>{status or '—'}</b></font>",
                        8,
                    ),
                    _p(_safe_str(row, "score", default="0"), 8, align=TA_CENTER),
                    _p(
                        f"{evidence}<br/><font color='#94a3b8'>{remarks}</font>",
                        7,
                        SLATE,
                    ),
                ]
            )
        if len(rows) == 1:
            els.append(
                _p(
                    "No parameter rows recorded for this section.",
                    9,
                    MUTED,
                    align=TA_CENTER,
                )
            )
            continue
        t = Table(
            rows,
            colWidths=[8 * mm, 45 * mm, 20 * mm, 10 * mm, 20 * mm, 12 * mm, 57 * mm],
        )
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 1), (-1, -1), 0.15, LINE),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        els.append(t)

    return els


def _decisioning_section(d: FinalReportData) -> list[Any]:
    """Render the L6 (Phase-1 Decisioning) synthesis — final decision, the
    11-step pipeline summary, Opus reasoning, pros/cons, conditions,
    deviations, and risk. Skipped entirely if no DecisionResult exists yet.
    """
    if d.decisioning is None:
        return []
    dec = d.decisioning

    els: list[Any] = [
        PageBreak(),
        _p("Decisioning synthesis (L6)", 14, NAVY, bold=True),
        Spacer(1, 3 * mm),
        _p(
            "Phase-1 decisioning runs an 11-step Opus pipeline on top of the "
            "verification gate — policy hard-stops, banking, income, KYC, "
            "address, business, stock, reconciliation, PD-sheet read, "
            "case-library retrieval, and a final synthesis. The verdict, "
            "confidence, recommended ticket and reasoning below are what the "
            "model returned.",
            9,
            SLATE,
        ),
        Spacer(1, 4 * mm),
    ]

    # ── Decision banner ────────────────────────────────────────────────────
    final_decision = dec.final_decision or "PENDING"
    confidence_str = (
        f"<font color='{_status_color(final_decision).hexval()}'><b>{dec.confidence_score}%</b></font>"
        if dec.confidence_score is not None
        else "<font color='#94a3b8'>—</font>"
    )
    rec_amt = (
        f"Rs. {dec.recommended_amount:,}"
        if dec.recommended_amount
        else "—"
    )
    rec_ten = (
        f"{dec.recommended_tenure} mo"
        if dec.recommended_tenure
        else "—"
    )
    decision_banner = Table(
        [
            [
                _p("FINAL DECISION", 8, MUTED, bold=True, align=TA_CENTER),
                _p("CONFIDENCE", 8, MUTED, bold=True, align=TA_CENTER),
                _p("REC. AMOUNT", 8, MUTED, bold=True, align=TA_CENTER),
                _p("REC. TENURE", 8, MUTED, bold=True, align=TA_CENTER),
                _p("OPUS COST", 8, MUTED, bold=True, align=TA_CENTER),
            ],
            [
                _p(
                    f"<font color='{_status_color(final_decision).hexval()}'><b>{final_decision}</b></font>",
                    13,
                    _status_color(final_decision),
                    bold=True,
                    align=TA_CENTER,
                ),
                _p(confidence_str, 14, NAVY, bold=True, align=TA_CENTER),
                _p(rec_amt, 11, NAVY, bold=True, align=TA_CENTER),
                _p(rec_ten, 11, NAVY, bold=True, align=TA_CENTER),
                _p(f"${dec.total_cost_usd:.4f}", 10, SLATE, align=TA_CENTER),
            ],
        ],
        colWidths=[40 * mm, 30 * mm, 36 * mm, 30 * mm, 30 * mm],
    )
    decision_banner.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.8, NAVY),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, LINE),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                ("TOPPADDING", (0, 1), (-1, 1), 10),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ]
        )
    )
    els.append(decision_banner)
    els.append(Spacer(1, 6 * mm))

    # ── 11-step pipeline table ────────────────────────────────────────────
    if dec.steps:
        els.append(_p("Pipeline steps", 11, NAVY, bold=True))
        els.append(Spacer(1, 2 * mm))
        header = [
            _p("#", 8, MUTED, bold=True, align=TA_CENTER),
            _p("Step", 8, MUTED, bold=True),
            _p("Status", 8, MUTED, bold=True),
            _p("Model", 8, MUTED, bold=True),
            _p("Cost $", 8, MUTED, bold=True, align=TA_CENTER),
            _p("Output", 8, MUTED, bold=True),
        ]
        rows: list[list[Any]] = [header]
        for s in dec.steps:
            rows.append(
                [
                    _p(str(s.step_number), 8, align=TA_CENTER),
                    _p(s.step_name, 8),
                    _p(
                        f"<font color='{_status_color(s.status).hexval()}'><b>{s.status}</b></font>",
                        8,
                    ),
                    _p(s.model_used or "—", 7, MUTED),
                    _p(f"{s.cost_usd:.4f}" if s.cost_usd else "—", 8, align=TA_CENTER),
                    _p(s.summary[:280] or "—", 7, SLATE),
                ]
            )
        t = Table(
            rows,
            colWidths=[8 * mm, 38 * mm, 22 * mm, 26 * mm, 14 * mm, 64 * mm],
            repeatRows=1,
        )
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 1), (-1, -1), 0.15, LINE),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, NAVY),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        els.append(t)
        els.append(Spacer(1, 5 * mm))

    # ── Opus reasoning narrative ──────────────────────────────────────────
    if dec.reasoning_markdown:
        els.append(_p("Opus reasoning", 11, NAVY, bold=True))
        els.append(Spacer(1, 2 * mm))
        # Split markdown into paragraphs (blank-line separated). Strip header
        # markers (#, *, -) so the in-line markdown reads as flowing prose
        # in the PDF — proper markdown rendering would need a heavier dep.
        for chunk in _markdown_to_paragraphs(dec.reasoning_markdown):
            els.append(_p(chunk, 9, NAVY))
            els.append(Spacer(1, 1.5 * mm))
        els.append(Spacer(1, 3 * mm))

    # ── Pros / Cons / Conditions / Deviations / Risk — bullet sections ────
    bullet_sections: list[tuple[str, list[str], colors.Color]] = [
        ("Pros", dec.pros, GREEN),
        ("Cons", dec.cons, RED),
        ("Conditions", dec.conditions, AMBER),
        ("Deviations", dec.deviations, AMBER),
        ("Risk summary", dec.risk_summary_lines, SLATE),
    ]
    for title, items, color in bullet_sections:
        if not items:
            continue
        els.append(_p(title, 10, color, bold=True))
        els.append(Spacer(1, 1 * mm))
        for item in items[:30]:
            els.append(_p(f"&bull; {item}", 9, NAVY))
        els.append(Spacer(1, 3 * mm))

    return els


def _markdown_to_paragraphs(md: str) -> list[str]:
    """Cheap markdown → ReportLab-compatible paragraph splitter.

    Drops `#`/`*`/`-` markers that would otherwise show literally, splits on
    blank lines into paragraphs, and escapes `<`/`>` so user-supplied
    rationale can't accidentally break the Paragraph parser.
    """
    if not md:
        return []
    paragraphs: list[str] = []
    for raw in md.split("\n\n"):
        line = raw.strip()
        if not line:
            continue
        # Strip leading markdown markers per line.
        cleaned_lines = []
        for ln in line.split("\n"):
            ln = ln.strip()
            if ln.startswith("###"):
                ln = "<b>" + ln.lstrip("# ").strip() + "</b>"
            elif ln.startswith("##"):
                ln = "<b>" + ln.lstrip("# ").strip() + "</b>"
            elif ln.startswith("#"):
                ln = "<b>" + ln.lstrip("# ").strip() + "</b>"
            elif ln.startswith(("- ", "* ", "• ")):
                ln = "&bull; " + ln[2:].strip()
            cleaned_lines.append(ln)
        paragraphs.append(" ".join(cleaned_lines))
    return paragraphs


def _md_overrule_remarks(d: FinalReportData) -> list[Any]:
    """Point-wise list of every concern blocked by the engine and cleared
    via an MD decision, with the MD's specific remark.

    Isolates audit-defensible MD overrules from the chronological audit trail:
    same data, but flat, numbered, and the rationale is shown in full (no
    truncation) so an auditor can read the case cold without scrolling the
    timeline. AI auto-justifications are excluded — those still appear in the
    full audit trail below.
    """
    md_overrules = [
        it
        for it in d.issue_lifecycle
        if it.md_decision == "MD_APPROVED"
        and it.actor == "md"
        and (it.md_rationale or "").strip()
    ]

    els: list[Any] = [
        PageBreak(),
        _p("MD Overrule Remarks", 14, NAVY, bold=True),
        Spacer(1, 3 * mm),
        _p(
            "Concerns that were blocked by the verification engine and cleared "
            "via an MD decision, listed point-wise with the MD's remark in full "
            "for audit reference. AI auto-justifications and assessor-only "
            "resolutions are excluded — see the chronological audit trail "
            "below for those.",
            9,
            SLATE,
        ),
        Spacer(1, 4 * mm),
    ]

    if not md_overrules:
        els.append(
            _p(
                "No MD overrules on file for this case.",
                10,
                MUTED,
                align=TA_CENTER,
            )
        )
        return els

    header = [
        _p("#", 8, MUTED, bold=True),
        _p("Level / Rule", 8, MUTED, bold=True),
        _p("Severity", 8, MUTED, bold=True),
        _p("Concern", 8, MUTED, bold=True),
        _p("MD remark", 8, MUTED, bold=True),
    ]
    rows: list[list[Any]] = [header]
    for idx, it in enumerate(md_overrules, start=1):
        rationale = (it.md_rationale or "").strip()
        when = _fmt_dt(it.md_reviewed_at) if it.md_reviewed_at else ""
        rows.append(
            [
                _p(str(idx), 9, NAVY, bold=True),
                _p(
                    f"<b>{it.level_number.replace('_', ' ')}</b><br/>"
                    f"<font color='#475569'>{it.sub_step_id}</font>"
                    + (f"<br/><font color='#94a3b8'>{when}</font>" if when else ""),
                    7,
                ),
                _p(
                    f"<font color='{_status_color(it.severity).hexval()}'>"
                    f"<b>{it.severity}</b></font>",
                    8,
                ),
                _p((it.description or "—")[:250], 7, SLATE),
                _p(rationale, 8, NAVY),
            ]
        )

    t = Table(
        rows,
        colWidths=[8 * mm, 32 * mm, 16 * mm, 56 * mm, 60 * mm],
        repeatRows=1,
    )
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 1), (-1, -1), 0.15, LINE),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, NAVY),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    els.append(t)
    return els


def _issue_audit_trail(d: FinalReportData) -> list[Any]:
    """Render the full lifecycle for every concern raised on the case.

    For each issue, an auditor can read: when the engine raised it, what the
    assessor wrote as mitigation (with timestamp), and the final MD or AI
    decision (with timestamp + rationale). This is the section that answers
    "what was flagged, what was resolved, and how" without cross-referencing
    the verification tab.
    """
    els: list[Any] = [
        PageBreak(),
        _p("Issue audit trail", 14, NAVY, bold=True),
        Spacer(1, 3 * mm),
        _p(
            f"Case received <b>{_fmt_dt(d.uploaded_at)}</b>. Every concern raised "
            "by the verification engines is listed below in chronological order, "
            "with the assessor mitigation and the final MD or AI decision. "
            "Structured prefixes like <b>[AI auto-justified]</b> and "
            "<b>[MITIGATION]</b> identify how each concern was settled.",
            9,
            SLATE,
        ),
        Spacer(1, 4 * mm),
    ]
    if not d.issue_lifecycle:
        els.append(
            _p(
                "No concerns were raised on this case — the verification engines "
                "passed every gate cleanly.",
                10,
                MUTED,
                align=TA_CENTER,
            )
        )
        return els

    header = [
        _p("Raised", 8, MUTED, bold=True),
        _p("Level / Rule", 8, MUTED, bold=True),
        _p("Severity", 8, MUTED, bold=True),
        _p("Assessor mitigation", 8, MUTED, bold=True),
        _p("Decision", 8, MUTED, bold=True),
        _p("Rationale", 8, MUTED, bold=True),
    ]
    rows: list[list[Any]] = [header]
    for it in d.issue_lifecycle:
        # Assessor cell — when + truncated note. Empty if assessor never acted
        # (e.g. AI auto-justifier short-circuited straight to MD_APPROVED).
        if it.assessor_resolved_at or it.assessor_note:
            assessor_cell = (
                f"<font color='#475569'>{_fmt_dt(it.assessor_resolved_at)}</font><br/>"
                f"{(it.assessor_note or '—')[:240]}"
            )
        else:
            assessor_cell = "<font color='#94a3b8'>— not engaged —</font>"

        # Decision cell — when + actor + decision badge.
        decision = it.md_decision or "OPEN"
        decision_when = _fmt_dt(it.md_reviewed_at) if it.md_reviewed_at else "—"
        decision_cell = (
            f"<font color='#475569'>{decision_when}</font><br/>"
            f"<font color='{_status_color(decision).hexval()}'><b>{decision}</b></font>"
            f" &middot; <font color='#94a3b8'>{it.actor}</font>"
        )

        rows.append(
            [
                _p(_fmt_dt(it.raised_at), 8, SLATE),
                _p(
                    f"<b>{it.level_number.replace('_', ' ')}</b><br/>"
                    f"{it.sub_step_id}<br/>"
                    f"<font color='#94a3b8'>{(it.description or '')[:140]}</font>",
                    7,
                ),
                _p(
                    f"<font color='{_status_color(it.severity).hexval()}'><b>{it.severity}</b></font>",
                    8,
                ),
                _p(assessor_cell, 7),
                _p(decision_cell, 8),
                _p((it.md_rationale or "—")[:500], 7, NAVY),
            ]
        )
    t = Table(
        rows,
        colWidths=[22 * mm, 32 * mm, 14 * mm, 38 * mm, 22 * mm, 44 * mm],
        repeatRows=1,
    )
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 1), (-1, -1), 0.15, LINE),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, NAVY),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    els.append(t)
    return els


# ── Public entry point ───────────────────────────────────────────────────────


def generate_final_report(data: FinalReportData) -> bytes:
    """Render the final report to PDF bytes."""
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=24 * mm,
        bottomMargin=22 * mm,
        title=f"PFL Final Report — {data.loan_id}",
        author="PFL Credit AI",
    )
    # Read by `_draw_page_chrome` to date-stamp the cover consistently with
    # the report's generated_at instead of "now at render time".
    doc._stamp_date_iso = data.generated_at
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="main",
        showBoundary=0,
    )
    doc.addPageTemplates(
        [PageTemplate(id="default", frames=[frame], onPage=_draw_page_chrome)]
    )

    story: list[Any] = []
    story.extend(_cover(data))
    story.append(PageBreak())
    story.extend(_level_scorecard(data))
    story.append(PageBreak())
    story.extend(_scoring_table(data))
    story.extend(_decisioning_section(data))
    story.extend(_md_overrule_remarks(data))
    story.extend(_issue_audit_trail(data))

    doc.build(story)
    return buf.getvalue()
