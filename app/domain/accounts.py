"""Account rules: sessions, password changes, administrative resets, preferences."""
from __future__ import annotations

import hmac

from app.domain.errors import Conflict, Forbidden, NotFound, PreconditionRequired, Unauthenticated, fail

SESSION_HOURS = 8
PREFERENCE_DEFAULTS = {'theme': 'system', 'text_size': 'normal', 'reduce_motion': False,
                       'notifications_enabled': True}
# Routes a user who must change a temporary password may still call.
PASSWORD_CHANGE_ALLOWED_PATHS = ('/api/auth/me', '/api/auth/password', '/api/auth/logout', '/api/auth/sessions',
                                 '/api/auth/sessions/revoke-all')


def check_password_change(body: dict) -> None:
    if body.get('password') == body.get('current'):
        fail('PASSWORD_MUST_DIFFER')
    if 'confirmation' in body and body['confirmation'] != body.get('password'):
        fail('PASSWORD_CONFIRMATION_MISMATCH')


def check_registration_passwords(body: dict) -> None:
    if body.get('password') != body.get('confirmation'):
        fail('PASSWORD_CONFIRMATION_MISMATCH')


def require_platform(user: dict) -> None:
    if user['role'] != 'platform':
        fail('FORBIDDEN_ROLE', Forbidden)


def require_reset_target(actor: dict, target: dict) -> None:
    if not target['active']:
        fail('ACCOUNT_SUSPENDED', Conflict)
    if target['id'] == actor['id']:
        fail('USE_CURRENT_PASSWORD_CHANGE', Conflict)


def require_reset_authority(actor: dict) -> None:
    """Only staff reset passwords; the platform for anyone, an organizer for their own scope."""
    if actor['role'] not in ('platform', 'organizer'):
        fail('FORBIDDEN_ROLE', Forbidden)


def require_organizer_reset_scope(target: dict) -> None:
    """An organizer resets only scoped exhibitor/member accounts, never staff or global users."""
    if target['role'] not in ('agency', 'member') or not target['scope_id']:
        fail('FORBIDDEN_ROLE', Forbidden)


def require_known_user(target) -> dict:
    if not target:
        fail('USER_NOT_FOUND', NotFound)
    return target


def platform_status(active, actor: dict, user_id: str) -> bool:
    """Platform account (de)activation: a real boolean, never one's own account."""
    if not isinstance(active, bool):
        fail('USER_STATUS_INVALID')
    if user_id == actor['id']:
        fail('CANNOT_SUSPEND_SELF', Conflict)
    return active


def site_user_status(active) -> bool:
    if active not in (True, False, 0, 1):
        fail('USER_STATUS_INVALID')
    return bool(active)


def require_credentials(verified: bool) -> None:
    """Password re-entry for sensitive changes; one answer whether wrong or stale."""
    if not verified:
        fail('INVALID_CREDENTIALS', Unauthenticated)


def check_preferences(body: dict) -> dict:
    if (set(body) != set(PREFERENCE_DEFAULTS) or body.get('theme') not in ('system', 'light', 'dark')
            or body.get('text_size') not in ('normal', 'large')):
        fail('PREFERENCES_INVALID')
    if any(type(body.get(key)) is not bool for key in ('reduce_motion', 'notifications_enabled')):
        fail('PREFERENCES_INVALID')
    return body


def check_request_path(user: dict, path: str, has_management_access) -> None:
    """Attendees never reach admin APIs; temporary passwords must be changed first."""
    if user['role'] == 'attendee' and path.startswith('/api/admin/') and not has_management_access():
        fail('FORBIDDEN_ROLE', Forbidden)
    if user.get('must_change_password') and path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        fail('PASSWORD_CHANGE_REQUIRED', PreconditionRequired)


def require_live_session(session: dict | None, at: str) -> dict:
    """A stored, unexpired session."""
    if not session or session['expires_at'] <= at:
        fail('LOGIN_REQUIRED', Unauthenticated)
    return session


def require_active_account(user: dict | None) -> dict:
    """The session's account must still exist and be active."""
    if not user or not user['active']:
        fail('LOGIN_REQUIRED', Unauthenticated)
    return user


def require_csrf(sent: str, stored: str) -> None:
    """State-changing requests must echo the session's CSRF secret (constant-time compare)."""
    if not hmac.compare_digest(sent, stored):
        fail('CSRF_REQUIRED', Forbidden)


def require_notification(marked: bool) -> None:
    """Only the owner's own notification can be marked read."""
    if not marked:
        fail('NOT_FOUND', NotFound)


def require_active_target_account(target: dict | None) -> dict:
    """Messaging/administration targets must be existing, active accounts."""
    if not target or not target['active']:
        fail('ACCOUNT_NOT_FOUND', NotFound)
    return target
