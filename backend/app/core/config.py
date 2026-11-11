from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    PROJECT_NAME: str = "FloraMW Botanical Companion API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Defaults to SQLite+aiosqlite in backend dir for local testing; override with postgresql+asyncpg://... in production/docker
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BACKEND_DIR / 'floramw.db'}"

    # CORS Origins
    CORS_ORIGINS: List[str] = ["*"]

    # Sync & Retention Parameters
    SYNC_TOMBSTONE_RETENTION_DAYS: int = 90
    MAX_UPLOAD_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
