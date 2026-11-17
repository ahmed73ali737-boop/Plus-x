"""Account rules: sessions, password changes, administrative resets, preferences."""
from __future__ import annotations

from app.domain.errors import Conflict, Forbidden, PreconditionRequired, fail

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
