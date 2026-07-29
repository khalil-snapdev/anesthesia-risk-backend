"""Google Sign-In ID token verification.

The frontend obtains an ID token from Google Sign-In and sends it to us.
We verify it against Google's public keys (via the google-auth library),
rather than trusting the frontend's unverified claims about who the user
is — verify_google_token() is the only place a Google identity should be
trusted from.
"""

from dataclasses import dataclass

from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config import settings
from app.exceptions import AppException


@dataclass(frozen=True)
class GoogleUserInfo:
    google_sub_id: str
    email: str
    full_name: str


def verify_google_token(id_token: str) -> GoogleUserInfo:
    """Verify a Google Sign-In ID token and return the verified identity.

    Raises AppException(401) for any invalid, expired, or tampered token.
    """
    try:
        # google-auth ships py.typed but this function itself has no
        # parameter/return annotations upstream.
        claims = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            id_token, google_requests.Request(), audience=settings.GOOGLE_CLIENT_ID
        )
    except (ValueError, google_exceptions.GoogleAuthError) as exc:
        raise AppException("Invalid Google ID token", status_code=401) from exc

    google_sub_id = claims.get("sub")
    email = claims.get("email")
    if not google_sub_id or not email:
        raise AppException("Invalid Google ID token", status_code=401)

    return GoogleUserInfo(
        google_sub_id=google_sub_id,
        email=email,
        full_name=claims.get("name", ""),
    )
