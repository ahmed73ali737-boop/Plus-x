"""HTTP adapter: invitations, registration, bounded imports and approvals."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from fastapi import Request
from sqlalchemy import select, insert, update, func
from sqlalchemy.exc import IntegrityError
from app.application import invitation_service as svc
from app.application.access import require_scope
from app.application.guest_service import normalize_phone
from app.application.audit_service import new_id
from app.db import sites, guests, event_guests, versions
from app.invitations_db import invitations, guest_lists, invitation_imports, entitlements
from app.domain import fail, now, text


def install_invitation_routes(app, engine, public_origin, identify, log, authorize=None):
    def event(conn, event_id=None, slug=None):
        query = select(sites).where(sites.c.kind == 'event')
        query = query.where(sites.c.id == event_id) if event_id else query.where(sites.c.slug == slug)
        row = conn.execute(query).mappings().first()
        if not row: fail('EVENT_NOT_FOUND', 404)
        return dict(row)

    def published_event(conn, ev):
        if not ev['published_version']: fail('EVENT_NOT_PUBLISHED', 404)
        projection = conn.execute(select(versions.c.config).where(versions.c.site_id == ev['id'], versions.c.version == ev['published_version'])).scalar_one_or_none()
        if projection is None: fail('EVENT_NOT_PUBLISHED', 404)
        return {**ev, 'draft': projection}

    def permission(conn, request, event_id, action, mutate=False):
        user, _ = identify(request, conn, mutate)
        result = authorize(conn, user, event_id, action) if authorize else require_scope(conn, user, event_id)
        if result['kind'] != 'event': fail('EVENT_REQUIRED', 404)
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
            return {'lists': [dict(row) for row in conn.execute(select(guest_lists).where(guest_lists.c.event_id == event_id).order_by(guest_lists.c.name)).mappings()]}

    @app.post('/api/admin/events/{event_id}/guest-lists')
    def create_guest_list(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            row = {'id': new_id(), 'event_id': event_id, 'name': text(body.get('name'), 160, True), 'created_at': now()}
            try:
                with conn.begin_nested(): conn.execute(insert(guest_lists).values(**row))
            except IntegrityError: fail('GUEST_LIST_ALREADY_EXISTS', 409)
            log(conn, user, event_id, 'guest_list_created', {'list_id': row['id']})
            return row

    @app.get('/api/admin/events/{event_id}/invitations')
    def list_invitations(event_id: str, request: Request):
        with engine.connect() as conn:
            _, ev = permission(conn, request, event_id, 'invitations.manage')
            rows = [svc.staff_view(dict(row)) for row in conn.execute(select(invitations).where(invitations.c.event_id == event_id).order_by(invitations.c.created_at.desc())).mappings()]
            for row in rows:
                credential = svc.public_view(conn, ev, row, public_origin)
                row.update({key: credential[key] for key in ('guest_number', 'qr_url', 'pass_url', 'qr_image_url') if key in credential})
            counts = {state: sum(row['status'] == state for row in rows) for state in ('invited', 'pending_approval', 'approved', 'declined', 'rejected', 'revoked')}
            people = sum(1 + row['companions'] for row in rows if row['status'] == 'approved')
            admitted = conn.execute(select(func.coalesce(func.sum(entitlements.c.consumed), 0)).where(entitlements.c.event_id == event_id)).scalar_one()
            return {'invitations': rows, 'counts': counts, 'confirmed_people': people, 'admission_uses': admitted}

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
            raw = svc.parse_guest_file(text(body.get('filename'), 200, True), body.get('content_base64'))
            rows, errors, seen = [], [], set()
            for index, item in enumerate(raw, 2):
                if body.get('list_id') and not item.get('list_id'): item['list_id'] = body['list_id']
                try:
                    clean = svc.clean_invitation(conn, event_id, item)
                    if clean['phone'] in seen: fail('DUPLICATE_PHONE_IN_FILE')
                    if conn.execute(select(invitations.c.id).where(invitations.c.event_id == event_id, invitations.c.phone == clean['phone'])).first(): fail('INVITATION_ALREADY_EXISTS', 409)
                    seen.add(clean['phone'])
                    rows.append({'name': clean['name'], 'phone': clean['phone'], 'list_id': clean['list_id'], 'max_companions': clean['max_companions'], 'days': clean['allowed_days']})
                except Exception as exc:
                    if not hasattr(exc, 'detail'): raise
                    errors.append({'row': index, 'error': exc.detail})
            import_id = new_id()
            conn.execute(insert(invitation_imports).values(id=import_id, event_id=event_id, user_id=user['id'], rows=rows, errors=errors, state='preview', created_at=now()))
            return {'import_id': import_id, 'rows': rows, 'errors': errors, 'valid_count': len(rows), 'total_count': len(raw)}

    @app.post('/api/admin/events/{event_id}/invitations/import/commit')
    def commit_import(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user, _ = permission(conn, request, event_id, 'invitations.manage', True)
            preview = conn.execute(select(invitation_imports).where(invitation_imports.c.id == text(body.get('import_id'), 64, True), invitation_imports.c.event_id == event_id, invitation_imports.c.user_id == user['id']).with_for_update()).mappings().first()
            if not preview: fail('IMPORT_PREVIEW_NOT_FOUND', 404)
            if preview['state'] != 'preview': fail('IMPORT_ALREADY_COMMITTED', 409)
            if preview['errors'] or not preview['rows']: fail('IMPORT_ERRORS_MUST_BE_FIXED', 409)
            if datetime.fromisoformat(preview['created_at']) < datetime.now(timezone.utc) - timedelta(hours=1): fail('IMPORT_PREVIEW_EXPIRED', 409)
            result = []
            for body_row in preview['rows']:
                row, token = svc.create_invitation(conn, event_id, body_row)
                result.append(issued(row, token))
            conn.execute(update(invitation_imports).where(invitation_imports.c.id == preview['id']).values(state='committed'))
            log(conn, user, event_id, 'invitations_imported', {'import_id': preview['id'], 'count': len(result)})
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
            if not policy['enabled']: fail('ADMISSION_REGISTRATION_DISABLED', 409)
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
            return svc.public_view(conn, published_event(conn, event(conn, event_id=row['event_id'])), row, public_origin)

    @app.post('/api/public/invitations/{token}/rsvp')
    def public_rsvp(token: str, body: dict):
        with engine.begin() as conn:
            row = svc.by_token(conn, token)
            ev = published_event(conn, event(conn, event_id=row['event_id']))
            row = svc.respond(conn, ev, token, body)
            log(conn, {'id': None}, ev['id'], 'invitation_rsvp', {'invitation_id': row['id'], 'status': row['status'], 'revision': row['revision']})
            return svc.public_view(conn, ev, row, public_origin)

    @app.get('/api/public/events/{event_slug}/registration')
    def public_registration_config(event_slug: str):
        with engine.connect() as conn:
            ev = published_event(conn, event(conn, slug=event_slug))
            policy = svc.assert_public_registration(conn, ev['id'])
            return {'event': svc.event_view(ev), 'policy': policy}

    @app.post('/api/public/events/{event_slug}/registration')
    def public_registration(event_slug: str, body: dict):
        with engine.begin() as conn:
            ev = published_event(conn, event(conn, slug=event_slug))
            svc.lock_policy(conn, ev['id'])
            policy = svc.assert_public_registration(conn, ev['id'])
            phone = normalize_phone(body.get('phone'), body.get('country_code') or '+967')
            # Knowing a phone number must never recover an existing invitation/pass.
            existing = conn.execute(select(invitations.c.id).where(invitations.c.event_id == ev['id'], invitations.c.phone == phone)).first()
            registered = conn.execute(select(event_guests.c.id).join(guests, guests.c.id == event_guests.c.guest_id).where(event_guests.c.event_id == ev['id'], guests.c.phone_e164 == phone)).first()
            if existing or registered: return {'status': 'verification_required', 'verification_required': True}
            row, token = svc.create_invitation(conn, ev['id'], {'name': body.get('name'), 'phone': phone, 'max_companions': policy['max_companions']})
            row = svc.respond(conn, ev, token, {**body, 'response': 'accepted'})
            log(conn, {'id': None}, ev['id'], 'public_registration_requested', {'invitation_id': row['id'], 'status': row['status']})
            return {**svc.public_view(conn, ev, row, public_origin), 'token': token, 'invitation_url': f'{public_origin.rstrip("/")}/invite/{token}'}
