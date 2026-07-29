"""ASA physical status suggestion.

Per CLAUDE.md: ASA is clinician-suggested only and never auto-finalized —
this function always returns asa_suggested=True and must never be treated
as a confirmed value. The keyword mapping below is a simple starting
heuristic, not an authoritative clinical scoring system — a clinician
always makes the final call.
"""

from app.models.embedded import RiskLevel

# Ordered most-severe first: the first matching tier wins.
_CLASS_IV_KEYWORDS = (
    "unstable angina",
    "recent mi",
    "myocardial infarction",
    "decompensated heart failure",
    "severe copd",
    "sepsis",
    "severe valvular disease",
)
_CLASS_III_KEYWORDS = (
    "copd",
    "chf",
    "congestive heart failure",
    "coronary artery disease",
    "chronic kidney disease",
    "poorly controlled diabetes",
    "morbid obesity",
)
_CLASS_II_KEYWORDS = (
    "controlled hypertension",
    "controlled diabetes",
    "well-controlled diabetes",
    "mild asthma",
    "hypertension",
    "diabetes",
    "asthma",
    "obesity",
)


def _any_keyword_present(comorbidities: list[str], keywords: tuple[str, ...]) -> bool:
    return any(keyword in comorbidity for comorbidity in comorbidities for keyword in keywords)


def suggest_asa_class(comorbidities: list[str]) -> tuple[str, bool]:
    normalized = [c.lower() for c in comorbidities]

    if _any_keyword_present(normalized, _CLASS_IV_KEYWORDS):
        return "IV", True
    if _any_keyword_present(normalized, _CLASS_III_KEYWORDS):
        return "III", True
    if _any_keyword_present(normalized, _CLASS_II_KEYWORDS):
        return "II", True
    if normalized:
        return "II", True
    return "I", True


def asa_class_to_level(asa_class: str) -> RiskLevel:
    """Map an ASA class letter to a risk level, per CLAUDE.md's Scoring
    Logic section: I-II = Low, III = Moderate, IV-VI = High.
    """
    if asa_class in ("I", "II"):
        return RiskLevel.LOW
    if asa_class == "III":
        return RiskLevel.MODERATE
    return RiskLevel.HIGH
