"""Account-approval persistence: pending requests, their workflow rows, and the
login identities/grants an approval creates (the single insert authority for
users, memberships and assignments outside demo seeding).
"""
from __future__ import annotations

import hashlib

from sqlalchemy import insert, or_, select, text as sql_text, update

from app.infrastructure.account_requests import add_pending_account_request
from app.infrastructure.persistence.account_request_tables import (
    account_requests as ar,
    platform_account_invites as invites,
    request_workflows as wf,
)
from app.infrastructure.persistence.tables import (
    assignments,
    event_participations,
    memberships,
    organization_people,
    organizations,
    requests,
    signup_requests,
    sites,
    users,
)


def _one(tx, query):
    row = tx.execute(query).mappings().first()
    return dict(row) if row else None


def _all(tx, query):
    return [dict(row) for row in tx.execute(query).mappings().all()]


class SqlAccountRequestRepository:
    # Requests ----------------------------------------------------------------
    def expired_pending_ids(self, tx, at):
        query = select(ar.c.id).where(ar.c.status == 'pending', ar.c.expires_at <= at).with_for_update()
        return list(tx.execute(query).scalars().all())

    def close(self, tx, request_id, values, *, only_pending=False):
        conditions = [ar.c.id == request_id]
        if only_pending:
            conditions.append(ar.c.status == 'pending')
        tx.execute(update(ar).where(*conditions).values(**values))

    def request(self, tx, request_id, *, for_update=False):
        query = select(ar).where(ar.c.id == request_id)
        if for_update:
            query = query.with_for_update()
        return _one(tx, query)

    def by_request_key(self, tx, key_hash):
        return _one(tx, select(ar, wf.c.payload_hash).join(wf, ar.c.id == wf.c.request_id)
                    .where(ar.c.request_key == key_hash))

    def by_tracking_hash(self, tx, tracking_hash, *, for_update=False):
        query = select(ar).join(wf, ar.c.id == wf.c.request_id).where(wf.c.tracking_hash == tracking_hash)
        if for_update:
            query = query.with_for_update(of=ar)
        return _one(tx, query)

    def supervised_by(self, tx, supervisor_id, status=None, scope_id=None):
        query = (select(ar).join(wf, ar.c.id == wf.c.request_id).where(ar.c.supervisor_id == supervisor_id)
                 .order_by(ar.c.created_at))
        if status:
            query = query.where(ar.c.status == status)
        if scope_id:
            event_organizations = select(event_participations.c.organization_id).where(
                event_participations.c.event_id == scope_id)
            query = query.where(or_(ar.c.scope_id == scope_id, ar.c.organization_id.in_(event_organizations)))
        return _all(tx, query)

    def submitted_by(self, tx, user_id, status=None):
        query = (select(ar).join(wf, ar.c.id == wf.c.request_id).where(ar.c.requested_by == user_id)
                 .order_by(ar.c.created_at))
        if status:
            query = query.where(ar.c.status == status)
        return _all(tx, query)

    def add_pending(self, tx, **values):
        return add_pending_account_request(tx, **values)

    # Workflow --------------------------------------------------------------
    def workflow(self, tx, request_id):
        return _one(tx, select(wf).where(wf.c.request_id == request_id))

    def add_workflow(self, tx, row):
        tx.execute(insert(wf).values(**row))

    def update_workflow(self, tx, request_id, values):
        tx.execute(update(wf).where(wf.c.request_id == request_id).values(**values))

    def sync_legacy_status(self, tx, workflow, status):
        if workflow['signup_id']:
            tx.execute(update(signup_requests).where(signup_requests.c.id == workflow['signup_id']).values(status=status))
        if workflow['access_id']:
            tx.execute(update(requests).where(requests.c.id == workflow['access_id']).values(status=status))

    def lock_identities(self, tx, values):
        """Serialize approvals of the same e-mail/phone (PostgreSQL advisory locks)."""
        if tx.dialect.name != 'postgresql':
            return
        for value in sorted(values):
            key = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], 'big', signed=True)
            tx.execute(sql_text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})

    # Lookups used by review views and authorization ------------------------
    def active_users(self, tx):
        return _all(tx, select(users).where(users.c.active == 1).order_by(users.c.id))

    def user_name(self, tx, user_id):
        return tx.execute(select(users.c.name).where(users.c.id == user_id)).scalar()

    def signup(self, tx, signup_id):
        return _one(tx, select(signup_requests).where(signup_requests.c.id == signup_id))

    def organization_name(self, tx, organization_id):
        return tx.execute(select(organizations.c.name).where(organizations.c.id == organization_id)).scalar()

    def site_title(self, tx, site_id):
        draft = tx.execute(select(sites.c.draft).where(sites.c.id == site_id)).scalar()
        return (draft or {}).get('title')

    def organizer_runs_organization(self, tx, organization_id, event_id):
        query = select(event_participations.c.id).where(
            event_participations.c.organization_id == organization_id, event_participations.c.event_id == event_id,
            event_participations.c.status == 'active')
        return tx.execute(query).first() is not None

    def latest_active_agency_site(self, tx, organization_id):
        query = (select(event_participations.c.agency_site_id)
                 .where(event_participations.c.organization_id == organization_id,
                        event_participations.c.status == 'active')
                 .order_by(event_participations.c.created_at.desc()))
        return tx.execute(query).scalar()

    # What an approval creates ------------------------------------------------
    def add_user(self, tx, row):
        tx.execute(insert(users).values(**row))

    def activate_with_password(self, tx, user_id, password_hash):
        result = tx.execute(update(users).where(users.c.id == user_id, users.c.active == 0)
                            .values(password_hash=password_hash, active=1))
        return result.rowcount == 1

    def upsert_membership(self, tx, user_id, organization_id, values, created_at):
        exists = tx.execute(select(memberships.c.user_id).where(
            memberships.c.user_id == user_id, memberships.c.organization_id == organization_id)).first()
        if exists:
            tx.execute(update(memberships).where(memberships.c.user_id == user_id,
                                                 memberships.c.organization_id == organization_id).values(**values))
        else:
            tx.execute(insert(memberships).values(user_id=user_id, organization_id=organization_id,
                                                  created_at=created_at, **values))

    def upsert_assignment(self, tx, new_id, user_id, site_id, role, values, created_at):
        existing = tx.execute(select(assignments.c.id).where(
            assignments.c.user_id == user_id, assignments.c.site_id == site_id, assignments.c.role == role)).scalar()
        if existing:
            tx.execute(update(assignments).where(assignments.c.id == existing).values(**values))
        else:
            tx.execute(insert(assignments).values(id=new_id, user_id=user_id, site_id=site_id, role=role,
                                                  created_at=created_at, **values))

    def person(self, tx, person_id):
        return _one(tx, select(organization_people).where(organization_people.c.id == person_id))

    def link_person(self, tx, person_id, user_id):
        tx.execute(update(organization_people).where(organization_people.c.id == person_id).values(user_id=user_id))

    def add_organization(self, tx, row):
        tx.execute(insert(organizations).values(**row))

    def add_site(self, tx, row):
        tx.execute(insert(sites).values(**row))

    def add_participation(self, tx, row):
        tx.execute(insert(event_participations).values(**row))

    # Platform administrator invitations ------------------------------------
    def add_platform_invite(self, tx, row):
        tx.execute(insert(invites).values(**row))

    def platform_invite(self, tx, token_hash, *, for_update=False):
        query = select(invites).where(invites.c.token_hash == token_hash)
        if for_update:
            query = query.with_for_update()
        return _one(tx, query)

    def link_platform_invite(self, tx, invite_id, request_id):
        tx.execute(update(invites).where(invites.c.id == invite_id).values(request_id=request_id))
