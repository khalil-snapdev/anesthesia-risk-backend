from datetime import UTC, date, datetime
from typing import Any

from beanie import Link
from pydantic import BaseModel, Field, field_validator

from app.models.embedded import (
    ActorSnapshot,
    Alert,
    ExamFinding,
    IntakeRecord,
    IntakeSource,
    RecommendationSet,
    RiskAssessment,
    RiskLevel,
    VerificationStatus,
)
from app.models.patient import Patient, Sex
from app.models.user import User


def _created_by_id(created_by: "Link[User] | User") -> str:
    if isinstance(created_by, Link):
        return str(created_by.ref.id)
    return str(created_by.id)


class PatientCreate(BaseModel):
    full_name: str
    dob: date
    sex: Sex
    surgery_date: date
    # Plain user_id stand-in until Phase 6 auth exists.
    created_by: str

    # Mirrors Patient.dob_must_be_in_past so a bad dob fails FastAPI's
    # automatic 422 handling here, rather than as a raw ValidationError
    # from constructing the Patient document deeper in the route.
    @field_validator("dob")
    @classmethod
    def dob_must_be_in_past(cls, value: date) -> date:
        if value >= datetime.now(UTC).date():
            raise ValueError("dob must be in the past")
        return value


class PatientRead(BaseModel):
    id: str
    patient_identifier: str
    full_name: str
    dob: date
    sex: Sex
    surgery_date: date
    is_deleted: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str

    intake_record: IntakeRecord | None
    exam_finding: ExamFinding | None
    risk_assessment: RiskAssessment | None
    recommendation_set: RecommendationSet | None
    alerts: list[Alert]

    @classmethod
    def from_patient(cls, patient: Patient) -> "PatientRead":
        return cls(
            id=str(patient.id),
            patient_identifier=patient.patient_identifier,
            full_name=patient.full_name,
            dob=patient.dob,
            sex=patient.sex,
            surgery_date=patient.surgery_date,
            is_deleted=patient.is_deleted,
            notes=patient.notes,
            created_at=patient.created_at,
            updated_at=patient.updated_at,
            created_by=_created_by_id(patient.created_by),
            intake_record=patient.intake_record,
            exam_finding=patient.exam_finding,
            risk_assessment=patient.risk_assessment,
            recommendation_set=patient.recommendation_set,
            alerts=patient.alerts,
        )


class PatientListItem(BaseModel):
    id: str
    name: str
    dob: date
    surgery_date: date
    overall_risk_category: RiskLevel | None
    has_unacknowledged_alerts: bool

    @classmethod
    def from_patient(cls, patient: Patient) -> "PatientListItem":
        return cls(
            id=str(patient.id),
            name=patient.full_name,
            dob=patient.dob,
            surgery_date=patient.surgery_date,
            overall_risk_category=(
                patient.risk_assessment.overall_risk_category if patient.risk_assessment else None
            ),
            has_unacknowledged_alerts=any(not alert.acknowledged for alert in patient.alerts),
        )


class IntakeRecordUpdate(BaseModel):
    raw_truform_payload: dict[str, Any]
    medical_history: dict[str, Any]
    medications: dict[str, Any]
    allergies: dict[str, Any]
    surgical_history: dict[str, Any]
    is_pregnant: bool = False
    verification_status: VerificationStatus = VerificationStatus.PENDING
    submitted_at: datetime
    source: IntakeSource
    # Who performed this update — audit-trail only, no auth yet (Phase 6).
    actor: ActorSnapshot


class ExamFindingUpdate(BaseModel):
    mallampati_class: int | None = None
    airway_notes: str | None = None
    # Doubles as both the exam_finding.entered_by value and the audit actor.
    entered_by: ActorSnapshot

    # Mirrors ExamFinding.mallampati_class_in_range — see PatientCreate.dob
    # comment above for why this is duplicated at the schema layer.
    @field_validator("mallampati_class")
    @classmethod
    def mallampati_class_in_range(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 4:
            raise ValueError("mallampati_class must be between 1 and 4")
        return value


class CalculateRiskRequest(BaseModel):
    # STOP-Bang inputs
    snoring: bool
    tired: bool
    observed_apnea: bool
    hypertension: bool
    bmi: float
    age: int
    neck_circumference_cm: float
    is_male: bool

    # RCRI inputs
    high_risk_surgery: bool
    ischemic_heart_disease: bool
    chf: bool
    cerebrovascular_disease: bool
    insulin_dependent_diabetes: bool
    creatinine_above_2: bool

    # ASA inputs
    comorbidities: list[str] = Field(default_factory=list)

    # METs inputs
    can_climb_two_flights: bool

    # Alert / recommendation inputs — mallampati_class comes from the
    # patient's stored exam_finding instead of being resupplied here.
    medications: list[str] = Field(default_factory=list)
    allergy_notes: str = ""
    airway_history_notes: str = ""
    is_diabetic: bool = False
    has_osa_diagnosis: bool = False
    is_pregnant: bool = False

    # Doubles as both risk_assessment.calculated_by and the audit actor.
    calculated_by: ActorSnapshot


class NotesUpdate(BaseModel):
    notes: str
    # Audit-trail only — Patient has no notes-author field of its own.
    actor: ActorSnapshot
