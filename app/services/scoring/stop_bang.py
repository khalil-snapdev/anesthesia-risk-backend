from app.models.embedded import RiskLevel


def calculate_stop_bang(
    snoring: bool,
    tired: bool,
    observed_apnea: bool,
    hypertension: bool,
    bmi: float,
    age: int,
    neck_circumference_cm: float,
    is_male: bool,
) -> tuple[int, RiskLevel]:
    """STOP-Bang OSA screening score, per CLAUDE.md's Scoring Logic section.

    One point each for: Snoring, Tired, Observed apnea, Pressure/HTN,
    BMI>35, Age>50, Neck>40cm, Gender=male. 0-2 = low, 3-4 = moderate,
    5-8 = high.
    """
    score = sum(
        (
            snoring,
            tired,
            observed_apnea,
            hypertension,
            bmi > 35,
            age > 50,
            neck_circumference_cm > 40,
            is_male,
        )
    )

    if score <= 2:
        level = RiskLevel.LOW
    elif score <= 4:
        level = RiskLevel.MODERATE
    else:
        level = RiskLevel.HIGH

    return score, level
