"""Visitor submissions: visits, surveys, polls, feedback, contact requests."""
from __future__ import annotations

from sqlalchemy import and_, insert, or_, select

from app.infrastructure.persistence.tables import submissions


class SqlSubmissionRepository:
    def get(self, tx, submission_id):
        row = tx.execute(select(submissions).where(submissions.c.id == submission_id)).mappings().first()
        return dict(row) if row else None

    def add(self, tx, row):
        tx.execute(insert(submissions).values(**row))

    def for_site(self, tx, site_id):
        return [dict(row) for row in tx.execute(select(submissions).where(submissions.c.site_id == site_id)).mappings().all()]

    def for_metrics(self, tx, site, aggregate):
        query = select(submissions)
        if aggregate and site['kind'] == 'event':
            query = query.where(submissions.c.event_id == site['id'])
        elif aggregate and site['kind'] == 'platform':
            pass
        else:
            query = query.where(or_(submissions.c.site_id == site['id'],
                                    and_(submissions.c.kind == 'feedback', submissions.c.target.like(site['id'] + ':%'))))
        return [dict(row) for row in tx.execute(query).mappings().all()]

    def poll_payloads(self, tx, site_id, target, version):
        query = select(submissions.c.payload).where(submissions.c.site_id == site_id, submissions.c.kind == 'poll',
                                                    submissions.c.target == target, submissions.c.version == version)
        return list(tx.execute(query).scalars())
