"""Field device rows."""
from __future__ import annotations

from sqlalchemy import insert, select, update

from app.infrastructure.persistence.tables import devices


class SqlDeviceRepository:
    def add(self, tx, row):
        tx.execute(insert(devices).values(**row))

    def for_site(self, tx, site_id):
        query = select(devices).where(devices.c.site_id == site_id).order_by(devices.c.created_at.desc())
        return [dict(row) for row in tx.execute(query).mappings()]

    def get(self, tx, device_id, *, for_update=False):
        query = select(devices).where(devices.c.id == device_id)
        if for_update:
            query = query.with_for_update()
        row = tx.execute(query).mappings().first()
        return dict(row) if row else None

    def by_token_hash(self, tx, token_hash, *, for_update=False):
        query = select(devices).where(devices.c.token_hash == token_hash)
        if for_update:
            query = query.with_for_update()
        row = tx.execute(query).mappings().first()
        return dict(row) if row else None

    def update(self, tx, device_id, values):
        tx.execute(update(devices).where(devices.c.id == device_id).values(**values))
