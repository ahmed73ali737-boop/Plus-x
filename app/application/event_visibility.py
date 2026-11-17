"""Public visibility checks shared by site, results and registration routes.

An unlisted event permits possession-of-link reads but never discovery. Private
event reads require a separately validated invitation; this module never treats
a guessed event ID, a phone number, or a login cookie as an invitation.
"""
from __future__ import annotations

from app.application.ports import persistence
from app.domain import NotFound, fail
from app.domain.sites import visibility_from_policy


def event_id_for_site(tx, site_or_id):
    if isinstance(site_or_id, str):
        site = persistence.sites.get(tx, site_or_id)
        if not site:
            fail('SITE_NOT_FOUND', NotFound)
    else:
        site = site_or_id
    if site['kind'] == 'event':
        return site['id']
    return site.get('event_id')


def get_visibility(tx, event_id: str | None) -> str:
    if not event_id:
        return 'public'
    return visibility_from_policy(persistence.admission.policy_config(tx, event_id))


def is_public_event(tx, event_id: str | None) -> bool:
    """True only for discoverable events; unlisted must not enter a listing."""
    return get_visibility(tx, event_id) == 'public'


def require_public_event(tx, event_id: str | None):
    """Allow public/unlisted direct access; conceal private event existence."""
    if get_visibility(tx, event_id) == 'private':
        fail('SITE_NOT_FOUND', NotFound)
    return event_id
