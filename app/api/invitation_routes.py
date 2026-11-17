"""HTTP adapter: invitations, registration, bounded imports and approvals."""
from __future__ import annotations
from fastapi import Request
from app.application import invitation_service as svc
from app.application.access import require_scope
from app.application.event_lookup import event_by_id_or_slug, published_event
from app.domain import fail, NotFound, Conflict
from app.api.errors import install_error_handlers


def install_invitation_routes(app, engine, public_origin, identify, log, authorize=None):
    install_error_handlers(app)
    def permission(conn, request, event_id, action, mutate=False):
        user, _ = identify(request, conn, mutate)
        result = authorize(conn, user, event_id, action) if authorize else require_scope(conn, user, event_id)
        if result['kind'] != 'event': fail('EVENT_REQUIRED', NotFound)
        return user, result

    def issued(row, token):
        return {'invitation': svc.staff_view(row), 'token': token, 'invitation_url': f'{public_origin.rstrip("/")}/invite/{token}'}

    @app.get('/api/admin/events/{event_id}/admission-policy')
    def admission_policy(event_id: str, request: Request):
        with engine.connect() as conn:
            permission(conn, request, event_id, 'invitations.manage')
            return {'policy': svc.get_policy(conn, event_id)}

    @app.put('/api/admin/events/{event_id}/admission-policy')
    def update_admission_policy(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'policy.manage', True)
            result = svc.save_policy(conn, event_id, body.get('policy', body))
            log(conn, user, event_id, 'admission_policy_updated', {'revision': result['rev'], 'visibility': result['visibility']})
            return {'policy': result}

    @app.get('/api/admin/events/{event_id}/guest-lists')
    def list_guest_lists(event_id: str, request: Request):
        with engine.connect() as conn:
            permission(conn, request, event_id, 'invitations.manage')
            return {'lists': svc.list_guest_lists(conn, event_id)}

    @app.post('/api/admin/events/{event_id}/guest-lists')
    def create_guest_list(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            row = svc.create_guest_list(conn, event_id, body)
            log(conn, user, event_id, 'guest_list_created', {'list_id': row['id']})
            return row

    @app.get('/api/admin/events/{event_id}/invitations')
    def list_invitations(event_id: str, request: Request):
        with engine.connect() as conn:
            _, ev = permission(conn, request, event_id, 'invitations.manage')
            return svc.invitation_overview(conn, ev, public_origin)

    @app.post('/api/admin/events/{event_id}/invitations')
    def create_invitation(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            row, token = svc.create_invitation(conn, event_id, body)
            log(conn, user, event_id, 'invitation_created', {'invitation_id': row['id'], 'list_id': row['list_id']})
            return issued(row, token)

    @app.post('/api/admin/events/{event_id}/invitations/import/preview')
    def preview_import(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            return svc.preview_import(conn, event_id, user, body)

    @app.post('/api/admin/events/{event_id}/invitations/import/commit')
    def commit_import(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            import_id, created = svc.commit_import(conn, event_id, user, body.get('import_id'))
            result = [issued(row, token) for row, token in created]
            log(conn, user, event_id, 'invitations_imported', {'import_id': import_id, 'count': len(result)})
            return {'invitations': result, 'created_count': len(result)}

    @app.post('/api/admin/events/{event_id}/invitations/{invitation_id}/review')
    def review_invitation(event_id: str, invitation_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, ev = permission(conn, request, event_id, 'invitations.review', True)
            row = svc.review(conn, ev, invitation_id, body.get('decision'), user['id'], body.get('revision'))
            log(conn, user, event_id, 'invitation_reviewed', {'invitation_id': invitation_id, 'status': row['status'], 'revision': row['revision']})
            return {'invitation': svc.staff_view(row)}

    @app.post('/api/admin/events/{event_id}/invitations/{invitation_id}/revoke')
    def revoke_invitation(event_id: str, invitation_id: str, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            row = svc.revoke(conn, event_id, invitation_id)
            log(conn, user, event_id, 'invitation_revoked', {'invitation_id': invitation_id})
            return {'invitation': svc.staff_view(row)}

    @app.post('/api/admin/events/{event_id}/invitations/{invitation_id}/rotate')
    def rotate_invitation(event_id: str, invitation_id: str, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            row, token = svc.rotate(conn, event_id, invitation_id)
            log(conn, user, event_id, 'invitation_token_rotated', {'invitation_id': invitation_id})
            return issued(row, token)

    @app.get('/api/admin/events/{event_id}/on-site-registration')
    def onsite_registration_config(event_id: str, request: Request):
        with engine.connect() as conn:
            _, ev = permission(conn, request, event_id, 'guests.register')
            return {'event': svc.event_view(ev), 'policy': svc.get_policy(conn, event_id)}

    @app.post('/api/admin/events/{event_id}/on-site-registration')
    def onsite_registration(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, ev = permission(conn, request, event_id, 'guests.register', True)
            policy = svc.lock_policy(conn, event_id)
            if not policy['enabled']: fail('ADMISSION_REGISTRATION_DISABLED', Conflict)
            row, token = svc.create_invitation(conn, event_id, {'name': body.get('name'), 'phone': body.get('phone'), 'max_companions': policy['max_companions']})
            row = svc.respond(conn, ev, token, {**body, 'response': 'accepted'})
            if row['status'] == 'pending_approval' and body.get('approve') is True:
                permission(conn, request, event_id, 'invitations.review', True)
                row = svc.review(conn, ev, row['id'], 'approve', user['id'], row['revision'])
            log(conn, user, event_id, 'onsite_registration', {'invitation_id': row['id'], 'status': row['status']})
            return {**svc.public_view(conn, ev, row, public_origin), 'token': token, 'invitation_url': f'{public_origin.rstrip("/")}/invite/{token}'}

    @app.get('/api/public/invitations/{token}')
    def public_invitation(token: str):
        with engine.connect() as conn:
            row = svc.by_token(conn, token)
            return svc.public_view(conn, published_event(conn, event_by_id_or_slug(conn, event_id=row['event_id'])), row, public_origin)

    @app.post('/api/public/invitations/{token}/rsvp')
    def public_rsvp(token: str, body: dict):
        with engine.begin() as conn:
            row = svc.by_token(conn, token)
            ev = published_event(conn, event_by_id_or_slug(conn, event_id=row['event_id']))
            row = svc.respond(conn, ev, token, body)
            log(conn, {'id': None}, ev['id'], 'invitation_rsvp', {'invitation_id': row['id'], 'status': row['status'], 'revision': row['revision']})
            return svc.public_view(conn, ev, row, public_origin)

    @app.get('/api/public/events/{event_slug}/registration')
    def public_registration_config(event_slug: str):
        with engine.connect() as conn:
            ev = published_event(conn, event_by_id_or_slug(conn, slug=event_slug))
            policy = svc.assert_public_registration(conn, ev['id'])
            return {'event': svc.event_view(ev), 'policy': policy}

    @app.post('/api/public/events/{event_slug}/registration')
    def public_registration(event_slug: str, body: dict):
        with engine.begin() as conn:
            ev = published_event(conn, event_by_id_or_slug(conn, slug=event_slug))
            registered = svc.register_publicly(conn, ev, body)
            if registered is None: return {'status': 'verification_required', 'verification_required': True}
            row, token = registered
            log(conn, {'id': None}, ev['id'], 'public_registration_requested', {'invitation_id': row['id'], 'status': row['status']})
            return {**svc.public_view(conn, ev, row, public_origin), 'token': token, 'invitation_url': f'{public_origin.rstrip("/")}/invite/{token}'}
