import asyncio
import io
from datetime import UTC, date, datetime
from typing import Any

import pytest
from beanie import init_beanie
from pypdf import PdfReader

from app.models import Patient, User, document_models
from app.models.embedded import (
    ActorSnapshot,
    Alert,
    AlertSeverity,
    AlertType,
    MetsCapacity,
    RecommendationSet,
    RiskAssessment,
    RiskLevel,
)
from app.models.patient import Sex
from app.services.pdf.lab_order import generate_lab_order_pdf
from app.services.pdf.risk_report import generate_risk_report_pdf


class _FakeCollection:
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
            document_models=document_models,
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
        "full_name": "Nora Nurse",
        "role": "nurse",
    }
    defaults.update(overrides)
    return ActorSnapshot(**defaults)


def make_full_patient(**overrides: Any) -> Patient:
    ack_by = make_actor_snapshot()
    defaults: dict[str, Any] = {
        "full_name": "John O'Brien & Sons",
        "dob": date(1968, 3, 15),
        "sex": Sex.MALE,
        "surgery_date": date(2026, 9, 1),
        "created_by": make_user(),
        "notes": "Patient reports <5% chance of complication & needs f/u.",
        "risk_assessment": RiskAssessment(
            asa_class="III",
            asa_suggested=True,
            stop_bang_score=6,
            stop_bang_level=RiskLevel.HIGH,
            rcri_score=1,
            rcri_level=RiskLevel.MODERATE,
            mets_capacity=MetsCapacity.BELOW_4,
            overall_risk_category=RiskLevel.HIGH,
        ),
        "recommendation_set": RecommendationSet(recommended_tests=["EKG", "CBC", "INR"]),
        "alerts": [
            Alert(
                alert_type=AlertType.OSA,
                message="STOP-Bang score 6 - high risk of OSA",
                severity=AlertSeverity.CRITICAL,
                acknowledged=True,
                acknowledged_by=ack_by,
                acknowledged_at=datetime.now(UTC),
            ),
            Alert(
                alert_type=AlertType.ANTICOAGULANT,
                message="Patient is on Warfarin",
                severity=AlertSeverity.CRITICAL,
            ),
        ],
    }
    defaults.update(overrides)
    return Patient(**defaults)


def make_minimal_patient(**overrides: Any) -> Patient:
    defaults: dict[str, Any] = {
        "full_name": "Minimal Patient",
        "dob": date(1990, 1, 1),
        "sex": Sex.FEMALE,
        "surgery_date": date(2026, 10, 1),
        "created_by": make_user(),
    }
    defaults.update(overrides)
    return Patient(**defaults)


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


class TestGenerateRiskReportPdf:
    def test_produces_valid_pdf_bytes(self) -> None:
        pdf_bytes = generate_risk_report_pdf(make_full_patient())

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        assert pdf_bytes.startswith(b"%PDF")
        assert pdf_bytes.rstrip().endswith(b"%%EOF")

    def test_contains_expected_content_for_full_patient(self) -> None:
        patient = make_full_patient()
        text = _extract_text(generate_risk_report_pdf(patient))

        assert "Anesthesia Risk Assessment Report" in text
        assert "John O'Brien & Sons" in text
        assert "1968-03-15" in text
        assert patient.patient_identifier in text
        assert "III" in text
        assert "clinician-suggested" in text
        assert "High" in text  # STOP-Bang / RCRI levels
        assert "Overall Risk Category: HIGH" in text
        assert "Anticoagulant" in text
        assert "Yes - Nora Nurse" in text
        assert "EKG, CBC, INR" in text
        assert "Patient reports <5% chance of complication & needs f/u." in text

    def test_does_not_double_escape_special_characters(self) -> None:
        text = _extract_text(generate_risk_report_pdf(make_full_patient()))

        assert "&amp;" not in text
        assert "&#x27;" not in text
        assert "&lt;" not in text

    def test_handles_patient_with_no_risk_assessment(self) -> None:
        patient = make_minimal_patient()
        assert patient.risk_assessment is None

        pdf_bytes = generate_risk_report_pdf(patient)

        assert pdf_bytes.startswith(b"%PDF")
        text = _extract_text(pdf_bytes)
        assert "Risk assessment has not yet been calculated" in text

    def test_handles_patient_with_no_alerts_no_recommendations_no_notes(self) -> None:
        patient = make_minimal_patient()

        pdf_bytes = generate_risk_report_pdf(patient)

        assert pdf_bytes.startswith(b"%PDF")
        text = _extract_text(pdf_bytes)
        assert "No alerts on record." in text
        assert "No tests recommended." in text
        assert "No notes on file." in text

    def test_asa_confirmed_note_differs_from_suggested(self) -> None:
        patient = make_full_patient(
            risk_assessment=RiskAssessment(
                asa_class="II",
                asa_suggested=False,
                overall_risk_category=RiskLevel.LOW,
            )
        )
        text = _extract_text(generate_risk_report_pdf(patient))

        assert "clinician-confirmed" in text
        assert "clinician-suggested" not in text

    def test_acknowledged_alert_without_acknowledged_by_still_shows_yes(self) -> None:
        patient = make_full_patient(
            alerts=[
                Alert(
                    alert_type=AlertType.OSA,
                    message="STOP-Bang score 6",
                    severity=AlertSeverity.CRITICAL,
                    acknowledged=True,
                    acknowledged_by=None,
                )
            ]
        )
        text = _extract_text(generate_risk_report_pdf(patient))

        assert "Yes" in text


class TestGenerateLabOrderPdf:
    def test_produces_valid_pdf_bytes(self) -> None:
        pdf_bytes = generate_lab_order_pdf(make_full_patient(), make_actor_snapshot())

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        assert pdf_bytes.startswith(b"%PDF")
        assert pdf_bytes.rstrip().endswith(b"%%EOF")

    def test_contains_expected_content(self) -> None:
        patient = make_full_patient()
        provider = make_actor_snapshot(full_name="Sam Surgeon", role="surgeon")
        text = _extract_text(generate_lab_order_pdf(patient, provider))

        assert "Laboratory Order" in text
        assert "John O'Brien & Sons" in text
        assert "1968-03-15" in text
        assert "Sam Surgeon (Surgeon)" in text
        assert "Pre-operative clearance - anesthesia risk assessment" in text
        assert "EKG" in text
        assert "CBC" in text
        assert "INR" in text
        assert "Ordering Provider Signature" in text
        assert "Generated" in text

    def test_handles_patient_with_no_recommended_tests(self) -> None:
        patient = make_minimal_patient()
        assert patient.recommendation_set is None

        pdf_bytes = generate_lab_order_pdf(patient, make_actor_snapshot())

        assert pdf_bytes.startswith(b"%PDF")
        text = _extract_text(pdf_bytes)
        assert "No tests currently recommended." in text

    def test_does_not_double_escape_special_characters(self) -> None:
        text = _extract_text(generate_lab_order_pdf(make_full_patient(), make_actor_snapshot()))

        assert "&amp;" not in text
        assert "&#x27;" not in text
