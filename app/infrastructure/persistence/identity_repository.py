"""Accounts: users, login sessions, phone principals, preferences and inbox."""
from __future__ import annotations

from sqlalchemy import delete, func, insert, select, update

from app.domain.values import now
from app.infrastructure.persistence.account_request_tables import request_workflows
from app.infrastructure.persistence.tables import notifications, phone_verifications, preferences, sessions, user_phones, users


def _one(tx, query):
    row = tx.execute(query).mappings().first()
    return dict(row) if row else None


class SqlIdentityRepository:
    # Users ----------------------------------------------------------------
    def user(self, tx, user_id, *, for_update=False):
        query = select(users).where(users.c.id == user_id)
        if for_update:
            query = query.with_for_update()
        return _one(tx, query)

    def users_with_email(self, tx, email):
        """Case/whitespace-insensitive e-mail match (legacy rows may differ in case)."""
        query = select(users).where(func.lower(func.trim(users.c.email)) == email.lower())
        return [dict(row) for row in tx.execute(query).mappings().all()]

    def user_with_exact_email(self, tx, email):
        return _one(tx, select(users).where(users.c.email == email))

    def user_by_phone(self, tx, phone):
        return _one(tx, select(users).join(user_phones, users.c.id == user_phones.c.user_id)
                    .where(user_phones.c.phone == phone))

    def users_in_scope(self, tx, scope_id):
        query = (select(users.c.id, users.c.email, users.c.name, users.c.role, users.c.scope_id, users.c.active,
                        user_phones.c.phone)
                 .outerjoin(user_phones, users.c.id == user_phones.c.user_id).where(users.c.scope_id == scope_id))
        return [dict(row) for row in tx.execute(query).mappings()]

    def users_awaiting_setup(self, tx, scope_id):
        query = (select(request_workflows.c.user_id).join(users, users.c.id == request_workflows.c.user_id)
                 .where(users.c.scope_id == scope_id, request_workflows.c.setup_expires_at.is_not(None)))
        return set(tx.execute(query).scalars())

    def set_active(self, tx, user_id, active: bool):
        tx.execute(update(users).where(users.c.id == user_id).values(active=1 if active else 0))

    def cancel_account_setup(self, tx, user_id):
        tx.execute(update(request_workflows).where(request_workflows.c.user_id == user_id)
                   .values(setup_expires_at=None))

    def change_password(self, tx, user_id, expected_hash, new_hash):
        """Compare-and-set on the current hash of an active user."""
        result = tx.execute(update(users).where(users.c.id == user_id, users.c.password_hash == expected_hash,
                                                users.c.active == 1)
                            .values(password_hash=new_hash, must_change_password=0))
        return result.rowcount == 1

    def set_temporary_password(self, tx, user_id, password_hash):
        tx.execute(update(users).where(users.c.id == user_id)
                   .values(password_hash=password_hash, must_change_password=1))

    # Sessions -------------------------------------------------------------
    def session(self, tx, token_hash):
        return _one(tx, select(sessions).where(sessions.c.token_hash == token_hash))

    def add_session(self, tx, row):
        tx.execute(insert(sessions).values(**row))

    def delete_session(self, tx, token_hash):
        tx.execute(delete(sessions).where(sessions.c.token_hash == token_hash))

    def delete_sessions_of(self, tx, user_id):
        return tx.execute(delete(sessions).where(sessions.c.user_id == user_id)).rowcount

    def active_session_count(self, tx, user_id):
        query = select(func.count()).select_from(sessions).where(sessions.c.user_id == user_id,
                                                                 sessions.c.expires_at > now())
        return tx.execute(query).scalar_one()

    # Phone principals -------------------------------------------------------
    def phone_of(self, tx, user_id):
        return tx.execute(select(user_phones.c.phone).where(user_phones.c.user_id == user_id)).scalar()

    def phone_binding(self, tx, phone):
        return _one(tx, select(user_phones).where(user_phones.c.phone == phone))

    def phone_binding_of(self, tx, user_id):
        return _one(tx, select(user_phones).where(user_phones.c.user_id == user_id))

    def bind_phone(self, tx, phone, user_id):
        tx.execute(insert(user_phones).values(phone=phone, user_id=user_id, created_at=now()))

    # Optional proof of phone ownership (the code itself lives in the Channel Gateway) -----
    def phone_is_verified(self, tx, user_id, phone):
        return tx.execute(select(phone_verifications.c.id).where(
            phone_verifications.c.user_id == user_id, phone_verifications.c.phone == phone,
            phone_verifications.c.verified_at.is_not(None)).limit(1)).first() is not None

    def phone_verifications_since(self, tx, user_id, since):
        return tx.execute(select(func.count()).select_from(phone_verifications).where(
            phone_verifications.c.user_id == user_id, phone_verifications.c.created_at > since)).scalar()

    def add_phone_verification(self, tx, row):
        tx.execute(insert(phone_verifications).values(**row))

    def pending_phone_verification(self, tx, user_id, phone, since):
        return _one(tx, select(phone_verifications).where(
            phone_verifications.c.user_id == user_id, phone_verifications.c.phone == phone,
            phone_verifications.c.verified_at.is_(None), phone_verifications.c.created_at > since
        ).order_by(phone_verifications.c.created_at.desc()).limit(1))

    def mark_phone_verified(self, tx, verification_row_id, at):
        tx.execute(update(phone_verifications).where(
            phone_verifications.c.id == verification_row_id, phone_verifications.c.verified_at.is_(None)).values(verified_at=at))

    # Preferences and inbox --------------------------------------------------
    def preferences(self, tx, user_id):
        return tx.execute(select(preferences.c.config).where(preferences.c.user_id == user_id)).scalar_one_or_none()

    def save_preferences(self, tx, user_id, config):
        exists = tx.execute(select(preferences.c.user_id).where(preferences.c.user_id == user_id)).first()
        if exists:
            tx.execute(update(preferences).where(preferences.c.user_id == user_id).values(config=config))
        else:
            tx.execute(insert(preferences).values(user_id=user_id, config=config))

    def inbox(self, tx, user_id, limit=100):
        query = (select(notifications.c.id, notifications.c.title, notifications.c.body,
                        notifications.c.created_at, notifications.c.read_at)
                 .where(notifications.c.user_id == user_id)
                 .order_by(notifications.c.created_at.desc(), notifications.c.id).limit(limit))
        return [dict(row) for row in tx.execute(query).mappings().all()]

    def mark_read(self, tx, notification_id, user_id):
        result = tx.execute(update(notifications).where(notifications.c.id == notification_id,
                                                        notifications.c.user_id == user_id).values(read_at=now()))
        return bool(result.rowcount)

    def add_notification(self, tx, row):
        tx.execute(insert(notifications).values(**row))
