from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text as sql_text

from ...core.build_info import APP_VERSION, BUILD_LABEL, API_VERSION
from ...db import metadata
from ...core.migrations import postgres_migration_status


def create_health_router(engine) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/api/health")
    def health():
        return {
            "status": "hardening_candidate",
            "version": APP_VERSION,
            "build": BUILD_LABEL,
            "api_version": API_VERSION,
            "database": engine.dialect.name,
            "native_postgres_tested_here": False,
            "production_ready": False,
            "analytics_refresh_seconds": 5,
        }

    @router.get("/api/health/live")
    def liveness():
        return {"status": "ok", "version": APP_VERSION, "build": BUILD_LABEL}

    @router.get("/api/health/ready")
    def readiness():
        details = {
            "database": engine.dialect.name,
            "version": APP_VERSION,
            "build": BUILD_LABEL,
        }
        try:
            with engine.connect() as connection:
                connection.execute(sql_text("SELECT 1")).scalar_one()

                inspector = inspect(connection)
                present = set(inspector.get_table_names())
                required = set(metadata.tables)
                missing_tables = sorted(required - present)
                if missing_tables:
                    raise RuntimeError("SCHEMA_TABLES_MISSING:" + ",".join(missing_tables))

                guest_columns = {x["name"] for x in inspector.get_columns("px_event_guests")}
                required_guest_columns = {"pass_token_hash", "pass_number"}
                missing_columns = sorted(required_guest_columns - guest_columns)
                if missing_columns:
                    raise RuntimeError("SCHEMA_COLUMNS_MISSING:" + ",".join(missing_columns))

                details["schema_tables_current"] = True
                details["critical_columns_current"] = True

                if engine.dialect.name == "postgresql":
                    migration = postgres_migration_status(connection)
                    details.update(migration)
                    if not migration["schema_migrations_current"]:
                        problems = []
                        if migration["migration_missing"]:
                            problems.append(
                                "missing=" + ",".join(migration["migration_missing"])
                            )
                        if migration["migration_checksum_mismatch"]:
                            problems.append(
                                "checksum=" + ",".join(
                                    migration["migration_checksum_mismatch"]
                                )
                            )
                        raise RuntimeError(
                            "SCHEMA_MIGRATIONS_NOT_CURRENT:" + ";".join(problems)
                        )
                else:
                    details.update(
                        {
                            "schema_migrations_current": "not_applicable_local_sqlite",
                            "migration_count": 0,
                            "migration_expected": 0,
                            "migration_missing": [],
                            "migration_checksum_mismatch": [],
                        }
                    )

            return {"status": "ready", **details}
        except Exception as exc:
            return JSONResponse(
                {
                    "status": "not_ready",
                    **details,
                    "reason": str(exc).splitlines()[0][:300],
                },
                status_code=503,
            )

    return router
