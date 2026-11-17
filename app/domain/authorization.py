"""Roles, event capabilities and time-bounded assignments.

Admission authority is separate from editing a site: a scanner never gains
access to publishing, account administration or guest exports.
"""
from __future__ import annotations

from datetime import datetime

from app.domain.values import now

EVENT_PERMISSIONS = frozenset({
    'guests.read', 'guests.register', 'guests.export', 'guests.checkin',
    'invitations.manage', 'invitations.review', 'policy.manage', 'committee.manage',
    'certificates.manage', 'certificates.issue', 'certificates.revoke',
})
EVENT_ROLE_PERMISSIONS = {
    'event_manager': EVENT_PERMISSIONS,
    'reception': frozenset({'guests.read', 'guests.register', 'guests.checkin'}),
    'scanner': frozenset({'guests.read', 'guests.checkin'}),
    'committee_supervisor': frozenset({
        'guests.read', 'guests.register', 'guests.checkin',
        'invitations.manage', 'invitations.review',
    }),
    'analyst': frozenset({'guests.read'}),
    'auditor': frozenset({'guests.read'}),
}
SITE_MANAGEMENT_ROLES = frozenset({'owner', 'admin', 'editor', 'event_manager', 'site_manager'})
ORGANIZATION_MANAGEMENT_ROLES = frozenset({'owner', 'admin', 'editor'})
READ_ONLY_ASSIGNMENT_ROLES = ('analyst', 'auditor')


def _parse(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def active_window(record: dict, at: str | None = None) -> bool:
    """Time-bounded assignment check at ``at`` (ISO timestamp, default: now).

    Assignments may intentionally expire. Participation access is different:
    an ended event must remain administrable for reporting, export and archive
    work; only an explicit participation status change revokes that access.
    """
    if record.get('status', 'active') != 'active':
        return False
    try:
        current = datetime.fromisoformat((at or now()).replace('Z', '+00:00'))
        start = _parse(record.get('valid_from'))
        end = _parse(record.get('valid_until'))
        return (start is None or start <= current) and (end is None or current < end)
    except (TypeError, ValueError, AttributeError):
        # Invalid/naive timestamps fail closed rather than granting a shift.
        return False


def active_participation(record: dict) -> bool:
    return record.get('status', 'active') == 'active'


def is_active_user(user) -> bool:
    return bool(user) and bool(user.get('active', 1))


def has_full_event_authority(user: dict, event_id: str) -> bool:
    return user['role'] == 'platform' or (user['role'] == 'organizer' and user.get('scope_id') == event_id)


def event_capabilities(user, event_id: str, assignments: list[dict], at: str | None = None) -> frozenset[str]:
    """Capabilities granted by role or by the user's currently active assignments."""
    if not is_active_user(user):
        return frozenset()
    if has_full_event_authority(user, event_id):
        return EVENT_PERMISSIONS
    grants = set()
    for assignment in assignments:
        if active_window(assignment, at):
            grants.update(EVENT_ROLE_PERMISSIONS.get(assignment['role'], ()))
    return frozenset(grants)


def manages_by_role(user: dict, site: dict) -> bool:
    return user['role'] == 'platform' or (
        user['role'] == 'organizer' and (user['scope_id'] == site['id'] or site['event_id'] == user['scope_id']))


def direct_agency_access(user_id: str, linked: list[dict], memberships: list[dict]) -> bool:
    """An agency account on its own page is still governed by the participation lifecycle.

    A legacy standalone agency page without a participation row keeps direct
    access; a legacy direct account without a membership keeps its original scope.
    """
    if not linked:
        return True
    if memberships:
        authorized = {m['organization_id'] for m in memberships
                      if m['status'] == 'active' and m['role'] in ORGANIZATION_MANAGEMENT_ROLES}
        return any(active_participation(p) and p['organization_id'] in authorized for p in linked)
    return any(active_participation(p) for p in linked)


def manages_by_assignment(assignments: list[dict], at: str | None = None) -> bool:
    return any(a['role'] in SITE_MANAGEMENT_ROLES and active_window(a, at) for a in assignments)


def reads_by_assignment(assignments: list[dict], at: str | None = None) -> bool:
    return any(a['role'] in READ_ONLY_ASSIGNMENT_ROLES and active_window(a, at) for a in assignments)


def committee_roles() -> list[str]:
    return [role for role, permissions in EVENT_ROLE_PERMISSIONS.items() if 'committee.manage' in permissions]
