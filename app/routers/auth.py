from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.google_oauth import verify_google_token
from app.auth.jwt_handler import create_access_token
from app.exceptions import AppException
from app.models.user import User
from app.schemas.auth import (
    GoogleLoginRequest,
    GoogleLoginResponse,
    SelectRoleRequest,
    SelectRoleResponse,
    UserMeResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=GoogleLoginResponse)
async def login_with_google(payload: GoogleLoginRequest) -> GoogleLoginResponse:
    """Verify a Google ID token, find-or-create the User, issue our JWT.

    role is null in the response when the user hasn't picked one yet —
    the frontend uses that to decide whether to show /select-role.
    """
    google_user = verify_google_token(payload.id_token)

    user = await User.find_one(User.google_sub_id == google_user.google_sub_id)
    if user is None:
        user = User(
            email=google_user.email,
            full_name=google_user.full_name,
            google_sub_id=google_user.google_sub_id,
            role=None,
            is_active=True,
        )
        await user.insert()

    role_value = user.role.value if user.role else None
    access_token = create_access_token(user_id=str(user.id), role=role_value)
    return GoogleLoginResponse(access_token=access_token, role=role_value)


@router.post("/select-role", response_model=SelectRoleResponse)
async def select_role(
    payload: SelectRoleRequest,
    current_user: User = Depends(get_current_user),
) -> SelectRoleResponse:
    """Set the current user's role — a one-time action.

    Changing an already-set role is an admin action, out of scope here.
    """
    if current_user.role is not None:
        raise AppException("Role has already been set", status_code=409)

    current_user.role = payload.role
    await current_user.save()

    access_token = create_access_token(user_id=str(current_user.id), role=current_user.role.value)
    return SelectRoleResponse(access_token=access_token, role=current_user.role.value)


@router.get("/me", response_model=UserMeResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserMeResponse:
    return UserMeResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value if current_user.role else None,
    )
