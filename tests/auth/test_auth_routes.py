import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.auth.google_oauth import GoogleUserInfo
from app.auth.jwt_handler import create_access_token
from app.config import settings
from app.database import get_db_client
from app.exceptions import AppException
from app.main import app
from app.models import User, document_models
from app.models.audit_log import AuditAction
from app.models.user import Role
from app.routers import auth as auth_router


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


class _FakeSession:
    async def with_transaction(self, callback: Any) -> Any:
        return await callback(self)


class _FakeSessionContext:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _FakeTransactionClient:
    def start_session(self) -> _FakeSessionContext:
        return _FakeSessionContext()


@pytest.fixture(autouse=True)
def _override_db_client() -> Iterator[None]:
    app.dependency_overrides[get_db_client] = lambda: _FakeTransactionClient()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "email": "jane.doe@example.com",
        "full_name": "Jane Doe",
        "role": None,
        "google_sub_id": "google-sub-123",
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _auth_headers_for(user: User) -> dict[str, str]:
    token = create_access_token(user_id=str(user.id), role=user.role.value if user.role else None)
    return {"Authorization": f"Bearer {token}"}


def _mock_google_verification(monkeypatch: pytest.MonkeyPatch, google_user: GoogleUserInfo) -> None:
    monkeypatch.setattr("app.routers.auth.verify_google_token", lambda id_token: google_user)


def _mock_record_audit_entry(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """See tests/routers/test_patients.py's helper of the same name — same
    reasoning: patching AuditLogEntry.insert directly can't assert on
    entry content, so patch the function that builds the entry instead.
    """
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(auth_router, "record_audit_entry", mock)
    return mock


class TestGoogleLogin:
    @pytest.mark.asyncio
    async def test_creates_new_user_when_google_sub_id_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        google_user = GoogleUserInfo(
            google_sub_id="new-google-sub-456", email="new.user@example.com", full_name="New User"
        )
        _mock_google_verification(monkeypatch, google_user)
        monkeypatch.setattr(User, "find_one", AsyncMock(return_value=None))
        insert_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(User, "insert", insert_mock)
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.post("/auth/google", json={"id_token": "fake-valid-token"})

        assert response.status_code == 200
        body = response.json()
        assert body["role"] is None
        assert body["access_token"]
        insert_mock.assert_awaited_once()

        decoded = jwt.decode(body["access_token"], settings.JWT_SECRET_KEY, algorithms=["HS256"])
        assert decoded["role"] is None

        audit_mock.assert_awaited_once()
        audit_kwargs = audit_mock.call_args.kwargs
        assert audit_kwargs["entity_type"] == "User"
        assert audit_kwargs["action"] == AuditAction.CREATE
        assert audit_kwargs["actor"].role == "unknown"
        assert audit_kwargs["changes"]["before"] is None
        assert audit_kwargs["changes"]["after"] == {
            "email": "new.user@example.com",
            "full_name": "New User",
            "google_sub_id": "new-google-sub-456",
        }

    @pytest.mark.asyncio
    async def test_finds_existing_user_and_does_not_create_a_new_one(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing_user = make_user(role=Role.NURSE, google_sub_id="existing-google-sub-789")
        google_user = GoogleUserInfo(
            google_sub_id="existing-google-sub-789",
            email=existing_user.email,
            full_name=existing_user.full_name,
        )
        _mock_google_verification(monkeypatch, google_user)
        monkeypatch.setattr(User, "find_one", AsyncMock(return_value=existing_user))
        insert_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(User, "insert", insert_mock)
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.post("/auth/google", json={"id_token": "fake-valid-token"})

        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "nurse"
        insert_mock.assert_not_awaited()
        # Returning-user logins aren't a mutation — no audit entry expected.
        audit_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_401_for_invalid_google_token(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(id_token: str) -> GoogleUserInfo:
            raise AppException("Invalid Google ID token", status_code=401)

        monkeypatch.setattr("app.routers.auth.verify_google_token", _raise)

        response = await client.post("/auth/google", json={"id_token": "a-tampered-token"})

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_422_when_id_token_missing(self, client: AsyncClient) -> None:
        response = await client.post("/auth/google", json={})

        assert response.status_code == 422


class TestSelectRole:
    @pytest.mark.asyncio
    async def test_sets_role_and_issues_new_token(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = make_user(role=None)
        monkeypatch.setattr(User, "get", AsyncMock(return_value=user))
        monkeypatch.setattr(User, "save", AsyncMock(return_value=None))
        audit_mock = _mock_record_audit_entry(monkeypatch)

        response = await client.post(
            "/auth/select-role",
            json={"role": "nurse"},
            headers=_auth_headers_for(user),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "nurse"

        decoded = jwt.decode(body["access_token"], settings.JWT_SECRET_KEY, algorithms=["HS256"])
        assert decoded["role"] == "nurse"

        audit_mock.assert_awaited_once()
        audit_kwargs = audit_mock.call_args.kwargs
        assert audit_kwargs["entity_type"] == "User"
        assert audit_kwargs["entity_id"] == str(user.id)
        assert audit_kwargs["action"] == AuditAction.UPDATE
        assert audit_kwargs["actor"].role == "nurse"
        assert audit_kwargs["changes"] == {"before": {"role": None}, "after": {"role": "nurse"}}

    @pytest.mark.asyncio
    async def test_rejects_when_role_already_set(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = make_user(role=Role.SURGEON)
        monkeypatch.setattr(User, "get", AsyncMock(return_value=user))

        response = await client.post(
            "/auth/select-role",
            json={"role": "nurse"},
            headers=_auth_headers_for(user),
        )

        assert response.status_code == 409
        assert response.json() == {"error": "conflict", "message": "Role has already been set"}

    @pytest.mark.asyncio
    async def test_returns_401_without_token(self, client: AsyncClient) -> None:
        response = await client.post("/auth/select-role", json={"role": "nurse"})

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_422_for_invalid_role_value(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = make_user(role=None)
        monkeypatch.setattr(User, "get", AsyncMock(return_value=user))

        response = await client.post(
            "/auth/select-role",
            json={"role": "administrator"},
            headers=_auth_headers_for(user),
        )

        assert response.status_code == 422


class TestGetMe:
    @pytest.mark.asyncio
    async def test_returns_current_user_info(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = make_user(role=Role.OFFICE_STAFF)
        monkeypatch.setattr(User, "get", AsyncMock(return_value=user))

        response = await client.get("/auth/me", headers=_auth_headers_for(user))

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "id": str(user.id),
            "email": "jane.doe@example.com",
            "full_name": "Jane Doe",
            "role": "office_staff",
        }

    @pytest.mark.asyncio
    async def test_returns_null_role_when_not_yet_selected(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = make_user(role=None)
        monkeypatch.setattr(User, "get", AsyncMock(return_value=user))

        response = await client.get("/auth/me", headers=_auth_headers_for(user))

        assert response.status_code == 200
        assert response.json()["role"] is None

    @pytest.mark.asyncio
    async def test_returns_401_without_token(self, client: AsyncClient) -> None:
        response = await client.get("/auth/me")

        assert response.status_code == 401
