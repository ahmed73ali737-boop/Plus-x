"""Sites (platform, events, agency pages) and their published versions."""
from __future__ import annotations

from sqlalchemy import and_, insert, select, update

from app.infrastructure.persistence.tables import event_participations, sites, versions


def _one(tx, query):
    row = tx.execute(query).mappings().first()
    return dict(row) if row else None


class SqlSiteRepository:
    def get(self, tx, site_id):
        return _one(tx, select(sites).where(sites.c.id == site_id))

    def get_by_slug(self, tx, slug):
        return _one(tx, select(sites).where(sites.c.slug == slug))

    def event_by_slug(self, tx, slug):
        return _one(tx, select(sites).where(sites.c.slug == slug, sites.c.kind == 'event'))

    def list_all(self, tx):
        return [dict(row) for row in tx.execute(select(sites)).mappings()]

    def published_events(self, tx):
        query = select(sites).where(sites.c.kind == 'event', sites.c.published_version > 0)
        return [dict(row) for row in tx.execute(query).mappings()]

    def published_agency_children(self, tx, parent_id):
        """Agency pages of a parent with their current published config (one query)."""
        joined = sites.outerjoin(versions, and_(versions.c.site_id == sites.c.id,
                                                versions.c.version == sites.c.published_version))
        query = (select(sites, versions.c.config.label('published_config')).select_from(joined)
                 .where(sites.c.parent_id == parent_id, sites.c.kind == 'agency', sites.c.published_version > 0))
        return [dict(row) for row in tx.execute(query).mappings()]

    def participations_of_children(self, tx, parent_id):
        query = (select(event_participations)
                 .join(sites, event_participations.c.agency_site_id == sites.c.id)
                 .where(sites.c.parent_id == parent_id))
        return [dict(row) for row in tx.execute(query).mappings()]

    def add(self, tx, site):
        tx.execute(insert(sites).values(**site))

    def save_draft(self, tx, site_id, expected_rev, draft):
        """Optimistic concurrency: only the holder of the current revision may save."""
        result = tx.execute(update(sites).where(sites.c.id == site_id, sites.c.draft_rev == expected_rev)
                            .values(draft=draft, draft_rev=expected_rev + 1))
        return result.rowcount == 1

    def advance_published_version(self, tx, site, version):
        result = tx.execute(update(sites).where(
            sites.c.id == site['id'],
            sites.c.draft_rev == site['draft_rev'],
            sites.c.published_version == site['published_version'],
        ).values(published_version=version))
        return result.rowcount == 1

    def add_version(self, tx, site_id, version, config, published_at):
        tx.execute(insert(versions).values(site_id=site_id, version=version, config=config, published_at=published_at))

    def get_version(self, tx, site_id, version):
        return _one(tx, select(versions).where(versions.c.site_id == site_id, versions.c.version == version))

    def version_configs(self, tx):
        return {(row['site_id'], row['version']): row['config'] for row in tx.execute(select(versions)).mappings()}
