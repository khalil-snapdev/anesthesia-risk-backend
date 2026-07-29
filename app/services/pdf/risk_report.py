"""Risk assessment report PDF.

Per CLAUDE.md's External Systems section: OMS Vision has no API, so this
is the entire integration — office staff manually attach this PDF to the
patient's chart in OMS Vision's Documents section.
"""

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models.embedded import MetsCapacity, RiskLevel
from app.models.patient import Patient
from app.services.pdf._shared import build_info_table, escape

_RISK_COLORS = {
    RiskLevel.LOW: colors.HexColor("#1a7f37"),
    RiskLevel.MODERATE: colors.HexColor("#9a6700"),
    RiskLevel.HIGH: colors.HexColor("#c9302c"),
}

_METS_LABELS = {
    MetsCapacity.BELOW_4: "< 4 METs (poor functional capacity - flag for further workup)",
    MetsCapacity.AT_OR_ABOVE_4: ">= 4 METs (adequate functional capacity)",
    MetsCapacity.UNKNOWN: "Unknown",
}

# Reportlab's default standard-14 fonts (Helvetica etc.) don't cover the
# Unicode em-dash — using a plain ASCII hyphen everywhere avoids missing
# glyphs (renders as a replacement box) without needing to embed a font.
_NOT_AVAILABLE = "N/A"


def _fmt_score(score: int | None) -> str:
    return str(score) if score is not None else _NOT_AVAILABLE


def _fmt_level(level: RiskLevel | None) -> str:
    return level.value.title() if level is not None else _NOT_AVAILABLE


def _fmt_mets(mets: MetsCapacity | None) -> str:
    if mets is None:
        return _NOT_AVAILABLE
    return _METS_LABELS[mets]


def generate_risk_report_pdf(patient: Patient) -> bytes:
    """Render a clinical risk assessment report as PDF bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        title=f"Risk Assessment Report - {patient.full_name}",
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    heading_style = styles["Heading2"]
    body_style = styles["Normal"]

    story: list[Any] = [
        Paragraph("Anesthesia Risk Assessment Report", styles["Title"]),
        Spacer(1, 12),
    ]

    # --- Patient demographics ---
    story.append(Paragraph("Patient Information", heading_style))
    demographics = [
        ["Name", patient.full_name],
        ["Date of Birth", patient.dob.isoformat()],
        ["Sex", patient.sex.value.title()],
        ["Surgery Date", patient.surgery_date.isoformat()],
        ["Patient ID", patient.patient_identifier],
    ]
    story.append(build_info_table(demographics))
    story.append(Spacer(1, 16))

    # --- Risk profile ---
    story.append(Paragraph("Risk Profile", heading_style))
    risk = patient.risk_assessment
    if risk is None:
        story.append(Paragraph("Risk assessment has not yet been calculated.", body_style))
    else:
        asa_note = (
            "clinician-suggested, pending confirmation"
            if risk.asa_suggested
            else "clinician-confirmed"
        )
        risk_rows = [
            ["ASA Class", f"{risk.asa_class or _NOT_AVAILABLE} ({asa_note})"],
            [
                "STOP-Bang",
                f"{_fmt_score(risk.stop_bang_score)} - {_fmt_level(risk.stop_bang_level)}",
            ],
            ["RCRI", f"{_fmt_score(risk.rcri_score)} - {_fmt_level(risk.rcri_level)}"],
            ["METs Capacity", _fmt_mets(risk.mets_capacity)],
        ]
        story.append(build_info_table(risk_rows))
        story.append(Spacer(1, 10))

        overall = risk.overall_risk_category
        overall_color = _RISK_COLORS.get(overall, colors.black) if overall else colors.black
        overall_style = ParagraphStyle(
            "OverallRisk", parent=styles["Heading3"], textColor=overall_color
        )
        story.append(
            Paragraph(f"Overall Risk Category: {_fmt_level(overall).upper()}", overall_style)
        )
    story.append(Spacer(1, 16))

    # --- Alerts ---
    story.append(Paragraph("Active Alerts", heading_style))
    if not patient.alerts:
        story.append(Paragraph("No alerts on record.", body_style))
    else:
        alert_rows = [["Type", "Message", "Severity", "Acknowledged"]]
        for alert in patient.alerts:
            if alert.acknowledged and alert.acknowledged_by:
                ack = f"Yes - {alert.acknowledged_by.full_name}"
            elif alert.acknowledged:
                ack = "Yes"
            else:
                ack = "No"
            alert_rows.append(
                [
                    alert.alert_type.value.replace("_", " ").title(),
                    alert.message,
                    alert.severity.value.title(),
                    ack,
                ]
            )
        story.append(build_info_table(alert_rows, header=True))
    story.append(Spacer(1, 16))

    # --- Recommended tests ---
    story.append(Paragraph("Recommended Pre-Operative Tests", heading_style))
    recommended = patient.recommendation_set.recommended_tests if patient.recommendation_set else []
    if not recommended:
        story.append(Paragraph("No tests recommended.", body_style))
    else:
        story.append(Paragraph(escape(", ".join(recommended)), body_style))
    story.append(Spacer(1, 16))

    # --- Clinician notes ---
    story.append(Paragraph("Clinician Notes", heading_style))
    story.append(
        Paragraph(escape(patient.notes) if patient.notes else "No notes on file.", body_style)
    )

    doc.build(story)
    return buffer.getvalue()
