from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATHS = (
    ROOT / "ops/002_windows07_devices.sql",
    ROOT / "ops/003_windows11_people_password.sql",
    ROOT / "ops/004_windows12_guest_identity.sql",
    ROOT / "ops/005_guest_presence.sql",
    ROOT / "ops/006_guest_pass_token.sql",
    ROOT / "ops/007_event_guest_pass_number.sql",
)


def expected_migration_checksums() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in MIGRATION_PATHS
    }


def postgres_migration_status(connection) -> dict:
    """Return an evidence-oriented migration status for PostgreSQL readiness.

    Readiness is current only when every migration expected by this build is
    recorded with the exact checksum. Extra historical rows do not make the
    build unready, but missing or changed required rows do.
    """
    expected = expected_migration_checksums()
    table_exists = connection.execute(
        text("SELECT to_regclass('public.px_schema_migrations')")
    ).scalar_one()
    if not table_exists:
        return {
            "schema_migrations_current": False,
            "migration_count": 0,
            "migration_expected": len(expected),
            "migration_missing": sorted(expected),
            "migration_checksum_mismatch": [],
        }

    rows = connection.execute(
        text("SELECT migration_id, checksum FROM px_schema_migrations")
    ).mappings()
    applied = {row["migration_id"]: row["checksum"] for row in rows}
    missing = sorted(name for name in expected if name not in applied)
    mismatched = sorted(
        name for name, checksum in expected.items()
        if name in applied and applied[name] != checksum
    )
    matched = sum(
        1 for name, checksum in expected.items()
        if applied.get(name) == checksum
    )
    return {
        "schema_migrations_current": not missing and not mismatched,
        "migration_count": matched,
        "migration_expected": len(expected),
        "migration_missing": missing,
        "migration_checksum_mismatch": mismatched,
    }
