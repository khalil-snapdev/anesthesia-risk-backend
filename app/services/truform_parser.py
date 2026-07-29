"""Truform (PBHS) intake field parser.

Truform's API defaults to JSON over a poll-based API — see CLAUDE.md's
External Systems section. A submission is a list of key/value pairs;
forms are dynamic, so a field the patient left blank is simply omitted
rather than sent as null/empty — never assume a fixed schema. Values may
arrive as native JSON types or as strings depending on the field, so
every extraction here defensively coerces rather than assuming a type.

parse_truform_payload() must never raise on malformed/incomplete input —
it always returns a best-effort ParsedIntakeData plus gap lists
(missing_for_scoring, unmapped_fields).
"""

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field

# Per CLAUDE.md's Alert Trigger Rules anticoagulant list.
_ANTICOAGULANT_DRUGS = frozenset(
    {
        "warfarin",
        "apixaban",
        "rivaroxaban",
        "dabigatran",
        "edoxaban",
        "clopidogrel",
    }
)

# Truform structurally has no field for these — always flagged as missing
# for scoring, regardless of payload content.
_ALWAYS_MISSING_FOR_SCORING = (
    "tired_during_day",
    "observed_apnea",
    "neck_circumference_cm",
    "mallampati_class",  # exam-only, never captured at intake
)

# health_history_allergies_penicillin, _sulfa_drugs, _latex are the
# specific flag fields confirmed so far — PBHS may have more of these that
# aren't yet documented; extend this tuple as more are confirmed.
_SPECIFIC_ALLERGY_FLAG_FIELDS = (
    "health_history_allergies_penicillin",
    "health_history_allergies_sulfa_drugs",
    "health_history_allergies_latex",
)

_MEDICATION_FIELD_COUNT = 20
_ALLERGY_NAME_FIELD_COUNT = 10

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y")


class ParsedIntakeData(BaseModel):
    # IntakeRecord-shaped fields.
    raw_truform_payload: dict[str, Any]
    medical_history: dict[str, Any]
    medications: dict[str, Any]
    allergies: dict[str, Any]
    surgical_history: dict[str, Any]
    is_pregnant: bool

    # Best-effort scoring inputs — None means genuinely unknown, not "no".
    snoring: bool | None = None
    hypertension: bool | None = None
    age: int | None = None
    is_male: bool | None = None
    bmi: float | None = None
    on_anticoagulant: bool | None = None
    is_diabetic: bool | None = None
    ischemic_heart_disease: bool | None = None
    cerebrovascular_disease: bool | None = None
    # Weak signal only (yes/no, not a lab value) — needs lab confirmation
    # before it's used to auto-score the RCRI creatinine point.
    kidney_trouble_flag: bool | None = None

    # Demographics, best-effort (used by callers constructing a Patient).
    full_name: str | None = None
    dob: str | None = None

    missing_for_scoring: list[str] = Field(default_factory=list)
    unmapped_fields: list[str] = Field(default_factory=list)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_bool_flag(value: Any) -> bool | None:
    text = _as_str(value)
    if text is None:
        return None
    normalized = text.lower()
    if normalized in ("yes", "true", "1", "y"):
        return True
    if normalized in ("no", "false", "0", "n"):
        return False
    return None


def _parse_float(value: Any) -> float | None:
    text = _as_str(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    return int(parsed) if parsed is not None else None


def parse_date_string(text: str) -> date | None:
    """Best-effort parse of a Truform date field into a real date.

    Exposed for callers (e.g. the router) that need an actual date —
    ParsedIntakeData only carries dob as a raw string, since the exact
    format isn't confirmed by real sample data yet. Tries a small set of
    common formats and gives up (returns None) rather than guess further.
    """
    for fmt in _DATE_FORMATS:
        try:
            # Only the date component is kept — a birthdate has no
            # timezone to be aware of.
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _combine_optional_flags(*flags: bool | None) -> bool | None:
    """OR-combine flags conservatively.

    Any confirmed True wins. Only resolves to False when every flag is
    confirmed False (no unknowns mixed in) — a mix of False and unknown
    stays unknown rather than silently reporting a clean negative.
    """
    if any(flag is True for flag in flags):
        return True
    if all(flag is False for flag in flags):
        return False
    return None


def _derive_is_male(sex_description: Any) -> bool | None:
    text = _as_str(sex_description)
    if text is None:
        return None
    normalized = text.lower()
    if normalized in ("female", "f"):
        return False
    if normalized in ("male", "m"):
        return True
    return None


def _derive_age(raw: dict[str, Any]) -> int | None:
    direct = _parse_int(raw.get("patient_self_age"))
    if direct is not None:
        return direct

    dob_text = _as_str(raw.get("patient_self_date_of_birth"))
    if dob_text is None:
        return None
    dob = parse_date_string(dob_text)
    if dob is None:
        return None
    today = datetime.now(UTC).date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _calculate_bmi(raw: dict[str, Any]) -> float | None:
    # PBHS intake forms are US-market — assumed imperial units (lbs,
    # inches), since no metric fields appear in the field docs. Revisit
    # once a real sample payload confirms units.
    weight_lb = _parse_float(raw.get("health_history_current_weight"))
    height_in = _parse_float(raw.get("health_history_current_height"))
    if weight_lb is None or height_in is None or height_in <= 0:
        return None
    return round(703 * weight_lb / (height_in**2), 1)


def _collect_medications(raw: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
    """Returns (medications, has_known_anticoagulant, has_any_entry).

    has_any_entry distinguishes "a medication list was actually provided
    but nothing matched our anticoagulant list" (a real negative) from
    "no medication data at all" (genuinely unknown) — see
    _combine_optional_flags.
    """
    medications: dict[str, Any] = {}
    has_known_anticoagulant = False
    has_any_entry = False
    for i in range(1, _MEDICATION_FIELD_COUNT + 1):
        name = _as_str(raw.get(f"medication{i}_name"))
        if name is None:
            continue
        has_any_entry = True
        medications[f"medication{i}_name"] = name
        if name.lower() in _ANTICOAGULANT_DRUGS:
            has_known_anticoagulant = True
    return medications, has_known_anticoagulant, has_any_entry


def _collect_allergies(raw: dict[str, Any]) -> dict[str, Any]:
    allergies: dict[str, Any] = {}

    for field in _SPECIFIC_ALLERGY_FLAG_FIELDS:
        flag = _parse_bool_flag(raw.get(field))
        if flag is not None:
            allergies[field] = flag

    known_allergies_text = _as_str(raw.get("health_history_allergies_known_allergies"))
    if known_allergies_text is not None:
        allergies["health_history_allergies_known_allergies"] = known_allergies_text

    for i in range(1, _ALLERGY_NAME_FIELD_COUNT + 1):
        name = _as_str(raw.get(f"health_history_allergies{i}_name"))
        if name is not None:
            allergies[f"health_history_allergies{i}_name"] = name

    return allergies


def _recognized_field_names() -> set[str]:
    names = {
        "health_history_medical_snoring",
        "health_history_medical_sleep_apnea_snoring",
        "health_history_medical_high_blood_pressure",
        "patient_self_age",
        "patient_self_date_of_birth",
        "patient_self_sex_description",
        "patient_self_first_name",
        "patient_self_last_name",
        "health_history_current_weight",
        "health_history_current_height",
        "health_history_medication_blood_thinners",
        "health_history_medical_diabetes",
        "health_history_medical_heart_attack",
        "health_history_medical_angina",
        "health_history_medical_stroke",
        "health_history_medical_kidney_trouble",
        "health_history_pregnancy",
        "health_history_allergies_known_allergies",
        *_SPECIFIC_ALLERGY_FLAG_FIELDS,
    }
    names.update(f"medication{i}_name" for i in range(1, _MEDICATION_FIELD_COUNT + 1))
    names.update(
        f"health_history_allergies{i}_name" for i in range(1, _ALLERGY_NAME_FIELD_COUNT + 1)
    )
    return names


def _empty_result(raw: Any) -> ParsedIntakeData:
    return ParsedIntakeData(
        raw_truform_payload=raw if isinstance(raw, dict) else {},
        medical_history={},
        medications={},
        allergies={},
        surgical_history={},
        is_pregnant=False,
        missing_for_scoring=[*_ALWAYS_MISSING_FOR_SCORING, "bmi", "age", "is_male"],
        unmapped_fields=[],
    )


def parse_truform_payload(raw: dict[str, Any]) -> ParsedIntakeData:
    if not isinstance(raw, dict):
        return _empty_result(raw)

    try:
        snoring = _parse_bool_flag(raw.get("health_history_medical_snoring"))
        if snoring is None:
            snoring = _parse_bool_flag(raw.get("health_history_medical_sleep_apnea_snoring"))

        hypertension = _parse_bool_flag(raw.get("health_history_medical_high_blood_pressure"))
        age = _derive_age(raw)
        is_male = _derive_is_male(raw.get("patient_self_sex_description"))
        bmi = _calculate_bmi(raw)

        blood_thinner_flag = _parse_bool_flag(raw.get("health_history_medication_blood_thinners"))
        medications, medication_list_has_anticoagulant, medication_list_has_any_entry = (
            _collect_medications(raw)
        )
        if medication_list_has_anticoagulant:
            medication_signal: bool | None = True
        elif medication_list_has_any_entry:
            medication_signal = False
        else:
            medication_signal = None
        on_anticoagulant = _combine_optional_flags(blood_thinner_flag, medication_signal)

        is_diabetic = _parse_bool_flag(raw.get("health_history_medical_diabetes"))
        heart_attack = _parse_bool_flag(raw.get("health_history_medical_heart_attack"))
        angina = _parse_bool_flag(raw.get("health_history_medical_angina"))
        ischemic_heart_disease = _combine_optional_flags(heart_attack, angina)
        cerebrovascular_disease = _parse_bool_flag(raw.get("health_history_medical_stroke"))
        kidney_trouble_flag = _parse_bool_flag(raw.get("health_history_medical_kidney_trouble"))
        is_pregnant = bool(_parse_bool_flag(raw.get("health_history_pregnancy")))

        allergies = _collect_allergies(raw)

        first_name = _as_str(raw.get("patient_self_first_name"))
        last_name = _as_str(raw.get("patient_self_last_name"))
        full_name = " ".join(part for part in (first_name, last_name) if part) or None
        dob = _as_str(raw.get("patient_self_date_of_birth"))

        missing: list[str] = list(_ALWAYS_MISSING_FOR_SCORING)
        if bmi is None:
            missing.append("bmi")
        if age is None:
            missing.append("age")
        if is_male is None:
            missing.append("is_male")

        recognized = _recognized_field_names()
        unmapped = sorted(key for key in raw if key not in recognized)

        return ParsedIntakeData(
            raw_truform_payload=raw,
            medical_history={
                "diabetes": is_diabetic,
                "heart_attack": heart_attack,
                "angina": angina,
                "stroke": cerebrovascular_disease,
                "hypertension": hypertension,
                "kidney_trouble": kidney_trouble_flag,
            },
            medications=medications,
            allergies=allergies,
            surgical_history={},
            is_pregnant=is_pregnant,
            snoring=snoring,
            hypertension=hypertension,
            age=age,
            is_male=is_male,
            bmi=bmi,
            on_anticoagulant=on_anticoagulant,
            is_diabetic=is_diabetic,
            ischemic_heart_disease=ischemic_heart_disease,
            cerebrovascular_disease=cerebrovascular_disease,
            kidney_trouble_flag=kidney_trouble_flag,
            full_name=full_name,
            dob=dob,
            missing_for_scoring=missing,
            unmapped_fields=unmapped,
        )
    except Exception:  # noqa: BLE001 — must never raise on malformed input
        return _empty_result(raw)
