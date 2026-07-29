import secrets
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Comma-separated in the environment (e.g. "http://a.com,http://b.com"),
    # split into a list below. NoDecode tells pydantic-settings not to
    # JSON-parse this as a complex type before our validator runs.
    # Defaults to localhost-only so local dev is safe out of the box even
    # if unset — production must set the real deployed Ember frontend
    # URL(s).
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def split_comma_separated_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
