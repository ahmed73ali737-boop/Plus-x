"""EventSite aggregate: the platform, events and agency (exhibitor) pages.

A site owns a draft configuration (``draft`` + optimistic ``draft_rev``) and an
append-only list of published versions (``published_version``). Publishing
snapshots a normalized copy of the draft.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import Conflict, Forbidden, fail
from app.domain.site_config import default_config, normalize_config
from app.domain.values import slug, text

VISIBILITIES = ('public', 'unlisted', 'private')
SLUG_MAX = 70


def visibility_from_policy(config) -> str:
    """Visibility of an event from its admission policy config (None: legacy public)."""
    if config is None:
        return 'public'  # Existing events keep their explicit legacy behavior.
    visibility = config.get('visibility', 'public') if isinstance(config, dict) else 'private'
    return visibility if visibility in VISIBILITIES else 'private'


def require_draft_revision(site: dict, revision) -> int:
    """Only the holder of the current draft revision may save or publish it."""
    if not isinstance(revision, int) or revision != site['draft_rev']:
        fail('DRAFT_CHANGED_REFRESH_REQUIRED', Conflict)
    return revision


def require_publish_revision(site: dict, revision) -> None:
    if revision != site['draft_rev']:
        fail('DRAFT_CHANGED_REFRESH_REQUIRED', Conflict)


@dataclass(frozen=True)
class Publication:
    site_id: str
    version: int
    config: dict


def publish(site: dict) -> Publication:
    """Snapshot the normalized draft as the next published version."""
    return Publication(site_id=site['id'], version=site['published_version'] + 1,
                       config=normalize_config(site['draft']))


def authorize_new_site(user_role: str, parent: dict, kind) -> str:
    """Only the platform creates events; platform or organizers create agency pages."""
    if kind == 'event' and (user_role != 'platform' or parent['kind'] != 'platform'):
        fail('FORBIDDEN_ROLE', Forbidden)
    if kind == 'agency' and (user_role not in ('platform', 'organizer') or parent['kind'] != 'event'):
        fail('FORBIDDEN_ROLE', Forbidden)
    if kind not in ('agency', 'event'):
        fail('SITE_KIND')
    return kind


def new_site(site_id: str, parent: dict, kind: str, site_slug: str, draft: dict) -> dict:
    return {
        'id': site_id, 'parent_id': parent['id'], 'event_id': site_id if kind == 'event' else parent['id'],
        'kind': kind, 'slug': site_slug, 'draft': draft, 'draft_rev': 1, 'published_version': 0,
    }


def new_site_draft(body: dict, kind: str) -> dict:
    return default_config(text(body.get('title'), 160, True), kind)


def site_slug(value) -> str:
    return slug(value)


def agency_slug(organization_slug: str, event_slug: str) -> str:
    return (organization_slug + '-' + event_slug)[:SLUG_MAX]


def fallback_agency_slug(organization_slug: str, random_hex: str) -> str:
    return (organization_slug + '-' + random_hex)[:SLUG_MAX]


def agency_draft(organization: dict, *, normalized: bool) -> dict:
    """Initial agency page for an organization joining an event."""
    profile = organization['profile']
    draft = default_config(organization['name'], 'agency')
    draft['description'] = profile.get('description', '')
    if normalized:
        draft['logo'] = profile.get('logo', '')
        draft['primary'] = profile.get('primary', '#176B73')
        return normalize_config(draft)
    return draft


def public_path(site: dict, event_slug: str | None) -> str:
    """Path of the public page of a site (QR codes link here)."""
    if site['kind'] == 'platform':
        return '/'
    if site['kind'] == 'event':
        return '/e/' + site['slug']
    return '/e/' + event_slug + '/p/' + site['slug']


def event_status(config: dict, current) -> str:
    """upcoming / current / completed from a published event's start and end."""
    start = datetime.fromisoformat(config['start']) if config.get('start') else None
    end = datetime.fromisoformat(config['end']) if config.get('end') else None
    if start and current < start:
        return 'upcoming'
    if end and current >= end:
        return 'completed'
    return 'current'
