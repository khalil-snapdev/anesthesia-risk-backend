"""Our own session tokens, issued after Google verification succeeds.

Google's ID token proves identity at login time only — we issue our own
short-lived signed JWT (containing user_id and role) so subsequent
requests don't need to re-verify with Google on every call.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings
from app.exceptions import AppException

_ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    role: str | None


def create_access_token(user_id: str, role: str | None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    """Verify and decode one of our access tokens.

    Raises AppException(401) if the token is invalid, expired, or
    tampered with.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AppException("Invalid or expired token", status_code=401) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise AppException("Invalid or expired token", status_code=401)

    return TokenPayload(user_id=user_id, role=payload.get("role"))
