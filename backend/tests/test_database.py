"""Tests for database configuration and SQLite foreign-key enforcement."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_engine
from app.models.plant import PlantSection


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_pragma_enabled(db_session: AsyncSession):
    """Verify that SQLite connections have PRAGMA foreign_keys enabled (returns 1)."""
    result = await db_session.execute(text("PRAGMA foreign_keys"))
    pragma_val = result.scalar()
    assert pragma_val == 1, f"Expected PRAGMA foreign_keys=1, got {pragma_val}"


@pytest.mark.asyncio
async def test_foreign_key_valid_insert_succeeds(db_session: AsyncSession):
    """Verify that inserting a child with a valid existing parent succeeds."""
    # 'hibiscus' is a seeded plant
    section = PlantSection(
        plant_id="hibiscus",
        section_key="Test Section Key",
        content="Test content for valid foreign key verification",
        content_disclaimer_type="educational_summary",
        verification_status="unreviewed",
    )
    db_session.add(section)
    await db_session.commit()
    assert section.id is not None

    # Clean up test section
    await db_session.delete(section)
    await db_session.commit()


@pytest.mark.asyncio
async def test_foreign_key_invalid_insert_rejected(db_session: AsyncSession):
    """Verify that inserting a child with a non-existent parent raises an IntegrityError."""
    orphan_section = PlantSection(
        plant_id="non_existent_plant_id_xyz",
        section_key="Orphan Key",
        content="Content for orphan record",
        content_disclaimer_type="educational_summary",
        verification_status="unreviewed",
    )
    db_session.add(orphan_section)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


def test_engine_pool_resilience_configuration():
    """Verify that the application database engine has pool_pre_ping and pool_recycle enabled.

    In production PostgreSQL deployments, firewalls and load balancers drop idle TCP
    connections. pool_pre_ping=True prevents stale connection failures (HTTP 500),
    and pool_recycle limits maximum connection lifespan.
    """
    assert async_engine.sync_engine.pool._pre_ping is True
    assert async_engine.sync_engine.pool._recycle == 1800

