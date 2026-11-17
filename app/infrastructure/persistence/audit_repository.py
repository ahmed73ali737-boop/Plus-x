"""Append-only audit log."""
from __future__ import annotations

from sqlalchemy import insert, select

from app.infrastructure.persistence.tables import audit


class SqlAuditLog:
    def add(self, tx, row):
        tx.execute(insert(audit).values(**row))

    def recent(self, tx, limit, *, site_id=None, site_ids=None):
        query = select(audit).order_by(audit.c.at.desc()).limit(limit)
        if site_id is not None:
            query = query.where(audit.c.site_id == site_id)
        elif site_ids is not None:
            query = query.where(audit.c.site_id.in_(site_ids))
        return [dict(row) for row in tx.execute(query).mappings()]
