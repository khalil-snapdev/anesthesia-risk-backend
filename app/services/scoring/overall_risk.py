from app.models.embedded import RiskLevel

_LEVEL_ORDER = {RiskLevel.LOW: 0, RiskLevel.MODERATE: 1, RiskLevel.HIGH: 2}


def calculate_overall_risk(
    asa_level: RiskLevel,
    stop_bang_level: RiskLevel,
    rcri_level: RiskLevel,
    has_critical_alert: bool,
) -> RiskLevel:
    """Overall risk category, per CLAUDE.md's Scoring Logic section.

    Overall = worst (highest) of ASA/STOP-Bang/RCRI levels. Any critical
    alert forces the result to HIGH regardless of the individual scores.
    """
    if has_critical_alert:
        return RiskLevel.HIGH

    return max((asa_level, stop_bang_level, rcri_level), key=lambda level: _LEVEL_ORDER[level])
