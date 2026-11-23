"""Authorization facts: assignments, organization memberships and participations."""
from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.persistence.tables import assignments, event_participations, memberships


def _all(tx, query):
    return [dict(row) for row in tx.execute(query).mappings().all()]


class SqlAccessRepository:
    def participations_for_agency_site(self, tx, site_id):
        return _all(tx, select(event_participations).where(event_participations.c.agency_site_id == site_id))

    def memberships_in(self, tx, user_id, organization_ids):
        return _all(tx, select(memberships).where(memberships.c.user_id == user_id,
                                                  memberships.c.organization_id.in_(organization_ids)))

    def assignments(self, tx, user_id, site_id, roles=None):
        query = select(assignments).where(assignments.c.user_id == user_id, assignments.c.site_id == site_id)
        if roles is not None:
            query = query.where(assignments.c.role.in_(tuple(roles)))
        return _all(tx, query)

    def user_assignments_with_roles(self, tx, user_id, roles):
        return _all(tx, select(assignments).where(assignments.c.user_id == user_id,
                                                  assignments.c.role.in_(tuple(roles))))

    def active_membership_org_ids(self, tx, user_id, roles):
        query = select(memberships.c.organization_id).where(
            memberships.c.user_id == user_id, memberships.c.status == 'active', memberships.c.role.in_(tuple(roles)))
        return list(tx.execute(query).scalars().all())

    def participations_of(self, tx, organization_ids, agency_site_id, *, active_only=False):
        query = select(event_participations).where(event_participations.c.organization_id.in_(organization_ids),
                                                   event_participations.c.agency_site_id == agency_site_id)
        if active_only:
            query = query.where(event_participations.c.status == 'active')
        return _all(tx, query)

    def has_active_membership(self, tx, user_id, organization_id=None, role=None):
        query = select(memberships.c.user_id).where(memberships.c.user_id == user_id, memberships.c.status == 'active')
        if organization_id is not None:
            query = query.where(memberships.c.organization_id == organization_id)
        if role is not None:
            query = query.where(memberships.c.role == role)
        return tx.execute(query).first() is not None

    def membership_role(self, tx, user_id, organization_id):
        query = select(memberships.c.role).where(memberships.c.user_id == user_id,
                                                 memberships.c.organization_id == organization_id,
                                                 memberships.c.status == 'active')
        return tx.execute(query).scalar()

    def organization_in_event(self, tx, organization_id, event_id):
        query = select(event_participations.c.id).where(event_participations.c.organization_id == organization_id,
                                                        event_participations.c.event_id == event_id)
        return tx.execute(query).first() is not None
