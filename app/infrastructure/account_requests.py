"""Persistence primitives for phase 1; not an approval service or public API.

Callers must supply server-validated roles, scope and supervisor. Authorization,
transactional approval and route integration belong to the next phase. These
primitives never create users, sessions, memberships or assignments.
"""
from datetime import datetime, timezone
import re
import uuid

from sqlalchemy import insert, select, func
from sqlalchemy.exc import IntegrityError

from app.account_requests_db import account_requests
from app.core.security import hash_password
from app.db import users
from app.domain import fail, now, text

# Explicit projection: future storage fields are private until consciously exposed.
PUBLIC_FIELDS = (
    'id', 'email', 'name', 'phone', 'requested_role', 'scope_type', 'scope_id',
    'site_id', 'organization_id', 'event_id', 'person_id', 'participation_id',
    'membership_role', 'assignment_role', 'source', 'supervisor_id', 'requested_by',
    'reviewed_by', 'status', 'created_at', 'expires_at', 'reviewed_at', 'decision_reason',
)


def public_account_request(record):
    return {key: record[key] for key in PUBLIC_FIELDS}


def read_account_request(conn, request_id):
    """Internal projection; the application service must authorize its caller."""
    return conn.execute(select(*(account_requests.c[key] for key in PUBLIC_FIELDS))
                        .where(account_requests.c.id == request_id)).mappings().first()


def add_pending_account_request(conn, *, email, name, requested_role, scope_type,
                                scope_id, supervisor_id, expires_at, request_key,
                                source='admin', requested_by=None, password=None,
                                phone=None, event_id=None, person_id=None,
                                participation_id=None, membership_role=None,
                                assignment_role=None, allow_existing=False):
    """Insert a normalized pending record in the caller's transaction.

    password is accepted only as transient input and immediately scrypt-hashed.
    Omit it when a later approval flow will offer a time-limited setup link.
    No pending row or credential is automatically migrated into px_users.
    """
    email = text(email, 200, True).lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) and not (phone and email == 'tel:' + phone):
        fail('EMAIL_INVALID')
    name = text(name, 160, True)
    request_key = text(request_key, 80, True)
    if requested_role not in ('platform', 'organizer', 'agency', 'member'):
        fail('ACCOUNT_REQUEST_ROLE_INVALID')
    if scope_type not in ('site', 'organization'):
        fail('ACCOUNT_REQUEST_SCOPE_INVALID')
    try:
        expiry = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        if expiry.utcoffset() is None:
            raise ValueError('timezone required')
        expiry = expiry.astimezone(timezone.utc)
        created_at = now()
        if expiry <= datetime.fromisoformat(created_at):
            raise ValueError('already expired')
    except (AttributeError, TypeError, ValueError):
        fail('ACCOUNT_REQUEST_EXPIRY_INVALID')
    if not allow_existing and conn.execute(select(users.c.id).where(func.lower(func.trim(users.c.email)) == email)).first():
        fail('ACCOUNT_ALREADY_EXISTS', 409)
    record = dict(id=uuid.uuid4().hex, email=email, name=name,
                  phone=text(phone, 40) or None, requested_role=requested_role,
                  scope_type=scope_type, scope_id=scope_id,
                  site_id=scope_id if scope_type == 'site' else None,
                  organization_id=scope_id if scope_type == 'organization' else None,
                  supervisor_id=supervisor_id, requested_by=requested_by,
                  event_id=event_id, person_id=person_id, participation_id=participation_id,
                  membership_role=membership_role, assignment_role=assignment_role,
                  source=source, status='pending', created_at=created_at,
                  expires_at=expiry.isoformat(), reviewed_by=None, reviewed_at=None,
                  decision_reason=None,
                  request_key=request_key, password_hash=hash_password(password) if password is not None else None)
    try:
        with conn.begin_nested():
            conn.execute(insert(account_requests).values(**record))
    except IntegrityError:
        # Recover the transaction after a uniqueness race; never hide FK/schema errors.
        duplicate = conn.execute(select(account_requests.c.id).where(
            ((account_requests.c.email == email) | (account_requests.c.phone == phone)) if phone else account_requests.c.email == email, account_requests.c.scope_type == scope_type,
            account_requests.c.scope_id == scope_id, account_requests.c.status == 'pending')).first()
        if duplicate:
            fail('ACCOUNT_REQUEST_PENDING', 409)
        if conn.execute(select(account_requests.c.id).where(account_requests.c.request_key == request_key)).first():
            fail('ACCOUNT_REQUEST_KEY_EXISTS', 409)
        raise
    return public_account_request(record)
