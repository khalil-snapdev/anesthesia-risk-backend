from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import database
from app.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await database.init_db()
    yield
    await database.close_db()


app = FastAPI(title="Anesthesia Risk Score 2.0", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    try:
        await database.client.admin.command("ping")
        logger.info("Health check succeeded")
        return JSONResponse(status_code=200, content={"status": "ok", "database": "connected"})
    except Exception:
        logger.exception("Health check failed: database unreachable")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "disconnected"},
        )
