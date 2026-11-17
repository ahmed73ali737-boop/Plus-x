"""Account use cases: login sessions, passwords, phone principals, user status,
preferences and the in-app inbox. Phone input never proves ownership.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.application.access import require_scope
from app.application.audit_service import AuditedDenial, new_id, write_audit
from app.application.phone_accounts import bind_phone, find_by_phone, public_user
from app.application.ports import is_conflict, persistence
from app.core.security import (
    digest,
    hash_password,
    new_csrf_token,
    new_session_token,
    new_temporary_password,
    verify_password,
)
from app.domain import Conflict, DomainError, Forbidden, NotFound, Unauthenticated, fail, now, text
from app.domain.accounts import (
    PREFERENCE_DEFAULTS,
    SESSION_HOURS,
    check_password_change,
    check_preferences,
    require_platform,
    require_reset_target,
)

SESSION_SUMMARY_TIMEOUT_SECONDS = 28800


def open_session(tx, user) -> tuple[str, dict]:
    """Create a login session; returns (cookie token, response body)."""
    token, csrf = new_session_token(), new_csrf_token()
    persistence.identity.add_session(tx, {
        'token_hash': digest(token), 'user_id': user['id'], 'csrf': csrf,
        'expires_at': (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat(),
    })
    write_audit(tx, user, user['scope_id'], 'login')
    return token, {'user': public_user(tx, user), 'csrf': csrf}


def authenticate(tx, body: dict, dummy_hash: str):
    """Phone or legacy e-mail login; constant work whether or not the user exists."""
    if body.get('phone'):
        try:
            user = find_by_phone(tx, body.get('phone'))
        except DomainError:
            user = None
    else:
        email = text(body.get('email'), 200).lower()
        # Retain existing email accounts; internal tel principals are not emails.
        matches = [] if email.startswith('tel:') else persistence.identity.users_with_email(tx, email)
        user = matches[0] if len(matches) == 1 else None
    valid = verify_password(body.get('password'), user['password_hash'] if user else dummy_hash)
    if not user or not valid or not user['active']:
        raise AuditedDenial('INVALID_CREDENTIALS', Unauthenticated, action='login_failed')
    return user


def current_account(tx, user, session) -> dict:
    return {'user': public_user(tx, user), 'csrf': session['csrf']}


def logout(tx, session) -> None:
    persistence.identity.delete_session(tx, session['token_hash'])


def session_summary(tx, user, session) -> dict:
    """Owner-only session summary, never session hashes or CSRF secrets."""
    return {
        'active_count': persistence.identity.active_session_count(tx, user['id']),
        'current_expires_at': session['expires_at'],
        'absolute_timeout_seconds': SESSION_SUMMARY_TIMEOUT_SECONDS,
        'device_inventory_available': False,
    }


def revoke_all_sessions(tx, user) -> int:
    revoked = persistence.identity.delete_sessions_of(tx, user['id'])
    write_audit(tx, user, user['scope_id'], 'sessions_revoked_all', {'revoked_count': revoked})
    return revoked


def change_password(tx, user, body: dict) -> None:
    if not verify_password(body.get('current'), user['password_hash']):
        fail('INVALID_CREDENTIALS', Unauthenticated)
    check_password_change(body)
    hashed = hash_password(body.get('password'))
    if not persistence.identity.change_password(tx, user['id'], user['password_hash'], hashed):
        fail('INVALID_CREDENTIALS', Unauthenticated)
    persistence.identity.delete_sessions_of(tx, user['id'])
    write_audit(tx, user, user['scope_id'], 'password_changed')


def add_phone_login(tx, user, phone: str, current_password) -> None:
    if not verify_password(current_password, user['password_hash']):
        fail('INVALID_CREDENTIALS', Unauthenticated)
    bind_phone(tx, user['id'], phone)
    # A new login identifier ends other sessions, including this one.
    persistence.identity.delete_sessions_of(tx, user['id'])
    write_audit(tx, user, user['scope_id'], 'phone_login_added')


def admin_reset_password(tx, actor, user_id: str) -> str:
    if actor['role'] not in ('platform', 'organizer'):
        fail('FORBIDDEN_ROLE', Forbidden)
    target = persistence.identity.user(tx, user_id, for_update=True)
    if not target:
        fail('USER_NOT_FOUND', NotFound)
    if actor['role'] != 'platform':
        if target['role'] not in ('agency', 'member') or not target['scope_id']:
            fail('FORBIDDEN_ROLE', Forbidden)
        require_scope(tx, actor, target['scope_id'])
    require_reset_target(actor, target)
    temporary = new_temporary_password()
    persistence.identity.set_temporary_password(tx, user_id, hash_password(temporary))
    persistence.identity.delete_sessions_of(tx, user_id)
    write_audit(tx, actor, target['scope_id'], 'admin_password_reset', {'target_user_id': user_id})
    return temporary


def lookup_by_phone(tx, actor, phone) -> list[dict]:
    require_platform(actor)
    target = find_by_phone(tx, phone)
    return [{**public_user(tx, target), 'active': bool(target['active'])}] if target else []


def _deactivate(tx, user_id: str) -> None:
    persistence.identity.cancel_account_setup(tx, user_id)
    persistence.identity.delete_sessions_of(tx, user_id)


def set_account_status(tx, actor, user_id: str, active) -> None:
    require_platform(actor)
    if not isinstance(active, bool):
        fail('USER_STATUS_INVALID')
    if user_id == actor['id']:
        fail('CANNOT_SUSPEND_SELF', Conflict)
    target = persistence.identity.user(tx, user_id, for_update=True)
    if not target:
        fail('USER_NOT_FOUND', NotFound)
    persistence.identity.set_active(tx, user_id, active)
    if not active:
        _deactivate(tx, user_id)
    write_audit(tx, actor, target['scope_id'], 'user_status_changed', {'user_id': user_id, 'active': active})


def set_site_user_status(tx, actor, site_id: str, user_id: str, active) -> dict:
    require_scope(tx, actor, site_id)
    if actor['role'] == 'agency':
        fail('FORBIDDEN_ROLE', Forbidden)
    target = persistence.identity.user(tx, user_id)
    if not target or target['scope_id'] != site_id:
        fail('USER_NOT_FOUND', NotFound)
    if active not in (True, False, 0, 1):
        fail('USER_STATUS_INVALID')
    persistence.identity.set_active(tx, user_id, bool(active))
    if not active:
        _deactivate(tx, user_id)
    write_audit(tx, actor, site_id, 'user_status_changed', {'user_id': user_id, 'active': bool(active)})
    return {'id': user_id, 'active': bool(active), 'sessions_revoked': not bool(active)}


def preferences(tx, user) -> dict:
    return {**PREFERENCE_DEFAULTS, **(persistence.identity.preferences(tx, user['id']) or {})}


def save_preferences(tx, user, body: dict) -> dict:
    persistence.identity.save_preferences(tx, user['id'], body)
    return body


def inbox(tx, user) -> dict:
    return {'items': persistence.identity.inbox(tx, user['id']), 'channel': 'in_app'}


def mark_read(tx, user, notification_id: str) -> None:
    if not persistence.identity.mark_read(tx, notification_id, user['id']):
        fail('NOT_FOUND', NotFound)


def send_notification(tx, sender, body: dict) -> dict:
    require_platform(sender)
    if body.get('phone'):
        target = find_by_phone(tx, body['phone'])
    else:
        target = persistence.identity.user_with_exact_email(tx, text(body.get('email'), 200, True).lower())
    if not target or not target['active']:
        fail('ACCOUNT_NOT_FOUND', NotFound)
    notification_id = new_id()
    persistence.identity.add_notification(tx, {
        'id': notification_id, 'user_id': target['id'], 'sender_id': sender['id'],
        'title': text(body.get('title'), 160, True), 'body': text(body.get('body'), 2000, True), 'created_at': now(),
    })
    write_audit(tx, sender, sender['scope_id'], 'notification_sent',
                {'notification_id': notification_id, 'recipient_id': target['id']})
    return {'id': notification_id, 'status': 'delivered_to_inbox', 'channel': 'in_app'}


__all__ = [
    'PREFERENCE_DEFAULTS', 'add_phone_login', 'admin_reset_password', 'authenticate', 'change_password',
    'check_preferences', 'current_account', 'inbox', 'logout', 'lookup_by_phone', 'mark_read', 'open_session',
    'preferences', 'revoke_all_sessions', 'save_preferences', 'send_notification', 'session_summary',
    'set_account_status', 'set_site_user_status', 'is_conflict',
]
