"""Certificate library authority is independent from event-specific issuance."""
from sqlalchemy import select
from fastapi import HTTPException
from app.db import users, sites, memberships, organizations, event_participations, assignments
from app.application.access import active_window
from app.domain import fail

CAPABILITIES = frozenset({'models.manage', 'links.manage', 'requests.read', 'requests.export'})
MANAGER_ROLES = ('owner', 'admin')

def live_principal(conn, user):
    principal = conn.execute(select(users).where(users.c.id == (user or {}).get('id'))).mappings().first()
    if not principal or not principal['active']:
        fail('LOGIN_REQUIRED', 401)
    if principal['must_change_password']:
        fail('PASSWORD_CHANGE_REQUIRED', 428)
    return dict(principal)

def _organization_management(user_id):
    return select(memberships.c.organization_id).select_from(
        memberships.join(organizations, organizations.c.id == memberships.c.organization_id)
    ).where(memberships.c.user_id == user_id, memberships.c.status == 'active',
            memberships.c.role.in_(MANAGER_ROLES), organizations.c.status == 'active')

def _manager_assignments(conn, user_id, event_id=None):
    query = select(assignments).join(sites, sites.c.id == assignments.c.site_id).where(
        assignments.c.user_id == user_id, assignments.c.role == 'event_manager', sites.c.kind == 'event')
    if event_id is not None:
        query = query.where(assignments.c.site_id == event_id)
    return [dict(a) for a in conn.execute(query).mappings() if active_window(dict(a))]

def can_manage_library(conn, user):
    principal = live_principal(conn, user)
    return bool(principal['role'] in ('platform', 'organizer')
        or conn.execute(_organization_management(principal['id']).limit(1)).first()
        or _manager_assignments(conn, principal['id']))

def require_library(conn, user):
    principal = live_principal(conn, user)
    if not can_manage_library(conn, principal):
        fail('FORBIDDEN', 403)
    return principal

def eligible_events(conn, user):
    principal = live_principal(conn, user)
    query = select(sites).where(sites.c.kind == 'event')
    if principal['role'] == 'platform':
        return [dict(e) for e in conn.execute(query).mappings()]
    event_ids = {principal['scope_id']} if principal['role'] == 'organizer' else set()
    event_ids.update(a['site_id'] for a in _manager_assignments(conn, principal['id']))
    event_ids.update(conn.execute(select(event_participations.c.event_id).where(
        event_participations.c.organization_id.in_(_organization_management(principal['id'])),
        event_participations.c.status == 'active')).scalars())
    if not event_ids:
        return []
    return [dict(e) for e in conn.execute(query.where(sites.c.id.in_(event_ids))).mappings()]

def require_capability(conn, user, capability):
    principal = live_principal(conn, user)
    if capability not in CAPABILITIES:
        fail('FORBIDDEN', 403)
    if capability in ('models.manage', 'links.manage'):
        require_library(conn, principal)
    # Historical own-account reads remain possible after an event grant is removed.
    return principal

def require_event(conn, user, event_id):
    """Check this event directly; no scan of the full event library on public POST."""
    principal = live_principal(conn, user)
    event = conn.execute(select(sites).where(sites.c.id == event_id, sites.c.kind == 'event')).mappings().first()
    if not event:
        fail('FORBIDDEN', 403)
    if principal['role'] == 'platform' or (principal['role'] == 'organizer' and principal['scope_id'] == event_id):
        return dict(event)
    if _manager_assignments(conn, principal['id'], event_id):
        return dict(event)
    if conn.execute(select(event_participations.c.id).where(
        event_participations.c.event_id == event_id,
        event_participations.c.status == 'active',
        event_participations.c.organization_id.in_(_organization_management(principal['id']))
    ).limit(1)).first():
        return dict(event)
    fail('FORBIDDEN', 403)

def require_owner(conn, user, owner_account_id):
    principal = live_principal(conn, user)
    if principal['id'] != owner_account_id:
        fail('NOT_FOUND', 404)
    return principal

def owner_can_accept(conn, owner_id, event_id):
    try:
        require_event(conn, {'id': owner_id}, event_id)
        return True
    except HTTPException as exc:
        if exc.status_code in (401, 403, 428):
            return False
        raise
