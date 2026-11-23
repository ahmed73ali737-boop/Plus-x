"""HTTP adapter: anonymous site bundles, results, collection and public requests."""
from __future__ import annotations

from fastapi import Request

from app.api.errors import install_error_handlers
from app.application import site_admin
from app.application.collection_service import collect as collect_submissions
from app.application.device_service import heartbeat
from app.application.public_service import build_public_bundle, build_public_poll_results
from app.domain import now


def install_public_routes(app, engine, public_origin):
    install_error_handlers(app)

    @app.post('/api/access-request')
    def access_request(body: dict):
        with engine.begin() as tx:
            return site_admin.request_access(tx, body)

    @app.post('/api/signup-request')
    def signup_request(body: dict):
        with engine.begin() as tx:
            return site_admin.request_signup(tx, body)

    @app.get('/api/public/site/{slug}')
    def public_site(slug: str):
        with engine.connect() as tx:
            return build_public_bundle(tx, site_admin.site_by_slug(tx, slug), public_origin)

    @app.get('/api/public/site/{slug}/results')
    def public_results(slug: str):
        with engine.connect() as tx:
            return build_public_poll_results(tx, site_admin.site_by_slug(tx, slug))

    @app.post('/api/collect')
    def collect(body: dict):
        return {"receipts": collect_submissions(engine, body.get("items")), "server_time": now()}

    @app.post('/api/device/heartbeat')
    def heartbeat_endpoint(body: dict, request: Request):
        raw = request.headers.get('X-PulseX-Device-Token', '')
        with engine.begin() as tx:
            return heartbeat(tx, raw, body)
