import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db_client
from app.main import app


@pytest.mark.asyncio
async def test_unhandled_exception_returns_generic_500() -> None:
    def broken_dependency() -> None:
        raise RuntimeError("boom")

    app.dependency_overrides[get_db_client] = broken_dependency

    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_server_error",
        "message": "An unexpected error occurred",
    }
    assert "RuntimeError" not in response.text
    assert "boom" not in response.text
