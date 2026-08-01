from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import AsyncMongoClient

from app.config import settings
from app.database import close_db, get_db_client, init_db
from app.exceptions import AppException
from app.logging_config import configure_logging, get_logger
from app.routers import auth, mock_truform, patients

configure_logging()
logger = get_logger(__name__)

_ERROR_NAMES_BY_STATUS = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db(app)
    yield
    await close_db(app)


app = FastAPI(title="Anesthesia Risk Score 2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
    # Content-Disposition isn't in the CORS-safelisted response headers, so
    # without this the frontend's PDF downloads can't read the real
    # server-generated filename via response.headers.get(...).
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(patients.router)

# Fake stand-in for the real Truform API (no real credentials for this
# practice project) — must never exist in a real deployment. See
# app/routers/mock_truform.py's module docstring for the full rationale.
if settings.ENVIRONMENT != "production":
    app.include_router(mock_truform.router)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.warning("Handled application exception: %s", exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": _ERROR_NAMES_BY_STATUS.get(exc.status_code, "application_error"),
            "message": exc.message,
        },
    )


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
