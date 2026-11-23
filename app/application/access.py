"""Authorization use cases: site management/read scope and event capabilities.

The role/capability rules live in app.domain.authorization; this module loads
the facts (assignments, memberships, participations) and applies them.
"""
from __future__ import annotations

from app.application.audit_service import AuditedDenial
from app.application.ports import persistence
from app.domain import Forbidden, NotFound, fail, now
from app.domain import authorization
from app.domain.authorization import (
    EVENT_PERMISSIONS,
    EVENT_ROLE_PERMISSIONS,
    ORGANIZATION_MANAGEMENT_ROLES,
    SITE_MANAGEMENT_ROLES,
    active_participation,
    direct_agency_access,
    event_capabilities,
    has_full_event_authority,
    is_active_user,
    manages_by_assignment,
    manages_by_role,
    reads_by_assignment,
)

__all__ = [
    'EVENT_PERMISSIONS', 'EVENT_ROLE_PERMISSIONS', 'ORGANIZATION_MANAGEMENT_ROLES', 'SITE_MANAGEMENT_ROLES',
    'active_participation', 'active_window', 'can_manage', 'can_read', 'event_permissions', 'get_site',
    'organization_visible', 'require_event_permission', 'require_read_scope', 'require_scope',
]


def active_window(record: dict) -> bool:
    """Assignment/shift window check against this module's clock (``now``)."""
    return authorization.active_window(record, now())


def get_site(tx, site_id: str) -> dict:
    site = persistence.sites.get(tx, site_id)
    if not site:
        fail('SITE_NOT_FOUND', NotFound)
    return site


def can_manage(tx, user, site) -> bool:
    if not is_active_user(user):
        return False
    if manages_by_role(user, site):
        return True
    access = persistence.access
    if user['role'] == 'agency' and user['scope_id'] == site['id']:
        linked = access.participations_for_agency_site(tx, site['id'])
        related = access.memberships_in(tx, user['id'], [p['organization_id'] for p in linked]) if linked else []
        return direct_agency_access(user['id'], linked, related)
    if manages_by_assignment(access.assignments(tx, user['id'], site['id']), now()):
        return True
    organization_ids = access.active_membership_org_ids(tx, user['id'], ORGANIZATION_MANAGEMENT_ROLES)
    if organization_ids:
        participations = access.participations_of(tx, organization_ids, site['id'])
        if any(active_participation(p) for p in participations):
            return True
    return False


def event_permissions(tx, user, event_id: str) -> frozenset[str]:
    """Return event capabilities for this scope and current shift."""
    event = get_site(tx, event_id)
    if event['kind'] != 'event':
        fail('EVENT_REQUIRED')
    if not is_active_user(user):
        return frozenset()
    if has_full_event_authority(user, event_id):
        return EVENT_PERMISSIONS
    return event_capabilities(user, event_id, persistence.access.assignments(tx, user['id'], event_id), now())


def require_event_permission(tx, user, event_id: str, action: str):
    """Authorize one action, failing closed for unknown permission names."""
    if action not in EVENT_PERMISSIONS:
        raise AuditedDenial('FORBIDDEN_EVENT_PERMISSION', Forbidden, action='scope_denied', user=user)
    if action not in event_permissions(tx, user, event_id):
        raise AuditedDenial('FORBIDDEN_EVENT_PERMISSION', Forbidden, action='scope_denied', user=user, site_id=event_id)
    return get_site(tx, event_id)


def require_scope(tx, user, site_id: str):
    site = get_site(tx, site_id)
    if not can_manage(tx, user, site):
        raise AuditedDenial('FORBIDDEN_SCOPE', Forbidden, action='scope_denied', user=user, site_id=site['id'])
    return site


def can_read(tx, user, site) -> bool:
    """Read-only analytics access never flows back into can_manage."""
    if can_manage(tx, user, site):
        return True
    if not is_active_user(user):
        return False
    access = persistence.access
    if reads_by_assignment(access.assignments(tx, user['id'], site['id'], roles=('analyst', 'auditor')), now()):
        return True
    organization_ids = access.active_membership_org_ids(tx, user['id'], ('analyst',))
    if not organization_ids:
        return False
    return bool(access.participations_of(tx, organization_ids, site['id'], active_only=True))


def require_read_scope(tx, user, site_id: str):
    site = get_site(tx, site_id)
    if not can_read(tx, user, site):
        raise AuditedDenial('FORBIDDEN_SCOPE', Forbidden, action='scope_denied', user=user, site_id=site['id'])
    return site


def organization_visible(tx, user, organization_id: str) -> bool:
    if user['role'] == 'platform':
        return True
    if persistence.access.has_active_membership(tx, user['id'], organization_id):
        return True
    if user['role'] == 'organizer':
        return persistence.access.organization_in_event(tx, organization_id, user['scope_id'])
    return False
