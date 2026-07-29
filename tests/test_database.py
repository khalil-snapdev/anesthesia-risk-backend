from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.database import close_db, get_db_client, init_db


@pytest.mark.asyncio
async def test_init_db_sets_client_on_app_state() -> None:
    app = FastAPI()
    fake_client = MagicMock()
    fake_client.get_default_database.return_value = MagicMock()

    with (
        patch("app.database.AsyncMongoClient", return_value=fake_client) as mock_ctor,
        patch("app.database.init_beanie", new=AsyncMock()) as mock_init_beanie,
    ):
        await init_db(app)

    mock_ctor.assert_called_once()
    mock_init_beanie.assert_awaited_once()
    assert app.state.mongo_client is fake_client


@pytest.mark.asyncio
async def test_init_db_constructs_client_with_tz_aware_true() -> None:
    app = FastAPI()
    fake_client = MagicMock()
    fake_client.get_default_database.return_value = MagicMock()

    with (
        patch("app.database.AsyncMongoClient", return_value=fake_client) as mock_ctor,
        patch("app.database.init_beanie", new=AsyncMock()),
    ):
        await init_db(app)

    assert mock_ctor.call_args.kwargs["tz_aware"] is True


@pytest.mark.asyncio
async def test_init_db_raises_on_connection_failure() -> None:
    app = FastAPI()

    with (
        patch("app.database.AsyncMongoClient", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        await init_db(app)


@pytest.mark.asyncio
async def test_close_db_closes_existing_client() -> None:
    app = FastAPI()
    fake_client = MagicMock()
    fake_client.close = AsyncMock()
    app.state.mongo_client = fake_client

    await close_db(app)

    fake_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_db_is_noop_when_no_client_present() -> None:
    app = FastAPI()

    await close_db(app)


def test_get_db_client_reads_client_from_request_app_state() -> None:
    app = FastAPI()
    fake_client = MagicMock()
    app.state.mongo_client = fake_client
    request = MagicMock()
    request.app = app

    assert get_db_client(request) is fake_client
