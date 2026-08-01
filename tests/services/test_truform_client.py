"""Tests for fetch_pending_submissions — the internal HTTP call to the
(mock, for now) Truform polling endpoint. No respx/pytest-httpx dependency
is available in this project, so httpx.AsyncClient itself is faked
directly rather than mocking at the transport layer.
"""

from typing import Any, Self

import httpx
import pytest

from app.services.truform_client import TruformSubmission, fetch_pending_submissions


class _FakeResponse:
    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError(f"Server returned {self.status_code}")

    def json(self) -> Any:
        return self._json_data


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient as an async context manager."""

    def __init__(
        self, response: _FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


class TestFetchPendingSubmissions:
    @pytest.mark.asyncio
    async def test_returns_parsed_submissions_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_data = [
            {"submission_id": "sub-1", "payload": {"patient_self_first_name": "Alice"}},
            {"submission_id": "sub-2", "payload": {"patient_self_first_name": "Bob"}},
        ]
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: _FakeAsyncClient(response=_FakeResponse(fake_data)),
        )

        result = await fetch_pending_submissions()

        assert result == [
            TruformSubmission(submission_id="sub-1", payload={"patient_self_first_name": "Alice"}),
            TruformSubmission(submission_id="sub-2", payload={"patient_self_first_name": "Bob"}),
        ]

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_network_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Truform (or mock-endpoint) outage must not crash the poll
        flow — the caller just sees zero pending submissions this time."""
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: _FakeAsyncClient(error=httpx.ConnectError("connection refused")),
        )

        result = await fetch_pending_submissions()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_non_2xx_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: _FakeAsyncClient(
                response=_FakeResponse({"error": "boom"}, status_code=500)
            ),
        )

        result = await fetch_pending_submissions()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_response_shape_is_unexpected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Missing the "payload" key entirely -> KeyError, caught defensively
        # rather than propagating and crashing the whole poll request.
        malformed_data = [{"submission_id": "sub-1"}]
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: _FakeAsyncClient(response=_FakeResponse(malformed_data)),
        )

        result = await fetch_pending_submissions()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_non_list_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: _FakeAsyncClient(response=_FakeResponse({"not": "a list"})),
        )

        result = await fetch_pending_submissions()

        assert result == []
