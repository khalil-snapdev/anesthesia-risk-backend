from pydantic import BaseModel

from app.models.user import Role


class GoogleLoginRequest(BaseModel):
    id_token: str


class GoogleLoginResponse(BaseModel):
    access_token: str
    # null means the user hasn't picked a role yet — frontend shows
    # /select-role in that case.
    role: str | None


class SelectRoleRequest(BaseModel):
    role: Role


class SelectRoleResponse(BaseModel):
    access_token: str
    role: str


class UserMeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str | None
