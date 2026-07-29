from app.models.embedded import RiskLevel


def calculate_rcri(
    high_risk_surgery: bool,
    ischemic_heart_disease: bool,
    chf: bool,
    cerebrovascular_disease: bool,
    insulin_dependent_diabetes: bool,
    creatinine_above_2: bool,
) -> tuple[int, RiskLevel]:
    """Revised Cardiac Risk Index, per CLAUDE.md's Scoring Logic section.

    One point each for: high-risk surgery, ischemic heart disease, CHF,
    cerebrovascular disease, insulin-dependent diabetes, creatinine >2.0.
    0 points = low, 1 point = moderate, 2+ points = high.
    """
    score = sum(
        (
            high_risk_surgery,
            ischemic_heart_disease,
            chf,
            cerebrovascular_disease,
            insulin_dependent_diabetes,
            creatinine_above_2,
        )
    )

    if score == 0:
        level = RiskLevel.LOW
    elif score == 1:
        level = RiskLevel.MODERATE
    else:
        level = RiskLevel.HIGH

    return score, level
