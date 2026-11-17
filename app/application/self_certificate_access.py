"""Certificate library authority is independent from event-specific issuance."""
from app.application.access import active_window
from app.application.ports import persistence
from app.domain import Forbidden, NotFound, PreconditionRequired, Unauthenticated, fail

CAPABILITIES = frozenset({'models.manage', 'links.manage', 'requests.read', 'requests.export'})


def _store():
    return persistence.self_certificates


def live_principal(tx, user):
    principal = _store().user(tx, (user or {}).get('id'))
    if not principal or not principal['active']:
        fail('LOGIN_REQUIRED', Unauthenticated)
    if principal['must_change_password']:
        fail('PASSWORD_CHANGE_REQUIRED', PreconditionRequired)
    return principal


def _manager_assignments(tx, user_id, event_id=None):
    return [row for row in _store().event_manager_assignments(tx, user_id, event_id) if active_window(row)]


def can_manage_library(tx, user):
    principal = live_principal(tx, user)
    return bool(principal['role'] in ('platform', 'organizer')
                or _store().manages_an_organization(tx, principal['id'])
                or _manager_assignments(tx, principal['id']))


def require_library(tx, user):
    principal = live_principal(tx, user)
    if not can_manage_library(tx, principal):
        fail('FORBIDDEN', Forbidden)
    return principal


def eligible_events(tx, user):
    principal = live_principal(tx, user)
    if principal['role'] == 'platform':
        return _store().events(tx)
    event_ids = {principal['scope_id']} if principal['role'] == 'organizer' else set()
    event_ids.update(row['site_id'] for row in _manager_assignments(tx, principal['id']))
    event_ids.update(_store().managed_participation_event_ids(tx, principal['id']))
    if not event_ids:
        return []
    return _store().events(tx, event_ids)


def require_capability(tx, user, capability):
    principal = live_principal(tx, user)
    if capability not in CAPABILITIES:
        fail('FORBIDDEN', Forbidden)
    if capability in ('models.manage', 'links.manage'):
        require_library(tx, principal)
    # Historical own-account reads remain possible after an event grant is removed.
    return principal


def require_event(tx, user, event_id):
    """Check this event directly; no scan of the full event library on public POST."""
    principal = live_principal(tx, user)
    event = _store().event(tx, event_id)
    if not event:
        fail('FORBIDDEN', Forbidden)
    if principal['role'] == 'platform' or (principal['role'] == 'organizer' and principal['scope_id'] == event_id):
        return event
    if _manager_assignments(tx, principal['id'], event_id):
        return event
    if _store().manages_event_participation(tx, principal['id'], event_id):
        return event
    fail('FORBIDDEN', Forbidden)


def require_owner(tx, user, owner_account_id):
    principal = live_principal(tx, user)
    if principal['id'] != owner_account_id:
        fail('NOT_FOUND', NotFound)
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
