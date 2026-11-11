"""Pytest fixtures for FloraMW Backend Test Suite.

Provides isolated SQLite database sessions pre-seeded with official Malawi
botanical and district catalogs, along with an async HTTPX test client.

Architecture Note — File-based SQLite in tempdir:
  A tempfile-backed SQLite database is used rather than pure in-memory
  so that multiple connections (FastAPI client dependency overrides and test
  assertion sessions) see the exact same persisted rows across concurrent or
  sequential transactions, without connection isolation discrepancies.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Ensure backend directory is in python path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import Base, get_db
from app.core.readiness import get_expected_migration_head
from app.core.seed import seed_all
from app.main import app as _app

# Ensure all ORM models are registered with Base.metadata before create_all runs.
from app.models import (  # noqa: F401
    District,
    IdentificationRequest,
    IdentificationCandidate,
    ModelVersion,
    DatasetVersion,
    Plant,
    PlantSection,
    PlantSource,
    PlantDistribution,
    User,
)

# Re-expose FastAPI app
app = _app

TEMP_DB_PATH = Path(tempfile.gettempdir()) / f"floramw_test_{os.getpid()}.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEMP_DB_PATH.as_posix()}"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(test_engine.sync_engine, "connect")
def set_test_sqlite_pragma(dbapi_connection, connection_record):
    """Enforce foreign keys and WAL mode on the test SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Create all tables and seed reference data once for the test session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        head = get_expected_migration_head()
        await conn.execute(
            text(f"INSERT OR REPLACE INTO alembic_version (version_num) VALUES ('{head}')")
        )

    async with TestingSessionLocal() as session:
        await seed_all(session)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()

    if TEMP_DB_PATH.exists():
        try:
            TEMP_DB_PATH.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session within a transaction for test assertions."""
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP test client bound to the FastAPI application."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
