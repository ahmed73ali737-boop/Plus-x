"""PulseX HTTP composition root.

SQLite remains the local QA backend; PostgreSQL requires native acceptance before production.
This module wires settings, the database engine (which installs the persistence
adapters), middleware, error mapping and the route adapters. Business rules live
in app.domain, use cases in app.application and SQL in app.infrastructure.
Build identity is centralized in app.core.build_info.
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tools.production_gate import assert_production_ready

from .api.account_request_routes import install_account_request_routes
from .api.account_routes import install_account_routes
from .api.admission_access_routes import install_admission_access_routes
from .api.auth_routes import install_auth_routes, install_session_routes
from .api.certificate_routes import install_certificate_routes
from .api.errors import error_response, install_error_handlers
from .api.guest_routes import install_guest_routes
from .api.invitation_routes import install_invitation_routes
from .api.middleware import install_security_middleware
from .api.public_routes import install_public_routes
from .api.routers.downloads import create_download_router
from .api.routers.health import create_health_router
from .api.self_certificate_routes import install_self_certificate_routes
from .api.site_admin_routes import install_site_admin_routes
from .application.access import get_site as site_row
from .application.access import require_event_permission
from .application.audit_service import AuditedDenial, DenialAuditWriter
from .application.audit_service import write_audit as log
from .application.auth_service import identify_request
from .application.phone_accounts import management_access
from .core.build_info import APP_NAME, APP_VERSION
from .core.security import hash_password as password_hash
from .core.serialization import canonical_json as canon
from .core.settings import load_settings
from .infrastructure.persistence.tables import ensure_compat_schema, make_engine, metadata
from .domain import NotFound, fail
from .domain.accounts import check_request_path
from .domain.media import MEDIA_MAX_BYTES, media_extension
from .infrastructure.g_observability import FASTAPI_TELEMETRY, install_observability
from .infrastructure.seed import seed_demo_data as seed

ROOT = Path(__file__).resolve().parent.parent
MIN_CERTIFICATE_WORKERS, MAX_CERTIFICATE_WORKERS = 1, 6
# Do not inherit OS-specific MIME registry drift for browser module assets.
# Chromium refuses ES modules unless .mjs is served with a JavaScript MIME type.
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/manifest+json", ".webmanifest")


def _certificate_worker_count() -> int:
    try:
        workers = int(os.environ.get('PX_SELF_CERTIFICATE_WORKERS', '6'))
    except ValueError as error:
        raise RuntimeError('INVALID_SELF_CERTIFICATE_WORKERS') from error
    if not MIN_CERTIFICATE_WORKERS <= workers <= MAX_CERTIFICATE_WORKERS:
        raise RuntimeError('INVALID_SELF_CERTIFICATE_WORKERS')
    return workers


def create_app(database_url=None, origin=None, seed_demo=None, credentials_path=None, shared_authorizer=None):
    shared_mode = os.environ.get('PULSEX_SHARED_AUTHORIZATION_MODE', 'Off')
    if shared_mode not in ('Off', 'Enforce'):
        raise RuntimeError('SHARED_AUTHORIZATION_MODE_INVALID')
    if shared_mode == 'Enforce' and shared_authorizer is None:
        raise RuntimeError('SHARED_AUTHORIZATION_PROVIDER_REQUIRED')
    settings = load_settings(database_url=database_url, origin=origin,
                             seed_demo=seed_demo, credentials_path=credentials_path)
    if settings.production_mode:
        # Evaluate effective factory arguments BEFORE constructing the database engine.
        assert_production_ready(database_url=settings.database_url, origin=settings.public_origin,
                                seed_demo=settings.seed_demo, workers=settings.workers)
    engine = make_engine(settings.database_url)
    if not settings.production_mode:
        metadata.create_all(engine)
        ensure_compat_schema(engine)

    @asynccontextmanager
    async def lifespan(_app):
        from .application.certificate_batches import process_pending
        from .application.self_certificate_runtime import CertificateWorkers

        certificate_workers = _certificate_worker_count()
        background_enabled = not (engine.dialect.name == 'sqlite' and engine.url.database in (None, '', ':memory:'))
        runtime = app.state.self_certificate_runtime
        runtime.background_enabled = background_enabled
        service = CertificateWorkers(engine, runtime, lambda: process_pending(engine), certificate_workers)
        if background_enabled:
            service.start()
        try:
            yield
        finally:
            if background_enabled:
                service.close()
            engine.dispose()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url=None, redoc_url=None,
                  lifespan=lifespan, telemetry=FASTAPI_TELEMETRY)
    install_observability(app, "pulsex-api")
    app.state.engine = engine
    app.state.denial_audit = DenialAuditWriter(engine)

    install_error_handlers(app)

    @app.exception_handler(AuditedDenial)
    async def audited_denial_handler(request, exc):
        # Endpoint context managers have unwound (and rolled back) here.
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(app.state.denial_audit.record, exc)
        return error_response(exc)

    app.state.shared_organizer_authorizer = shared_authorizer
    # Explicit ASGI/QA factory calls historically seed in-memory only unless a
    # credential file was requested. Never write a shared default file across
    # independent test DBs; run.py passes the settings path explicitly.
    seed_file = (str(settings.credentials_path) if
                 credentials_path is not None or os.environ.get("CREDENTIALS_PATH")
                 else None)
    app.state.seed_credentials = seed(engine, seed_file) if settings.seed_demo else []
    public_origin = settings.public_origin
    media_dir = settings.media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    dummy = password_hash(secrets.token_urlsafe(20))

    install_security_middleware(
        app,
        public_origin,
        allow_local_loopback_origins=(settings.environment == "local" and not settings.production_mode),
    )

    app.include_router(create_health_router(engine))
    app.include_router(create_download_router(ROOT))

    def identify(req, tx, write=False):
        user, session = identify_request(req, tx, write)
        check_request_path(user, req.scope.get('path') or '/', lambda: management_access(tx, user))
        return user, session

    install_account_request_routes(app, engine, identify)
    install_auth_routes(app, engine, identify)
    install_guest_routes(app, engine, public_origin, identify=identify, site_row=site_row, log=log)
    install_invitation_routes(app, engine, public_origin, identify=identify, log=log, authorize=require_event_permission)
    install_admission_access_routes(app, engine, identify=identify)
    install_account_routes(app, engine, identify=identify)
    install_certificate_routes(app, engine, public_origin, identify=identify, log=log)
    install_self_certificate_routes(app, engine, settings, identify, log)
    install_session_routes(app, engine, identify, dummy)
    install_public_routes(app, engine, public_origin)
    install_site_admin_routes(app, engine, public_origin, identify, shared_mode=shared_mode,
                              shared_authorizer=shared_authorizer, canon=canon)

    @app.post('/api/admin/media')
    def upload_media(body: dict, request: Request):
        with engine.connect() as tx:
            identify(request, tx, True)
        try:
            data = base64.b64decode(body.get('base64', ''), validate=True)
        except Exception:
            fail('MEDIA_INVALID')
        if not data or len(data) > MEDIA_MAX_BYTES:
            fail('MEDIA_MAX_4_MB')
        extension = media_extension(data)
        name = hashlib.sha256(data).hexdigest() + '.' + extension
        (media_dir / name).write_bytes(data)
        return {'url': '/media/' + name, 'bytes': len(data), 'type': 'video' if extension == 'mp4' else 'image'}

    @app.get('/media/{name}')
    def media(name: str):
        if not re.fullmatch(r'[a-f0-9]{64}\.(png|jpg|webp|mp4)|[a-z-]+-demo\.svg', name):
            fail('MEDIA_NOT_FOUND', NotFound)
        path = media_dir / name
        if not path.exists():
            path = ROOT / 'web/media' / name
        if not path.is_file():
            fail('MEDIA_NOT_FOUND', NotFound)
        return FileResponse(path, headers={'Cache-Control': 'public, max-age=86400'})

    @app.get('/templates/{name}')
    def template(name: str):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.(xlsx|csv)', name):
            fail('TEMPLATE_NOT_FOUND', NotFound)
        path = ROOT / 'templates' / name
        if not path.is_file():
            fail('TEMPLATE_NOT_FOUND', NotFound)
        return FileResponse(path, filename=name)

    @app.get('/sw.js')
    def sw():
        return FileResponse(ROOT / 'web/sw.js', media_type='application/javascript',
                            headers={'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/'})

    app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')

    @app.get('/{path:path}')
    def spa(path: str):
        if path.startswith(('api/', 'media/', 'templates/')):
            fail('NOT_FOUND', NotFound)
        return FileResponse(ROOT / 'web/index.html', headers={'Cache-Control': 'no-cache'})

    return app
