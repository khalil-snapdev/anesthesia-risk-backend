"""Mock Truform (PBHS) API — simulates the external intake-forms system.

Real Truform API credentials aren't available for this practice project,
so this module stands in for Truform's actual servers during local
development and testing. app/services/truform_client.py calls this the
same way it would call the real Truform polling API — the payload shapes
below use real, researched Truform field names (see this backend's
CLAUDE.md) so that swapping to the real API later requires changing only
truform_client.py's target URL, never the parsing/normalization logic in
truform_parser.py.

SECURITY: this simulates a system EXTERNAL to us — it must never be
confused with, or reachable the same way as, our own API surface:
- The frontend never calls these routes directly and doesn't know they
  exist; only truform_client.py's internal server-to-server call does.
- None of our own auth (get_current_user / require_role) applies here —
  a real Truform API wouldn't recognize our session cookies anyway.
- Mounted only when ENVIRONMENT != "production" (see app/main.py) — a
  real deployment must never ship these fake endpoints live. When real
  Truform credentials exist, this entire module gets deleted.
- Additionally gated to loopback callers only, as defense in depth on
  top of the production exclusion above (see _require_internal_caller).
"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.exceptions import AppException

router = APIRouter(prefix="/mock/truform", tags=["mock-truform (dev only)"])

_INTERNAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


async def _require_internal_caller(request: Request) -> None:
    """Reject any caller that isn't the loopback interface (or an
    in-process test harness, where request.client may be unset/absent).

    This is defense in depth, not the primary safeguard — the primary
    safeguard is that this router is never mounted at all in production
    (see app/main.py). This just means a misconfigured non-production
    environment (e.g. a shared staging box reachable by others) doesn't
    also expose these endpoints over the network.
    """
    client = request.client
    if client is not None and client.host not in _INTERNAL_HOSTS:
        raise AppException("Mock Truform API is internal-only", status_code=403)


# Real, researched Truform field names (see CLAUDE.md) — deliberately NOT
# firstName/lastName-style oversimplifications. Kept as pending forever
# (never marked "consumed" here) since idempotency is enforced on our
# side, by checking for an existing patient per submission_id — this
# lets polling be tested repeatedly without the mock needing its own
# consumed-state tracking.
_MOCK_SUBMISSIONS: list[dict[str, Any]] = [
    {
        "submission_id": "truform-sub-1001",
        "payload": {
            "patient_self_first_name": "Alice",
            "patient_self_last_name": "Nakamura",
            "patient_self_age": "62",
            "patient_self_date_of_birth": "1964-02-11",
            "patient_self_sex_description": "Female",
            "health_history_medical_snoring": "yes",
            "health_history_medical_high_blood_pressure": "yes",
            "health_history_current_weight": "165",
            "health_history_current_height": "64",
            "health_history_medication_blood_thinners": "no",
            "health_history_medical_diabetes": "yes",
            "health_history_medical_heart_attack": "no",
            "health_history_medical_angina": "no",
            "health_history_medical_stroke": "no",
            "health_history_medical_kidney_trouble": "no",
            "health_history_pregnancy": "no",
            "health_history_allergies_penicillin": "no",
            "health_history_allergies_sulfa_drugs": "yes",
            "health_history_allergies_latex": "no",
            "health_history_allergies_known_allergies": "Sulfa drugs - hives",
            "health_history_allergies1_name": "Sulfa",
            "insurance_provider_name": "Cigna",
        },
    },
    {
        "submission_id": "truform-sub-1002",
        "payload": {
            "patient_self_first_name": "Marcus",
            "patient_self_last_name": "Webb",
            "patient_self_age": "45",
            "patient_self_date_of_birth": "1980-11-30",
            "patient_self_sex_description": "Male",
            "health_history_medical_snoring": "no",
            "health_history_medical_high_blood_pressure": "no",
            "health_history_current_weight": "190",
            "health_history_current_height": "71",
            "health_history_medication_blood_thinners": "yes",
            "medication1_name": "Apixaban",
            "health_history_medical_diabetes": "no",
            "health_history_medical_heart_attack": "yes",
            "health_history_medical_angina": "no",
            "health_history_medical_stroke": "no",
            "health_history_medical_kidney_trouble": "no",
            "health_history_pregnancy": "no",
            "health_history_allergies_penicillin": "no",
            "health_history_allergies_sulfa_drugs": "no",
            "health_history_allergies_latex": "no",
        },
    },
    {
        "submission_id": "truform-sub-1003",
        "payload": {
            "patient_self_first_name": "Priya",
            "patient_self_last_name": "Desai",
            "patient_self_age": "34",
            "patient_self_date_of_birth": "1991-07-19",
            "patient_self_sex_description": "Female",
            "health_history_medical_snoring": "no",
            "health_history_medical_high_blood_pressure": "no",
            "health_history_current_weight": "140",
            "health_history_current_height": "66",
            "health_history_medication_blood_thinners": "no",
            "health_history_medical_diabetes": "no",
            "health_history_medical_heart_attack": "no",
            "health_history_medical_angina": "no",
            "health_history_medical_stroke": "no",
            "health_history_medical_kidney_trouble": "no",
            "health_history_pregnancy": "yes",
            "health_history_allergies_penicillin": "no",
            "health_history_allergies_sulfa_drugs": "no",
            "health_history_allergies_latex": "no",
        },
    },
]


@router.get("/submissions", dependencies=[Depends(_require_internal_caller)])
async def list_mock_submissions() -> list[dict[str, Any]]:
    return _MOCK_SUBMISSIONS


@router.get("/submissions/{submission_id}", dependencies=[Depends(_require_internal_caller)])
async def get_mock_submission(submission_id: str) -> dict[str, Any]:
    for submission in _MOCK_SUBMISSIONS:
        if submission["submission_id"] == submission_id:
            return submission
    raise AppException("Submission not found", status_code=404)
