import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": .env may carry vars this Settings class doesn't
    # model yet (e.g. GOOGLE_CLIENT_SECRET, unused by our ID-token-only
    # verification flow — no server-side OAuth code exchange happens
    # here) — an unmodeled env var shouldn't be able to crash startup.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MONGODB_URI: str
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    MONGO_MAX_POOL_SIZE: int = 20
    MONGO_MIN_POOL_SIZE: int = 5
    MONGO_SERVER_SELECTION_TIMEOUT_MS: int = 5000
    MONGO_CONNECT_TIMEOUT_MS: int = 10000

    # Verifies Google Sign-In ID tokens' audience claim — must match the
    # OAuth client ID configured in Google Cloud Console.
    GOOGLE_CLIENT_ID: str

    # Auto-generated per process for local dev convenience only. NOT safe
    # for production: a random default here (a) invalidates every issued
    # token on every restart, and (b) differs across worker processes,
    # breaking token validation under any multi-worker deployment. Set a
    # real, stable JWT_SECRET_KEY via the production environment.
    JWT_SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_EXPIRY_MINUTES: int = 60 * 24


settings = Settings()
