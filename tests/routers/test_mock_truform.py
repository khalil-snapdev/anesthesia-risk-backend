"""Tests for the mock Truform API (app/routers/mock_truform.py) — the
simulated stand-in for the real external Truform system, mounted only in
non-production environments (see app/main.py).
"""

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.exceptions import AppException
from app.main import app
from app.routers.mock_truform import _require_internal_caller


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestListMockSubmissions:
    @pytest.mark.asyncio
    async def test_returns_a_list_of_realistic_submissions(self, client: AsyncClient) -> None:
        response = await client.get("/mock/truform/submissions")

        assert response.status_code == 200
        submissions = response.json()
        assert len(submissions) >= 2

        for submission in submissions:
            assert "submission_id" in submission
            assert "payload" in submission
            # Real researched Truform field names, not firstName/lastName.
            assert "patient_self_first_name" in submission["payload"]
            assert "patient_self_date_of_birth" in submission["payload"]

    @pytest.mark.asyncio
    async def test_submission_ids_are_unique(self, client: AsyncClient) -> None:
        response = await client.get("/mock/truform/submissions")

        submission_ids = [s["submission_id"] for s in response.json()]
        assert len(submission_ids) == len(set(submission_ids))


class TestGetMockSubmission:
    @pytest.mark.asyncio
    async def test_returns_the_matching_submission(self, client: AsyncClient) -> None:
        list_response = await client.get("/mock/truform/submissions")
        first_id = list_response.json()[0]["submission_id"]

        response = await client.get(f"/mock/truform/submissions/{first_id}")

        assert response.status_code == 200
        assert response.json()["submission_id"] == first_id

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_id(self, client: AsyncClient) -> None:
        response = await client.get("/mock/truform/submissions/does-not-exist")

        assert response.status_code == 404


class TestRequireInternalCaller:
    """Unit tests for the internal-only guard itself — the defense-in-depth
    layer on top of this router only ever being mounted outside production
    (see app/main.py)."""

    @pytest.mark.asyncio
    async def test_allows_loopback_client(self) -> None:
        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")

        await _require_internal_caller(request)  # must not raise

    @pytest.mark.asyncio
    async def test_allows_missing_client_info(self) -> None:
        # In-process test/ASGI harnesses may not populate a real client —
        # treated as internal rather than blocked.
        request = MagicMock()
        request.client = None

        await _require_internal_caller(request)  # must not raise

    @pytest.mark.asyncio
    async def test_rejects_non_loopback_client(self) -> None:
        request = MagicMock()
        request.client = MagicMock(host="203.0.113.5")

        with pytest.raises(AppException) as exc_info:
            await _require_internal_caller(request)
        assert exc_info.value.status_code == 403
