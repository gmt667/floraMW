"""Tests for database schema readiness verification.

Validates that application startup strictly checks Alembic revision heads,
table existence, and critical column compatibility while rejecting unmigrated,
outdated, corrupt, or incomplete database states.
"""

from pathlib import Path
import pytest
from sqlalchemy import create_engine, text

from app.core.readiness import (
    DatabaseReadinessError,
    get_expected_migration_head,
    verify_database_readiness,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
FLORAMW_DB_PATH = BACKEND_DIR / "floramw.db"


def _create_base_schema(conn, revision: str = "0004_add_lease_fencing_and_candidate_rank_constraint"):
    """Helper to construct a valid schema matching revision 0004 on an isolated connection."""
    conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
    conn.execute(text(f"INSERT INTO alembic_version (version_num) VALUES ('{revision}')"))

    conn.execute(text(
        "CREATE TABLE districts ("
        "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, "
        "region VARCHAR(50) NOT NULL, created_at DATETIME NOT NULL)"
    ))
    conn.execute(text(
        "CREATE TABLE plants ("
        "id VARCHAR(100) PRIMARY KEY, common_name_en VARCHAR(150) NOT NULL, "
        "scientific_name VARCHAR(150) NOT NULL UNIQUE, family VARCHAR(100) NOT NULL, "
        "category VARCHAR(50) NOT NULL, symbol VARCHAR(10), description TEXT NOT NULL, "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, is_published BOOLEAN NOT NULL)"
    ))
    conn.execute(text(
        "CREATE TABLE plant_sections ("
        "id INTEGER PRIMARY KEY, plant_id VARCHAR(100) NOT NULL, "
        "section_key VARCHAR(100) NOT NULL, content TEXT NOT NULL, "
        "content_disclaimer_type VARCHAR(50) NOT NULL, verification_status VARCHAR(50) NOT NULL, "
        "source_citation TEXT, verified_by CHAR(36), verified_at DATETIME, updated_at DATETIME NOT NULL)"
    ))
    conn.execute(text(
        "CREATE TABLE plant_sources ("
        "id INTEGER PRIMARY KEY, plant_id VARCHAR(100) NOT NULL, "
        "title VARCHAR(255) NOT NULL, url VARCHAR(500) NOT NULL, is_pmra_reference BOOLEAN NOT NULL)"
    ))
    conn.execute(text(
        "CREATE TABLE plant_distributions ("
        "id INTEGER PRIMARY KEY, plant_id VARCHAR(100) NOT NULL, "
        "district_id INTEGER NOT NULL, native_status VARCHAR(50) NOT NULL, "
        "herbarium_specimen_id VARCHAR(100), is_verified BOOLEAN NOT NULL, verified_at DATETIME)"
    ))
    conn.execute(text(
        "CREATE TABLE users ("
        "id CHAR(36) PRIMARY KEY, email VARCHAR(255) UNIQUE, password_hash VARCHAR(255), "
        "role VARCHAR(30) NOT NULL, is_anonymous BOOLEAN NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
    ))
    conn.execute(text(
        "CREATE TABLE identification_requests ("
        "id CHAR(36) PRIMARY KEY, client_request_id VARCHAR(128) NOT NULL UNIQUE, user_id CHAR(36), "
        "status VARCHAR(30) NOT NULL, lease_version INTEGER NOT NULL DEFAULT 1, image_sha256 VARCHAR(64) NOT NULL, image_format VARCHAR(10) NOT NULL, "
        "image_size_bytes INTEGER NOT NULL, image_width_px INTEGER, image_height_px INTEGER, "
        "provider_id VARCHAR(100) NOT NULL, model_id VARCHAR(100), model_version VARCHAR(50), "
        "outcome VARCHAR(30) NOT NULL, top_confidence_level VARCHAR(20), execution_duration_ms INTEGER, "
        "error_code VARCHAR(50), error_message TEXT, created_at DATETIME NOT NULL, completed_at DATETIME)"
    ))
    conn.execute(text(
        "CREATE TABLE identification_candidates ("
        "id CHAR(36) PRIMARY KEY, request_id CHAR(36) NOT NULL, rank INTEGER NOT NULL, "
        "scientific_name VARCHAR(200) NOT NULL, common_names TEXT, family VARCHAR(100), "
        "genus VARCHAR(100), confidence FLOAT NOT NULL, matched_plant_id VARCHAR(64), "
        "provider_taxon_id VARCHAR(100), notes TEXT, created_at DATETIME NOT NULL)"
    ))
    conn.execute(text(
        "CREATE TABLE model_versions ("
        "id CHAR(36) PRIMARY KEY, model_id VARCHAR(100) NOT NULL, version_tag VARCHAR(50) NOT NULL, "
        "provider_type VARCHAR(50) NOT NULL, framework VARCHAR(50), artifact_uri VARCHAR(500), "
        "associated_dataset_version VARCHAR(50), target_species_count INTEGER, is_active BOOLEAN NOT NULL, "
        "notes TEXT, created_at DATETIME NOT NULL)"
    ))
    conn.execute(text(
        "CREATE TABLE dataset_versions ("
        "id CHAR(36) PRIMARY KEY, dataset_id VARCHAR(100) NOT NULL, version_tag VARCHAR(50) NOT NULL, "
        "description TEXT, species_count INTEGER NOT NULL, image_count INTEGER NOT NULL, "
        "checksum_sha256 VARCHAR(64), storage_uri VARCHAR(500), provenance TEXT, "
        "validation_status VARCHAR(50) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"
    ))


def test_get_expected_migration_head():
    """Verify that get_expected_migration_head returns the current Alembic head revision."""
    head = get_expected_migration_head()
    assert head == "0004_add_lease_fencing_and_candidate_rank_constraint"


def test_readiness_valid_schema_and_head_accepted():
    """A database with the full expected schema and matching Alembic head passes verification."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn, "0004_add_lease_fencing_and_candidate_rank_constraint")
        # Should execute cleanly without raising any exception
        verify_database_readiness(conn, expected_head="0004_add_lease_fencing_and_candidate_rank_constraint")


def test_readiness_missing_alembic_version_rejected():
    """A database missing the 'alembic_version' table is rejected."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn)
        conn.execute(text("DROP TABLE alembic_version"))
        with pytest.raises(DatabaseReadinessError, match="alembic_version.*table is missing"):
            verify_database_readiness(conn)


def test_readiness_empty_alembic_version_rejected():
    """A database whose 'alembic_version' table has no revision rows is rejected."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn)
        conn.execute(text("DELETE FROM alembic_version"))
        with pytest.raises(DatabaseReadinessError, match="contains no revision records"):
            verify_database_readiness(conn)


def test_readiness_outdated_revision_rejected():
    """A database recording an outdated revision (e.g. 0001) is rejected with upgrade guidance."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn, revision="0001_initial_schema")
        with pytest.raises(DatabaseReadinessError, match="revision mismatch.*recorded revision is '0001_initial_schema'"):
            verify_database_readiness(conn, expected_head="0002_align_schema_with_models")


def test_readiness_unknown_revision_rejected():
    """A database recording a non-existent or unknown revision is rejected."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn, revision="9999_unknown_future_revision")
        with pytest.raises(DatabaseReadinessError, match="revision mismatch.*9999_unknown_future_revision"):
            verify_database_readiness(conn, expected_head="0002_align_schema_with_models")


def test_readiness_multiple_revisions_rejected():
    """A database with multiple conflicting revision entries in alembic_version is rejected."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn)
        # Drop PK constraint by recreation to insert multiple rows
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0001_initial_schema')"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0002_align_schema_with_models')"))
        with pytest.raises(DatabaseReadinessError, match="multiple revisions"):
            verify_database_readiness(conn, expected_head="0002_align_schema_with_models")


def test_readiness_missing_required_table_rejected():
    """A database missing a required table (e.g. 'districts') is rejected."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn)
        conn.execute(text("DROP TABLE districts"))
        with pytest.raises(DatabaseReadinessError, match="missing required tables.*districts"):
            verify_database_readiness(conn)


def test_readiness_missing_critical_column_rejected():
    """A database where a critical column is missing (e.g. plants.common_name_en) is rejected."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn)
        conn.execute(text("ALTER TABLE plants DROP COLUMN common_name_en"))
        with pytest.raises(DatabaseReadinessError, match="missing required columns.*common_name_en"):
            verify_database_readiness(conn)


def test_readiness_obsolete_column_rejected():
    """A database containing deprecated columns (e.g. plants.common_name or plant_sources.label) is rejected."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _create_base_schema(conn)
        # Add back obsolete column
        conn.execute(text("ALTER TABLE plants ADD COLUMN common_name VARCHAR(255)"))
        with pytest.raises(DatabaseReadinessError, match="found deprecated columns.*common_name"):
            verify_database_readiness(conn)


def test_readiness_healthy_development_database_accepted():
    """The actual development database (floramw.db) must pass all readiness checks cleanly."""
    assert FLORAMW_DB_PATH.exists(), f"Expected floramw.db at: {FLORAMW_DB_PATH}"
    engine = create_engine(f"sqlite:///{FLORAMW_DB_PATH}")
    with engine.connect() as conn:
        verify_database_readiness(conn)

