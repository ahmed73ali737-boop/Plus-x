from __future__ import annotations

from sqlalchemy import insert, select, update

from app.application.audit_service import write_audit
from app.db import sites, versions
from app.domain import fail, normalize_config, now


def publish_site_version(conn, site, user) -> int:
    config = normalize_config(site['draft'])
    version = site['published_version'] + 1
    result = conn.execute(
        update(sites)
        .where(
            sites.c.id == site['id'],
            sites.c.draft_rev == site['draft_rev'],
            sites.c.published_version == site['published_version'],
        )
        .values(published_version=version)
    )
    if result.rowcount != 1:
        fail('VERSION_CONFLICT', 409)
    conn.execute(
        insert(versions).values(
            site_id=site['id'],
            version=version,
            config=config,
            published_at=now(),
        )
    )
    write_audit(conn, user, site['id'], 'publish', {'version': version})
    return version


def get_site_version(conn, site, version=None):
    wanted = site['published_version'] if version is None else version
    value = conn.execute(
        select(versions).where(
            versions.c.site_id == site['id'],
            versions.c.version == wanted,
        )
    ).mappings().first()
    if not value:
        fail('NOT_PUBLISHED', 404)
    return value
