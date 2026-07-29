import json
from pathlib import Path
from typing import Any

from app.services.truform_parser import parse_date_string, parse_truform_payload

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "sample_truform_payload.json"


def _load_sample_submission() -> dict[str, Any]:
    return dict(json.loads(_FIXTURE_PATH.read_text(encoding="utf-8")))


class TestParseRealisticFixture:
    def test_extracts_demographics(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        assert parsed.full_name == "John Doe"
        assert parsed.age == 58
        assert parsed.is_male is True
        assert parsed.dob == "1968-03-15"

    def test_calculates_bmi_from_weight_and_height(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        # 703 * 180 / 70**2 = 25.82... rounded to 1 decimal place.
        assert parsed.bmi == 25.8

    def test_extracts_stop_bang_and_rcri_relevant_flags(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        assert parsed.snoring is True
        assert parsed.hypertension is True
        assert parsed.is_diabetic is False
        assert parsed.ischemic_heart_disease is False
        assert parsed.cerebrovascular_disease is False
        assert parsed.is_pregnant is False

    def test_kidney_trouble_is_a_weak_flag_not_a_creatinine_value(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        assert parsed.kidney_trouble_flag is False

    def test_detects_anticoagulant_via_blood_thinner_flag_and_medication_name(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        assert parsed.on_anticoagulant is True
        assert "medication2_name" in parsed.medications
        assert parsed.medications["medication2_name"] == "Warfarin"

    def test_collects_specific_and_free_text_allergies(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        assert parsed.allergies["health_history_allergies_penicillin"] is True
        assert parsed.allergies["health_history_allergies_sulfa_drugs"] is False
        assert (
            parsed.allergies["health_history_allergies_known_allergies"]
            == "Penicillin - causes rash"
        )
        assert parsed.allergies["health_history_allergies1_name"] == "Penicillin"

    def test_always_flags_permanently_missing_scoring_fields(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        for field in (
            "tired_during_day",
            "observed_apnea",
            "neck_circumference_cm",
            "mallampati_class",
        ):
            assert field in parsed.missing_for_scoring

    def test_bmi_age_is_male_not_flagged_missing_when_present(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        assert "bmi" not in parsed.missing_for_scoring
        assert "age" not in parsed.missing_for_scoring
        assert "is_male" not in parsed.missing_for_scoring

    def test_flags_unrecognized_fields_as_unmapped(self) -> None:
        parsed = parse_truform_payload(_load_sample_submission())
        assert "insurance_provider_name" in parsed.unmapped_fields
        assert "patient_self_middle_name" in parsed.unmapped_fields

    def test_raw_payload_preserved_untouched(self) -> None:
        raw = _load_sample_submission()
        parsed = parse_truform_payload(raw)
        assert parsed.raw_truform_payload == raw


class TestAgeFallbackToDateOfBirth:
    def test_derives_age_from_dob_when_age_field_absent(self) -> None:
        raw = {
            "patient_self_date_of_birth": "1990-06-01",
            "patient_self_sex_description": "Female",
        }
        parsed = parse_truform_payload(raw)
        assert parsed.age is not None
        assert parsed.age >= 34  # as of 2026, born mid-1990

    def test_age_field_takes_priority_over_dob(self) -> None:
        raw = {
            "patient_self_age": "45",
            "patient_self_date_of_birth": "1968-03-15",
        }
        parsed = parse_truform_payload(raw)
        assert parsed.age == 45


class TestSexDerivation:
    def test_female_is_not_male(self) -> None:
        parsed = parse_truform_payload({"patient_self_sex_description": "Female"})
        assert parsed.is_male is False

    def test_unrecognized_sex_description_is_unknown(self) -> None:
        parsed = parse_truform_payload({"patient_self_sex_description": "Unspecified"})
        assert parsed.is_male is None


class TestAnticoagulantCrossCheck:
    def test_medication_name_alone_triggers_without_blood_thinner_flag(self) -> None:
        raw = {"medication1_name": "Apixaban"}
        parsed = parse_truform_payload(raw)
        assert parsed.on_anticoagulant is True

    def test_aspirin_alone_does_not_trigger(self) -> None:
        raw = {
            "health_history_medication_blood_thinners": "no",
            "medication1_name": "Aspirin",
        }
        parsed = parse_truform_payload(raw)
        assert parsed.on_anticoagulant is False

    def test_unknown_when_no_signal_at_all(self) -> None:
        parsed = parse_truform_payload({})
        assert parsed.on_anticoagulant is None


class TestBmiCalculation:
    def test_none_when_weight_missing(self) -> None:
        parsed = parse_truform_payload({"health_history_current_height": "70"})
        assert parsed.bmi is None
        assert "bmi" in parsed.missing_for_scoring

    def test_none_when_height_missing(self) -> None:
        parsed = parse_truform_payload({"health_history_current_weight": "180"})
        assert parsed.bmi is None

    def test_none_when_height_is_zero(self) -> None:
        raw = {"health_history_current_weight": "180", "health_history_current_height": "0"}
        parsed = parse_truform_payload(raw)
        assert parsed.bmi is None


class TestMalformedAndEmptyInput:
    def test_empty_dict_does_not_raise(self) -> None:
        parsed = parse_truform_payload({})
        assert parsed.full_name is None
        assert parsed.missing_for_scoring[:4] == [
            "tired_during_day",
            "observed_apnea",
            "neck_circumference_cm",
            "mallampati_class",
        ]

    def test_non_dict_input_does_not_raise(self) -> None:
        parsed = parse_truform_payload(None)  # type: ignore[arg-type]
        assert parsed.raw_truform_payload == {}
        assert parsed.medications == {}

    def test_garbage_values_do_not_raise(self) -> None:
        raw = {
            "patient_self_age": "not-a-number",
            "health_history_current_weight": "heavy",
            "health_history_current_height": [],
            "patient_self_sex_description": 12345,
            "medication1_name": {"unexpected": "structure"},
        }
        parsed = parse_truform_payload(raw)
        assert parsed.age is None
        assert parsed.bmi is None
        assert parsed.is_male is None

    def test_never_raises_regardless_of_input_shape(self) -> None:
        bad_inputs: list[Any] = [None, [], "a string", 42, {"a": {"b": {"c": object()}}}]
        for bad_input in bad_inputs:
            parse_truform_payload(bad_input)


class TestParseDateString:
    def test_parses_iso_format(self) -> None:
        result = parse_date_string("1990-06-01")
        assert result is not None
        assert (result.year, result.month, result.day) == (1990, 6, 1)

    def test_parses_us_slash_format(self) -> None:
        result = parse_date_string("06/01/1990")
        assert result is not None
        assert (result.year, result.month, result.day) == (1990, 6, 1)

    def test_returns_none_for_unparseable_text(self) -> None:
        assert parse_date_string("not a date") is None
