"""Site administration records: access/sign-up requests, content imports,
organizations, their people, memberships and event participations.
"""
from __future__ import annotations

from sqlalchemy import delete, insert, select, update

from app.infrastructure.persistence.account_request_tables import request_workflows
from app.infrastructure.persistence.tables import (
    event_participations,
    imports,
    memberships,
    organization_people,
    organizations,
    requests,
    signup_requests,
    users,
)


def _one(tx, query):
    row = tx.execute(query).mappings().first()
    return dict(row) if row else None


def _all(tx, query):
    return [dict(row) for row in tx.execute(query).mappings().all()]


class SqlSiteAdminRepository:
    # Legacy access requests and sign-up requests -------------------------
    def access_requests(self, tx, site_id):
        return _all(tx, select(requests).where(requests.c.site_id == site_id).order_by(requests.c.created_at.desc()))

    def access_request(self, tx, site_id, request_id):
        return _one(tx, select(requests).where(requests.c.id == request_id, requests.c.site_id == site_id))

    def set_access_request_status(self, tx, request_id, status):
        tx.execute(update(requests).where(requests.c.id == request_id).values(status=status))

    def add_access_request(self, tx, row):
        tx.execute(insert(requests).values(**row))

    def delete_access_request(self, tx, request_id):
        tx.execute(delete(requests).where(requests.c.id == request_id))

    def add_signup_request(self, tx, row):
        tx.execute(insert(signup_requests).values(**row))

    def delete_signup_request(self, tx, request_id):
        tx.execute(delete(signup_requests).where(signup_requests.c.id == request_id))

    def signup_requests(self, tx):
        return _all(tx, select(signup_requests).order_by(signup_requests.c.created_at.desc()))

    def workflow_request_id(self, tx, *, signup_id=None, access_id=None):
        column = request_workflows.c.signup_id if signup_id is not None else request_workflows.c.access_id
        value = signup_id if signup_id is not None else access_id
        return tx.execute(select(request_workflows.c.request_id).where(column == value)).scalar()

    # Content imports -------------------------------------------------------
    def add_import(self, tx, row):
        tx.execute(insert(imports).values(**row))

    def content_import(self, tx, import_id):
        return _one(tx, select(imports).where(imports.c.id == import_id))

    def mark_import_committed(self, tx, import_id):
        tx.execute(update(imports).where(imports.c.id == import_id).values(state='committed'))

    # Organizations ---------------------------------------------------------
    def organizations(self, tx):
        return _all(tx, select(organizations).order_by(organizations.c.name))

    def organization(self, tx, organization_id):
        return _one(tx, select(organizations).where(organizations.c.id == organization_id))

    def organization_by_slug(self, tx, slug):
        return _one(tx, select(organizations).where(organizations.c.slug == slug))

    def add_organization(self, tx, row):
        tx.execute(insert(organizations).values(**row))

    def people(self, tx, organization_id):
        return _all(tx, select(organization_people).where(organization_people.c.organization_id == organization_id)
                    .order_by(organization_people.c.name))

    def person(self, tx, person_id):
        return _one(tx, select(organization_people).where(organization_people.c.id == person_id))

    def add_person(self, tx, row):
        tx.execute(insert(organization_people).values(**row))

    def update_person(self, tx, person_id, values):
        tx.execute(update(organization_people).where(organization_people.c.id == person_id).values(**values))

    def members(self, tx, organization_id):
        query = (select(memberships, users.c.email, users.c.name, users.c.active)
                 .join(users, memberships.c.user_id == users.c.id).where(memberships.c.organization_id == organization_id))
        return _all(tx, query)

    def membership(self, tx, user_id, organization_id):
        return _one(tx, select(memberships).where(memberships.c.user_id == user_id,
                                                  memberships.c.organization_id == organization_id))

    def is_active_owner(self, tx, user_id, organization_id):
        query = select(memberships.c.user_id).where(
            memberships.c.user_id == user_id, memberships.c.organization_id == organization_id,
            memberships.c.role == 'owner', memberships.c.status == 'active')
        return tx.execute(query).first() is not None

    def update_membership(self, tx, user_id, organization_id, values):
        tx.execute(update(memberships).where(memberships.c.user_id == user_id,
                                             memberships.c.organization_id == organization_id).values(**values))

    # Event participations --------------------------------------------------
    def participations_of_organization(self, tx, organization_id):
        return _all(tx, select(event_participations).where(event_participations.c.organization_id == organization_id))

    def participations_of_event(self, tx, event_id):
        query = (select(event_participations, organizations.c.name, organizations.c.slug)
                 .join(organizations, event_participations.c.organization_id == organizations.c.id)
                 .where(event_participations.c.event_id == event_id))
        return _all(tx, query)

    def participation(self, tx, participation_id):
        return _one(tx, select(event_participations).where(event_participations.c.id == participation_id))

    def participation_exists(self, tx, event_id, organization_id):
        query = select(event_participations.c.id).where(event_participations.c.event_id == event_id,
                                                        event_participations.c.organization_id == organization_id)
        return tx.execute(query).first() is not None

    def add_participation(self, tx, row):
        tx.execute(insert(event_participations).values(**row))

    def update_participation(self, tx, participation_id, values):
        tx.execute(update(event_participations).where(event_participations.c.id == participation_id).values(**values))
