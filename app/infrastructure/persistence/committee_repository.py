"""Event committee assignments with their users."""
from __future__ import annotations

from sqlalchemy import select, update

from app.infrastructure.persistence.tables import assignments, user_phones, users


class SqlCommitteeRepository:
    def members(self, tx, event_id, roles):
        query = (select(assignments, users.c.name, users.c.email, users.c.active, user_phones.c.phone)
                 .join(users, users.c.id == assignments.c.user_id)
                 .outerjoin(user_phones, user_phones.c.user_id == users.c.id)
                 .where(assignments.c.site_id == event_id, assignments.c.role.in_(roles)))
        return [dict(row) for row in tx.execute(query).mappings()]

    def assignment(self, tx, assignment_id, event_id, roles):
        query = select(assignments).where(assignments.c.id == assignment_id, assignments.c.site_id == event_id,
                                          assignments.c.role.in_(roles))
        row = tx.execute(query).mappings().first()
        return dict(row) if row else None

    def update_assignment(self, tx, assignment_id, values):
        tx.execute(update(assignments).where(assignments.c.id == assignment_id).values(**values))
