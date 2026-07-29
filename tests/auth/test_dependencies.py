import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from beanie import init_beanie
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.dependencies import get_current_user, require_role
from app.auth.jwt_handler import create_access_token
from app.exceptions import AppException
from app.models import User, document_models
from app.models.user import Role


class _FakeCollection:
    async def index_information(self) -> dict[str, Any]:
        return {}

    async def create_indexes(self, indexes: list[Any]) -> list[str]:
        return [f"idx_{i}" for i in range(len(indexes))]


class _FakeDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection())

    async def command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        return {"version": "7.0.0"}


@pytest.fixture(scope="module", autouse=True)
def _init_models() -> None:
    asyncio.run(
        init_beanie(
            database=_FakeDatabase(),  # type: ignore[arg-type]
            document_models=document_models,
        )
    )


def make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "email": "jane.doe@example.com",
        "full_name": "Jane Doe",
        "role": Role.NURSE,
        "google_sub_id": "google-sub-123",
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _credentials_for(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_returns_user_for_valid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        user = make_user()
        monkeypatch.setattr(User, "get", AsyncMock(return_value=user))
        token = create_access_token(user_id=str(user.id), role="nurse")

        result = await get_current_user(credentials=_credentials_for(token))

        assert result is user

    @pytest.mark.asyncio
    async def test_raises_401_when_no_credentials_provided(self) -> None:
        with pytest.raises(AppException) as exc_info:
            await get_current_user(credentials=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_for_invalid_token(self) -> None:
        with pytest.raises(AppException) as exc_info:
            await get_current_user(credentials=_credentials_for("not-a-real-token"))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_when_user_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(User, "get", AsyncMock(return_value=None))
        token = create_access_token(user_id="507f1f77bcf86cd799439011", role="nurse")

        with pytest.raises(AppException) as exc_info:
            await get_current_user(credentials=_credentials_for(token))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_when_user_inactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        inactive_user = make_user(is_active=False)
        monkeypatch.setattr(User, "get", AsyncMock(return_value=inactive_user))
        token = create_access_token(user_id=str(inactive_user.id), role="nurse")

        with pytest.raises(AppException) as exc_info:
            await get_current_user(credentials=_credentials_for(token))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_for_malformed_user_id_in_token(self) -> None:
        token = create_access_token(user_id="not-a-valid-object-id", role="nurse")

        with pytest.raises(AppException) as exc_info:
            await get_current_user(credentials=_credentials_for(token))
        assert exc_info.value.status_code == 401


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_allows_matching_role(self) -> None:
        nurse = make_user(role=Role.NURSE)
        dependency = require_role("nurse")

        result = await dependency(nurse)

        assert result is nurse

    @pytest.mark.asyncio
    async def test_allows_any_of_multiple_roles(self) -> None:
        surgeon = make_user(role=Role.SURGEON)
        dependency = require_role("surgeon", "nurse")

        result = await dependency(surgeon)

        assert result is surgeon

    @pytest.mark.asyncio
    async def test_blocks_non_matching_role_with_403(self) -> None:
        office_staff = make_user(role=Role.OFFICE_STAFF)
        dependency = require_role("surgeon", "nurse")

        with pytest.raises(AppException) as exc_info:
            await dependency(office_staff)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_blocks_when_role_not_yet_selected(self) -> None:
        roleless_user = make_user(role=None)
        dependency = require_role("nurse")

        with pytest.raises(AppException) as exc_info:
            await dependency(roleless_user)
        assert exc_info.value.status_code == 403
