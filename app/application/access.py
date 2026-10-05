from __future__ import annotations

from sqlalchemy import select

from app.db import assignments, event_participations, memberships
from app.domain import fail, now
from app.infrastructure.repository import get_site


def active_window(record: dict) -> bool:
    """Time-bounded assignment check.

    Assignments may intentionally expire. Participation access is different:
    an ended event must remain administrable for reporting, export and archive
    work; only an explicit participation status change revokes that access.
    """
    current = now()
    return (
        record.get('status', 'active') == 'active'
        and (not record.get('valid_from') or record['valid_from'] <= current)
        and (not record.get('valid_until') or record['valid_until'] > current)
    )


def active_participation(record: dict) -> bool:
    return record.get('status', 'active') == 'active'


def can_manage(conn, user, site) -> bool:
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
        if any(active_participation(dict(p)) for p in linked):
            return True
        return False

    user_assignments = conn.execute(
        select(assignments).where(
            assignments.c.user_id == user['id'],
            assignments.c.site_id == site['id'],
        )
    ).mappings().all()
    if any(active_window(dict(a)) for a in user_assignments):
        return True

    organization_ids = [
        m['organization_id']
        for m in conn.execute(
            select(memberships).where(
                memberships.c.user_id == user['id'],
                memberships.c.status == 'active',
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


def require_scope(conn, user, site_id: str):
    site = get_site(conn, site_id)
    if not can_manage(conn, user, site):
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
