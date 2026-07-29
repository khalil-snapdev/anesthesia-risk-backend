import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from beanie import Link, init_beanie
from bson import DBRef, ObjectId
from httpx import ASGITransport, AsyncClient

from app.auth.jwt_handler import create_access_token
from app.database import get_db_client
from app.main import app
from app.models import AuditLogEntry, Patient, User, document_models
from app.models.audit_log import AuditAction
from app.models.embedded import (
    ActorSnapshot,
    Alert,
    AlertSeverity,
    AlertType,
    ExamFinding,
    RiskAssessment,
    RiskLevel,
)
from app.models.patient import Sex
from app.models.user import Role
from app.routers import patients as patients_router


class _FakeCollection:
    """Minimal stand-in for the async collection surface init_beanie touches.

    No real MongoDB exists in CI — this only needs to support beanie's own
    init_beanie bookkeeping. Every actual read/write the routes perform is
    monkeypatched directly on the Document classes per test.
    """

    async def index_information(self) -> dict[str, Any]:
        return {}

    async def create_indexes(self, indexes: list[Any]) -> list[str]:
        return [f"idx_{i}" for i in range(len(indexes))]


class _FakeClient:
    """Stands in for AsyncMongoClient's driver-metadata reporting (PyMongo
    >=4.14). append_metadata=None makes beanie's callable() check skip it,
    matching pre-4.14 behavior.
    """

    append_metadata = None


class _FakeDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = {}
        self.client = _FakeClient()

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection())

    async def command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        return {"version": "7.0.0"}


@pytest.fixture(scope="module", autouse=True)
def _init_models() -> None:
    asyncio.run(
        init_beanie(
            database=_FakeDatabase(),  # type: ignore[arg-type]
            document_models=document_models,
        )
    )


class _FakeSession:
    async def with_transaction(self, callback: Any) -> Any:
        return await callback(self)


class _FakeSessionContext:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _FakeTransactionClient:
    def start_session(self) -> _FakeSessionContext:
        return _FakeSessionContext()


@pytest.fixture(autouse=True)
def _override_db_client() -> Iterator[None]:
    app.dependency_overrides[get_db_client] = lambda: _FakeTransactionClient()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "email": "jane.doe@example.com",
        "full_name": "Jane Doe",
        "role": Role.NURSE,
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


def _patch_writes_as_no_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Patient, "insert", AsyncMock(return_value=None))
    monkeypatch.setattr(Patient, "save", AsyncMock(return_value=None))
    monkeypatch.setattr(AuditLogEntry, "insert", AsyncMock(return_value=None))


def _mock_record_audit_entry(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch record_audit_entry as imported into the router module.

    Patching AuditLogEntry.insert directly can't assert on entry content:
    AsyncMock doesn't bind `self`, so it never receives the constructed
    entry object, only the `session=` kwarg. Patching the function that
    builds the entry lets tests inspect call_args.kwargs instead.
    """
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(patients_router, "record_audit_entry", mock)
    return mock


def _auth_headers_for(user: User) -> dict[str, str]:
    token = create_access_token(user_id=str(user.id), role=user.role.value if user.role else None)
    return {"Authorization": f"Bearer {token}"}


def _mock_current_user(monkeypatch: pytest.MonkeyPatch, user: User) -> None:
    """Mock the DB lookup get_current_user performs while decoding a token."""
    monkeypatch.setattr(User, "get", AsyncMock(return_value=user))


class TestGetPatient:
    @pytest.mark.asyncio
    async def test_returns_full_patient_detail(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))

        response = await client.get(f"/patients/{patient.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(patient.id)
        assert body["full_name"] == "John Smith"
        assert body["intake_record"] is None
        assert body["alerts"] == []

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        response = await client.get("/patients/507f1f77bcf86cd799439011")

        assert response.status_code == 404
        assert response.json() == {"error": "not_found", "message": "Patient not found"}

    @pytest.mark.asyncio
    async def test_returns_404_when_soft_deleted(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient(is_deleted=True)
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))

        response = await client.get(f"/patients/{patient.id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_404_for_malformed_id(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await client.get("/patients/not-a-valid-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resolves_created_by_when_stored_as_unresolved_link(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A patient fetched straight from MongoDB (rather than constructed
        # in-process) holds created_by as an unresolved Link, not a User
        # instance — confirm PatientRead handles that shape too.
        owner_id = ObjectId()
        patient = make_patient(created_by=Link(DBRef("users", owner_id), User))
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))

        response = await client.get(f"/patients/{patient.id}")

        assert response.status_code == 200
        assert response.json()["created_by"] == str(owner_id)


class TestListPatients:
    @pytest.mark.asyncio
    async def test_returns_list_items_with_expected_shape(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient_with_risk = make_patient(
            full_name="Alice Alpha",
            risk_assessment=RiskAssessment(overall_risk_category=RiskLevel.HIGH),
            alerts=[
                Alert(
                    alert_type=AlertType.OSA,
                    message="STOP-Bang score 6",
                    severity=AlertSeverity.CRITICAL,
                )
            ],
        )
        patient_without_risk = make_patient(full_name="Bob Beta")

        find_result = MagicMock()
        find_result.to_list = AsyncMock(return_value=[patient_with_risk, patient_without_risk])
        monkeypatch.setattr(Patient, "find", MagicMock(return_value=find_result))

        actor = make_user()
        _mock_current_user(monkeypatch, actor)

        response = await client.get("/patients", headers=_auth_headers_for(actor))

        assert response.status_code == 200
        body = response.json()
        assert body == [
            {
                "id": str(patient_with_risk.id),
                "name": "Alice Alpha",
                "dob": "1990-01-01",
                "surgery_date": "2026-08-01",
                "overall_risk_category": "high",
                "has_unacknowledged_alerts": True,
            },
            {
                "id": str(patient_without_risk.id),
                "name": "Bob Beta",
                "dob": "1990-01-01",
                "surgery_date": "2026-08-01",
                "overall_risk_category": None,
                "has_unacknowledged_alerts": False,
            },
        ]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_patients(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        find_result = MagicMock()
        find_result.to_list = AsyncMock(return_value=[])
        monkeypatch.setattr(Patient, "find", MagicMock(return_value=find_result))

        actor = make_user()
        _mock_current_user(monkeypatch, actor)

        response = await client.get("/patients", headers=_auth_headers_for(actor))

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_returns_401_without_token(self, client: AsyncClient) -> None:
        response = await client.get("/patients")

        assert response.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", [Role.SURGEON, Role.NURSE, Role.OFFICE_STAFF])
    async def test_accessible_to_all_three_roles(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, role: Role
    ) -> None:
        find_result = MagicMock()
        find_result.to_list = AsyncMock(return_value=[])
        monkeypatch.setattr(Patient, "find", MagicMock(return_value=find_result))

        actor = make_user(role=role)
        _mock_current_user(monkeypatch, actor)

        response = await client.get("/patients", headers=_auth_headers_for(actor))

        assert response.status_code == 200


class TestCreatePatient:
    @pytest.mark.asyncio
    async def test_creates_patient_and_returns_201(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.post(
            "/patients",
            json={
                "full_name": "New Patient",
                "dob": "1985-03-10",
                "sex": "female",
                "surgery_date": "2026-09-01",
                "created_by": str(owner.id),
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["full_name"] == "New Patient"
        assert body["created_by"] == str(owner.id)
        assert body["patient_identifier"].startswith("PT-")
        assert body["is_deleted"] is False

        audit_mock.assert_awaited_once()
        audit_kwargs = audit_mock.call_args.kwargs
        assert audit_kwargs["entity_type"] == "Patient"
        assert audit_kwargs["entity_id"] == body["id"]
        assert audit_kwargs["action"] == AuditAction.CREATE
        assert audit_kwargs["actor"].user_id == str(owner.id)
        assert audit_kwargs["actor"].role == "nurse"
        assert audit_kwargs["changes"]["before"] is None
        assert audit_kwargs["changes"]["after"] == {
            "full_name": "New Patient",
            "dob": "1985-03-10",
            "sex": "female",
            "surgery_date": "2026-09-01",
            "patient_identifier": body["patient_identifier"],
        }

    @pytest.mark.asyncio
    async def test_returns_404_when_created_by_user_missing(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(User, "get", AsyncMock(return_value=None))

        response = await client.post(
            "/patients",
            json={
                "full_name": "New Patient",
                "dob": "1985-03-10",
                "sex": "female",
                "surgery_date": "2026-09-01",
                "created_by": "507f1f77bcf86cd799439011",
            },
        )

        assert response.status_code == 404
        assert response.json() == {"error": "not_found", "message": "User not found"}

    @pytest.mark.asyncio
    async def test_returns_404_when_created_by_is_malformed_id(self, client: AsyncClient) -> None:
        response = await client.post(
            "/patients",
            json={
                "full_name": "New Patient",
                "dob": "1985-03-10",
                "sex": "female",
                "surgery_date": "2026-09-01",
                "created_by": "not-a-valid-id",
            },
        )

        assert response.status_code == 404
        assert response.json() == {"error": "not_found", "message": "User not found"}

    @pytest.mark.asyncio
    async def test_returns_422_when_required_field_missing(self, client: AsyncClient) -> None:
        response = await client.post(
            "/patients",
            json={
                "dob": "1985-03-10",
                "sex": "female",
                "surgery_date": "2026-09-01",
                "created_by": "507f1f77bcf86cd799439011",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_for_future_dob(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))

        response = await client.post(
            "/patients",
            json={
                "full_name": "New Patient",
                "dob": "2999-01-01",
                "sex": "female",
                "surgery_date": "2026-09-01",
                "created_by": str(owner.id),
            },
        )

        assert response.status_code == 422


class TestUpdateIntake:
    @pytest.mark.asyncio
    async def test_updates_intake_record(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)

        response = await client.patch(
            f"/patients/{patient.id}/intake",
            json={
                "raw_truform_payload": {"patient_name": "John Smith"},
                "medical_history": {"diabetes": True},
                "medications": {"warfarin": "5mg"},
                "allergies": {},
                "surgical_history": {},
                "is_pregnant": False,
                "verification_status": "verified",
                "submitted_at": "2026-07-01T12:00:00Z",
                "source": "truform",
                "actor": {"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["intake_record"]["verification_status"] == "verified"
        assert body["intake_record"]["medical_history"] == {"diabetes": True}

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        response = await client.patch(
            "/patients/507f1f77bcf86cd799439011/intake",
            json={
                "raw_truform_payload": {},
                "medical_history": {},
                "medications": {},
                "allergies": {},
                "surgical_history": {},
                "submitted_at": "2026-07-01T12:00:00Z",
                "source": "manual",
                "actor": {"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
            },
        )

        assert response.status_code == 404


class TestUpdateExamFinding:
    @pytest.mark.asyncio
    async def test_updates_exam_finding(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)

        nurse = make_user(role=Role.NURSE)
        _mock_current_user(monkeypatch, nurse)

        response = await client.patch(
            f"/patients/{patient.id}/exam-finding",
            json={
                "mallampati_class": 3,
                "airway_notes": "Limited neck extension",
                "entered_by": {"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
            },
            headers=_auth_headers_for(nurse),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["exam_finding"]["mallampati_class"] == 3
        assert body["exam_finding"]["entered_by"]["full_name"] == "Nora Nurse"

    @pytest.mark.asyncio
    async def test_returns_422_for_out_of_range_mallampati(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nurse = make_user(role=Role.NURSE)
        _mock_current_user(monkeypatch, nurse)

        response = await client.patch(
            "/patients/507f1f77bcf86cd799439011/exam-finding",
            json={
                "mallampati_class": 5,
                "entered_by": {"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
            },
            headers=_auth_headers_for(nurse),
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        nurse = make_user(role=Role.NURSE)
        _mock_current_user(monkeypatch, nurse)

        response = await client.patch(
            "/patients/507f1f77bcf86cd799439011/exam-finding",
            json={
                "mallampati_class": 2,
                "entered_by": {"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
            },
            headers=_auth_headers_for(nurse),
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_401_without_token(self, client: AsyncClient) -> None:
        response = await client.patch(
            "/patients/507f1f77bcf86cd799439011/exam-finding",
            json={
                "mallampati_class": 2,
                "entered_by": {"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", [Role.SURGEON, Role.OFFICE_STAFF])
    async def test_rejects_non_nurse_role_with_403(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, role: Role
    ) -> None:
        non_nurse = make_user(role=role)
        _mock_current_user(monkeypatch, non_nurse)

        response = await client.patch(
            "/patients/507f1f77bcf86cd799439011/exam-finding",
            json={
                "mallampati_class": 2,
                "entered_by": {"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
            },
            headers=_auth_headers_for(non_nurse),
        )

        assert response.status_code == 403
        assert response.json() == {
            "error": "forbidden",
            "message": "Insufficient permissions for this action",
        }


class TestCalculateRisk:
    def _valid_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "snoring": True,
            "tired": True,
            "observed_apnea": True,
            "hypertension": True,
            "bmi": 40.0,
            "age": 60,
            "neck_circumference_cm": 45.0,
            "is_male": True,
            "high_risk_surgery": False,
            "ischemic_heart_disease": False,
            "chf": False,
            "cerebrovascular_disease": False,
            "insulin_dependent_diabetes": False,
            "creatinine_above_2": False,
            "comorbidities": ["controlled hypertension"],
            "can_climb_two_flights": True,
            "medications": ["Warfarin"],
            "allergy_notes": "History of anaphylaxis",
            "airway_history_notes": "",
            "is_diabetic": True,
            "has_osa_diagnosis": False,
            "is_pregnant": False,
            "calculated_by": {"user_id": "u1", "full_name": "Sam Surgeon", "role": "surgeon"},
        }
        payload.update(overrides)
        return payload

    @pytest.mark.asyncio
    async def test_calculates_and_persists_full_risk_profile(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.post(
            f"/patients/{patient.id}/calculate-risk", json=self._valid_payload()
        )

        assert response.status_code == 200
        body = response.json()
        risk = body["risk_assessment"]
        assert risk["stop_bang_score"] == 8
        assert risk["stop_bang_level"] == "high"
        assert risk["rcri_score"] == 0
        assert risk["rcri_level"] == "low"
        assert risk["asa_class"] == "II"
        assert risk["asa_suggested"] is True
        assert risk["mets_capacity"] == "at_or_above_4"
        # A critical alert (OSA/anticoagulant/severe_allergy) forces HIGH.
        assert risk["overall_risk_category"] == "high"

        recommended_tests = body["recommendation_set"]["recommended_tests"]
        assert "INR" in recommended_tests
        assert "HbA1c" in recommended_tests
        assert "Sleep Study" in recommended_tests

        alert_types = {a["alert_type"] for a in body["alerts"]}
        assert alert_types == {"anticoagulant", "severe_allergy", "osa"}

        audit_mock.assert_awaited_once()
        audit_kwargs = audit_mock.call_args.kwargs
        assert audit_kwargs["entity_type"] == "Patient"
        assert audit_kwargs["action"] == AuditAction.UPDATE
        assert audit_kwargs["actor"].full_name == "Sam Surgeon"
        # A first-time calculation has no prior state.
        assert audit_kwargs["changes"]["before"] == {
            "risk_assessment": None,
            "recommendation_set": None,
            "alerts": [],
        }
        after = audit_kwargs["changes"]["after"]
        assert after["risk_assessment"]["overall_risk_category"] == "high"
        assert {a["alert_type"] for a in after["alerts"]} == {
            "anticoagulant",
            "severe_allergy",
            "osa",
        }

    @pytest.mark.asyncio
    async def test_audit_entry_captures_prior_state_on_recalculation(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prior_risk_assessment = RiskAssessment(
            asa_class="II",
            asa_suggested=True,
            stop_bang_score=2,
            stop_bang_level=RiskLevel.LOW,
            rcri_score=0,
            rcri_level=RiskLevel.LOW,
            overall_risk_category=RiskLevel.LOW,
        )
        existing_alert = Alert(
            alert_type=AlertType.ANTICOAGULANT,
            message="Patient is on anticoagulant medication: Warfarin",
            severity=AlertSeverity.CRITICAL,
        )
        patient = make_patient(risk_assessment=prior_risk_assessment, alerts=[existing_alert])
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.post(
            f"/patients/{patient.id}/calculate-risk", json=self._valid_payload()
        )

        assert response.status_code == 200
        audit_kwargs = audit_mock.call_args.kwargs
        before = audit_kwargs["changes"]["before"]
        assert before["risk_assessment"]["overall_risk_category"] == "low"
        assert before["risk_assessment"]["stop_bang_score"] == 2
        assert len(before["alerts"]) == 1
        assert before["alerts"][0]["alert_type"] == "anticoagulant"
        # The recalculation itself produces a HIGH-risk profile — before
        # must reflect the prior LOW state, not the freshly-calculated one.
        after = audit_kwargs["changes"]["after"]
        assert after["risk_assessment"]["overall_risk_category"] == "high"

    @pytest.mark.asyncio
    async def test_uses_stored_exam_finding_mallampati_for_airway_alert(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient(exam_finding=ExamFinding(mallampati_class=4))
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)

        payload = self._valid_payload(
            medications=[], allergy_notes="", comorbidities=[], hypertension=False, snoring=False
        )
        response = await client.post(f"/patients/{patient.id}/calculate-risk", json=payload)

        assert response.status_code == 200
        alert_types = {a["alert_type"] for a in response.json()["alerts"]}
        assert "airway_concern" in alert_types

    @pytest.mark.asyncio
    async def test_preserves_acknowledgment_when_same_alert_type_recurs(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ack_by = make_actor_snapshot(full_name="Nora Nurse", role="nurse")
        ack_at = datetime(2026, 7, 1, tzinfo=UTC)
        existing_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 5 — high risk of OSA",
            severity=AlertSeverity.CRITICAL,
            acknowledged=True,
            acknowledged_by=ack_by,
            acknowledged_at=ack_at,
        )
        patient = make_patient(alerts=[existing_alert])
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)

        payload = self._valid_payload(medications=[], allergy_notes="", comorbidities=[])
        response = await client.post(f"/patients/{patient.id}/calculate-risk", json=payload)

        assert response.status_code == 200
        alerts = response.json()["alerts"]
        osa_alerts = [a for a in alerts if a["alert_type"] == "osa"]
        assert len(osa_alerts) == 1
        assert osa_alerts[0]["acknowledged"] is True
        assert osa_alerts[0]["acknowledged_by"]["full_name"] == "Nora Nurse"
        assert osa_alerts[0]["message"] != existing_alert.message

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        response = await client.post(
            "/patients/507f1f77bcf86cd799439011/calculate-risk", json=self._valid_payload()
        )

        assert response.status_code == 404


class TestAcknowledgeAlert:
    @pytest.mark.asyncio
    async def test_acknowledges_matching_alert(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 6",
            severity=AlertSeverity.CRITICAL,
        )
        patient = make_patient(alerts=[alert])
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.patch(
            f"/patients/{patient.id}/alerts/{alert.id}/acknowledge",
            json={"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
        )

        assert response.status_code == 200
        body = response.json()
        acked = next(a for a in body["alerts"] if a["id"] == alert.id)
        assert acked["acknowledged"] is True
        assert acked["acknowledged_by"]["full_name"] == "Nora Nurse"
        assert acked["acknowledged_at"] is not None

        audit_mock.assert_awaited_once()
        audit_kwargs = audit_mock.call_args.kwargs
        assert audit_kwargs["entity_type"] == "Patient"
        assert audit_kwargs["action"] == AuditAction.UPDATE
        assert audit_kwargs["actor"].full_name == "Nora Nurse"
        before = audit_kwargs["changes"]["before"]
        assert before["alert_id"] == alert.id
        assert before["alert_type"] == "osa"
        assert before["acknowledged"] is False
        assert before["acknowledged_by"] is None
        after = audit_kwargs["changes"]["after"]
        assert after["acknowledged"] is True
        assert after["acknowledged_by"]["full_name"] == "Nora Nurse"
        assert after["acknowledged_at"] is not None

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        response = await client.patch(
            "/patients/507f1f77bcf86cd799439011/alerts/abc123/acknowledge",
            json={"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_404_when_alert_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient(alerts=[])
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))

        response = await client.patch(
            f"/patients/{patient.id}/alerts/does-not-exist/acknowledge",
            json={"user_id": "u1", "full_name": "Nora Nurse", "role": "nurse"},
        )

        assert response.status_code == 404
        assert response.json() == {"error": "not_found", "message": "Alert not found"}


class TestUpdateNotes:
    @pytest.mark.asyncio
    async def test_updates_notes(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        _patch_writes_as_no_ops(monkeypatch)

        response = await client.patch(
            f"/patients/{patient.id}/notes",
            json={
                "notes": "Cleared for surgery pending EKG.",
                "actor": {"user_id": "u1", "full_name": "Sam Surgeon", "role": "surgeon"},
            },
        )

        assert response.status_code == 200
        assert response.json()["notes"] == "Cleared for surgery pending EKG."

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        response = await client.patch(
            "/patients/507f1f77bcf86cd799439011/notes",
            json={
                "notes": "Some note",
                "actor": {"user_id": "u1", "full_name": "Sam Surgeon", "role": "surgeon"},
            },
        )

        assert response.status_code == 404


def _sample_truform_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "patient_self_first_name": "John",
        "patient_self_last_name": "Doe",
        "patient_self_date_of_birth": "1968-03-15",
        "patient_self_sex_description": "Male",
        "health_history_medical_snoring": "yes",
        "health_history_medical_high_blood_pressure": "yes",
        "health_history_current_weight": "180",
        "health_history_current_height": "70",
        "health_history_medication_blood_thinners": "yes",
        "medication1_name": "Warfarin",
        "health_history_allergies_known_allergies": "Penicillin - causes rash",
        "insurance_provider_name": "Delta Dental",
    }
    payload.update(overrides)
    return payload


class TestCreatePatientFromTruform:
    @pytest.mark.asyncio
    async def test_creates_patient_from_manual_payload(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.post(
            "/patients/from-truform",
            json={
                "payload": _sample_truform_payload(),
                "surgery_date": "2026-09-01",
                "created_by": str(owner.id),
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert len(body["created"]) == 1
        assert body["skipped"] == []

        result = body["created"][0]
        assert result["patient"]["full_name"] == "John Doe"
        assert result["patient"]["intake_record"]["source"] == "truform"
        assert result["patient"]["intake_record"]["verification_status"] == "pending"
        for field in (
            "tired_during_day",
            "observed_apnea",
            "neck_circumference_cm",
            "mallampati_class",
        ):
            assert field in result["missing_for_scoring"]
        assert "insurance_provider_name" in result["unmapped_fields"]

        audit_mock.assert_awaited_once()
        audit_kwargs = audit_mock.call_args.kwargs
        assert audit_kwargs["entity_type"] == "Patient"
        assert audit_kwargs["action"] == AuditAction.CREATE
        assert audit_kwargs["actor"].user_id == str(owner.id)
        assert audit_kwargs["changes"]["after"] == {
            "full_name": "John Doe",
            "dob": "1968-03-15",
            "sex": "male",
            "surgery_date": "2026-09-01",
            "patient_identifier": result["patient"]["patient_identifier"],
            "source": "truform",
        }

    @pytest.mark.asyncio
    async def test_returns_404_when_created_by_user_missing(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(User, "get", AsyncMock(return_value=None))

        response = await client.post(
            "/patients/from-truform",
            json={
                "payload": _sample_truform_payload(),
                "surgery_date": "2026-09-01",
                "created_by": "507f1f77bcf86cd799439011",
            },
        )

        assert response.status_code == 404
        assert response.json() == {"error": "not_found", "message": "User not found"}

    @pytest.mark.asyncio
    async def test_maps_female_sex_description_to_female(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)

        response = await client.post(
            "/patients/from-truform",
            json={
                "payload": _sample_truform_payload(patient_self_sex_description="Female"),
                "surgery_date": "2026-09-01",
                "created_by": str(owner.id),
            },
        )

        assert response.status_code == 201
        assert response.json()["created"][0]["patient"]["sex"] == "female"

    @pytest.mark.asyncio
    async def test_maps_unspecified_sex_description_to_other(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)

        response = await client.post(
            "/patients/from-truform",
            json={
                "payload": _sample_truform_payload(patient_self_sex_description="Unspecified"),
                "surgery_date": "2026-09-01",
                "created_by": str(owner.id),
            },
        )

        assert response.status_code == 201
        assert response.json()["created"][0]["patient"]["sex"] == "other"

    @pytest.mark.asyncio
    async def test_skips_submission_missing_a_derivable_name(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)

        payload = _sample_truform_payload()
        del payload["patient_self_first_name"]
        del payload["patient_self_last_name"]

        response = await client.post(
            "/patients/from-truform",
            json={"payload": payload, "surgery_date": "2026-09-01", "created_by": str(owner.id)},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["created"] == []
        assert len(body["skipped"]) == 1
        assert "name" in body["skipped"][0]["reason"]

    @pytest.mark.asyncio
    async def test_skips_submission_missing_a_parseable_dob(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)

        payload = _sample_truform_payload(patient_self_date_of_birth="not-a-date")

        response = await client.post(
            "/patients/from-truform",
            json={"payload": payload, "surgery_date": "2026-09-01", "created_by": str(owner.id)},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["created"] == []
        assert len(body["skipped"]) == 1
        assert "date of birth" in body["skipped"][0]["reason"]

    @pytest.mark.asyncio
    async def test_returns_422_when_surgery_date_missing(self, client: AsyncClient) -> None:
        response = await client.post(
            "/patients/from-truform",
            json={"payload": _sample_truform_payload(), "created_by": "507f1f77bcf86cd799439011"},
        )

        assert response.status_code == 422


class TestPollTruform:
    @pytest.mark.asyncio
    async def test_returns_empty_created_list_since_fetch_is_stubbed(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))

        response = await client.post(
            "/patients/poll-truform",
            json={"surgery_date": "2026-09-01", "created_by": str(owner.id)},
        )

        assert response.status_code == 200
        assert response.json() == {"created": [], "skipped": []}

    @pytest.mark.asyncio
    async def test_returns_404_when_created_by_user_missing(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(User, "get", AsyncMock(return_value=None))

        response = await client.post(
            "/patients/poll-truform",
            json={"surgery_date": "2026-09-01", "created_by": "507f1f77bcf86cd799439011"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_creates_patient_when_a_submission_is_pending(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)
        audit_mock = _mock_record_audit_entry(monkeypatch)
        monkeypatch.setattr(
            patients_router,
            "fetch_pending_submissions",
            AsyncMock(return_value=[_sample_truform_payload()]),
        )

        response = await client.post(
            "/patients/poll-truform",
            json={"surgery_date": "2026-09-01", "created_by": str(owner.id)},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["created"]) == 1
        assert body["created"][0]["patient"]["full_name"] == "John Doe"
        assert body["skipped"] == []

        audit_mock.assert_awaited_once()
        audit_kwargs = audit_mock.call_args.kwargs
        assert audit_kwargs["action"] == AuditAction.CREATE
        assert audit_kwargs["entity_type"] == "Patient"
        assert audit_kwargs["changes"]["after"]["source"] == "truform"

    @pytest.mark.asyncio
    async def test_skips_pending_submission_missing_a_derivable_name(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=owner))
        _patch_writes_as_no_ops(monkeypatch)
        unnamed_submission = _sample_truform_payload()
        del unnamed_submission["patient_self_first_name"]
        del unnamed_submission["patient_self_last_name"]
        monkeypatch.setattr(
            patients_router,
            "fetch_pending_submissions",
            AsyncMock(return_value=[unnamed_submission]),
        )

        response = await client.post(
            "/patients/poll-truform",
            json={"surgery_date": "2026-09-01", "created_by": str(owner.id)},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["created"] == []
        assert len(body["skipped"]) == 1
        assert "name" in body["skipped"][0]["reason"]


class TestExportRiskReport:
    @pytest.mark.asyncio
    async def test_returns_pdf_with_correct_headers(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        monkeypatch.setattr(AuditLogEntry, "insert", AsyncMock(return_value=None))

        actor = make_user()
        _mock_current_user(monkeypatch, actor)

        response = await client.get(
            f"/patients/{patient.id}/export/risk-report", headers=_auth_headers_for(actor)
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="risk-report-{patient.patient_identifier}.pdf"'
        )
        assert response.content.startswith(b"%PDF")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", [Role.SURGEON, Role.NURSE, Role.OFFICE_STAFF])
    async def test_accessible_to_all_three_roles(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, role: Role
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        monkeypatch.setattr(AuditLogEntry, "insert", AsyncMock(return_value=None))

        actor = make_user(role=role)
        _mock_current_user(monkeypatch, actor)

        response = await client.get(
            f"/patients/{patient.id}/export/risk-report", headers=_auth_headers_for(actor)
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_401_without_token(self, client: AsyncClient) -> None:
        response = await client.get("/patients/507f1f77bcf86cd799439011/export/risk-report")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        actor = make_user()
        _mock_current_user(monkeypatch, actor)

        response = await client.get(
            "/patients/507f1f77bcf86cd799439011/export/risk-report",
            headers=_auth_headers_for(actor),
        )

        assert response.status_code == 404


class TestExportLabOrder:
    @pytest.mark.asyncio
    async def test_returns_pdf_with_correct_headers(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        monkeypatch.setattr(AuditLogEntry, "insert", AsyncMock(return_value=None))

        nurse = make_user(role=Role.NURSE)
        _mock_current_user(monkeypatch, nurse)

        response = await client.post(
            f"/patients/{patient.id}/export/lab-order", headers=_auth_headers_for(nurse)
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="lab-order-{patient.patient_identifier}.pdf"'
        )
        assert response.content.startswith(b"%PDF")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", [Role.SURGEON, Role.OFFICE_STAFF])
    async def test_rejects_non_nurse_role_with_403(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, role: Role
    ) -> None:
        patient = make_patient()
        non_nurse = make_user(role=role)
        _mock_current_user(monkeypatch, non_nurse)

        response = await client.post(
            f"/patients/{patient.id}/export/lab-order", headers=_auth_headers_for(non_nurse)
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_401_without_token(self, client: AsyncClient) -> None:
        response = await client.post("/patients/507f1f77bcf86cd799439011/export/lab-order")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        nurse = make_user(role=Role.NURSE)
        _mock_current_user(monkeypatch, nurse)

        response = await client.post(
            "/patients/507f1f77bcf86cd799439011/export/lab-order",
            headers=_auth_headers_for(nurse),
        )

        assert response.status_code == 404


class _FakeAuditFindQuery:
    def __init__(self, entries: list[AuditLogEntry]) -> None:
        self._entries = entries
        self.sort_args: tuple[Any, ...] | None = None

    def sort(self, *args: Any) -> "_FakeAuditFindQuery":
        self.sort_args = args
        return self

    async def to_list(self) -> list[AuditLogEntry]:
        return self._entries


class TestGetPatientAuditLog:
    @pytest.mark.asyncio
    async def test_returns_entries_newest_first(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))

        actor = make_actor_snapshot()
        older = AuditLogEntry(
            id=ObjectId(),
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.CREATE,
            actor=actor,
            changes={"before": None, "after": {"full_name": patient.full_name}},
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        )
        newer = AuditLogEntry(
            id=ObjectId(),
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.UPDATE,
            actor=actor,
            changes={"before": {"notes": None}, "after": {"notes": "hi"}},
            timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        )
        fake_query = _FakeAuditFindQuery([newer, older])
        monkeypatch.setattr(AuditLogEntry, "find", MagicMock(return_value=fake_query))

        nurse = make_user(role=Role.NURSE)
        _mock_current_user(monkeypatch, nurse)

        response = await client.get(
            f"/patients/{patient.id}/audit-log", headers=_auth_headers_for(nurse)
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert body[0]["action"] == "update"
        assert body[1]["action"] == "create"

        assert fake_query.sort_args == ("-timestamp",)

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_patient_with_no_history(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))
        monkeypatch.setattr(AuditLogEntry, "find", MagicMock(return_value=_FakeAuditFindQuery([])))

        surgeon = make_user(role=Role.SURGEON)
        _mock_current_user(monkeypatch, surgeon)

        response = await client.get(
            f"/patients/{patient.id}/audit-log", headers=_auth_headers_for(surgeon)
        )

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_rejects_office_staff_with_403(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patient = make_patient()
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=patient))

        office_staff = make_user(role=Role.OFFICE_STAFF)
        _mock_current_user(monkeypatch, office_staff)

        response = await client.get(
            f"/patients/{patient.id}/audit-log", headers=_auth_headers_for(office_staff)
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_404_when_patient_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Patient, "get", AsyncMock(return_value=None))

        nurse = make_user(role=Role.NURSE)
        _mock_current_user(monkeypatch, nurse)

        response = await client.get(
            "/patients/507f1f77bcf86cd799439011/audit-log", headers=_auth_headers_for(nurse)
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_401_without_token(self, client: AsyncClient) -> None:
        response = await client.get("/patients/507f1f77bcf86cd799439011/audit-log")

        assert response.status_code == 401
