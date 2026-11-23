"""Event lookups shared by the guest, invitation and gate use cases."""
from __future__ import annotations

from app.application.ports import persistence
from app.domain.sites import require_event_record, require_published_event


def event_by_id_or_slug(tx, event_id: str | None = None, slug: str | None = None) -> dict:
    event = persistence.sites.get(tx, event_id) if event_id else persistence.sites.event_by_slug(tx, slug)
    return require_event_record(event)


def published_event(tx, event: dict) -> dict:
    """The event as the public sees it: its draft replaced by the published config."""
    version = persistence.sites.get_version(tx, event['id'], event['published_version']) if event['published_version'] else None
    return {**event, 'draft': require_published_event(event, version)['config']}
