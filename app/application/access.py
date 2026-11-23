"""Authorization use cases: site management/read scope and event capabilities.

The role/capability rules live in app.domain.authorization; this module loads
the facts (assignments, memberships, participations) and applies them.
"""
from __future__ import annotations

from app.application.audit_service import AuditedDenial
from app.application.ports import persistence
from app.domain import Forbidden, now
from app.domain import authorization
from app.domain.authorization import (
    EVENT_PERMISSIONS,
    EVENT_ROLE_PERMISSIONS,
    ORGANIZATION_MANAGEMENT_ROLES,
    SITE_MANAGEMENT_ROLES,
    active_participation,
    event_capabilities,
    has_full_event_authority,
    is_active_user,
)
from app.domain.guards import require_found

__all__ = [
    'EVENT_PERMISSIONS', 'EVENT_ROLE_PERMISSIONS', 'ORGANIZATION_MANAGEMENT_ROLES', 'SITE_MANAGEMENT_ROLES',
    'active_participation', 'active_window', 'can_manage', 'can_read', 'event_permissions', 'get_site',
    'organization_visible', 'require_event_permission', 'require_read_scope', 'require_scope',
]


def active_window(record: dict) -> bool:
    """Assignment/shift window check against this module's clock (``now``)."""
    return authorization.active_window(record, now())


class _SiteFacts:
    """Reads the facts about one user and one site through the access port, on demand."""

    def __init__(self, tx, user, site):
        self.tx, self.user, self.site = tx, user, site

    def participations_for_agency_site(self):
        return persistence.access.participations_for_agency_site(self.tx, self.site['id'])

    def memberships_in(self, organization_ids):
        return persistence.access.memberships_in(self.tx, self.user['id'], organization_ids)

    def assignments(self, roles=None):
        if roles is None:
            return persistence.access.assignments(self.tx, self.user['id'], self.site['id'])
        return persistence.access.assignments(self.tx, self.user['id'], self.site['id'], roles=roles)

    def active_membership_org_ids(self, roles):
        return persistence.access.active_membership_org_ids(self.tx, self.user['id'], roles)

    def participations_of(self, organization_ids, active_only=False):
        if active_only:
            return persistence.access.participations_of(self.tx, organization_ids, self.site['id'], active_only=True)
        return persistence.access.participations_of(self.tx, organization_ids, self.site['id'])


def get_site(tx, site_id: str) -> dict:
    return require_found(persistence.sites.get(tx, site_id), 'SITE_NOT_FOUND')


def can_manage(tx, user, site) -> bool:
    return authorization.can_manage_site(user, site, _SiteFacts(tx, user, site), now())


def event_permissions(tx, user, event_id: str) -> frozenset[str]:
    """Return event capabilities for this scope and current shift."""
    authorization.require_event_kind(get_site(tx, event_id))
    if not is_active_user(user):
        return frozenset()
    if has_full_event_authority(user, event_id):
        return EVENT_PERMISSIONS
    return event_capabilities(user, event_id, persistence.access.assignments(tx, user['id'], event_id), now())


def require_event_permission(tx, user, event_id: str, action: str):
    """Authorize one action, failing closed for unknown permission names."""
    if not authorization.is_known_event_permission(action):
        raise AuditedDenial(authorization.EVENT_PERMISSION_DENIED, Forbidden, action='scope_denied', user=user)
    if action not in event_permissions(tx, user, event_id):
        raise AuditedDenial(authorization.EVENT_PERMISSION_DENIED, Forbidden, action='scope_denied', user=user,
                            site_id=event_id)
    return get_site(tx, event_id)


def require_scope(tx, user, site_id: str):
    site = get_site(tx, site_id)
    if not can_manage(tx, user, site):
        raise AuditedDenial('FORBIDDEN_SCOPE', Forbidden, action='scope_denied', user=user, site_id=site['id'])
    return site


def can_read(tx, user, site) -> bool:
    """Read-only analytics access never flows back into can_manage."""
    return authorization.can_read_site(user, site, _SiteFacts(tx, user, site), now())


def require_read_scope(tx, user, site_id: str):
    site = get_site(tx, site_id)
    if not can_read(tx, user, site):
        raise AuditedDenial('FORBIDDEN_SCOPE', Forbidden, action='scope_denied', user=user, site_id=site['id'])
    return site


def organization_visible(tx, user, organization_id: str) -> bool:
    return authorization.organization_visible(
        user['role'],
        user['role'] != 'platform' and persistence.access.has_active_membership(tx, user['id'], organization_id),
        user['role'] == 'organizer'
        and persistence.access.organization_in_event(tx, organization_id, user['scope_id']))
