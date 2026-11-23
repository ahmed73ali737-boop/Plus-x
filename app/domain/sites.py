"""EventSite aggregate: the platform, events and agency (exhibitor) pages.

A site owns a draft configuration (``draft`` + optimistic ``draft_rev``) and an
append-only list of published versions (``published_version``). Publishing
snapshots a normalized copy of the draft.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import Conflict, Forbidden, NotFound, fail
from app.domain.guards import reject_existing, require_found
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


def require_platform_or_organizer(user: dict) -> None:
    """Directory-wide administration (signup queue, organization creation) is staff-only."""
    if user['role'] not in ('platform', 'organizer'):
        fail('FORBIDDEN_ROLE', Forbidden)


def require_not_agency(user: dict, site: dict | None = None) -> None:
    """Exhibitor staff never manage site users; nobody manages users of the platform site."""
    if user['role'] == 'agency' or (site is not None and site['kind'] == 'platform'):
        fail('FORBIDDEN_ROLE', Forbidden)


def require_event_site(site: dict) -> None:
    if site['kind'] != 'event':
        fail('EVENT_REQUIRED')


class ContentImport:
    """A previewed content import commits once, to the revision it was previewed against."""

    @staticmethod
    def require_owned(job: dict | None, site_id: str, user_id: str) -> dict:
        if not job or job['site_id'] != site_id or job['user_id'] != user_id:
            fail('IMPORT_NOT_FOUND', NotFound)
        return job

    @staticmethod
    def require_committable(job: dict, draft_rev: int) -> None:
        """Call only for a job that is not already committed (that case replays idempotently)."""
        if job['errors']:
            fail('IMPORT_HAS_ERRORS')
        if job['base_rev'] != draft_rev:
            fail('DRAFT_CHANGED_REPREVIEW_REQUIRED', Conflict)

    @staticmethod
    def stale_draft() -> None:
        fail('DRAFT_CHANGED_REPREVIEW_REQUIRED', Conflict)


def require_requestable_target(site: dict) -> None:
    """Account access is requested for an event or an agency page, never for the platform site."""
    if site['kind'] == 'platform':
        fail('EVENT_REQUIRED')


def requested_role_for(site: dict) -> str:
    """Access to an event is granted as organizer, to an agency page as agency staff."""
    return 'organizer' if site['kind'] == 'event' else 'agency'


def require_workflow_request(linked_request_id: str | None) -> str:
    """Legacy requests that never entered the reviewed workflow must be resubmitted."""
    if not linked_request_id:
        fail('LEGACY_REQUEST_REQUIRES_RESUBMISSION', Conflict)
    return linked_request_id


def require_request_in_scope(request_scope_id: str | None, site_id: str) -> None:
    """A site manager may review only requests aimed at that site; others are concealed."""
    if request_scope_id != site_id:
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)


def require_free_slug(existing_site: dict | None) -> None:
    reject_existing(existing_site, 'SLUG_EXISTS')


def require_site(site: dict | None) -> dict:
    return require_found(site, 'SITE_NOT_FOUND')


def require_draft_saved(saved: bool) -> None:
    """The guarded save touched no row: another editor moved the draft first."""
    if not saved:
        fail('DRAFT_CHANGED_REFRESH_REQUIRED', Conflict)
