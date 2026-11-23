"""Roles, event capabilities and time-bounded assignments.

Admission authority is separate from editing a site: a scanner never gains
access to publishing, account administration or guest exports.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.errors import Forbidden, NotFound, PreconditionRequired, Unauthenticated, fail
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


# Site management and read scope ----------------------------------------------------------

class SiteAccessFacts(Protocol):
    """Facts a decision may need; each call is a read, so they are asked for lazily and in order."""

    def participations_for_agency_site(self) -> list[dict]: ...

    def memberships_in(self, organization_ids: list[str]) -> list[dict]: ...

    def assignments(self, roles: tuple[str, ...] | None = None) -> list[dict]: ...

    def active_membership_org_ids(self, roles) -> list[str]: ...

    def participations_of(self, organization_ids: list[str], active_only: bool = False) -> list[dict]: ...


def can_manage_site(user: dict, site: dict, facts: SiteAccessFacts, at: str | None = None) -> bool:
    """Editing authority over one site: role, own agency page, shift assignment, organization membership."""
    if not is_active_user(user):
        return False
    if manages_by_role(user, site):
        return True
    if user['role'] == 'agency' and user['scope_id'] == site['id']:
        linked = facts.participations_for_agency_site()
        related = facts.memberships_in([p['organization_id'] for p in linked]) if linked else []
        return direct_agency_access(user['id'], linked, related)
    if manages_by_assignment(facts.assignments(), at):
        return True
    organization_ids = facts.active_membership_org_ids(ORGANIZATION_MANAGEMENT_ROLES)
    if organization_ids:
        return any(active_participation(p) for p in facts.participations_of(organization_ids))
    return False


def can_read_site(user: dict, site: dict, facts: SiteAccessFacts, at: str | None = None) -> bool:
    """Read-only analytics access; it is a superset of management and never flows back into it."""
    if can_manage_site(user, site, facts, at):
        return True
    if not is_active_user(user):
        return False
    if reads_by_assignment(facts.assignments(READ_ONLY_ASSIGNMENT_ROLES), at):
        return True
    organization_ids = facts.active_membership_org_ids(('analyst',))
    return bool(organization_ids) and bool(facts.participations_of(organization_ids, active_only=True))


def organization_visible(role: str, is_member: bool, organizer_event_includes_it: bool) -> bool:
    """Platform sees all; others need a membership; an organizer also sees organizations in its event."""
    if role == 'platform':
        return True
    if is_member:
        return True
    return role == 'organizer' and organizer_event_includes_it


def require_event_kind(site: dict) -> None:
    """Event capabilities exist only on event sites."""
    if site['kind'] != 'event':
        fail('EVENT_REQUIRED')


def is_known_event_permission(action: str) -> bool:
    """Unknown permission names are never granted (callers fail closed)."""
    return action in EVENT_PERMISSIONS


EVENT_PERMISSION_DENIED = 'FORBIDDEN_EVENT_PERMISSION'


# Certificate library authority (independent of event-specific issuance) ----------------------

LIBRARY_CAPABILITIES = frozenset({'models.manage', 'links.manage', 'requests.read', 'requests.export'})
LIBRARY_MANAGEMENT_CAPABILITIES = frozenset({'models.manage', 'links.manage'})


def require_live_principal(principal: dict | None) -> dict:
    """A stored, active account whose forced password change is done."""
    if not principal or not principal['active']:
        fail('LOGIN_REQUIRED', Unauthenticated)
    if principal['must_change_password']:
        fail('PASSWORD_CHANGE_REQUIRED', PreconditionRequired)
    return principal


def can_manage_library(role: str, manages_organization: bool, has_manager_assignment: bool) -> bool:
    return role in ('platform', 'organizer') or manages_organization or has_manager_assignment


def require_library_authority(allowed: bool) -> None:
    if not allowed:
        fail('FORBIDDEN', Forbidden)


def require_event_authority(allowed: bool) -> None:
    """Issuing for an event needs direct, shift or managed-participation authority."""
    if not allowed:
        fail('FORBIDDEN', Forbidden)


def require_library_capability(capability: str) -> bool:
    """Reject unknown capabilities; True when the capability needs library authority.

    Own-account reads (requests.read/export) stay possible after an event grant is removed.
    """
    if capability not in LIBRARY_CAPABILITIES:
        fail('FORBIDDEN', Forbidden)
    return capability in LIBRARY_MANAGEMENT_CAPABILITIES


def eligible_event_ids(role: str, scope_id: str | None, assignment_event_ids, participation_event_ids) -> set[str]:
    """Events the account may issue for (platform is handled by the caller: it sees every event)."""
    ids = {scope_id} if role == 'organizer' else set()
    ids.update(assignment_event_ids)
    ids.update(participation_event_ids)
    return ids


def has_direct_event_authority(role: str, scope_id: str | None, event_id: str) -> bool:
    return role == 'platform' or (role == 'organizer' and scope_id == event_id)


def require_owner_account(principal_id: str, owner_account_id: str) -> None:
    """Owner-only objects are concealed from everyone else."""
    if principal_id != owner_account_id:
        fail('NOT_FOUND', NotFound)
