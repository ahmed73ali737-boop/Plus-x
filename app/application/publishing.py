"""Publish a site's draft as an immutable version; read published versions."""
from __future__ import annotations

from app.application.audit_service import write_audit
from app.application.ports import persistence
from app.domain import now
from app.domain.sites import publish, require_publication_advanced, require_site_version


def publish_site_version(tx, site, user) -> int:
    publication = publish(site)
    # Optimistic concurrency: the draft revision and version must be unchanged.
    require_publication_advanced(persistence.sites.advance_published_version(tx, site, publication.version))
    persistence.sites.add_version(tx, site['id'], publication.version, publication.config, now())
    write_audit(tx, user, site['id'], 'publish', {'version': publication.version})
    return publication.version


def get_site_version(tx, site, version=None):
    wanted = site['published_version'] if version is None else version
    return require_site_version(persistence.sites.get_version(tx, site['id'], wanted))
