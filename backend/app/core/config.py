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

    # Image upload limits (identification engine)
    MAX_UPLOAD_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
    MAX_IMAGE_DIMENSION_PX: int = 4096  # Maximum width or height in pixels

    # Identification confidence thresholds (0.0–1.0)
    # Provider confidence scores are not independently calibrated accuracy values.
    CONFIDENCE_THRESHOLD_HIGH: float = 0.70
    CONFIDENCE_THRESHOLD_MODERATE: float = 0.45
    CONFIDENCE_THRESHOLD_LOW: float = 0.20

    # Identification provider selection.
    # Accepted values: "deterministic" (dev/test only), "plantnet" (production or dev), or future provider IDs.
    # Must never be "deterministic" in ENVIRONMENT=production.
    IDENTIFICATION_PROVIDER: str = "deterministic"

    # Explicit opt-in to allow the deterministic mock provider.
    # Defaults False in production. Set True in development/test environments.
    # An unset or False value in production causes identification to return 503.
    ALLOW_MOCK_PROVIDER: bool = True

    # Pl@ntNet Botanical Identification API Configuration
    # Official API: https://my.plantnet.org/
    PLANTNET_API_KEY: str = ""
    PLANTNET_PROJECT: str = "all"  # 'all' covers world flora including Malawi
    PLANTNET_API_BASE_URL: str = "https://my-api.plantnet.org/v2/identify"
    PLANTNET_TIMEOUT_SECONDS: float = 15.0
    PLANTNET_CONNECT_TIMEOUT_SECONDS: float = 5.0
    PLANTNET_DEFAULT_ORGAN: str = "auto"
    PLANTNET_LANGUAGE: str = "en"
    PLANTNET_MAX_RESULTS: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
