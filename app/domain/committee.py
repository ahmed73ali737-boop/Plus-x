"""Committee assignments: time-bounded event roles of admission staff."""
from __future__ import annotations

from datetime import datetime

from app.domain.errors import NotFound, fail
from app.domain.values import stamp

ASSIGNMENT_STATUSES = ('active', 'suspended', 'revoked')
VIEW_FIELDS = ('id', 'user_id', 'site_id', 'role', 'status', 'valid_from', 'valid_until', 'name', 'email', 'phone',
               'active')


def assignment_view(row: dict) -> dict:
    result = {key: row[key] for key in VIEW_FIELDS if key in row}
    if (result.get('email') or '').startswith('tel:'):
        result['email'] = None
    return result


def validated_window(body: dict, old: dict | None = None) -> dict:
    old = old or {}
    start = stamp(body.get('valid_from', old.get('valid_from')))
    end = stamp(body.get('valid_until', old.get('valid_until')))
    if start and end and (datetime.fromisoformat(end.replace('Z', '+00:00'))
                          <= datetime.fromisoformat(start.replace('Z', '+00:00'))):
        fail('ASSIGNMENT_WINDOW_INVALID')
    return {'valid_from': start or None, 'valid_until': end or None}


def assignment_changes(current: dict, body: dict) -> dict:
    """Status and shift window may change; a role change requires revoke and reassign."""
    status = body.get('status', current['status'])
    if status not in ASSIGNMENT_STATUSES:
        fail('ASSIGNMENT_STATUS_INVALID')
    if 'role' in body and body['role'] != current['role']:
        fail('REVOKE_AND_REASSIGN_ROLE')
    return {'status': status, **validated_window(body, current)}


def require_committee_role(role, known_roles) -> str:
    """Only roles that carry event permissions can be assigned."""
    if role not in known_roles:
        fail('COMMITTEE_ROLE_INVALID')
    return role


def require_assignee(user_id, target) -> None:
    """A named assignee must be an existing account."""
    if user_id and not target:
        fail('ACTIVE_USER_NOT_FOUND', NotFound)


def require_assignment(row: dict | None) -> dict:
    if not row:
        fail('ASSIGNMENT_NOT_FOUND', NotFound)
    return row
