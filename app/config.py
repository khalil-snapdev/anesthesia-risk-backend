from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    MONGODB_URI: str
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    MONGO_MAX_POOL_SIZE: int = 20
    MONGO_MIN_POOL_SIZE: int = 5
    MONGO_SERVER_SELECTION_TIMEOUT_MS: int = 5000
    MONGO_CONNECT_TIMEOUT_MS: int = 10000


settings = Settings()
