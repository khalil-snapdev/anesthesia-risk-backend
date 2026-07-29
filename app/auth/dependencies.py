"""FastAPI dependencies for authenticating requests and gating by role."""

from collections.abc import Awaitable, Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.auth.jwt_handler import decode_access_token
from app.exceptions import AppException
from app.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """Decode the bearer token and load the corresponding active User.

    Raises AppException(401) if the token is missing, invalid/expired, or
    doesn't resolve to an active user.
    """
    if credentials is None:
        raise AppException("Not authenticated", status_code=401)

    payload = decode_access_token(credentials.credentials)

    try:
        user = await User.get(payload.user_id)
    except ValidationError:
        user = None

    if user is None or not user.is_active:
        raise AppException("Not authenticated", status_code=401)

    return user


def require_role(*allowed_roles: str) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: require_role("surgeon", "nurse") builds a
    dependency that raises AppException(403) unless current_user's role
    is one of the given values.
    """

    async def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role is None or current_user.role.value not in allowed_roles:
            raise AppException("Insufficient permissions for this action", status_code=403)
        return current_user

    return _dependency
