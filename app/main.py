from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo import AsyncMongoClient

from app.database import close_db, get_db_client, init_db
from app.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db(app)
    yield
    await close_db(app)


app = FastAPI(title="Anesthesia Risk Score 2.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception during request processing")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": "An unexpected error occurred"},
    )


@app.get("/health")
async def health(mongo_client: AsyncMongoClient[Any] = Depends(get_db_client)) -> JSONResponse:
    try:
        await mongo_client.admin.command("ping")
        logger.info("Health check succeeded")
        return JSONResponse(status_code=200, content={"status": "ok", "database": "connected"})
    except Exception:
        logger.exception("Health check failed: database unreachable")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "disconnected"},
        )
