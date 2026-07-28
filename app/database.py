from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.logging_config import get_logger
from app.models import document_models

logger = get_logger(__name__)

client: AsyncIOMotorClient | None = None


async def init_db() -> None:
    global client
    try:
        client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            maxPoolSize=settings.MONGO_MAX_POOL_SIZE,
            minPoolSize=settings.MONGO_MIN_POOL_SIZE,
            serverSelectionTimeoutMS=settings.MONGO_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
        )
        await init_beanie(database=client.get_default_database(), document_models=document_models)
        logger.info("Database connection initialized")
    except Exception:
        logger.exception("Failed to initialize database connection")
        raise


async def close_db() -> None:
    global client
    if client is not None:
        client.close()
        logger.info("Database connection closed")
        client = None
