"""Guests (global phone identity) and their per-event registrations (passes)."""
from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.errors import NotFound, Unavailable, fail
from app.domain.guests import PASS_ALLOCATION_ATTEMPTS, is_event_pass, new_event_pass_number
from app.infrastructure.persistence.tables import event_guests, guests


def _joined():
    return (select(
        guests,
        event_guests.c.id.label('event_guest_id'),
        event_guests.c.status.label('event_guest_status'),
        event_guests.c.guest_type,
        event_guests.c.pass_number,
        event_guests.c.metadata_json,
        event_guests.c.registered_at,
    ).join(event_guests, event_guests.c.guest_id == guests.c.id))


def _identity(phone, phone_hash, guest_number):
    return (guests.c.phone_e164 == phone) | (guests.c.phone_hash == phone_hash) | (guests.c.guest_number == guest_number)


class SqlGuestRepository:
    def find_by_identity(self, tx, phone, phone_hash, guest_number):
        row = tx.execute(select(guests).where(_identity(phone, phone_hash, guest_number))).mappings().first()
        return dict(row) if row else None

    def find_id_by_phone(self, tx, phone):
        return tx.execute(select(guests.c.id).where(guests.c.phone_e164 == phone)).scalar()

    def add_if_absent(self, tx, guest):
        """Insert in a savepoint so a concurrent same-phone insert becomes a lookup."""
        try:
            with tx.begin_nested():
                tx.execute(insert(guests).values(**guest))
            return True
        except IntegrityError:
            return False

    def update(self, tx, guest_id, values):
        tx.execute(update(guests).where(guests.c.id == guest_id).values(**values))

    def registration(self, tx, event_id, guest_id):
        row = tx.execute(select(event_guests).where(
            event_guests.c.event_id == event_id, event_guests.c.guest_id == guest_id)).mappings().first()
        return dict(row) if row else None

    def registration_by_id(self, tx, registration_id):
        row = tx.execute(select(event_guests).where(event_guests.c.id == registration_id)).mappings().first()
        return dict(row) if row else None

    def registrations(self, tx, event_id=None, status=None):
        query = select(event_guests)
        if event_id is not None:
            query = query.where(event_guests.c.event_id == event_id)
        if status is not None:
            query = query.where(event_guests.c.status == status)
        return [dict(row) for row in tx.execute(query).mappings().all()]

    def add_registration_if_absent(self, tx, registration):
        try:
            with tx.begin_nested():
                tx.execute(insert(event_guests).values(**registration))
            return True
        except IntegrityError:
            return False

    def update_registration(self, tx, registration_id, values):
        tx.execute(update(event_guests).where(event_guests.c.id == registration_id).values(**values))

    def update_registration_of_guest(self, tx, event_id, guest_id, values):
        tx.execute(update(event_guests).where(
            event_guests.c.event_id == event_id, event_guests.c.guest_id == guest_id).values(**values))

    def ensure_pass_number(self, tx, registration):
        """Allocate a random event pass number; concurrent callers agree on one.

        Compare-and-set on the current value inside a savepoint: the unique index
        stays the authority, and a (vanishingly unlikely) collision is retried
        without aborting the caller's import/registration transaction. The
        caller owns the transaction; read-only endpoints never mint passes.
        """
        current = dict(registration)
        for _ in range(PASS_ALLOCATION_ATTEMPTS):
            existing = current.get('pass_number')
            if is_event_pass(existing):
                return existing
            candidate = new_event_pass_number()
            condition = (event_guests.c.pass_number.is_(None) if existing is None
                         else event_guests.c.pass_number == existing)
            try:
                with tx.begin_nested():
                    changed = tx.execute(update(event_guests)
                                         .where(event_guests.c.id == current['id'], condition)
                                         .values(pass_number=candidate))
                if changed.rowcount:
                    return candidate
            except IntegrityError:
                continue
            current = self.registration_by_id(tx, current['id'])
            if current is None:
                fail('GUEST_NOT_FOUND', NotFound)
        fail('GUEST_PASS_ALLOCATION_FAILED', Unavailable)

    def backfill_pass_numbers(self, tx, event_id=None):
        """Upgrade legacy registrations; the old phone-derived pass is not kept as an alias."""
        changed = 0
        for registration in self.registrations(tx, event_id):
            if not is_event_pass(registration.get('pass_number')):
                self.ensure_pass_number(tx, registration)
                changed += 1
        return changed

    def by_pass_number(self, tx, event_id, pass_number):
        row = tx.execute(_joined().where(event_guests.c.event_id == event_id,
                                         event_guests.c.pass_number == pass_number)).mappings().first()
        return dict(row) if row else None

    def for_event(self, tx, event_id):
        query = _joined().where(event_guests.c.event_id == event_id).order_by(event_guests.c.registered_at.desc())
        return [dict(row) for row in tx.execute(query).mappings()]

    def registered_with_phone(self, tx, event_id, phone):
        query = (select(event_guests.c.id).join(guests, guests.c.id == event_guests.c.guest_id)
                 .where(event_guests.c.event_id == event_id, guests.c.phone_e164 == phone))
        return tx.execute(query).first() is not None
