import pytest

from app.models.embedded import MetsCapacity, RiskLevel
from app.services.scoring.asa import asa_class_to_level, suggest_asa_class
from app.services.scoring.mets import classify_mets
from app.services.scoring.overall_risk import calculate_overall_risk
from app.services.scoring.rcri import calculate_rcri
from app.services.scoring.stop_bang import calculate_stop_bang


class TestStopBang:
    def test_all_negative_is_zero_low(self) -> None:
        score, level = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=22.0,
            age=30,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 0
        assert level == RiskLevel.LOW

    def test_all_positive_is_eight_high(self) -> None:
        score, level = calculate_stop_bang(
            snoring=True,
            tired=True,
            observed_apnea=True,
            hypertension=True,
            bmi=40.0,
            age=60,
            neck_circumference_cm=45.0,
            is_male=True,
        )
        assert score == 8
        assert level == RiskLevel.HIGH

    def test_score_two_is_low(self) -> None:
        score, level = calculate_stop_bang(
            snoring=True,
            tired=True,
            observed_apnea=False,
            hypertension=False,
            bmi=22.0,
            age=30,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 2
        assert level == RiskLevel.LOW

    def test_score_three_is_moderate(self) -> None:
        score, level = calculate_stop_bang(
            snoring=True,
            tired=True,
            observed_apnea=True,
            hypertension=False,
            bmi=22.0,
            age=30,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 3
        assert level == RiskLevel.MODERATE

    def test_score_four_is_moderate(self) -> None:
        score, level = calculate_stop_bang(
            snoring=True,
            tired=True,
            observed_apnea=True,
            hypertension=True,
            bmi=22.0,
            age=30,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 4
        assert level == RiskLevel.MODERATE

    def test_score_five_is_high(self) -> None:
        score, level = calculate_stop_bang(
            snoring=True,
            tired=True,
            observed_apnea=True,
            hypertension=True,
            bmi=40.0,
            age=30,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 5
        assert level == RiskLevel.HIGH

    def test_bmi_exactly_35_does_not_count(self) -> None:
        score, _ = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=35.0,
            age=30,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 0

    def test_bmi_above_35_counts(self) -> None:
        score, _ = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=35.1,
            age=30,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 1

    def test_age_exactly_50_does_not_count(self) -> None:
        score, _ = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=22.0,
            age=50,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 0

    def test_age_above_50_counts(self) -> None:
        score, _ = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=22.0,
            age=51,
            neck_circumference_cm=35.0,
            is_male=False,
        )
        assert score == 1

    def test_neck_exactly_40_does_not_count(self) -> None:
        score, _ = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=22.0,
            age=30,
            neck_circumference_cm=40.0,
            is_male=False,
        )
        assert score == 0

    def test_neck_above_40_counts(self) -> None:
        score, _ = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=22.0,
            age=30,
            neck_circumference_cm=40.1,
            is_male=False,
        )
        assert score == 1

    def test_is_male_counts_as_one_point(self) -> None:
        score, _ = calculate_stop_bang(
            snoring=False,
            tired=False,
            observed_apnea=False,
            hypertension=False,
            bmi=22.0,
            age=30,
            neck_circumference_cm=35.0,
            is_male=True,
        )
        assert score == 1


class TestRcri:
    def test_zero_factors_is_low(self) -> None:
        score, level = calculate_rcri(
            high_risk_surgery=False,
            ischemic_heart_disease=False,
            chf=False,
            cerebrovascular_disease=False,
            insulin_dependent_diabetes=False,
            creatinine_above_2=False,
        )
        assert score == 0
        assert level == RiskLevel.LOW

    def test_one_factor_is_moderate(self) -> None:
        score, level = calculate_rcri(
            high_risk_surgery=True,
            ischemic_heart_disease=False,
            chf=False,
            cerebrovascular_disease=False,
            insulin_dependent_diabetes=False,
            creatinine_above_2=False,
        )
        assert score == 1
        assert level == RiskLevel.MODERATE

    def test_two_factors_is_high(self) -> None:
        score, level = calculate_rcri(
            high_risk_surgery=True,
            ischemic_heart_disease=True,
            chf=False,
            cerebrovascular_disease=False,
            insulin_dependent_diabetes=False,
            creatinine_above_2=False,
        )
        assert score == 2
        assert level == RiskLevel.HIGH

    def test_all_six_factors_is_high(self) -> None:
        score, level = calculate_rcri(
            high_risk_surgery=True,
            ischemic_heart_disease=True,
            chf=True,
            cerebrovascular_disease=True,
            insulin_dependent_diabetes=True,
            creatinine_above_2=True,
        )
        assert score == 6
        assert level == RiskLevel.HIGH

    def test_each_factor_individually_scores_one_point(self) -> None:
        assert calculate_rcri(True, False, False, False, False, False)[0] == 1
        assert calculate_rcri(False, True, False, False, False, False)[0] == 1
        assert calculate_rcri(False, False, True, False, False, False)[0] == 1
        assert calculate_rcri(False, False, False, True, False, False)[0] == 1
        assert calculate_rcri(False, False, False, False, True, False)[0] == 1
        assert calculate_rcri(False, False, False, False, False, True)[0] == 1


class TestSuggestAsaClass:
    def test_no_comorbidities_suggests_class_one(self) -> None:
        asa_class, asa_suggested = suggest_asa_class([])
        assert asa_class == "I"
        assert asa_suggested is True

    def test_controlled_hypertension_suggests_class_two(self) -> None:
        asa_class, asa_suggested = suggest_asa_class(["controlled hypertension"])
        assert asa_class == "II"
        assert asa_suggested is True

    def test_copd_suggests_class_three(self) -> None:
        asa_class, _ = suggest_asa_class(["COPD"])
        assert asa_class == "III"

    def test_unstable_angina_suggests_class_four(self) -> None:
        asa_class, _ = suggest_asa_class(["unstable angina"])
        assert asa_class == "IV"

    def test_unrecognized_comorbidity_defaults_to_class_two(self) -> None:
        asa_class, _ = suggest_asa_class(["some rare condition not in the keyword list"])
        assert asa_class == "II"

    def test_worst_comorbidity_wins_when_multiple_present(self) -> None:
        asa_class, _ = suggest_asa_class(["controlled hypertension", "unstable angina"])
        assert asa_class == "IV"

    def test_is_case_insensitive(self) -> None:
        asa_class, _ = suggest_asa_class(["UNSTABLE ANGINA"])
        assert asa_class == "IV"

    def test_asa_suggested_is_always_true_never_a_final_value(self) -> None:
        for comorbidities in ([], ["hypertension"], ["unstable angina"], ["copd"]):
            _, asa_suggested = suggest_asa_class(comorbidities)
            assert asa_suggested is True


class TestAsaClassToLevel:
    def test_class_one_is_low(self) -> None:
        assert asa_class_to_level("I") == RiskLevel.LOW

    def test_class_two_is_low(self) -> None:
        assert asa_class_to_level("II") == RiskLevel.LOW

    def test_class_three_is_moderate(self) -> None:
        assert asa_class_to_level("III") == RiskLevel.MODERATE

    @pytest.mark.parametrize("asa_class", ["IV", "V", "VI"])
    def test_classes_four_through_six_are_high(self, asa_class: str) -> None:
        assert asa_class_to_level(asa_class) == RiskLevel.HIGH


class TestClassifyMets:
    def test_can_climb_two_flights_is_at_or_above_4(self) -> None:
        assert classify_mets(True) == MetsCapacity.AT_OR_ABOVE_4

    def test_cannot_climb_two_flights_is_below_4(self) -> None:
        assert classify_mets(False) == MetsCapacity.BELOW_4


class TestCalculateOverallRisk:
    def test_all_low_is_low(self) -> None:
        result = calculate_overall_risk(
            asa_level=RiskLevel.LOW,
            stop_bang_level=RiskLevel.LOW,
            rcri_level=RiskLevel.LOW,
            has_critical_alert=False,
        )
        assert result == RiskLevel.LOW

    def test_one_moderate_among_lows_is_moderate(self) -> None:
        result = calculate_overall_risk(
            asa_level=RiskLevel.MODERATE,
            stop_bang_level=RiskLevel.LOW,
            rcri_level=RiskLevel.LOW,
            has_critical_alert=False,
        )
        assert result == RiskLevel.MODERATE

    @pytest.mark.parametrize(
        ("asa_level", "stop_bang_level", "rcri_level"),
        [
            (RiskLevel.HIGH, RiskLevel.LOW, RiskLevel.LOW),
            (RiskLevel.LOW, RiskLevel.HIGH, RiskLevel.LOW),
            (RiskLevel.LOW, RiskLevel.LOW, RiskLevel.HIGH),
            (RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.MODERATE),
        ],
    )
    def test_any_high_makes_overall_high(
        self, asa_level: RiskLevel, stop_bang_level: RiskLevel, rcri_level: RiskLevel
    ) -> None:
        result = calculate_overall_risk(
            asa_level=asa_level,
            stop_bang_level=stop_bang_level,
            rcri_level=rcri_level,
            has_critical_alert=False,
        )
        assert result == RiskLevel.HIGH

    def test_critical_alert_forces_high_even_when_all_low(self) -> None:
        result = calculate_overall_risk(
            asa_level=RiskLevel.LOW,
            stop_bang_level=RiskLevel.LOW,
            rcri_level=RiskLevel.LOW,
            has_critical_alert=True,
        )
        assert result == RiskLevel.HIGH

    def test_critical_alert_forces_high_even_when_others_moderate(self) -> None:
        result = calculate_overall_risk(
            asa_level=RiskLevel.MODERATE,
            stop_bang_level=RiskLevel.MODERATE,
            rcri_level=RiskLevel.MODERATE,
            has_critical_alert=True,
        )
        assert result == RiskLevel.HIGH
