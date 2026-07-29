import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest
from beanie import init_beanie
from beanie.odm.actions import ActionDirections, ActionRegistry, EventTypes
from pydantic import ValidationError

from app.models import Patient, User
from app.models.embedded import (
    ActorSnapshot,
    ExamFinding,
    IntakeRecord,
    IntakeSource,
    MetsCapacity,
    RiskAssessment,
    RiskLevel,
    VerificationStatus,
)
from app.models.patient import Sex
from app.models.user import Role


class _FakeCollection:
    """Minimal stand-in for the async collection surface init_beanie touches.

    No real MongoDB exists in CI for this phase — this fakes just enough of
    the index-management calls beanie makes during init_beanie so Document
    classes can be constructed and their save-hooks exercised in-process.
    """

    async def index_information(self) -> dict[str, Any]:
        return {}

    async def create_indexes(self, indexes: list[Any]) -> list[str]:
        return [f"idx_{i}" for i in range(len(indexes))]


class _FakeDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection())

    async def command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        return {"version": "7.0.0"}


@pytest.fixture(scope="module", autouse=True)
def _init_models() -> None:
    asyncio.run(
        init_beanie(
            database=_FakeDatabase(),  # type: ignore[arg-type]
            document_models=[User, Patient],
        )
    )


def make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "email": "jane.doe@example.com",
        "full_name": "Jane Doe",
        "google_sub_id": "google-sub-123",
    }
    defaults.update(overrides)
    return User(**defaults)


def make_actor_snapshot(**overrides: Any) -> ActorSnapshot:
    defaults: dict[str, Any] = {
        "user_id": "user-123",
        "full_name": "Jane Doe",
        "role": "nurse",
    }
    defaults.update(overrides)
    return ActorSnapshot(**defaults)


def make_patient(**overrides: Any) -> Patient:
    defaults: dict[str, Any] = {
        "full_name": "John Smith",
        "dob": date(1990, 1, 1),
        "sex": Sex.MALE,
        "surgery_date": date(2026, 8, 1),
        "created_by": make_user(),
    }
    defaults.update(overrides)
    return Patient(**defaults)


class TestUser:
    def test_creates_with_required_fields(self) -> None:
        user = make_user()
        assert user.email == "jane.doe@example.com"
        assert user.full_name == "Jane Doe"
        assert user.google_sub_id == "google-sub-123"

    def test_role_defaults_to_none(self) -> None:
        assert make_user().role is None

    def test_role_accepts_enum_value(self) -> None:
        assert make_user(role=Role.SURGEON).role == Role.SURGEON

    def test_is_active_defaults_to_true(self) -> None:
        assert make_user().is_active is True

    def test_created_at_and_updated_at_default_to_now(self) -> None:
        user = make_user()
        assert user.created_at is not None
        assert user.updated_at is not None

    @pytest.mark.asyncio
    async def test_updated_at_refreshes_on_save_hook(self) -> None:
        user = make_user()
        original_updated_at = user.updated_at

        await asyncio.sleep(0.01)
        await ActionRegistry.run_actions(
            user,
            event_type=EventTypes.SAVE,
            action_direction=ActionDirections.BEFORE,
            exclude=[],
        )

        assert user.updated_at > original_updated_at


class TestPatient:
    def test_creates_with_required_fields(self) -> None:
        patient = make_patient()
        assert patient.full_name == "John Smith"
        assert patient.sex == Sex.MALE

    def test_patient_identifier_auto_generated_when_omitted(self) -> None:
        patient = make_patient()
        assert patient.patient_identifier.startswith("PT-")

    def test_patient_identifier_respects_explicit_value(self) -> None:
        patient = make_patient(patient_identifier="PT-custom-001")
        assert patient.patient_identifier == "PT-custom-001"

    def test_is_deleted_defaults_to_false(self) -> None:
        assert make_patient().is_deleted is False

    def test_clinical_fields_default_to_none_before_intake(self) -> None:
        patient = make_patient()
        assert patient.intake_record is None
        assert patient.exam_finding is None
        assert patient.risk_assessment is None

    def test_clinical_fields_can_be_populated(self) -> None:
        actor = make_actor_snapshot()
        patient = make_patient(
            intake_record=IntakeRecord(
                raw_truform_payload={"patient_name": "John Smith"},
                medical_history={"diabetes": True},
                medications={},
                allergies={},
                surgical_history={},
                is_pregnant=False,
                verification_status=VerificationStatus.VERIFIED,
                submitted_at=datetime.now(UTC),
                source=IntakeSource.TRUFORM,
            ),
            exam_finding=ExamFinding(mallampati_class=2, entered_by=actor),
            risk_assessment=RiskAssessment(
                stop_bang_score=5,
                stop_bang_level=RiskLevel.HIGH,
                overall_risk_category=RiskLevel.HIGH,
                calculated_by=actor,
            ),
        )

        assert patient.intake_record is not None
        assert patient.intake_record.source == IntakeSource.TRUFORM
        assert patient.exam_finding is not None
        assert patient.exam_finding.mallampati_class == 2
        assert patient.risk_assessment is not None
        assert patient.risk_assessment.stop_bang_level == RiskLevel.HIGH

    def test_created_by_holds_linked_user(self) -> None:
        user = make_user()
        patient = make_patient(created_by=user)
        assert isinstance(patient.created_by, User)
        assert patient.created_by.full_name == user.full_name

    def test_dob_in_future_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            make_patient(dob=date(2999, 1, 1))

    def test_dob_today_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            make_patient(dob=datetime.now(UTC).date())

    def test_dob_in_past_is_accepted(self) -> None:
        patient = make_patient(dob=date(1990, 1, 1))
        assert patient.dob == date(1990, 1, 1)

    @pytest.mark.asyncio
    async def test_updated_at_refreshes_on_save_hook(self) -> None:
        patient = make_patient()
        original_updated_at = patient.updated_at

        await asyncio.sleep(0.01)
        await ActionRegistry.run_actions(
            patient,
            event_type=EventTypes.SAVE,
            action_direction=ActionDirections.BEFORE,
            exclude=[],
        )

        assert patient.updated_at > original_updated_at


def make_intake_record(**overrides: Any) -> IntakeRecord:
    defaults: dict[str, Any] = {
        "raw_truform_payload": {"patient_name": "John Smith"},
        "medical_history": {},
        "medications": {},
        "allergies": {},
        "surgical_history": {},
        "submitted_at": datetime.now(UTC),
        "source": IntakeSource.MANUAL,
    }
    defaults.update(overrides)
    return IntakeRecord(**defaults)


class TestIntakeRecord:
    def test_creates_with_required_fields(self) -> None:
        record = make_intake_record()
        assert record.source == IntakeSource.MANUAL
        assert record.raw_truform_payload == {"patient_name": "John Smith"}

    def test_is_pregnant_defaults_to_false(self) -> None:
        assert make_intake_record().is_pregnant is False

    def test_verification_status_defaults_to_pending(self) -> None:
        assert make_intake_record().verification_status == VerificationStatus.PENDING

    def test_verification_status_accepts_verified(self) -> None:
        record = make_intake_record(verification_status=VerificationStatus.VERIFIED)
        assert record.verification_status == VerificationStatus.VERIFIED


class TestExamFinding:
    def test_creates_with_no_findings_yet(self) -> None:
        finding = ExamFinding()
        assert finding.mallampati_class is None
        assert finding.airway_notes is None
        assert finding.entered_by is None
        assert finding.created_at is not None

    def test_mallampati_class_accepts_valid_range(self) -> None:
        for value in (1, 2, 3, 4):
            assert ExamFinding(mallampati_class=value).mallampati_class == value

    def test_mallampati_class_below_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ExamFinding(mallampati_class=0)

    def test_mallampati_class_above_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ExamFinding(mallampati_class=5)

    def test_entered_by_holds_actor_snapshot(self) -> None:
        actor = make_actor_snapshot(full_name="Nora Nurse", role="nurse")
        finding = ExamFinding(entered_by=actor)
        assert isinstance(finding.entered_by, ActorSnapshot)
        assert finding.entered_by.full_name == "Nora Nurse"
        assert finding.entered_by.role == "nurse"


class TestRiskAssessment:
    def test_creates_with_no_scores_yet(self) -> None:
        assessment = RiskAssessment()
        assert assessment.asa_class is None
        assert assessment.stop_bang_score is None
        assert assessment.rcri_score is None

    def test_asa_suggested_defaults_to_true(self) -> None:
        assert RiskAssessment().asa_suggested is True

    def test_asa_suggested_can_be_set_false_once_confirmed(self) -> None:
        assessment = RiskAssessment(asa_class="III", asa_suggested=False)
        assert assessment.asa_suggested is False

    def test_stop_bang_score_accepts_valid_range(self) -> None:
        for value in (0, 4, 8):
            assert RiskAssessment(stop_bang_score=value).stop_bang_score == value

    def test_stop_bang_score_below_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            RiskAssessment(stop_bang_score=-1)

    def test_stop_bang_score_above_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            RiskAssessment(stop_bang_score=9)

    def test_rcri_score_accepts_valid_range(self) -> None:
        for value in (0, 3, 6):
            assert RiskAssessment(rcri_score=value).rcri_score == value

    def test_rcri_score_below_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            RiskAssessment(rcri_score=-1)

    def test_rcri_score_above_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            RiskAssessment(rcri_score=7)

    def test_calculated_by_holds_actor_snapshot(self) -> None:
        actor = make_actor_snapshot(full_name="Sam Surgeon", role="surgeon")
        assessment = RiskAssessment(calculated_by=actor)
        assert isinstance(assessment.calculated_by, ActorSnapshot)
        assert assessment.calculated_by.full_name == "Sam Surgeon"
        assert assessment.calculated_by.role == "surgeon"

    def test_mets_capacity_accepts_enum_value(self) -> None:
        assessment = RiskAssessment(mets_capacity=MetsCapacity.BELOW_4)
        assert assessment.mets_capacity == MetsCapacity.BELOW_4
