from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from ...core.build_info import APP_VERSION, BUILD_LABEL, API_VERSION
from ...infrastructure.persistence.schema_probe import schema_status


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
    def readiness(request: Request):
        details = {
            "database": engine.dialect.name,
            "version": APP_VERSION,
            "build": BUILD_LABEL,
        }
        try:
            details.update(schema_status(engine))

            runtime=getattr(request.app.state,'self_certificate_runtime',None)
            if runtime is not None and hasattr(runtime,'readiness'):
                component=runtime.readiness()
                details['certificates']={key:component[key] for key in ('ready','capabilities','probe_cache_seconds')}
                if not component['ready']:
                    return JSONResponse({'status':'not_ready',**details,'reason':'CERTIFICATE_CAPABILITY_UNAVAILABLE'},status_code=503)
            return {"status": "ready", **details}
        except Exception as exc:
            # Exception type separates DB transport failures without logging SQL/URLs.
            logging.getLogger(__name__).warning("APP_NOT_READY kind=%s", type(exc).__name__)
            return JSONResponse(
                {
                    "status": "not_ready",
                    **details,
                    "reason": (str(exc).splitlines()[0][:300]
                               if isinstance(exc, RuntimeError) and str(exc).startswith("SCHEMA_")
                               else "DATABASE_UNAVAILABLE"),
                },
                status_code=503,
            )

    return router
