"""Phone/password accounts without OTP. Phone input never proves ownership.

Legacy px_users.email is a required unique login identifier. Phone-only accounts
use a reserved `tel:` principal in it, never a made-up deliverable email address.
The additive mapping avoids rebuilding the existing users table and foreign keys.
Public responses expose phone and null email for these principals.
"""
import re

from sqlalchemy import insert, select

from app.application.guest_service import PHONE_DIGIT_TRANSLATION, normalize_phone
from app.db import user_phones, users
from app.domain import fail, now, text


def account_phone(raw):
    value = text(raw, 40, True).translate(PHONE_DIGIT_TRANSLATION)
    if not re.fullmatch(r'(?:\+|00)?[0-9][0-9\s().-]*', value):
        fail('PHONE_INVALID')
    phone = normalize_phone(value)
    if phone.startswith('+967') and not re.fullmatch(r'\+9677[0-9]{8}', phone):
        fail('PHONE_INVALID')
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
        fail('PHONE_INVALID')
    return phone


def principal(phone):
    return 'tel:' + phone


def contact_identity(body, preserve_email=False):
    """Phone is primary for new UI; email-only legacy/operator callers still work."""
    phone = account_phone(body['phone']) if body.get('phone') else None
    email = text(body.get('email'), 200).lower()
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        fail('EMAIL_INVALID')
    if not phone and not email:
        fail('PHONE_REQUIRED')
    return (email if preserve_email and email else principal(phone) if phone else email), phone


def find_contact_user(conn, email, phone):
    by_phone = find_by_phone(conn, phone) if phone else None
    by_email = conn.execute(select(users).where(users.c.email == email)).mappings().first() if not email.startswith('tel:') else None
    if by_phone and by_email and by_phone['id'] != by_email['id']:
        fail('CONTACT_IDENTITIES_CONFLICT', 409)
    return by_phone or by_email


def find_by_phone(conn, raw):
    phone = account_phone(raw)
    return conn.execute(select(users).join(user_phones, users.c.id == user_phones.c.user_id).where(
        user_phones.c.phone == phone)).mappings().first()


def bind_phone(conn, user_id, phone):
    existing = conn.execute(select(user_phones).where(user_phones.c.phone == phone)).mappings().first()
    if existing and existing['user_id'] != user_id:
        fail('PHONE_ALREADY_REGISTERED', 409)
    owned = conn.execute(select(user_phones).where(user_phones.c.user_id == user_id)).mappings().first()
    if owned and owned['phone'] != phone:
        fail('PHONE_CHANGE_REQUIRES_SUPPORT', 409)
    if not existing:
        conn.execute(insert(user_phones).values(phone=phone, user_id=user_id, created_at=now()))


def public_user(conn, user):
    result = {k: user[k] for k in ('id', 'name', 'role', 'scope_id')}
    result['email'] = None if user['email'].startswith('tel:') else user['email']
    result['phone'] = conn.execute(select(user_phones.c.phone).where(user_phones.c.user_id == user['id'])).scalar()
    result['must_change_password'] = bool(user.get('must_change_password'))
    return result
