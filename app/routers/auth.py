from typing import Any

from fastapi import APIRouter, Depends
from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession

from app.auth.dependencies import get_current_user
from app.auth.google_oauth import verify_google_token
from app.auth.jwt_handler import create_access_token
from app.database import get_db_client
from app.exceptions import AppException
from app.models.audit_log import AuditAction
from app.models.embedded import ActorSnapshot
from app.models.user import User
from app.schemas.auth import (
    GoogleLoginRequest,
    GoogleLoginResponse,
    SelectRoleRequest,
    SelectRoleResponse,
    UserMeResponse,
)
from app.services.audit import record_audit_entry, run_in_transaction

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=GoogleLoginResponse)
async def login_with_google(
    payload: GoogleLoginRequest,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
) -> GoogleLoginResponse:
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

        async def _txn(session: AsyncClientSession) -> None:
            await user.insert(session=session)
            # The new user is their own actor — self-service signup, no
            # other user is involved. role is "unknown" since it's unset
            # until /select-role.
            actor = ActorSnapshot(user_id=str(user.id), full_name=user.full_name, role="unknown")
            await record_audit_entry(
                session,
                entity_type="User",
                entity_id=str(user.id),
                action=AuditAction.CREATE,
                actor=actor,
                changes={
                    "before": None,
                    "after": {
                        "email": user.email,
                        "full_name": user.full_name,
                        "google_sub_id": user.google_sub_id,
                    },
                },
            )

        await run_in_transaction(client, _txn)

    role_value = user.role.value if user.role else None
    access_token = create_access_token(user_id=str(user.id), role=role_value)
    return GoogleLoginResponse(access_token=access_token, role=role_value)


@router.post("/select-role", response_model=SelectRoleResponse)
async def select_role(
    payload: SelectRoleRequest,
    client: AsyncMongoClient[Any] = Depends(get_db_client),
    current_user: User = Depends(get_current_user),
) -> SelectRoleResponse:
    """Set the current user's role — a one-time action.

    Changing an already-set role is an admin action, out of scope here.
    """
    if current_user.role is not None:
        raise AppException("Role has already been set", status_code=409)

    new_role = payload.role

    async def _txn(session: AsyncClientSession) -> None:
        current_user.role = new_role
        await current_user.save(session=session)
        actor = ActorSnapshot(
            user_id=str(current_user.id), full_name=current_user.full_name, role=new_role.value
        )
        await record_audit_entry(
            session,
            entity_type="User",
            entity_id=str(current_user.id),
            action=AuditAction.UPDATE,
            actor=actor,
            changes={"before": {"role": None}, "after": {"role": new_role.value}},
        )

    await run_in_transaction(client, _txn)

    access_token = create_access_token(user_id=str(current_user.id), role=new_role.value)
    return SelectRoleResponse(access_token=access_token, role=new_role.value)


@router.get("/me", response_model=UserMeResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserMeResponse:
    return UserMeResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value if current_user.role else None,
    )
