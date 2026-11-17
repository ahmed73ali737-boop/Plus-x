"""Managed admission persistence: policy rows, guest lists, invitations,
entitlements, admission uses and invitation import previews.

PostgreSQL serializes admission changes with the event policy row (SELECT ...
FOR UPDATE); SQLite serializes writers with BEGIN IMMEDIATE.
"""
from __future__ import annotations

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.admission import ALL_DAYS, DEFAULT_POLICY
from app.domain.values import now
from app.infrastructure.persistence.invitation_tables import (
    admission_policies,
    admission_uses,
    entitlements,
    guest_lists,
    invitation_imports,
    invitations,
)


def _one(tx, query):
    row = tx.execute(query).mappings().first()
    return dict(row) if row else None


class SqlAdmissionRepository:
    # Policy -------------------------------------------------------------
    def policy_record(self, tx, event_id):
        return _one(tx, select(admission_policies).where(admission_policies.c.event_id == event_id))

    def lock_policy(self, tx, event_id):
        """Row-lock the policy, creating the default row first when missing."""
        row = tx.execute(select(admission_policies).where(admission_policies.c.event_id == event_id)
                         .with_for_update()).mappings().first()
        if not row:
            try:
                with tx.begin_nested():
                    tx.execute(insert(admission_policies).values(event_id=event_id, config=DEFAULT_POLICY, rev=1,
                                                                 updated_at=now()))
            except IntegrityError:
                pass
            tx.execute(select(admission_policies).where(admission_policies.c.event_id == event_id)
                       .with_for_update()).first()

    def save_policy(self, tx, event_id, config, rev):
        tx.execute(update(admission_policies).where(admission_policies.c.event_id == event_id)
                   .values(config=config, rev=rev, updated_at=now()))

    def policy_config(self, tx, event_id):
        return tx.execute(select(admission_policies.c.config)
                          .where(admission_policies.c.event_id == event_id)).scalar_one_or_none()

    # Guest lists --------------------------------------------------------
    def guest_list_in_event(self, tx, list_id, event_id):
        query = select(guest_lists.c.id).where(guest_lists.c.id == list_id, guest_lists.c.event_id == event_id)
        return tx.execute(query).first() is not None

    def guest_lists(self, tx, event_id):
        query = select(guest_lists).where(guest_lists.c.event_id == event_id).order_by(guest_lists.c.name)
        return [dict(row) for row in tx.execute(query).mappings()]

    def add_guest_list_if_absent(self, tx, row):
        try:
            with tx.begin_nested():
                tx.execute(insert(guest_lists).values(**row))
            return True
        except IntegrityError:
            return False

    # Invitations --------------------------------------------------------
    def invitations(self, tx, event_id, *, newest_first=False):
        query = select(invitations).where(invitations.c.event_id == event_id)
        if newest_first:
            query = query.order_by(invitations.c.created_at.desc())
        return [dict(row) for row in tx.execute(query).mappings().all()]

    def invitation(self, tx, event_id, invitation_id):
        return _one(tx, select(invitations).where(invitations.c.id == invitation_id,
                                                  invitations.c.event_id == event_id))

    def invitation_by_token_hash(self, tx, token_hash):
        return _one(tx, select(invitations).where(invitations.c.token_hash == token_hash))

    def invitation_with_phone_exists(self, tx, event_id, phone):
        query = select(invitations.c.id).where(invitations.c.event_id == event_id, invitations.c.phone == phone)
        return tx.execute(query).first() is not None

    def invitation_links_guest(self, tx, invitation_id, event_id, guest_id):
        query = select(invitations.c.id).where(invitations.c.id == invitation_id, invitations.c.event_id == event_id,
                                               invitations.c.guest_id == guest_id)
        return tx.execute(query).first() is not None

    def add_invitation(self, tx, row):
        tx.execute(insert(invitations).values(**row))

    def update_invitation(self, tx, invitation_id, values):
        tx.execute(update(invitations).where(invitations.c.id == invitation_id).values(**values))

    # Entitlements and uses ------------------------------------------------
    def consumed_total(self, tx, invitation_id):
        query = select(func.coalesce(func.sum(entitlements.c.consumed), 0)).where(
            entitlements.c.invitation_id == invitation_id)
        return tx.execute(query).scalar_one()

    def consumed_for_day(self, tx, invitation_id, day):
        query = select(func.coalesce(func.sum(entitlements.c.consumed), 0)).where(
            entitlements.c.invitation_id == invitation_id, entitlements.c.day.in_([day, ALL_DAYS]))
        return tx.execute(query).scalar_one()

    def consumed_for_event(self, tx, event_id):
        query = select(func.coalesce(func.sum(entitlements.c.consumed), 0)).where(entitlements.c.event_id == event_id)
        return tx.execute(query).scalar_one()

    def revoke_entitlements(self, tx, invitation_id):
        tx.execute(update(entitlements).where(entitlements.c.invitation_id == invitation_id).values(status='revoked'))

    def replace_entitlements(self, tx, invitation_id, rows):
        tx.execute(delete(entitlements).where(entitlements.c.invitation_id == invitation_id))
        for row in rows:
            tx.execute(insert(entitlements).values(**row))

    def active_entitlement(self, tx, invitation_id, event_id, guest_id, slot):
        return _one(tx, select(entitlements).where(
            entitlements.c.invitation_id == invitation_id, entitlements.c.event_id == event_id,
            entitlements.c.guest_id == guest_id, entitlements.c.day == slot, entitlements.c.status == 'active'))

    def entitlement(self, tx, entitlement_id):
        return dict(tx.execute(select(entitlements).where(entitlements.c.id == entitlement_id)).mappings().one())

    def consume(self, tx, entitlement_id, quantity):
        """Atomic capacity check: never consume beyond the entitlement's quantity."""
        result = tx.execute(update(entitlements).where(
            entitlements.c.id == entitlement_id, entitlements.c.status == 'active',
            entitlements.c.consumed + quantity <= entitlements.c.quantity,
        ).values(consumed=entitlements.c.consumed + quantity))
        return result.rowcount == 1

    def admission_use(self, tx, scan_id):
        return _one(tx, select(admission_uses).where(admission_uses.c.scan_id == scan_id))

    def add_admission_use(self, tx, row):
        tx.execute(insert(admission_uses).values(**row))

    def admitted_people(self, tx, event_id):
        query = (select(func.coalesce(func.sum(admission_uses.c.quantity), 0))
                 .select_from(admission_uses.join(entitlements, admission_uses.c.entitlement_id == entitlements.c.id))
                 .where(entitlements.c.event_id == event_id))
        return tx.execute(query).scalar_one()

    # Import previews ----------------------------------------------------
    def add_import(self, tx, row):
        tx.execute(insert(invitation_imports).values(**row))

    def lock_import(self, tx, import_id, event_id, user_id):
        return _one(tx, select(invitation_imports).where(
            invitation_imports.c.id == import_id, invitation_imports.c.event_id == event_id,
            invitation_imports.c.user_id == user_id).with_for_update())

    def mark_import_committed(self, tx, import_id):
        tx.execute(update(invitation_imports).where(invitation_imports.c.id == import_id).values(state='committed'))
