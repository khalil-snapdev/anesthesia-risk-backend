from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.patient import PatientRead


class TruformPayload(BaseModel):
    """Permissive representation of one Truform submission.

    Truform's API defaults to JSON — a submission is a list of key/value
    pairs, so this validates a plain JSON dict directly. Forms are
    dynamic (a field left blank is omitted, not sent as null), and PBHS's
    full schema isn't documented, so `extra="allow"` lets unrecognized
    fields pass through rather than be rejected — parse_truform_payload()
    decides what to do with them.
    """

    model_config = ConfigDict(extra="allow")


class TruformManualIngestRequest(BaseModel):
    """Body for POST /patients/from-truform — a single test/manual payload.

    surgery_date and created_by are required inputs (not derivable from
    Truform data) per the office-staff-initiated workflow: staff import
    one specific patient's Truform submission for a surgery they've
    already scheduled — this isn't an unattended background job.
    """

    payload: TruformPayload
    surgery_date: date
    # Plain user_id stand-in until Phase 6 auth exists.
    created_by: str


class TruformPollRequest(BaseModel):
    """Body for POST /patients/poll-truform.

    fetch_pending_submissions() returns a list, but surgery_date/created_by
    here apply to a single patient — so this endpoint currently processes
    at most the first pending submission per call. Revisit once real
    Truform polling is confirmed to return multiple submissions that need
    independent surgery_date/created_by assignment.
    """

    surgery_date: date
    created_by: str


class TruformIngestResult(BaseModel):
    patient: PatientRead
    missing_for_scoring: list[str]
    unmapped_fields: list[str]


class TruformIngestSkipped(BaseModel):
    raw_payload: dict[str, Any]
    reason: str


class TruformIngestResponse(BaseModel):
    created: list[TruformIngestResult]
    skipped: list[TruformIngestSkipped]


class TruformAlreadyImported(BaseModel):
    """One pending submission that was already imported on a prior poll.

    Reported instead of silently skipping it or creating a duplicate —
    this is what makes repeated/retried polling safe (idempotent).
    """

    submission_id: str
    patient_id: str
    patient_name: str


class TruformPollResponse(BaseModel):
    created: list[TruformIngestResult]
    skipped: list[TruformIngestSkipped]
    already_imported: list[TruformAlreadyImported]
