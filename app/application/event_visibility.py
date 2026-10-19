"""Public visibility checks shared by site, results and registration routes.

An unlisted event permits possession-of-link reads but never discovery. Private
event reads require a separately validated invitation; this module never treats
a guessed event ID, a phone number, or a login cookie as an invitation.
"""
from __future__ import annotations

from sqlalchemy import select

from app.domain import fail
from app.infrastructure.repository import get_site


def event_id_for_site(conn, site_or_id):
    site = get_site(conn, site_or_id) if isinstance(site_or_id, str) else site_or_id
    if site['kind'] == 'event':
        return site['id']
    return site.get('event_id')


def get_visibility(conn, event_id: str | None) -> str:
    if not event_id:
        return 'public'
    # Lazy import keeps the admission schema independent of its application
    # service and prevents a public_service <-> invitation_service cycle.
    from app.invitations_db import admission_policies
    config = conn.execute(select(admission_policies.c.config).where(
        admission_policies.c.event_id == event_id,
    )).scalar_one_or_none()
    if config is None:
        return 'public'  # Existing events keep their explicit legacy behavior.
    visibility = config.get('visibility', 'public') if isinstance(config, dict) else 'private'
    return visibility if visibility in ('public', 'unlisted', 'private') else 'private'


def is_public_event(conn, event_id: str | None) -> bool:
    """True only for discoverable events; unlisted must not enter a listing."""
    return get_visibility(conn, event_id) == 'public'


def require_public_event(conn, event_id: str | None):
    """Allow public/unlisted direct access; conceal private event existence."""
    if get_visibility(conn, event_id) == 'private':
        fail('SITE_NOT_FOUND', 404)
    return event_id
