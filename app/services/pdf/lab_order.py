"""Lab order PDF — the nurse's "Generate Lab Order" action output.

Printed/attached for the lab and for the patient's OMS Vision chart (no
API integration exists for either — see CLAUDE.md's External Systems
section).
"""

import io
from datetime import UTC, datetime
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models.embedded import ActorSnapshot
from app.models.patient import Patient
from app.services.pdf._shared import build_info_table

# Plain ASCII hyphen — reportlab's default standard-14 fonts don't cover
# the Unicode em-dash (renders as a missing-glyph box).
_REASON = "Pre-operative clearance - anesthesia risk assessment"


def generate_lab_order_pdf(patient: Patient, ordering_provider: ActorSnapshot) -> bytes:
    """Render a lab order as PDF bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        title=f"Laboratory Order - {patient.full_name}",
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    body_style = styles["Normal"]

    now = datetime.now(UTC)
    story: list[Any] = [
        Paragraph("Laboratory Order", styles["Title"]),
        Spacer(1, 12),
    ]

    info_rows = [
        ["Patient", patient.full_name],
        ["Date of Birth", patient.dob.isoformat()],
        [
            "Ordering Provider",
            f"{ordering_provider.full_name} ({ordering_provider.role.title()})",
        ],
        ["Order Date", now.date().isoformat()],
        ["Reason", _REASON],
    ]
    story.append(build_info_table(info_rows))
    story.append(Spacer(1, 20))

    story.append(Paragraph("Requested Tests", styles["Heading2"]))
    recommended_tests = (
        patient.recommendation_set.recommended_tests if patient.recommendation_set else []
    )
    if not recommended_tests:
        story.append(Paragraph("No tests currently recommended.", body_style))
    else:
        rows = [["Test"], *[[test] for test in recommended_tests]]
        story.append(build_info_table(rows, header=True))
    story.append(Spacer(1, 48))

    story.append(Paragraph("_" * 40, body_style))
    story.append(Paragraph("Ordering Provider Signature", body_style))
    story.append(Spacer(1, 16))
    story.append(Paragraph(f"Generated {now.strftime('%Y-%m-%d %H:%M UTC')}", styles["Italic"]))

    doc.build(story)
    return buffer.getvalue()
