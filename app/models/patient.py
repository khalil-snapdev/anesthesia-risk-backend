import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import ClassVar

from beanie import Document, Link, Save, before_event
from pydantic import Field, field_validator
from pymongo import IndexModel

from app.models.embedded import ExamFinding, IntakeRecord, RiskAssessment
from app.models.user import User


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class Patient(Document):
    patient_identifier: str = Field(default_factory=lambda: f"PT-{uuid.uuid4()}")
    full_name: str
    dob: date
    sex: Sex
    surgery_date: date
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: Link[User]

    intake_record: IntakeRecord | None = None
    exam_finding: ExamFinding | None = None
    risk_assessment: RiskAssessment | None = None

    # Added in Step 1.5:
    # recommendation_set: RecommendationSet | None = None
    # alerts: list[Alert] = []

    class Settings:
        name = "patients"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel("patient_identifier", unique=True),
            IndexModel("surgery_date"),
            IndexModel("is_deleted"),
        ]

    @field_validator("dob")
    @classmethod
    def dob_must_be_in_past(cls, value: date) -> date:
        if value >= datetime.now(UTC).date():
            raise ValueError("dob must be in the past")
        return value

    @before_event(Save)
    def refresh_updated_at(self) -> None:
        self.updated_at = datetime.now(UTC)
