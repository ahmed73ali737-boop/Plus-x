"""HTTP adapter: login sessions, passwords and account administration.

Direct phone/password signup. No OTP or unauthenticated password resets.
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.errors import install_error_handlers
from app.application import account_requests as account_request_service
from app.application import account_service as accounts
from app.application.phone_accounts import account_phone
from app.core.security import hash_password
from app.domain import Conflict, Forbidden, fail
from app.domain.accounts import check_registration_passwords

SESSION_COOKIE = 'px_session'
SESSION_MAX_AGE = 28800


def session_response(app, tx, user):
    token, body = accounts.open_session(tx, user)
    response = JSONResponse(body)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=app.state.cookie_secure,
                        samesite='strict', max_age=SESSION_MAX_AGE, path='/')
    return response


def _signed_out(body: dict) -> JSONResponse:
    response = JSONResponse(body)
    response.delete_cookie(SESSION_COOKIE, path='/')
    return response


def install_session_routes(app, engine, identify, dummy_hash: str):
    """Login, current account, logout, session summary and password change."""
    install_error_handlers(app)

    @app.post('/api/auth/login')
    def login(body: dict, request: Request):
        with engine.begin() as tx:
            user = accounts.authenticate(tx, body, dummy_hash)
            return session_response(app, tx, user)

    @app.get('/api/auth/me')
    def me(request: Request):
        with engine.connect() as tx:
            user, session = identify(request, tx)
            return accounts.current_account(tx, user, session)

    @app.post('/api/auth/logout')
    def logout(request: Request):
        with engine.begin() as tx:
            _, session = identify(request, tx, True)
            accounts.logout(tx, session)
        return _signed_out({'ok': True})

    @app.get('/api/auth/sessions')
    def my_sessions(request: Request):
        """Return an owner-only session summary, never session hashes or CSRF secrets."""
        with engine.connect() as tx:
            user, session = identify(request, tx)
            return accounts.session_summary(tx, user, session)

    @app.post('/api/auth/sessions/revoke-all')
    def revoke_all_my_sessions(request: Request):
        """Explicit account-wide revoke; CSRF and identity checks precede mutation."""
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            revoked = accounts.revoke_all_sessions(tx, user)
        return _signed_out({'ok': True, 'revoked_sessions': revoked})

    @app.post('/api/auth/password')
    def change_password(body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            accounts.change_password(tx, user, body)
        return _signed_out({'ok': True})


def install_auth_routes(app, engine, identify):
    install_error_handlers(app)

    @app.get('/api/auth/options')
    def options():
        return {'authentication': 'phone_password', 'verification_required': False, 'approval_required': True,
                'recovery_available': False, 'recovery': 'administrator_assisted',
                'legacy_email_login_available': True}

    @app.post('/api/auth/register')
    def register(body: dict):
        phone = account_phone(body.get('phone'))
        check_registration_passwords(body)
        # Validate policy before persisting the pending identity; never issue a session.
        hash_password(body.get('password'))
        with engine.begin() as tx:
            return account_request_service.submit(tx, actor=None, body={**body, 'phone': phone, 'email': None},
                                                  purpose='personal', scope_type='site', scope_id='platform',
                                                  role='member')

    @app.post('/api/auth/phone')
    def add_my_phone(body: dict, request: Request):
        phone = account_phone(body.get('phone'))
        try:
            with engine.begin() as tx:
                user, _ = identify(request, tx, True)
                accounts.add_phone_login(tx, user, phone, body.get('current'))
        except Exception as error:
            if not accounts.is_conflict(error):
                raise
            fail('PHONE_ALREADY_REGISTERED', Conflict)
        return _signed_out({'ok': True, 'phone': phone, 'login_required': True})

    @app.post('/api/auth/password/reset')
    def unauthenticated_reset_unavailable():
        # Knowing a phone number must never be enough to replace a password.
        fail('RECOVERY_REQUIRES_ADMIN', Forbidden)

    @app.post('/api/admin/users/{user_id}/password/reset')
    def admin_reset(user_id: str, request: Request):
        with engine.begin() as tx:
            actor, _ = identify(request, tx, True)
            temporary = accounts.admin_reset_password(tx, actor, user_id)
        return {'temporary_password': temporary, 'must_change_password': True, 'shown_once': True}

    @app.get('/api/admin/users')
    def lookup_user(phone: str, request: Request):
        with engine.connect() as tx:
            actor, _ = identify(request, tx)
            return {'users': accounts.lookup_by_phone(tx, actor, phone)}

    @app.patch('/api/admin/users/{user_id}')
    def set_account_status(user_id: str, body: dict, request: Request):
        active = body.get('active')
        with engine.begin() as tx:
            actor, _ = identify(request, tx, True)
            accounts.set_account_status(tx, actor, user_id, active)
        return {'id': user_id, 'active': active, 'sessions_revoked': not active}
