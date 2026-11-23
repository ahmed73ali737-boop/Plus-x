"""Phone/password accounts without OTP. Phone input never proves ownership.

Legacy px_users.email is a required unique login identifier. Phone-only accounts
use a reserved `tel:` principal in it, never a made-up deliverable email address.
The additive mapping avoids rebuilding the existing users table and foreign keys.
Public responses expose phone and null email for these principals.
"""
import re

from app.application.access import active_window, can_read, event_permissions
from app.application.ports import persistence
from app.domain.authorization import committee_roles
from app.domain.guests import PHONE_DIGIT_TRANSLATION, normalize_phone
from app.domain import Conflict, fail, text


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


def find_contact_user(tx, email, phone):
    by_phone = find_by_phone(tx, phone) if phone else None
    matches = persistence.identity.users_with_email(tx, email) if not email.startswith('tel:') else []
    if len(matches) > 1:
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)
    by_email = matches[0] if matches else None
    if by_phone and by_email and by_phone['id'] != by_email['id']:
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)
    return by_phone or by_email


def find_by_phone(tx, raw):
    return persistence.identity.user_by_phone(tx, account_phone(raw))


def bind_phone(tx, user_id, phone):
    existing = persistence.identity.phone_binding(tx, phone)
    if existing and existing['user_id'] != user_id:
        fail('PHONE_ALREADY_REGISTERED', Conflict)
    owned = persistence.identity.phone_binding_of(tx, user_id)
    if owned and owned['phone'] != phone:
        fail('PHONE_CHANGE_REQUIRES_SUPPORT', Conflict)
    if not existing:
        persistence.identity.bind_phone(tx, phone, user_id)


def public_user(tx, user):
    result = {key: user[key] for key in ('id', 'name', 'role', 'scope_id')}
    result['email'] = None if user['email'].startswith('tel:') else user['email']
    result['phone'] = persistence.identity.phone_of(tx, user['id'])
    result['must_change_password'] = bool(user.get('must_change_password'))
    result['management_access'] = bool(management_access(tx, user))
    result['can_review_account_requests'] = can_review_accounts(tx, user)
    return result


def management_access(tx, user):
    if persistence.access.has_active_membership(tx, user['id']):
        return True
    return any(can_read(tx, user, site) or (site['kind'] == 'event' and event_permissions(tx, user, site['id']))
               for site in persistence.sites.list_all(tx))


def can_review_accounts(tx, user):
    if user['role'] in ('platform', 'organizer'):
        return True
    if persistence.access.has_active_membership(tx, user['id'], role='owner'):
        return True
    return any(active_window(row) for row in persistence.access.user_assignments_with_roles(tx, user['id'], committee_roles()))
