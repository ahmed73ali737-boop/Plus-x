"""Additive account-request storage; a request is never a login identity.

Scope keys have explicit foreign-key bindings so both organization and site
requests are supported without weakening referential integrity. No free-form
JSON is stored here: credentials cannot be accidentally copied into metadata.
"""
from sqlalchemy import Table, Column, String, Text, ForeignKey, CheckConstraint, Index, text
from app.db import metadata

account_requests = Table('px_account_requests', metadata,
    Column('id', String(64), primary_key=True),
    Column('email', String(200), nullable=False),
    Column('name', String(160), nullable=False),
    Column('phone', String(40)),
    Column('requested_role', String(20), nullable=False),
    Column('scope_type', String(20), nullable=False),
    Column('scope_id', String(64), nullable=False),
    Column('site_id', String(64), ForeignKey('px_sites.id')),
    Column('organization_id', String(64), ForeignKey('px_organizations.id')),
    Column('event_id', String(64), ForeignKey('px_sites.id')),
    Column('person_id', String(64), ForeignKey('px_organization_people.id')),
    Column('participation_id', String(64), ForeignKey('px_event_participations.id')),
    Column('membership_role', String(20)),
    Column('assignment_role', String(40)),
    Column('source', String(20), nullable=False),
    Column('supervisor_id', String(64), ForeignKey('px_users.id'), nullable=False),
    Column('requested_by', String(64), ForeignKey('px_users.id')),
    Column('reviewed_by', String(64), ForeignKey('px_users.id')),
    Column('status', String(20), nullable=False, server_default='pending'),
    Column('created_at', String(64), nullable=False),
    Column('expires_at', String(64), nullable=False),
    Column('reviewed_at', String(64)),
    Column('decision_reason', String(500)),
    Column('request_key', String(80), nullable=False, unique=True),
    Column('password_hash', Text),
    CheckConstraint("status IN ('pending','approved','rejected','expired','cancelled')", name='ck_px_ar_status'),
    CheckConstraint("email = lower(trim(email)) AND length(email) BETWEEN 3 AND 200", name='ck_px_ar_email'),
    CheckConstraint("requested_role IN ('platform','organizer','agency','member')", name='ck_px_ar_role'),
    CheckConstraint("source IN ('signup','admin','organization','committee','access')", name='ck_px_ar_source'),
    CheckConstraint("(scope_type = 'site' AND site_id IS NOT NULL AND scope_id = site_id AND organization_id IS NULL) OR "
                    "(scope_type = 'organization' AND organization_id IS NOT NULL AND scope_id = organization_id AND site_id IS NULL)", name='ck_px_ar_scope'),
    CheckConstraint("membership_role IS NULL OR membership_role IN ('owner','admin','editor','analyst')", name='ck_px_ar_membership_role'),
    CheckConstraint("assignment_role IS NULL OR assignment_role IN ('event_manager','reception','scanner','committee_supervisor','analyst','auditor')", name='ck_px_ar_assignment_role'),
    CheckConstraint('expires_at > created_at', name='ck_px_ar_expiry'),
    # The application validates the complete salted scrypt encoding, not just its length.
    CheckConstraint("password_hash IS NULL OR (length(password_hash) = 161 AND substr(password_hash,33,1) = ':')", name='ck_px_ar_hash'),
    CheckConstraint("status = 'pending' OR password_hash IS NULL", name='ck_px_ar_terminal_secret'),
    CheckConstraint("status <> 'pending' OR (reviewed_by IS NULL AND reviewed_at IS NULL AND decision_reason IS NULL)", name='ck_px_ar_pending_review'),
    CheckConstraint("status NOT IN ('approved','rejected') OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)", name='ck_px_ar_review'),
    CheckConstraint("status <> 'rejected' OR (decision_reason IS NOT NULL AND length(trim(decision_reason)) > 0)", name='ck_px_ar_rejection_reason'),
)
Index('px_ar_pending_identity', account_requests.c.email, account_requests.c.scope_type, account_requests.c.scope_id,
      unique=True, sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'"))
Index('px_ar_scope_status_time', account_requests.c.scope_type, account_requests.c.scope_id, account_requests.c.status, account_requests.c.created_at)
Index('px_ar_supervisor_status_time', account_requests.c.supervisor_id, account_requests.c.status, account_requests.c.created_at)
Index('px_ar_status_expiry', account_requests.c.status, account_requests.c.expires_at)
