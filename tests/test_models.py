import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest
from beanie import init_beanie
from beanie.odm.actions import ActionDirections, ActionRegistry, EventTypes
from pydantic import ValidationError

from app.models import Patient, User
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
