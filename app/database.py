from typing import Any

from beanie import init_beanie
from fastapi import FastAPI, Request
from pymongo import AsyncMongoClient

from app.config import settings
from app.logging_config import get_logger
from app.models import document_models

logger = get_logger(__name__)


async def init_db(app: FastAPI) -> None:
    try:
        mongo_client: AsyncMongoClient[Any] = AsyncMongoClient(
            settings.MONGODB_URI,
            maxPoolSize=settings.MONGO_MAX_POOL_SIZE,
            minPoolSize=settings.MONGO_MIN_POOL_SIZE,
            serverSelectionTimeoutMS=settings.MONGO_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
            tz_aware=True,
        )
        await init_beanie(
            database=mongo_client.get_default_database(),
            document_models=document_models,
        )
        app.state.mongo_client = mongo_client
        logger.info("Database connection initialized")
    except Exception:
        logger.exception("Failed to initialize database connection")
        raise


async def close_db(app: FastAPI) -> None:
    mongo_client: AsyncMongoClient[Any] | None = getattr(app.state, "mongo_client", None)
    if mongo_client is not None:
        await mongo_client.close()
        logger.info("Database connection closed")


def get_db_client(request: Request) -> AsyncMongoClient[Any]:
    client: AsyncMongoClient[Any] = request.app.state.mongo_client
    return client
