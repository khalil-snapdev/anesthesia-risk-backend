"""Standalone, manually-run end-to-end CRUD smoke test against the real dev
database. Confirms the fully-assembled Patient model (all embedded
sub-documents from steps 1.3-1.5) round-trips correctly through MongoDB
before Phase 2 scoring logic is built on top of it. Not part of CI — run
this by hand:

    python scripts/smoke_test_patient_crud.py

Any documents it creates are deleted again before it exits, even on failure.
"""

import asyncio
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beanie import init_beanie
from pymongo import AsyncMongoClient

from app.config import settings
from app.models import document_models
from app.models.embedded import (
    ActorSnapshot,
    Alert,
    AlertSeverity,
    AlertType,
    ExamFinding,
    IntakeRecord,
    IntakeSource,
    MetsCapacity,
    RecommendationSet,
    RiskAssessment,
    RiskLevel,
    VerificationStatus,
)
from app.models.patient import Patient, Sex
from app.models.user import Role, User


def _check(condition: bool, description: str) -> bool:
    print(f"{'OK  ' if condition else 'FAIL'}: {description}")
    return condition


def _dt_close(a: datetime, b: datetime, tolerance_seconds: float = 1.0) -> bool:
    # Both sides are timezone-aware now that the client sets tz_aware=True,
    # so this is a plain subtraction. A tolerance is still needed because
    # BSON stores datetimes as milliseconds since epoch, so sub-millisecond
    # microseconds are truncated on round-trip (e.g. .198163 -> .198000) —
    # that's independent of timezone-awareness and won't go away.
    return abs((a - b).total_seconds()) < tolerance_seconds


async def main() -> int:
    client: AsyncMongoClient[Any] = AsyncMongoClient(settings.MONGODB_URI, tz_aware=True)
    marker = uuid.uuid4().hex[:8]
    results: list[bool] = []
    user: User | None = None
    patient: Patient | None = None

    try:
        await init_beanie(database=client.get_default_database(), document_models=document_models)
        print(f"Connected. Running Patient CRUD smoke test (marker={marker})...\n")

        # --- Create: User (role=nurse) ---
        user = User(
            email=f"smoke-test-{marker}@example.com",
            full_name="Nora Nurse",
            role=Role.NURSE,
            google_sub_id=f"smoke-sub-{marker}",
        )
        await user.insert()
        results.append(_check(user.id is not None, "User created (role=nurse)"))

        actor = ActorSnapshot(user_id=str(user.id), full_name=user.full_name, role=Role.NURSE.value)

        # --- Create: Patient with fully populated clinical payload ---
        submitted_at = datetime.now(UTC)
        intake_record = IntakeRecord(
            raw_truform_payload={"patient_name": "Smoke Test Patient", "dob": "1985-06-15"},
            medical_history={"diabetes": True, "hypertension": True},
            medications={"warfarin": "5mg daily"},
            allergies={"penicillin": "rash"},
            surgical_history={"prior_surgeries": ["appendectomy"]},
            is_pregnant=False,
            verification_status=VerificationStatus.VERIFIED,
            submitted_at=submitted_at,
            source=IntakeSource.TRUFORM,
        )
        exam_finding = ExamFinding(
            mallampati_class=3,
            airway_notes="Limited neck extension",
            entered_by=actor,
        )
        risk_assessment = RiskAssessment(
            asa_class="III",
            asa_suggested=True,
            stop_bang_score=6,
            stop_bang_level=RiskLevel.HIGH,
            rcri_score=1,
            rcri_level=RiskLevel.MODERATE,
            mets_capacity=MetsCapacity.BELOW_4,
            overall_risk_category=RiskLevel.HIGH,
            calculated_at=submitted_at,
            calculated_by=actor,
        )
        recommendation_set = RecommendationSet(
            recommended_tests=["EKG", "CBC", "INR", "Sleep Study"],
            generated_at=submitted_at,
        )
        # Severity/type pairing here is arbitrary test data for round-trip
        # purposes only — real alert-generation rules land in Phase 2.
        alert_critical = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 6 — high risk of OSA",
            severity=AlertSeverity.CRITICAL,
        )
        alert_warning = Alert(
            alert_type=AlertType.ANTICOAGULANT,
            message="Patient reports aspirin use — informational only",
            severity=AlertSeverity.WARNING,
        )

        patient = Patient(
            full_name="Smoke Test Patient",
            dob=date(1985, 6, 15),
            sex=Sex.FEMALE,
            surgery_date=date(2026, 9, 1),
            created_by=user,
            intake_record=intake_record,
            exam_finding=exam_finding,
            risk_assessment=risk_assessment,
            recommendation_set=recommendation_set,
            alerts=[alert_critical, alert_warning],
        )
        await patient.insert()
        results.append(_check(patient.id is not None, "Patient created, linked to User"))

        # --- Read: fetch back and verify every nested field round-trips ---
        fetched = await Patient.get(patient.id)
        assert fetched is not None, "Patient.get() returned None immediately after insert"
        results.append(_check(True, "Patient read back by id"))

        results.append(
            _check(
                fetched.intake_record is not None
                and fetched.intake_record.raw_truform_payload == intake_record.raw_truform_payload
                and fetched.intake_record.medical_history == intake_record.medical_history
                and fetched.intake_record.medications == intake_record.medications
                and fetched.intake_record.allergies == intake_record.allergies
                and fetched.intake_record.surgical_history == intake_record.surgical_history
                and fetched.intake_record.source == IntakeSource.TRUFORM
                and fetched.intake_record.verification_status == VerificationStatus.VERIFIED
                and _dt_close(fetched.intake_record.submitted_at, submitted_at),
                "intake_record round-trips intact",
            )
        )

        results.append(
            _check(
                fetched.exam_finding is not None
                and fetched.exam_finding.mallampati_class == 3
                and fetched.exam_finding.airway_notes == "Limited neck extension"
                and fetched.exam_finding.entered_by is not None
                and fetched.exam_finding.entered_by.full_name == "Nora Nurse"
                and fetched.exam_finding.entered_by.role == Role.NURSE.value,
                "exam_finding round-trips intact (including entered_by ActorSnapshot)",
            )
        )

        results.append(
            _check(
                fetched.risk_assessment is not None
                and fetched.risk_assessment.asa_class == "III"
                and fetched.risk_assessment.stop_bang_score == 6
                and fetched.risk_assessment.stop_bang_level == RiskLevel.HIGH
                and fetched.risk_assessment.rcri_score == 1
                and fetched.risk_assessment.mets_capacity == MetsCapacity.BELOW_4
                and fetched.risk_assessment.overall_risk_category == RiskLevel.HIGH
                and fetched.risk_assessment.calculated_by is not None
                and fetched.risk_assessment.calculated_by.full_name == "Nora Nurse",
                "risk_assessment round-trips intact (including calculated_by ActorSnapshot)",
            )
        )

        results.append(
            _check(
                fetched.recommendation_set is not None
                and fetched.recommendation_set.recommended_tests
                == ["EKG", "CBC", "INR", "Sleep Study"],
                "recommendation_set round-trips intact",
            )
        )

        results.append(
            _check(
                len(fetched.alerts) == 2
                and fetched.alerts[0].severity == AlertSeverity.CRITICAL
                and fetched.alerts[1].severity == AlertSeverity.WARNING
                and fetched.alerts[0].id != fetched.alerts[1].id
                and fetched.alerts[0].acknowledged is False
                and fetched.alerts[1].acknowledged is False,
                "alerts list round-trips intact (2 alerts, distinct ids, severities preserved)",
            )
        )

        # --- Update: acknowledge the critical alert ---
        ack_time = datetime.now(UTC)
        fetched.alerts[0].acknowledged = True
        fetched.alerts[0].acknowledged_by = actor
        fetched.alerts[0].acknowledged_at = ack_time
        await fetched.save()

        reread = await Patient.get(patient.id)
        assert reread is not None, "Patient.get() returned None after acknowledgment save"
        results.append(
            _check(
                reread.alerts[0].acknowledged is True
                and reread.alerts[0].acknowledged_by is not None
                and reread.alerts[0].acknowledged_by.full_name == "Nora Nurse"
                and reread.alerts[0].acknowledged_at is not None
                and _dt_close(reread.alerts[0].acknowledged_at, ack_time)
                and reread.alerts[1].acknowledged is False,
                "alert acknowledgment persists (only the targeted alert changed)",
            )
        )

        # --- Soft-delete: is_deleted=True, no hard delete ---
        reread.is_deleted = True
        await reread.save()

        after_soft_delete = await Patient.get(patient.id)
        results.append(
            _check(
                after_soft_delete is not None and after_soft_delete.is_deleted is True,
                "soft-delete sets is_deleted=True without removing the document",
            )
        )

    finally:
        if patient is not None:
            await patient.delete()
        if user is not None:
            await user.delete()
        await client.close()

    print()
    if all(results):
        print("All Patient CRUD smoke test steps passed.")
        return 0
    print("One or more smoke test steps FAILED — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
