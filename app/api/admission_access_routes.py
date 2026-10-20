"""Scoped admission capabilities and time-bounded committee assignments."""
from datetime import datetime
import re

from fastapi import Request
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.application.access import EVENT_ROLE_PERMISSIONS, event_permissions, require_event_permission
from app.application.audit_service import new_id, write_audit
from app.db import assignments, sites, users, user_phones
from app.application.phone_accounts import bind_phone, contact_identity
from app.core.security import hash_password, new_temporary_password
from app.domain import fail, now, stamp, text


def install_admission_access_routes(app, engine, identify):
    def assignment_view(row):
        result = {key: row[key] for key in ('id', 'user_id', 'site_id', 'role', 'status', 'valid_from', 'valid_until', 'name', 'email', 'phone', 'active') if key in row}
        if (result.get('email') or '').startswith('tel:'):
            result['email'] = None
        return result

    def validated_window(body, old=None):
        old = old or {}
        start = stamp(body.get('valid_from', old.get('valid_from')))
        end = stamp(body.get('valid_until', old.get('valid_until')))
        if start and end and datetime.fromisoformat(end.replace('Z', '+00:00')) <= datetime.fromisoformat(start.replace('Z', '+00:00')):
            fail('ASSIGNMENT_WINDOW_INVALID')
        return {'valid_from': start or None, 'valid_until': end or None}

    @app.get('/api/admin/admission/events')
    def admission_events(request: Request):
        with engine.connect() as conn:
            user, _ = identify(request, conn)
            events = []
            for event in conn.execute(select(sites).where(sites.c.kind == 'event')).mappings():
                permissions = event_permissions(conn, user, event['id'])
                if permissions:
                    events.append({'id': event['id'], 'slug': event['slug'], 'title': event['draft'].get('title', event['slug']), 'permissions': sorted(permissions)})
            return {'events': events}

    @app.get('/api/admin/events/{event_id}/permissions')
    def admission_permissions(event_id: str, request: Request):
        with engine.connect() as conn:
            user, _ = identify(request, conn)
            require_event_permission(conn, user, event_id, 'guests.read')
            return {'event_id': event_id, 'permissions': sorted(event_permissions(conn, user, event_id))}

    @app.get('/api/admin/events/{event_id}/committee')
    def committee_list(event_id: str, request: Request):
        with engine.connect() as conn:
            user, _ = identify(request, conn)
            require_event_permission(conn, user, event_id, 'committee.manage')
            rows = conn.execute(select(assignments, users.c.name, users.c.email, users.c.active, user_phones.c.phone).join(
                users, users.c.id == assignments.c.user_id,
            ).outerjoin(user_phones, user_phones.c.user_id == users.c.id).where(assignments.c.site_id == event_id, assignments.c.role.in_(EVENT_ROLE_PERMISSIONS))).mappings()
            return {'assignments': [assignment_view(row) for row in rows], 'roles': sorted(EVENT_ROLE_PERMISSIONS)}

    @app.post('/api/admin/events/{event_id}/committee')
    def committee_assign(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            actor, _ = identify(request, conn, True)
            require_event_permission(conn, actor, event_id, 'committee.manage')
            role = text(body.get('role'), 40, True)
            if role not in EVENT_ROLE_PERMISSIONS:
                fail('COMMITTEE_ROLE_INVALID')
            # Existing users keep their global role/scope. A new crew account is
            # always a member: event actions come only from its assignment.
            temporary_password = None
            account_created = False
            phone = None
            if body.get('user_id'):
                query = select(users).where(users.c.id == text(body['user_id'], 64, True))
            else:
                email, phone = contact_identity(body)
                query = select(users).join(user_phones, users.c.id == user_phones.c.user_id).where(user_phones.c.phone == phone) if phone else select(users).where(users.c.email == email)
            target = conn.execute(query).mappings().first()
            if target is None and body.get('create_account') is True and not body.get('user_id'):
                temporary_password = new_temporary_password()
                target = {'id': new_id(), 'email': email, 'name': text(body.get('name'), 160, True),
                          'role': 'member', 'scope_id': event_id, 'active': 1, 'must_change_password': 1,
                          'password_hash': hash_password(temporary_password)}
                try:
                    with conn.begin_nested():
                        conn.execute(insert(users).values(**target))
                        if phone: bind_phone(conn, target['id'], phone)
                except IntegrityError:
                    fail('USER_CONCURRENT_CHANGE', 409)
                account_created = True
            if not target or not target['active']:
                fail('ACTIVE_USER_NOT_FOUND', 404)
            if target['role'] == 'attendee':
                conn.execute(update(users).where(users.c.id == target['id']).values(role='member'))
            existing = conn.execute(select(assignments).where(assignments.c.user_id == target['id'], assignments.c.site_id == event_id, assignments.c.role == role)).mappings().first()
            values = {'status': 'active', **validated_window(body, existing)}
            assignment_id = existing['id'] if existing else new_id()
            if existing:
                conn.execute(update(assignments).where(assignments.c.id == assignment_id).values(**values))
            else:
                try:
                    with conn.begin_nested():
                        conn.execute(insert(assignments).values(id=assignment_id, user_id=target['id'], site_id=event_id, role=role, created_at=now(), **values))
                except IntegrityError:
                    fail('ASSIGNMENT_CONCURRENT_CHANGE', 409)
            write_audit(conn, actor, event_id, 'committee_assigned', {'assignment_id': assignment_id, 'user_id': target['id'], 'role': role, 'account_created': account_created, **values})
            return {'id': assignment_id, 'user_id': target['id'], 'site_id': event_id, 'name': target['name'], 'email': None if target['email'].startswith('tel:') else target['email'], 'phone': phone, 'role': role,
                    'account_created': account_created, 'temporary_password': temporary_password,
                    'must_change_password': bool(target.get('must_change_password')), **values}

    @app.patch('/api/admin/events/{event_id}/committee/{assignment_id}')
    def committee_update(event_id: str, assignment_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            actor, _ = identify(request, conn, True)
            require_event_permission(conn, actor, event_id, 'committee.manage')
            current = conn.execute(select(assignments).where(assignments.c.id == assignment_id, assignments.c.site_id == event_id, assignments.c.role.in_(EVENT_ROLE_PERMISSIONS))).mappings().first()
            if not current:
                fail('ASSIGNMENT_NOT_FOUND', 404)
            status = body.get('status', current['status'])
            if status not in ('active', 'suspended', 'revoked'):
                fail('ASSIGNMENT_STATUS_INVALID')
            if 'role' in body and body['role'] != current['role']:
                fail('REVOKE_AND_REASSIGN_ROLE')
            values = {'status': status, **validated_window(body, current)}
            conn.execute(update(assignments).where(assignments.c.id == assignment_id).values(**values))
            write_audit(conn, actor, event_id, 'committee_updated', {'assignment_id': assignment_id, **values})
            return {**assignment_view(current), **values}
