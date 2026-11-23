"""Publish a site's draft as an immutable version; read published versions."""
from __future__ import annotations

from app.application.audit_service import write_audit
from app.application.ports import persistence
from app.domain import Conflict, NotFound, fail, now
from app.domain.sites import publish


def publish_site_version(tx, site, user) -> int:
    publication = publish(site)
    # Optimistic concurrency: the draft revision and version must be unchanged.
    if not persistence.sites.advance_published_version(tx, site, publication.version):
        fail('VERSION_CONFLICT', Conflict)
    persistence.sites.add_version(tx, site['id'], publication.version, publication.config, now())
    write_audit(tx, user, site['id'], 'publish', {'version': publication.version})
    return publication.version


def get_site_version(tx, site, version=None):
    wanted = site['published_version'] if version is None else version
    value = persistence.sites.get_version(tx, site['id'], wanted)
    if not value:
        fail('NOT_PUBLISHED', NotFound)
    return value
