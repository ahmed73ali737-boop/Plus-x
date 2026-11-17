"""Readiness probe of the database: connectivity, schema tables, critical
columns and (on PostgreSQL) the versioned migration ledger."""
from __future__ import annotations

from sqlalchemy import inspect, text as sql_text

from app.core.migrations import postgres_migration_status
from app.infrastructure.persistence.tables import metadata

REQUIRED_GUEST_COLUMNS = {"pass_token_hash", "pass_number"}
NOT_APPLICABLE_ON_SQLITE = {
    "schema_migrations_current": "not_applicable_local_sqlite",
    "migration_count": 0,
    "migration_expected": 0,
    "migration_missing": [],
    "migration_checksum_mismatch": [],
}


def schema_status(engine) -> dict:
    """Return readiness details; raise RuntimeError('SCHEMA_...') when not current."""
    details = {}
    with engine.connect() as connection:
        connection.execute(sql_text("SELECT 1")).scalar_one()
        inspector = inspect(connection)
        missing_tables = sorted(set(metadata.tables) - set(inspector.get_table_names()))
        if missing_tables:
            raise RuntimeError("SCHEMA_TABLES_MISSING:" + ",".join(missing_tables))
        guest_columns = {column["name"] for column in inspector.get_columns("px_event_guests")}
        missing_columns = sorted(REQUIRED_GUEST_COLUMNS - guest_columns)
        if missing_columns:
            raise RuntimeError("SCHEMA_COLUMNS_MISSING:" + ",".join(missing_columns))
        details["schema_tables_current"] = True
        details["critical_columns_current"] = True
        if engine.dialect.name != "postgresql":
            details.update(NOT_APPLICABLE_ON_SQLITE)
            return details
        migration = postgres_migration_status(connection)
        details.update(migration)
        if not migration["schema_migrations_current"]:
            problems = []
            if migration["migration_missing"]:
                problems.append("missing=" + ",".join(migration["migration_missing"]))
            if migration["migration_checksum_mismatch"]:
                problems.append("checksum=" + ",".join(migration["migration_checksum_mismatch"]))
            raise RuntimeError("SCHEMA_MIGRATIONS_NOT_CURRENT:" + ";".join(problems))
    return details
