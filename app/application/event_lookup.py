"""Event lookups shared by the guest, invitation and gate use cases."""
from __future__ import annotations

from app.application.ports import persistence
from app.domain import NotFound, fail


def event_by_id_or_slug(tx, event_id: str | None = None, slug: str | None = None) -> dict:
    event = persistence.sites.get(tx, event_id) if event_id else persistence.sites.event_by_slug(tx, slug)
    if not event or event['kind'] != 'event':
        fail('EVENT_NOT_FOUND', NotFound)
    return event


def published_event(tx, event: dict) -> dict:
    """The event as the public sees it: its draft replaced by the published config."""
    if not event['published_version']:
        fail('EVENT_NOT_PUBLISHED', NotFound)
    version = persistence.sites.get_version(tx, event['id'], event['published_version'])
    if version is None:
        fail('EVENT_NOT_PUBLISHED', NotFound)
    return {**event, 'draft': version['config']}
