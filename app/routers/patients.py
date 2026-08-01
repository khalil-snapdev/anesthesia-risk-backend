from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from pydantic import ValidationError
from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db_client
from app.exceptions import AppException
from app.models.audit_log import AuditAction, AuditLogEntry
from app.models.embedded import (
    ActorSnapshot,
    AlertSeverity,
    AlertType,
    ExamFinding,
    IntakeRecord,
    IntakeSource,
    RecommendationSet,
    RiskAssessment,
    VerificationStatus,
)
from app.models.patient import Patient, Sex
from app.models.user import User
from app.schemas.audit import AuditLogEntryRead
from app.schemas.patient import (
    CalculateRiskRequest,
    ExamFindingUpdate,
    IntakeRecordUpdate,
    NotesUpdate,
    PatientCreate,
    PatientListItem,
    PatientRead,
)
from app.schemas.truform import (
    TruformAlreadyImported,
    TruformIngestResponse,
    TruformIngestResult,
    TruformIngestSkipped,
    TruformManualIngestRequest,
    TruformPollRequest,
    TruformPollResponse,
)
from app.services.alerts import generate_alerts, merge_alerts
from app.services.audit import record_audit_entry, run_in_transaction
from app.services.pdf.lab_order import generate_lab_order_pdf
from app.services.pdf.risk_report import generate_risk_report_pdf
from app.services.recommendations import generate_recommended_tests
from app.services.scoring.asa import asa_class_to_level, suggest_asa_class
from app.services.scoring.mets import classify_mets
from app.services.scoring.overall_risk import calculate_overall_risk
from app.services.scoring.rcri import calculate_rcri
from app.services.scoring.stop_bang import calculate_stop_bang
from app.services.truform_client import fetch_pending_submissions
from app.services.truform_parser import ParsedIntakeData, parse_date_string, parse_truform_payload

router = APIRouter(prefix="/patients", tags=["patients"])


async def _get_patient_or_404(patient_id: str) -> Patient:
    try:
        patient = await Patient.get(patient_id)
    except ValidationError:
        patient = None
    if patient is None or patient.is_deleted:
        raise AppException("Patient not found", status_code=404)
    return patient


async def _get_user_or_404(user_id: str) -> User:
    try:
        user = await User.get(user_id)
    except ValidationError:
        user = None
    if user is None:
        raise AppException("User not found", status_code=404)
    return user


def _actor_snapshot_for_user(user: User) -> ActorSnapshot:
    return ActorSnapshot(
        user_id=str(user.id),
        full_name=user.full_name,
        role=user.role.value if user.role else "unknown",
    )


def _sex_from_is_male(is_male: bool | None) -> Sex:
    if is_male is True:
        return Sex.MALE
    if is_male is False:
        return Sex.FEMALE
    return Sex.OTHER


def _build_patient_from_parsed_intake(
    parsed: ParsedIntakeData,
    surgery_date: date,
    owner: User,
    submission_id: str | None = None,
) -> Patient:
    """Build an unsaved Patient from a parsed Truform submission.

    Raises ValueError (caught by callers and reported as a skipped
    submission) if the data can't satisfy Patient's required fields —
    Truform's researched fields don't guarantee a parseable name or dob.

    submission_id is None for the manual single-payload upload path
    (POST /patients/from-truform has no submission id to track) and set
    for the poll-based auto-import path, where it's what makes re-polling
    idempotent — see IntakeRecord.submission_id's docstring.
    """
    if not parsed.full_name:
        raise ValueError("Truform submission is missing a patient name")

    dob = parse_date_string(parsed.dob) if parsed.dob else None
    if dob is None:
        raise ValueError("Truform submission is missing a parseable date of birth")

    intake_record = IntakeRecord(
        raw_truform_payload=parsed.raw_truform_payload,
        medical_history=parsed.medical_history,
        medications=parsed.medications,
        allergies=parsed.allergies,
        surgical_history=parsed.surgical_history,
        is_pregnant=parsed.is_pregnant,
        verification_status=VerificationStatus.PENDING,
        submitted_at=datetime.now(UTC),
        source=IntakeSource.TRUFORM,
        submission_id=submission_id,
    )

    return Patient(
        full_name=parsed.full_name,
        dob=dob,
        sex=_sex_from_is_male(parsed.is_male),
        surgery_date=surgery_date,
        created_by=owner,
        intake_record=intake_record,
    )


async def _create_patient_from_truform(
    client: AsyncMongoClient[Any],
    parsed: ParsedIntakeData,
    surgery_date: date,
    owner: User,
    actor: ActorSnapshot,
    submission_id: str | None = None,
) -> TruformIngestResult:
    patient = _build_patient_from_parsed_intake(parsed, surgery_date, owner, submission_id)

    async def _txn(session: AsyncClientSession) -> Patient:
        await patient.insert(session=session)
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.CREATE,
            actor=actor,
            changes={
                "before": None,
                "after": {
                    "full_name": patient.full_name,
                    "dob": patient.dob.isoformat(),
                    "sex": patient.sex.value,
                    "surgery_date": patient.surgery_date.isoformat(),
                    "patient_identifier": patient.patient_identifier,
                    "source": "truform",
                    "submission_id": submission_id,
                },
            },
        )
        return patient

    created = await run_in_transaction(client, _txn)
    return TruformIngestResult(
        patient=PatientRead.from_patient(created),
        missing_for_scoring=parsed.missing_for_scoring,
        unmapped_fields=parsed.unmapped_fields,
    )


@router.post("", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
async def create_patient(
    payload: PatientCreate,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> PatientRead:
    owner = await _get_user_or_404(payload.created_by)
    actor = _actor_snapshot_for_user(owner)

    patient = Patient(
        full_name=payload.full_name,
        dob=payload.dob,
        sex=payload.sex,
        surgery_date=payload.surgery_date,
        created_by=owner,
    )

    async def _txn(session: AsyncClientSession) -> Patient:
        await patient.insert(session=session)
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.CREATE,
            actor=actor,
            changes={
                "before": None,
                "after": {
                    "full_name": patient.full_name,
                    "dob": patient.dob.isoformat(),
                    "sex": patient.sex.value,
                    "surgery_date": patient.surgery_date.isoformat(),
                    "patient_identifier": patient.patient_identifier,
                },
            },
        )
        return patient

    created = await run_in_transaction(client, _txn)
    return PatientRead.from_patient(created)


@router.get("", response_model=list[PatientListItem])
async def list_patients(
    current_user: User = Depends(get_current_user),
) -> list[PatientListItem]:
    # Accessible to all 3 roles — office staff seeing fewer fields than
    # surgeon/nurse is a response-shape concern PatientListItem already
    # handles (Phase 3), not something this auth dependency needs to gate.
    patients = await Patient.find(Patient.is_deleted == False).to_list()
    return [PatientListItem.from_patient(patient) for patient in patients]


@router.get("/{patient_id}", response_model=PatientRead)
async def get_patient(patient_id: str) -> PatientRead:
    patient = await _get_patient_or_404(patient_id)
    return PatientRead.from_patient(patient)


@router.get("/{patient_id}/audit-log", response_model=list[AuditLogEntryRead])
async def get_patient_audit_log(
    patient_id: str,
    current_user: User = Depends(require_role("surgeon", "nurse")),
) -> list[AuditLogEntryRead]:
    # Surgeon/nurse only per CLAUDE.md's Roles section — office staff get
    # no clinical detail or alert visibility, and audit history is the
    # same tier of detail.
    patient = await _get_patient_or_404(patient_id)
    entries = (
        await AuditLogEntry.find(AuditLogEntry.entity_id == str(patient.id))
        .sort("-timestamp")
        .to_list()
    )
    return [AuditLogEntryRead.from_entry(entry) for entry in entries]


@router.patch("/{patient_id}/intake", response_model=PatientRead)
async def update_intake(
    patient_id: str,
    payload: IntakeRecordUpdate,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> PatientRead:
    patient = await _get_patient_or_404(patient_id)
    before = patient.intake_record.model_dump(mode="json") if patient.intake_record else None

    new_record = IntakeRecord(
        raw_truform_payload=payload.raw_truform_payload,
        medical_history=payload.medical_history,
        medications=payload.medications,
        allergies=payload.allergies,
        surgical_history=payload.surgical_history,
        is_pregnant=payload.is_pregnant,
        verification_status=payload.verification_status,
        submitted_at=payload.submitted_at,
        source=payload.source,
    )

    async def _txn(session: AsyncClientSession) -> Patient:
        patient.intake_record = new_record
        await patient.save(session=session)
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.UPDATE,
            actor=payload.actor,
            changes={
                "before": {"intake_record": before},
                "after": {"intake_record": new_record.model_dump(mode="json")},
            },
        )
        return patient

    updated = await run_in_transaction(client, _txn)
    return PatientRead.from_patient(updated)


@router.patch("/{patient_id}/exam-finding", response_model=PatientRead)
async def update_exam_finding(
    patient_id: str,
    payload: ExamFindingUpdate,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
    current_user: User = Depends(require_role("nurse")),
) -> PatientRead:
    # Nurse-only per CLAUDE.md's Roles section — surgeon is view-only on
    # exam findings.
    patient = await _get_patient_or_404(patient_id)
    before = patient.exam_finding.model_dump(mode="json") if patient.exam_finding else None

    new_finding = ExamFinding(
        mallampati_class=payload.mallampati_class,
        airway_notes=payload.airway_notes,
        entered_by=payload.entered_by,
        created_at=datetime.now(UTC),
    )

    async def _txn(session: AsyncClientSession) -> Patient:
        patient.exam_finding = new_finding
        await patient.save(session=session)
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.UPDATE,
            actor=payload.entered_by,
            changes={
                "before": {"exam_finding": before},
                "after": {"exam_finding": new_finding.model_dump(mode="json")},
            },
        )
        return patient

    updated = await run_in_transaction(client, _txn)
    return PatientRead.from_patient(updated)


@router.post("/{patient_id}/calculate-risk", response_model=PatientRead)
async def calculate_risk(
    patient_id: str,
    payload: CalculateRiskRequest,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> PatientRead:
    patient = await _get_patient_or_404(patient_id)

    before_risk_assessment = (
        patient.risk_assessment.model_dump(mode="json") if patient.risk_assessment else None
    )
    before_recommendation_set = (
        patient.recommendation_set.model_dump(mode="json") if patient.recommendation_set else None
    )
    before_alerts = [alert.model_dump(mode="json") for alert in patient.alerts]

    stop_bang_score, stop_bang_level = calculate_stop_bang(
        snoring=payload.snoring,
        tired=payload.tired,
        observed_apnea=payload.observed_apnea,
        hypertension=payload.hypertension,
        bmi=payload.bmi,
        age=payload.age,
        neck_circumference_cm=payload.neck_circumference_cm,
        is_male=payload.is_male,
    )
    rcri_score, rcri_level = calculate_rcri(
        high_risk_surgery=payload.high_risk_surgery,
        ischemic_heart_disease=payload.ischemic_heart_disease,
        chf=payload.chf,
        cerebrovascular_disease=payload.cerebrovascular_disease,
        insulin_dependent_diabetes=payload.insulin_dependent_diabetes,
        creatinine_above_2=payload.creatinine_above_2,
    )
    asa_class, asa_suggested = suggest_asa_class(payload.comorbidities)
    asa_level = asa_class_to_level(asa_class)
    mets_capacity = classify_mets(payload.can_climb_two_flights)

    mallampati_class = patient.exam_finding.mallampati_class if patient.exam_finding else None

    newly_generated_alerts = generate_alerts(
        medications=payload.medications,
        allergy_notes=payload.allergy_notes,
        stop_bang_score=stop_bang_score,
        mallampati_class=mallampati_class,
        airway_history_notes=payload.airway_history_notes,
    )
    merged_alerts = merge_alerts(patient.alerts, newly_generated_alerts)
    has_critical_alert = any(alert.severity == AlertSeverity.CRITICAL for alert in merged_alerts)

    overall_risk = calculate_overall_risk(
        asa_level, stop_bang_level, rcri_level, has_critical_alert
    )

    on_anticoagulant = any(
        alert.alert_type == AlertType.ANTICOAGULANT for alert in newly_generated_alerts
    )
    recommended_tests = generate_recommended_tests(
        on_anticoagulant=on_anticoagulant,
        is_diabetic=payload.is_diabetic,
        stop_bang_level=stop_bang_level,
        has_osa_diagnosis=payload.has_osa_diagnosis,
        asa_level=asa_level,
        rcri_level=rcri_level,
        rcri_score=rcri_score,
        is_pregnant=payload.is_pregnant,
    )

    now = datetime.now(UTC)
    risk_assessment = RiskAssessment(
        asa_class=asa_class,
        asa_suggested=asa_suggested,
        stop_bang_score=stop_bang_score,
        stop_bang_level=stop_bang_level,
        rcri_score=rcri_score,
        rcri_level=rcri_level,
        mets_capacity=mets_capacity,
        overall_risk_category=overall_risk,
        calculated_at=now,
        calculated_by=payload.calculated_by,
    )
    recommendation_set = RecommendationSet(recommended_tests=recommended_tests, generated_at=now)

    async def _txn(session: AsyncClientSession) -> Patient:
        patient.risk_assessment = risk_assessment
        patient.recommendation_set = recommendation_set
        patient.alerts = merged_alerts
        await patient.save(session=session)
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.UPDATE,
            actor=payload.calculated_by,
            changes={
                "before": {
                    "risk_assessment": before_risk_assessment,
                    "recommendation_set": before_recommendation_set,
                    "alerts": before_alerts,
                },
                "after": {
                    "risk_assessment": risk_assessment.model_dump(mode="json"),
                    "recommendation_set": recommendation_set.model_dump(mode="json"),
                    "alerts": [alert.model_dump(mode="json") for alert in merged_alerts],
                },
            },
        )
        return patient

    updated = await run_in_transaction(client, _txn)
    return PatientRead.from_patient(updated)


@router.patch("/{patient_id}/alerts/{alert_id}/acknowledge", response_model=PatientRead)
async def acknowledge_alert(
    patient_id: str,
    alert_id: str,
    payload: ActorSnapshot,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> PatientRead:
    patient = await _get_patient_or_404(patient_id)

    target_alert = next((alert for alert in patient.alerts if alert.id == alert_id), None)
    if target_alert is None:
        raise AppException("Alert not found", status_code=404)

    before_snapshot = {
        "alert_id": alert_id,
        "alert_type": target_alert.alert_type.value,
        "message": target_alert.message,
        "acknowledged": target_alert.acknowledged,
        "acknowledged_by": (
            target_alert.acknowledged_by.model_dump(mode="json")
            if target_alert.acknowledged_by
            else None
        ),
        "acknowledged_at": (
            target_alert.acknowledged_at.isoformat() if target_alert.acknowledged_at else None
        ),
    }

    ack_time = datetime.now(UTC)

    async def _txn(session: AsyncClientSession) -> Patient:
        target_alert.acknowledged = True
        target_alert.acknowledged_by = payload
        target_alert.acknowledged_at = ack_time
        await patient.save(session=session)
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.UPDATE,
            actor=payload,
            changes={
                "before": before_snapshot,
                "after": {
                    "alert_id": alert_id,
                    "alert_type": target_alert.alert_type.value,
                    "message": target_alert.message,
                    "acknowledged": True,
                    "acknowledged_by": payload.model_dump(mode="json"),
                    "acknowledged_at": ack_time.isoformat(),
                },
            },
        )
        return patient

    updated = await run_in_transaction(client, _txn)
    return PatientRead.from_patient(updated)


@router.post(
    "/from-truform", response_model=TruformIngestResponse, status_code=status.HTTP_201_CREATED
)
async def create_patient_from_truform(
    payload: TruformManualIngestRequest,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> TruformIngestResponse:
    """Manual/test Truform payload submission — not the poll-based path.

    Useful for testing the parser against a hand-supplied payload, or for
    staff who already have a Truform submission in hand. Doesn't conflict
    with POST /patients/poll-truform, which fetches submissions itself.
    """
    owner = await _get_user_or_404(payload.created_by)
    actor = _actor_snapshot_for_user(owner)

    parsed = parse_truform_payload(payload.payload.model_dump())

    try:
        result = await _create_patient_from_truform(
            client, parsed, payload.surgery_date, owner, actor
        )
    except ValueError as exc:
        return TruformIngestResponse(
            created=[],
            skipped=[TruformIngestSkipped(raw_payload=parsed.raw_truform_payload, reason=str(exc))],
        )

    return TruformIngestResponse(created=[result], skipped=[])


@router.post("/poll-truform", response_model=TruformPollResponse)
async def poll_truform(
    payload: TruformPollRequest,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> TruformPollResponse:
    """Poll Truform for pending submissions and create a Patient per new one.

    Idempotent per submission_id: every pending submission is checked
    against existing patients' intake_record.submission_id BEFORE
    attempting to create one. Already-imported submissions are reported
    under `already_imported`, never re-created — safe to click "poll"
    repeatedly (e.g. a double-click, or retrying after a partial failure)
    without ever producing duplicate patients. The mock Truform endpoint
    deliberately never marks its submissions "consumed" on its own side
    (see mock_truform.py) — this idempotency check is what makes repeated
    polling safe, mirroring how a real integration would need to behave
    too (Truform has no concept of "this office already imported this").

    surgery_date/created_by are shared across every submission processed
    in one call — per TruformPollRequest's docstring, this is a
    simplification (one "batch auto-import" action, not per-submission
    scheduling); revisit if per-submission surgery dates are ever needed.
    """
    owner = await _get_user_or_404(payload.created_by)
    actor = _actor_snapshot_for_user(owner)

    pending_submissions = await fetch_pending_submissions()

    created: list[TruformIngestResult] = []
    skipped: list[TruformIngestSkipped] = []
    already_imported: list[TruformAlreadyImported] = []

    for submission in pending_submissions:
        # Raw dict query (not Patient.intake_record.submission_id == ...)
        # since intake_record is an embedded (not linked) document — this
        # is plain Mongo dot-notation, guaranteed to work regardless of
        # Beanie's embedded-field query-expression support.
        existing = await Patient.find_one({"intake_record.submission_id": submission.submission_id})
        if existing is not None:
            already_imported.append(
                TruformAlreadyImported(
                    submission_id=submission.submission_id,
                    patient_id=str(existing.id),
                    patient_name=existing.full_name,
                )
            )
            continue

        parsed = parse_truform_payload(submission.payload)
        try:
            result = await _create_patient_from_truform(
                client, parsed, payload.surgery_date, owner, actor, submission.submission_id
            )
        except ValueError as exc:
            skipped.append(
                TruformIngestSkipped(raw_payload=parsed.raw_truform_payload, reason=str(exc))
            )
            continue
        created.append(result)

    return TruformPollResponse(created=created, skipped=skipped, already_imported=already_imported)


@router.patch("/{patient_id}/notes", response_model=PatientRead)
async def update_notes(
    patient_id: str,
    payload: NotesUpdate,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> PatientRead:
    patient = await _get_patient_or_404(patient_id)
    before_notes = patient.notes

    async def _txn(session: AsyncClientSession) -> Patient:
        patient.notes = payload.notes
        await patient.save(session=session)
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.UPDATE,
            actor=payload.actor,
            changes={"before": {"notes": before_notes}, "after": {"notes": payload.notes}},
        )
        return patient

    updated = await run_in_transaction(client, _txn)
    return PatientRead.from_patient(updated)


def _pdf_response(pdf_bytes: bytes, filename: str) -> Response:
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{patient_id}/export/risk-report")
async def export_risk_report(
    patient_id: str,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
    current_user: User = Depends(get_current_user),
) -> Response:
    # Accessible to all 3 roles — per CLAUDE.md's Roles section, exporting
    # PDFs is explicitly one of office staff's allowed actions, alongside
    # surgeon/nurse.
    patient = await _get_patient_or_404(patient_id)
    pdf_bytes = generate_risk_report_pdf(patient)
    actor = _actor_snapshot_for_user(current_user)

    async def _txn(session: AsyncClientSession) -> None:
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.PDF_GENERATED,
            actor=actor,
            changes={"before": None, "after": {"document": "risk_report"}},
        )

    await run_in_transaction(client, _txn)
    return _pdf_response(pdf_bytes, f"risk-report-{patient.patient_identifier}.pdf")


@router.post("/{patient_id}/export/lab-order")
async def export_lab_order(
    patient_id: str,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
    current_user: User = Depends(require_role("nurse")),
) -> Response:
    # Nurse-only per CLAUDE.md's Roles section — "Generate Lab Order" is a
    # nurse action.
    patient = await _get_patient_or_404(patient_id)
    ordering_provider = _actor_snapshot_for_user(current_user)
    pdf_bytes = generate_lab_order_pdf(patient, ordering_provider)

    async def _txn(session: AsyncClientSession) -> None:
        await record_audit_entry(
            session,
            entity_type="Patient",
            entity_id=str(patient.id),
            action=AuditAction.PDF_GENERATED,
            actor=ordering_provider,
            changes={"before": None, "after": {"document": "lab_order"}},
        )

    await run_in_transaction(client, _txn)
    return _pdf_response(pdf_bytes, f"lab-order-{patient.patient_identifier}.pdf")
