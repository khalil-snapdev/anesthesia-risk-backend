from app.models.embedded import RiskLevel


def generate_recommended_tests(
    on_anticoagulant: bool,
    is_diabetic: bool,
    stop_bang_level: RiskLevel,
    has_osa_diagnosis: bool,
    asa_level: RiskLevel,
    rcri_level: RiskLevel,
    rcri_score: int,
    is_pregnant: bool,
) -> list[str]:
    """Recommended tests, per CLAUDE.md's Recommended Test Rules."""
    tests: list[str] = []

    if on_anticoagulant:
        tests.append("INR")

    if is_diabetic:
        tests.append("HbA1c")

    if stop_bang_level == RiskLevel.HIGH or has_osa_diagnosis:
        tests.append("Sleep Study")

    if asa_level in (RiskLevel.MODERATE, RiskLevel.HIGH) or rcri_level != RiskLevel.LOW:
        tests.append("EKG")

    if rcri_score >= 2:
        tests.append("CBC")
        tests.append("CMP")

    if is_pregnant:
        tests.append("OB clearance")

    return tests
