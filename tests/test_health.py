from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app import database
from app.main import app


@pytest.mark.asyncio
async def test_health_returns_ok_when_database_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = AsyncMock()
    mock_client.admin.command = AsyncMock(return_value={"ok": 1.0})
    monkeypatch.setattr(database, "client", mock_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


@pytest.mark.asyncio
async def test_health_returns_degraded_when_database_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_client = AsyncMock()
    mock_client.admin.command = AsyncMock(side_effect=ConnectionError("could not connect"))
    monkeypatch.setattr(database, "client", mock_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "disconnected"}
