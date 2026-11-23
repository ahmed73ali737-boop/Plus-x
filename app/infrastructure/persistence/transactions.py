"""SQLAlchemy unit-of-work adapter: engine transactions and savepoints."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy.exc import DBAPIError, IntegrityError


class SqlTransactions:
    def write(self, engine):
        return engine.begin()

    def read(self, engine):
        return engine.connect()

    @contextmanager
    def savepoint(self, tx):
        with tx.begin_nested():
            yield

    def is_transient_failure(self, error: BaseException) -> bool:
        return isinstance(error, DBAPIError)

    def is_conflict(self, error: BaseException) -> bool:
        """True when a write failed on a uniqueness/integrity rule."""
        return isinstance(error, IntegrityError)
