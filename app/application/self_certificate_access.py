"""Certificate library authority is independent from event-specific issuance.

The authority rules live in app.domain.authorization; this module loads the facts
(account, assignments, participations) through the self-certificate port.
"""
from app.application.access import active_window
from app.application.ports import persistence
from app.domain import Forbidden, PreconditionRequired, Unauthenticated, authorization
from app.domain.guards import require_found


def _store():
    return persistence.self_certificates


def live_principal(tx, user):
    return authorization.require_live_principal(_store().user(tx, (user or {}).get('id')))


def _manager_assignments(tx, user_id, event_id=None):
    return [row for row in _store().event_manager_assignments(tx, user_id, event_id) if active_window(row)]


def can_manage_library(tx, user):
    principal = live_principal(tx, user)
    role = principal['role']
    if role in ('platform', 'organizer'):
        return True
    return authorization.can_manage_library(
        role, _store().manages_an_organization(tx, principal['id']),
        bool(_manager_assignments(tx, principal['id'])))


def require_library(tx, user):
    principal = live_principal(tx, user)
    authorization.require_library_authority(can_manage_library(tx, principal))
    return principal


def eligible_events(tx, user):
    principal = live_principal(tx, user)
    if principal['role'] == 'platform':
        return _store().events(tx)
    event_ids = authorization.eligible_event_ids(
        principal['role'], principal['scope_id'],
        (row['site_id'] for row in _manager_assignments(tx, principal['id'])),
        _store().managed_participation_event_ids(tx, principal['id']))
    if not event_ids:
        return []
    return _store().events(tx, event_ids)


def require_capability(tx, user, capability):
    principal = live_principal(tx, user)
    if authorization.require_library_capability(capability):
        require_library(tx, principal)
    # Historical own-account reads remain possible after an event grant is removed.
    return principal


def require_event(tx, user, event_id):
    """Check this event directly; no scan of the full event library on public POST."""
    principal = live_principal(tx, user)
    event = require_found(_store().event(tx, event_id), 'FORBIDDEN', Forbidden)
    if authorization.has_direct_event_authority(principal['role'], principal['scope_id'], event_id):
        return event
    if _manager_assignments(tx, principal['id'], event_id):
        return event
    authorization.require_event_authority(_store().manages_event_participation(tx, principal['id'], event_id))
    return event


def require_owner(tx, user, owner_account_id):
    principal = live_principal(tx, user)
    authorization.require_owner_account(principal['id'], owner_account_id)
    return principal


def owner_can_accept(tx, owner_id, event_id):
    try:
        require_event(tx, {'id': owner_id}, event_id)
        return True
    except (Unauthenticated, Forbidden, PreconditionRequired):
        return False


def has_history(tx, owner_id=None):
    """Any link/certificate exists (system-wide), or any request/link of one owner."""
    return _store().has_history(tx, owner_id)


def owner_has_links(tx, owner_id):
    return _store().owner_has_links(tx, owner_id)
