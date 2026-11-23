from sqlalchemy import insert, select, update

from app.infrastructure.persistence.tables import integration_settings


class SqlIntegrationSettings:
    def get(self, tx, key):
        row = tx.execute(select(integration_settings).where(integration_settings.c.key == key)).mappings().first()
        return dict(row) if row else None

    def put(self, tx, key, value, at, by):
        if self.get(tx, key):
            tx.execute(update(integration_settings).where(integration_settings.c.key == key).values(value=value, updated_at=at, updated_by=by))
        else:
            tx.execute(insert(integration_settings).values(key=key, value=value, updated_at=at, updated_by=by))
