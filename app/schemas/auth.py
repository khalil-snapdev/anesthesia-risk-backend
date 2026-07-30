from pydantic import BaseModel

from app.models.user import Role


class GoogleLoginRequest(BaseModel):
    id_token: str


class GoogleLoginResponse(BaseModel):
    # null means the user hasn't picked a role yet — frontend shows
    # /select-role in that case. The access token itself is set as an
    # httpOnly cookie (see routers/auth.py), never returned in the body —
    # a token readable by JS is a token stealable by XSS.
    role: str | None


class SelectRoleRequest(BaseModel):
    role: Role


class SelectRoleResponse(BaseModel):
    role: str


class UserMeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str | None
