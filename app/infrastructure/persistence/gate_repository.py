"""Gate persistence: GuestPresence aggregate rows and the scan (check-in) log."""
from __future__ import annotations

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.gate import GuestPresence
from app.infrastructure.persistence.tables import guest_checkins, guest_presence


def _key(event_id, guest_id):
    return (guest_presence.c.event_id == event_id, guest_presence.c.guest_id == guest_id)


class SqlPresenceRepository:
    def get(self, tx, event_id, guest_id):
        row = tx.execute(select(guest_presence).where(*_key(event_id, guest_id))).mappings().first()
        return GuestPresence.from_record(dict(row)) if row else None

    def add_if_absent(self, tx, presence):
        try:
            with tx.begin_nested():
                tx.execute(insert(guest_presence).values(**presence.to_record()))
            return presence
        except IntegrityError:
            current = self.get(tx, presence.event_id, presence.guest_id)
            if current is None:
                raise
            return current

    def lock(self, tx, event_id, guest_id):
        """Serialize all scans of one ticket (row lock on PostgreSQL, writer lock on SQLite)."""
        tx.execute(select(guest_presence).where(*_key(event_id, guest_id)).with_for_update()).first()

    def save(self, tx, presence, transition):
        """Persist an accepted transition.

        Anti-passback transitions are applied with a conditional UPDATE on the
        state the domain decided against (optimistic-concurrency defence): a
        concurrent scan that already moved the guest makes this return False.
        """
        conditions = list(_key(presence.event_id, presence.guest_id))
        if transition.guarded:
            conditions.append(guest_presence.c.state == transition.expected_state)
        result = tx.execute(update(guest_presence).where(*conditions).values(
            state=presence.state,
            last_scan_id=presence.last_scan_id,
            last_direction=presence.last_direction,
            last_checkpoint=presence.last_checkpoint,
            updated_at=presence.updated_at,
        ))
        return result.rowcount == 1 or not transition.guarded

    def for_event(self, tx, event_id):
        rows = tx.execute(select(guest_presence).where(guest_presence.c.event_id == event_id)).mappings()
        return {row['guest_id']: dict(row) for row in rows}


class SqlCheckinLog:
    def get(self, tx, scan_id):
        row = tx.execute(select(guest_checkins).where(guest_checkins.c.id == scan_id)).mappings().first()
        return dict(row) if row else None

    def add_if_absent(self, tx, scan):
        try:
            with tx.begin_nested():
                tx.execute(insert(guest_checkins).values(**scan))
            return True
        except IntegrityError:
            return False

    def for_event(self, tx, event_id, *, newest_first, limit=None):
        order = guest_checkins.c.scanned_at.desc() if newest_first else guest_checkins.c.scanned_at.asc()
        query = select(guest_checkins).where(guest_checkins.c.event_id == event_id).order_by(order)
        if limit is not None:
            query = query.limit(limit)
        return [dict(row) for row in tx.execute(query).mappings()]

    def count_for_event(self, tx, event_id):
        query = select(func.count()).select_from(guest_checkins).where(guest_checkins.c.event_id == event_id)
        return tx.execute(query).scalar_one()
