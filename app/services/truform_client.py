"""Truform (PBHS) polling client.

Integration is poll-based — see CLAUDE.md's External Systems section:
our backend periodically asks Truform "any new submissions?" rather than
Truform pushing to us. Truform's API defaults to JSON — each pending
submission is a dict of key/value pairs, matching TruformPayload's shape.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TruformSubmission:
    submission_id: str
    payload: dict[str, Any]


async def fetch_pending_submissions() -> list[TruformSubmission]:
    """Fetch pending Truform submissions (JSON) not yet ingested.

    Today this calls our own mock endpoint (app/routers/mock_truform.py),
    since real Truform API credentials aren't available for this practice
    project. settings.MOCK_TRUFORM_BASE_URL is the ONLY thing that changes
    once real credentials exist — swap it for Truform's real polling
    endpoint (and add real auth headers below). Everything downstream —
    parse_truform_payload(), patient creation, idempotency-by-submission-id
    — stays identical, since none of it cares where the payload came from.

    A Truform (or, today, mock-endpoint) outage shouldn't break the whole
    poll flow: network errors, non-2xx responses, and unexpectedly-shaped
    responses are all logged and treated as "no submissions right now"
    rather than raised — POST /patients/poll-truform just reports zero
    created/skipped/already_imported for this call, and office staff can
    try again later.
    """
    url = f"{settings.MOCK_TRUFORM_BASE_URL}/mock/truform/submissions"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            raw_submissions = response.json()

        return [
            TruformSubmission(submission_id=item["submission_id"], payload=item["payload"])
            for item in raw_submissions
        ]
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        logger.exception("Failed to fetch pending Truform submissions from %s", url)
        return []
