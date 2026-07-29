"""Truform (PBHS) polling client.

Integration is poll-based — see CLAUDE.md's External Systems section:
our backend periodically asks Truform "any new submissions?" rather than
Truform pushing to us. Truform's API defaults to JSON — each pending
submission is a dict of key/value pairs, matching TruformPayload's shape.
"""

from typing import Any


async def fetch_pending_submissions() -> list[dict[str, Any]]:
    """Fetch pending Truform submissions (JSON) not yet ingested.

    Stub: pending real Truform API credentials — this will call Truform's
    actual polling API once available. Returns an empty list for now, so
    POST /patients/poll-truform is expected to create zero patients until
    real credentials exist.
    """
    return []
