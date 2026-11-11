"""Database schema readiness verification module for FloraMW.

Ensures the database is fully initialized, structurally compatible, and at
the exact expected Alembic migration revision before the application serves traffic.

Schema creation and evolution are strictly owned by Alembic migrations;
application startup only verifies readiness and never silently creates or alters schema.
"""

from pathlib import Path
from typing import Dict, Optional, Set
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"


class DatabaseReadinessError(RuntimeError):
    """Raised when the database schema is missing, outdated, or incompatible."""
    pass


def get_expected_migration_head() -> str:
    """Retrieve the expected target migration head revision directly from Alembic.

    Inspects Alembic's version scripts dynamically to determine the current head,
    avoiding fragile hardcoded revision strings while ensuring deterministic checking.
    """
    if not ALEMBIC_INI_PATH.exists():
        raise DatabaseReadinessError(
            f"Alembic configuration file not found at: {ALEMBIC_INI_PATH}"
        )

    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    if head is None:
        raise DatabaseReadinessError(
            "No Alembic migration head found in the script directory."
        )

    return head


# Core application tables required for FloraMW operation
REQUIRED_TABLES: Set[str] = {
    "alembic_version",
    "districts",
    "plants",
    "plant_sections",
    "plant_sources",
    "plant_distributions",
    "users",
    "identification_requests",
    "identification_candidates",
    "model_versions",
    "dataset_versions",
}

# Critical columns required for ORM compatibility, and forbidden obsolete columns
# from earlier schema iterations that would indicate a failed or partial migration.
SCHEMA_COLUMN_SPEC: Dict[str, Dict[str, Set[str]]] = {
    "plants": {
        "required": {
            "id",
            "common_name_en",
            "scientific_name",
            "family",
            "category",
            "description",
            "is_published",
        },
        "forbidden": {"common_name"},
    },
    "plant_sources": {
        "required": {
            "id",
            "plant_id",
            "title",
            "url",
            "is_pmra_reference",
        },
        "forbidden": {"label", "order_index"},
    },
    "users": {
        "required": {
            "id",
            "password_hash",
            "role",
            "is_anonymous",
        },
        "forbidden": {"full_name", "is_active"},
    },
    "plant_sections": {
        "required": {
            "id",
            "plant_id",
            "section_key",
            "content",
            "content_disclaimer_type",
            "verification_status",
        },
        "forbidden": set(),
    },
    "plant_distributions": {
        "required": {
            "id",
            "plant_id",
            "district_id",
            "native_status",
        },
        "forbidden": {"status"},
    },
    "identification_requests": {
        "required": {
            "id",
            "client_request_id",
            "status",
            "image_sha256",
            "image_format",
            "image_size_bytes",
            "provider_id",
            "outcome",
            "created_at",
        },
        "forbidden": set(),
    },
    "identification_candidates": {
        "required": {
            "id",
            "request_id",
            "rank",
            "scientific_name",
            "confidence",
            "created_at",
        },
        "forbidden": set(),
    },
    "model_versions": {
        "required": {
            "id",
            "model_id",
            "version_tag",
            "provider_type",
            "is_active",
            "created_at",
        },
        "forbidden": set(),
    },
    "dataset_versions": {
        "required": {
            "id",
            "dataset_id",
            "version_tag",
            "species_count",
            "image_count",
            "validation_status",
            "is_active",
            "created_at",
        },
        "forbidden": set(),
    },
}


def verify_database_readiness(
    connection, expected_head: Optional[str] = None
) -> None:
    """Synchronously verify database schema readiness on a connection.

    Checks:
    1. The 'alembic_version' table exists.
    2. 'alembic_version' contains exactly one revision record.
    3. The recorded revision matches the expected migration head.
    4. All required core tables exist.
    5. Critical schema columns match current ORM expectations and no obsolete columns remain.

    Raises:
        DatabaseReadinessError: If any condition fails, with clear diagnostic guidance.
    """
    target_head = expected_head or get_expected_migration_head()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 1. Verify alembic_version table exists
    if "alembic_version" not in existing_tables:
        raise DatabaseReadinessError(
            "Database schema is uninitialized: 'alembic_version' table is missing. "
            "Alembic migrations must be executed prior to starting the application "
            "(run: alembic upgrade head)."
        )

    # 2. Verify recorded revision
    try:
        rows = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).fetchall()
    except Exception as exc:
        raise DatabaseReadinessError(
            f"Failed to query 'alembic_version' table: {exc}"
        ) from exc

    recorded_revisions = [r[0] for r in rows]

    if not recorded_revisions:
        raise DatabaseReadinessError(
            "Database migration state is uninitialized: 'alembic_version' contains no revision records. "
            "Run 'alembic upgrade head' to apply migrations."
        )

    if len(recorded_revisions) > 1:
        raise DatabaseReadinessError(
            f"Conflicting database migration state: 'alembic_version' contains multiple revisions {recorded_revisions}. "
            "The database must be resolved to a single migration head before starting the application."
        )

    recorded_revision = recorded_revisions[0]

    if recorded_revision != target_head:
        raise DatabaseReadinessError(
            f"Database schema revision mismatch: recorded revision is '{recorded_revision}', "
            f"but the expected target head is '{target_head}'. "
            "Run 'alembic upgrade head' to bring the database up to date."
        )

    # 3. Verify all required core tables exist
    missing_tables = REQUIRED_TABLES - existing_tables
    if missing_tables:
        raise DatabaseReadinessError(
            f"Database schema is incomplete: missing required tables {sorted(missing_tables)}. "
            "Run 'alembic upgrade head' to apply the full schema."
        )

    # 4. Verify critical column compatibility
    for table_name, spec in SCHEMA_COLUMN_SPEC.items():
        table_columns = {c["name"] for c in inspector.get_columns(table_name)}

        missing_cols = spec["required"] - table_columns
        if missing_cols:
            raise DatabaseReadinessError(
                f"Critical schema incompatibility in table '{table_name}': "
                f"missing required columns {sorted(missing_cols)}. "
                "The database schema does not match the current ORM models."
            )

        forbidden_present = spec["forbidden"] & table_columns
        if forbidden_present:
            raise DatabaseReadinessError(
                f"Obsolete schema remnants detected in table '{table_name}': "
                f"found deprecated columns {sorted(forbidden_present)}. "
                "The database requires migration alignment (run: alembic upgrade head)."
            )

