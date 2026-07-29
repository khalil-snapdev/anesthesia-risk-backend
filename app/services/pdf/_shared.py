"""Small shared helpers for building consistent-looking PDF reports."""

import html
from typing import Any

from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle


def escape(text: str) -> str:
    """Escape user-supplied text before handing it to a reportlab
    Paragraph, which interprets a small XML-like markup language —
    clinician-entered free text should never be treated as markup.
    """
    return html.escape(text)


def build_info_table(rows: list[list[str]], *, header: bool = False) -> Table:
    """A simple bordered info table.

    header=False: a label/value table — the first column is bold.
    header=True: a data table — the first row is bold with shading.
    """
    table = Table(rows, hAlign="LEFT")
    style_commands: list[tuple[Any, ...]] = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        style_commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")))
        style_commands.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
    else:
        style_commands.append(("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"))
    table.setStyle(TableStyle(style_commands))
    return table
