"""HTTP adapter: site, organization, participation, device and audit administration."""
from __future__ import annotations

import csv
import io
import re
import secrets

from fastapi import Request
from fastapi.responses import Response

from app.api.errors import install_error_handlers
from app.application import account_service as accounts
from app.application import site_admin
from app.application.access import require_read_scope, require_scope
from app.application.audit_service import write_audit
from app.application.collection_service import build_metrics
from app.application.device_service import create_device, list_devices, site_device, update_device
from app.application.public_service import build_public_bundle
from app.application.shared_authorization import authorize_organizer_action
from app.domain import Forbidden, fail, normalize_config
from app.imports import parse as parse_import

FORMULA_PREFIX = re.compile(r'^[\s\x00-\x1f]*[=+@-]')
EXPORT_COLUMNS = ['id', 'site_id', 'version', 'kind', 'source', 'target', 'payload', 'client_time', 'received_at']


def csv_safe(value: str) -> str:
    """Neutralize spreadsheet formulas in exported cells."""
    return "'" + value if FORMULA_PREFIX.match(value) else value


def install_site_admin_routes(app, engine, public_origin, identify, *, shared_mode, shared_authorizer, canon):
    install_error_handlers(app)

    def authorize(user, site, action):
        authorize_organizer_action(shared_mode, shared_authorizer, user, site, action)

    @app.get('/api/admin/signup-requests')
    def admin_signup_requests(request: Request, site_id: str | None = None):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return {'requests': site_admin.signup_requests_for(tx, user, site_id)}

    @app.patch('/api/admin/signup-requests/{rid}')
    def review_signup_request(rid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.review_signup_request(tx, user, rid, body.get('status'), body.get('reason'))

    @app.get('/api/admin/sites')
    def list_admin_sites(request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return site_admin.readable_sites(tx, user)

    @app.post('/api/admin/sites')
    def create_site(body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.create_site(tx, user, body)

    @app.get('/api/admin/sites/{sid}')
    def get_admin_site(sid: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return site_admin.admin_site_view(tx, user, sid)

    @app.put('/api/admin/sites/{sid}')
    def save_site(sid: str, body: dict, request: Request):
        config = normalize_config(body.get('config'))
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.save_draft(tx, user, sid, body.get('draft_rev'), config, authorize)

    @app.post('/api/admin/sites/{sid}/publish')
    def publish_site(sid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.publish(tx, user, sid, body.get('draft_rev'), authorize)

    @app.get('/api/admin/sites/{sid}/preview')
    def preview_site(sid: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return build_public_bundle(tx, require_scope(tx, user, sid), public_origin, True)

    @app.get('/api/admin/sites/{sid}/users')
    def list_users(sid: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return site_admin.site_users(tx, user, sid)

    @app.post('/api/admin/sites/{sid}/users')
    def add_user(sid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.request_site_user(tx, user, sid, body)

    @app.patch('/api/admin/sites/{sid}/users/{user_id}')
    def update_site_user(sid: str, user_id: str, body: dict, request: Request):
        with engine.begin() as tx:
            actor, _ = identify(request, tx, True)
            return accounts.set_site_user_status(tx, actor, sid, user_id, body.get('active'))

    @app.patch('/api/admin/sites/{sid}/access-requests/{rid}')
    def review_access_request(sid: str, rid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.review_access_request(tx, user, sid, rid, body.get('status'), body.get('reason'))

    @app.get('/api/admin/sites/{sid}/devices')
    def admin_devices(sid: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            require_scope(tx, user, sid)
            return {'devices': list_devices(tx, sid)}

    @app.post('/api/admin/sites/{sid}/devices')
    def add_device(sid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            require_scope(tx, user, sid)
            if user['role'] == 'agency' and body.get('device_type') == 'operator':
                fail('FORBIDDEN_ROLE', Forbidden)
            token = secrets.token_urlsafe(32)
            device_id = create_device(tx, sid, body.get('name'), body.get('device_type'), token,
                                      body.get('app_version', ''), body.get('metadata'))
            write_audit(tx, user, sid, 'device_created', {'device_id': device_id, 'device_type': body.get('device_type')})
            return {'id': device_id, 'device_token': token, 'token_shown_once': True}

    @app.patch('/api/admin/sites/{sid}/devices/{did}')
    def patch_device(sid: str, did: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            require_scope(tx, user, sid)
            site_device(tx, sid, did)
            result = update_device(tx, did, status=body.get('status'), name=body.get('name'),
                                   app_version=body.get('app_version'), metadata_json=body.get('metadata'))
            write_audit(tx, user, sid, 'device_updated', {'device_id': did, 'status': result['status']})
            return {'id': did, 'status': result['status'], 'name': result['name']}

    @app.get('/api/admin/organizations')
    def list_organizations(request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return {'organizations': site_admin.organizations_for(tx, user)}

    @app.post('/api/admin/organizations')
    def create_organization(body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.create_organization(tx, user, body)

    @app.get('/api/admin/events/{event_id}/participations')
    def list_participations(event_id: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return {'participations': site_admin.event_participations(tx, user, event_id)}

    @app.post('/api/admin/events/{event_id}/participations')
    def add_participation(event_id: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.add_participation(tx, user, event_id, body)

    @app.get('/api/admin/organizations/{oid}/people')
    def list_organization_people(oid: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return {'people': site_admin.organization_people(tx, user, oid)}

    @app.post('/api/admin/organizations/{oid}/people')
    def add_organization_person(oid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.add_person(tx, user, oid, body)

    @app.patch('/api/admin/organizations/{oid}/people/{pid}')
    def update_organization_person(oid: str, pid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.update_person(tx, user, oid, pid, body)

    @app.post('/api/admin/organizations/{oid}/people/{pid}/account')
    def create_person_account(oid: str, pid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.request_person_account(tx, user, oid, pid, body)

    @app.post('/api/admin/organizations/{oid}/users')
    def add_organization_user(oid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.request_organization_user(tx, user, oid, body)

    @app.get('/api/admin/organizations/{oid}/members')
    def list_organization_members(oid: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return {'members': site_admin.organization_members(tx, user, oid)}

    @app.patch('/api/admin/organizations/{oid}/members/{member_id}')
    def update_organization_member(oid: str, member_id: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.update_member(tx, user, oid, member_id, body)

    @app.patch('/api/admin/participations/{pid}')
    def update_participation(pid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.update_participation(tx, user, pid, body)

    @app.get('/api/admin/audit')
    def audit_log(request: Request, site_id: str | None = None, limit: int = 200):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return {'entries': site_admin.audit_entries(tx, user, site_id, limit)}

    @app.post('/api/admin/sites/{sid}/imports/preview')
    def import_preview(sid: str, body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            site = require_scope(tx, user, sid)
            records, errors, unknown = parse_import(body)
            return site_admin.preview_import(tx, user, site, records, errors, unknown)

    @app.post('/api/admin/sites/{sid}/imports/{iid}/commit')
    def import_commit(sid: str, iid: str, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return site_admin.commit_import(tx, user, sid, iid)

    @app.get('/api/admin/sites/{sid}/metrics')
    def admin_metrics(sid: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return build_metrics(tx, require_read_scope(tx, user, sid), True)

    @app.get('/api/admin/sites/{sid}/export')
    def export(sid: str, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx)
            entries = site_admin.raw_submissions(tx, user, sid)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_COLUMNS)
        for entry in entries:
            writer.writerow([csv_safe(canon(entry[key]) if isinstance(entry[key], dict) else str(entry[key] or ''))
                             for key in EXPORT_COLUMNS])
        return Response('﻿' + buffer.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="pulsex-{sid}-responses.csv"'})

    @app.get('/api/admin/sites/{sid}/qr')
    def qr(sid: str, request: Request):
        import qrcode

        with engine.connect() as tx:
            user, _ = identify(request, tx)
            path = site_admin.qr_path(tx, user, sid)
        image = qrcode.make(public_origin + path + '?source=qr')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return Response(buffer.getvalue(), media_type='image/png')
