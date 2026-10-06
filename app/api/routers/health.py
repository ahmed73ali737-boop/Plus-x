from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql_text

from ...core.build_info import BUILD_LABEL, API_VERSION

def create_health_router(engine) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/api/health")
    def health():
        return {
            "status": "hardening_candidate",
            "build": BUILD_LABEL,
            "api_version": API_VERSION,
            "database": engine.dialect.name,
            "native_postgres_tested_here": False,
            "production_ready": False,
            "analytics_refresh_seconds": 5,
        }

    @router.get("/api/health/live")
    def liveness():
        return {"status": "ok", "build": BUILD_LABEL}

    @router.get("/api/health/ready")
    def readiness():
        try:
            with engine.connect() as connection:
                connection.execute(sql_text("SELECT 1")).scalar_one()
            return {"status": "ready", "database": engine.dialect.name, "build": BUILD_LABEL}
        except Exception:
            return JSONResponse(
                {"status": "not_ready", "database": engine.dialect.name, "build": BUILD_LABEL},
                status_code=503,
            )

    return router
