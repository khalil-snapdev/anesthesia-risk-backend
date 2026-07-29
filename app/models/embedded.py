import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ActorSnapshot(BaseModel):
    user_id: str
    full_name: str
    role: str


class AlertType(StrEnum):
    ANTICOAGULANT = "anticoagulant"
    SEVERE_ALLERGY = "severe_allergy"
    OSA = "osa"
    AIRWAY_CONCERN = "airway_concern"


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"


class IntakeSource(StrEnum):
    TRUFORM = "truform"
    MANUAL = "manual"


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class MetsCapacity(StrEnum):
    BELOW_4 = "below_4"
    AT_OR_ABOVE_4 = "at_or_above_4"
    UNKNOWN = "unknown"


class IntakeRecord(BaseModel):
    raw_truform_payload: dict[str, Any]
    medical_history: dict[str, Any]
    medications: dict[str, Any]
    allergies: dict[str, Any]
    surgical_history: dict[str, Any]
    is_pregnant: bool = False
    verification_status: VerificationStatus = VerificationStatus.PENDING
    submitted_at: datetime
    source: IntakeSource


class ExamFinding(BaseModel):
    mallampati_class: int | None = None
    airway_notes: str | None = None
    entered_by: ActorSnapshot | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("mallampati_class")
    @classmethod
    def mallampati_class_in_range(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 4:
            raise ValueError("mallampati_class must be between 1 and 4")
        return value


class RiskAssessment(BaseModel):
    asa_class: str | None = None
    asa_suggested: bool = True
    stop_bang_score: int | None = None
    stop_bang_level: RiskLevel | None = None
    rcri_score: int | None = None
    rcri_level: RiskLevel | None = None
    mets_capacity: MetsCapacity | None = None
    overall_risk_category: RiskLevel | None = None
    calculated_at: datetime | None = None
    calculated_by: ActorSnapshot | None = None

    @field_validator("stop_bang_score")
    @classmethod
    def stop_bang_score_in_range(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 8:
            raise ValueError("stop_bang_score must be between 0 and 8")
        return value

    @field_validator("rcri_score")
    @classmethod
    def rcri_score_in_range(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 6:
            raise ValueError("rcri_score must be between 0 and 6")
        return value


class RecommendationSet(BaseModel):
    recommended_tests: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    alert_type: AlertType
    message: str
    severity: AlertSeverity
    acknowledged: bool = False
    acknowledged_by: ActorSnapshot | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
