from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db import assignments, event_participations, memberships
from app.domain import fail, now
from app.infrastructure.repository import get_site


# Admission authority is separate from editing a site. A scanner must never gain
# access to publishing, account administration or guest exports via require_scope.
EVENT_PERMISSIONS = frozenset({
    'guests.read', 'guests.register', 'guests.export', 'guests.checkin',
    'invitations.manage', 'invitations.review', 'policy.manage', 'committee.manage',
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


def active_window(record: dict) -> bool:
    """Time-bounded assignment check.

    Assignments may intentionally expire. Participation access is different:
    an ended event must remain administrable for reporting, export and archive
    work; only an explicit participation status change revokes that access.
    """
    if record.get('status', 'active') != 'active':
        return False
    try:
        current = datetime.fromisoformat(now().replace('Z', '+00:00'))
        start = datetime.fromisoformat(record['valid_from'].replace('Z', '+00:00')) if record.get('valid_from') else None
        end = datetime.fromisoformat(record['valid_until'].replace('Z', '+00:00')) if record.get('valid_until') else None
        return (start is None or start <= current) and (end is None or current < end)
    except (TypeError, ValueError, AttributeError):
        # Invalid/naive timestamps fail closed rather than granting a shift.
        return False


def active_participation(record: dict) -> bool:
    return record.get('status', 'active') == 'active'


def can_manage(conn, user, site) -> bool:
    if not user or not user.get('active', 1):
        return False
    if user['role'] == 'platform':
        return True
    if user['role'] == 'organizer' and (user['scope_id'] == site['id'] or site['event_id'] == user['scope_id']):
        return True
    # A direct agency/site account is still governed by the participation lifecycle.
    # If this is a legacy standalone agency page without a participation row, keep direct access.
    if user['role'] == 'agency' and user['scope_id'] == site['id']:
        linked = conn.execute(select(event_participations).where(event_participations.c.agency_site_id == site['id'])).mappings().all()
        if not linked:
            return True
        related_memberships = conn.execute(select(memberships).where(
            memberships.c.user_id == user['id'],
            memberships.c.organization_id.in_([p['organization_id'] for p in linked]),
        )).mappings().all()
        if related_memberships:
            authorized_orgs = {m['organization_id'] for m in related_memberships
                               if m['status'] == 'active' and m['role'] in ORGANIZATION_MANAGEMENT_ROLES}
            return any(active_participation(dict(p)) and p['organization_id'] in authorized_orgs for p in linked)
        # Legacy direct accounts without a membership keep their original scope.
        return any(active_participation(dict(p)) for p in linked)

    user_assignments = conn.execute(
        select(assignments).where(
            assignments.c.user_id == user['id'],
            assignments.c.site_id == site['id'],
        )
    ).mappings().all()
    if any(a['role'] in SITE_MANAGEMENT_ROLES and active_window(dict(a)) for a in user_assignments):
        return True

    organization_ids = [
        m['organization_id']
        for m in conn.execute(
            select(memberships).where(
                memberships.c.user_id == user['id'],
                memberships.c.status == 'active',
                memberships.c.role.in_(ORGANIZATION_MANAGEMENT_ROLES),
            )
        ).mappings()
    ]
    if organization_ids:
        participations = conn.execute(
            select(event_participations).where(
                event_participations.c.organization_id.in_(organization_ids),
                event_participations.c.agency_site_id == site['id'],
            )
        ).mappings().all()
        if any(active_participation(dict(p)) for p in participations):
            return True
    return False


def event_permissions(conn, user, event_id: str) -> frozenset[str]:
    """Return only admission permissions for this event and current shift."""
    event = get_site(conn, event_id)
    if event['kind'] != 'event':
        fail('EVENT_REQUIRED', 422)
    if not user or not user.get('active', 1):
        return frozenset()
    if user['role'] == 'platform' or (user['role'] == 'organizer' and user.get('scope_id') == event_id):
        return EVENT_PERMISSIONS
    grants = set()
    for assignment in conn.execute(select(assignments).where(
        assignments.c.user_id == user['id'], assignments.c.site_id == event_id,
    )).mappings():
        if active_window(dict(assignment)):
            grants.update(EVENT_ROLE_PERMISSIONS.get(assignment['role'], ()))
    return frozenset(grants)


def require_event_permission(conn, user, event_id: str, action: str):
    """Authorize one action, failing closed for unknown permission names."""
    if action not in EVENT_PERMISSIONS or action not in event_permissions(conn, user, event_id):
        fail('FORBIDDEN_EVENT_PERMISSION', 403)
    return get_site(conn, event_id)


def require_scope(conn, user, site_id: str):
    site = get_site(conn, site_id)
    if not can_manage(conn, user, site):
        fail('FORBIDDEN_SCOPE', 403)
    return site


def can_read(conn, user, site) -> bool:
    """Read-only analytics access never flows back into can_manage."""
    if can_manage(conn, user, site):
        return True
    if not user or not user.get('active', 1):
        return False
    for assignment in conn.execute(select(assignments).where(
        assignments.c.user_id == user['id'], assignments.c.site_id == site['id'],
        assignments.c.role.in_(('analyst', 'auditor')),
    )).mappings():
        if active_window(dict(assignment)):
            return True
    org_ids = conn.execute(select(memberships.c.organization_id).where(
        memberships.c.user_id == user['id'], memberships.c.status == 'active',
        memberships.c.role == 'analyst',
    )).scalars().all()
    if not org_ids:
        return False
    return bool(conn.execute(select(event_participations.c.id).where(
        event_participations.c.organization_id.in_(org_ids),
        event_participations.c.agency_site_id == site['id'],
        event_participations.c.status == 'active',
    )).first())


def require_read_scope(conn, user, site_id: str):
    site = get_site(conn, site_id)
    if not can_read(conn, user, site):
        fail('FORBIDDEN_SCOPE', 403)
    return site


def organization_visible(conn, user, organization_id: str) -> bool:
    if user['role']=='platform':
        return True
    if conn.execute(select(memberships).where(memberships.c.user_id==user['id'],memberships.c.organization_id==organization_id,memberships.c.status=='active')).first():
        return True
    if user['role']=='organizer':
        return bool(conn.execute(select(event_participations).where(event_participations.c.organization_id==organization_id,event_participations.c.event_id==user['scope_id'])).first())
    return False
