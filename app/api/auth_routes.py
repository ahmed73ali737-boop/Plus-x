"""Direct phone/password signup. No OTP or unauthenticated password resets."""
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.application.access import require_scope
from app.application.audit_service import new_id, write_audit
from app.application.phone_accounts import account_phone, bind_phone, find_by_phone, principal, public_user
from app.core.security import digest, hash_password, new_csrf_token, new_session_token, new_temporary_password, verify_password
from app.db import sessions, users
from app.domain import fail, text


def session_response(app, conn, user):
    token, csrf = new_session_token(), new_csrf_token()
    conn.execute(insert(sessions).values(token_hash=digest(token), user_id=user['id'], csrf=csrf,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()))
    write_audit(conn, user, user['scope_id'], 'login')
    response = JSONResponse({'user': public_user(conn, user), 'csrf': csrf})
    response.set_cookie('px_session', token, httponly=True, secure=app.state.cookie_secure,
                        samesite='strict', max_age=28800, path='/')
    return response


def install_auth_routes(app, engine, identify):
    @app.get('/api/auth/options')
    def options():
        return {'authentication': 'phone_password', 'verification_required': False,
                'recovery_available': False, 'recovery': 'administrator_assisted',
                'legacy_email_login_available': True}

    @app.post('/api/auth/register')
    def register(body: dict):
        phone = account_phone(body.get('phone'))
        name = text(body.get('name'), 160, True)
        password = body.get('password')
        if password != body.get('confirmation'):
            fail('PASSWORD_CONFIRMATION_MISMATCH')
        hashed = hash_password(password)
        try:
            with engine.begin() as conn:
                if find_by_phone(conn, phone):
                    fail('PHONE_ALREADY_REGISTERED', 409)
                user = dict(id=new_id(), email=principal(phone), name=name, role='attendee',
                            scope_id=None, password_hash=hashed, active=1, must_change_password=0)
                # Client role/scope/active fields are deliberately ignored.
                conn.execute(insert(users).values(**user))
                bind_phone(conn, user['id'], phone)
                write_audit(conn, user, None, 'phone_account_registered')
                return session_response(app, conn, user)
        except IntegrityError:
            fail('PHONE_ALREADY_REGISTERED', 409)

    @app.post('/api/auth/phone')
    def add_my_phone(body: dict, request: Request):
        phone = account_phone(body.get('phone'))
        try:
            with engine.begin() as conn:
                user, _ = identify(request, conn, True)
                if not verify_password(body.get('current'), user['password_hash']):
                    fail('INVALID_CREDENTIALS', 401)
                bind_phone(conn, user['id'], phone)
                # A new login identifier ends other sessions, including this one.
                conn.execute(delete(sessions).where(sessions.c.user_id == user['id']))
                write_audit(conn, user, user['scope_id'], 'phone_login_added')
        except IntegrityError:
            fail('PHONE_ALREADY_REGISTERED', 409)
        response = JSONResponse({'ok': True, 'phone': phone, 'login_required': True})
        response.delete_cookie('px_session', path='/')
        return response

    @app.post('/api/auth/password/reset')
    def unauthenticated_reset_unavailable():
        # Knowing a phone number must never be enough to replace a password.
        fail('RECOVERY_REQUIRES_ADMIN', 403)

    @app.post('/api/admin/users/{user_id}/password/reset')
    def admin_reset(user_id: str, request: Request):
        with engine.begin() as conn:
            actor, _ = identify(request, conn, True)
            if actor['role'] not in ('platform', 'organizer'):
                fail('FORBIDDEN_ROLE', 403)
            target = conn.execute(select(users).where(users.c.id == user_id).with_for_update()).mappings().first()
            if not target:
                fail('USER_NOT_FOUND', 404)
            if actor['role'] != 'platform':
                if target['role'] not in ('agency', 'member') or not target['scope_id']:
                    fail('FORBIDDEN_ROLE', 403)
                require_scope(conn, actor, target['scope_id'])
            if not target['active']:
                fail('ACCOUNT_SUSPENDED', 409)
            if target['id'] == actor['id']:
                fail('USE_CURRENT_PASSWORD_CHANGE', 409)
            temporary = new_temporary_password()
            conn.execute(update(users).where(users.c.id == user_id).values(
                password_hash=hash_password(temporary), must_change_password=1))
            conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
            write_audit(conn, actor, target['scope_id'], 'admin_password_reset', {'target_user_id': user_id})
        return {'temporary_password': temporary, 'must_change_password': True, 'shown_once': True}

    @app.get('/api/admin/users')
    def lookup_user(phone: str, request: Request):
        with engine.connect() as conn:
            actor, _ = identify(request, conn)
            if actor['role'] != 'platform':
                fail('FORBIDDEN_ROLE', 403)
            target = find_by_phone(conn, phone)
            return {'users': [{**public_user(conn, target), 'active': bool(target['active'])}] if target else []}

    @app.patch('/api/admin/users/{user_id}')
    def set_account_status(user_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            actor, _ = identify(request, conn, True)
            if actor['role'] != 'platform':
                fail('FORBIDDEN_ROLE', 403)
            active = body.get('active')
            if not isinstance(active, bool):
                fail('USER_STATUS_INVALID')
            if user_id == actor['id']:
                fail('CANNOT_SUSPEND_SELF', 409)
            target = conn.execute(select(users).where(users.c.id == user_id).with_for_update()).mappings().first()
            if not target:
                fail('USER_NOT_FOUND', 404)
            conn.execute(update(users).where(users.c.id == user_id).values(active=int(active)))
            if not active:
                conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
            write_audit(conn, actor, target['scope_id'], 'user_status_changed', {'user_id': user_id, 'active': active})
        return {'id': user_id, 'active': active, 'sessions_revoked': not active}
