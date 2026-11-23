"""Phone/password account contact rules. Phone input never proves ownership.

Legacy px_users.email is a required unique login identifier. Phone-only accounts
use a reserved ``tel:`` principal in it, never a made-up deliverable email address.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from app.domain.errors import Conflict, fail
from app.domain.guests import PHONE_DIGIT_TRANSLATION, normalize_phone
from app.domain.values import text

PRINCIPAL_PREFIX = 'tel:'
EMAIL_PATTERN = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
YEMEN_MOBILE = re.compile(r'\+9677[0-9]{8}')
E164 = re.compile(r'\+[1-9][0-9]{7,14}')
PHONE_INPUT = re.compile(r'(?:\+|00)?[0-9][0-9\s().-]*')


def account_phone(raw) -> str:
    """Strict E.164 account phone; Yemeni (+967) numbers must be mobile numbers."""
    value = text(raw, 40, True).translate(PHONE_DIGIT_TRANSLATION)
    if not PHONE_INPUT.fullmatch(value):
        fail('PHONE_INVALID')
    phone = normalize_phone(value)
    if phone.startswith('+967') and not YEMEN_MOBILE.fullmatch(phone):
        fail('PHONE_INVALID')
    if not E164.fullmatch(phone):
        fail('PHONE_INVALID')
    return phone


def principal(phone: str) -> str:
    return PRINCIPAL_PREFIX + phone


def is_phone_principal(login: str) -> bool:
    return login.startswith(PRINCIPAL_PREFIX)


def public_email(login: str) -> str | None:
    """Phone-only principals expose a null email."""
    return None if is_phone_principal(login) else login


def contact_identity(body: dict, preserve_email: bool = False) -> tuple[str, str | None]:
    """Login identifier and phone: phone is primary for new UI; email-only legacy callers still work."""
    phone = account_phone(body['phone']) if body.get('phone') else None
    email = text(body.get('email'), 200).lower()
    if email and not EMAIL_PATTERN.fullmatch(email):
        fail('EMAIL_INVALID')
    if not phone and not email:
        fail('PHONE_REQUIRED')
    return (email if preserve_email and email else principal(phone) if phone else email), phone


def looks_up_by_email(login: str) -> bool:
    """Phone principals are never matched by email."""
    return not is_phone_principal(login)


def resolve_contact_user(by_phone: dict | None, email_matches: list[dict]) -> dict | None:
    """One person per contact: the phone and email identities must not name two accounts."""
    if len(email_matches) > 1:
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)
    by_email = email_matches[0] if email_matches else None
    if by_phone and by_email and by_phone['id'] != by_email['id']:
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)
    return by_phone or by_email


def phone_binding_action(existing: dict | None, owned: dict | None, user_id: str, phone: str) -> str:
    """'bind' when the phone is new for this account, 'keep' when it is already theirs.

    A phone owned by another account, or a second phone for an account that has one, needs support.
    """
    if existing and existing['user_id'] != user_id:
        fail('PHONE_ALREADY_REGISTERED', Conflict)
    if owned and owned['phone'] != phone:
        fail('PHONE_CHANGE_REQUIRES_SUPPORT', Conflict)
    return 'keep' if existing else 'bind'


def may_review_accounts(role: str, is_organization_owner: Callable[[], bool],
                        has_active_committee_role: Callable[[], bool]) -> bool:
    """Who sees the account-review queue: staff, organization owners and committee supervisors.

    The two facts are read lazily (each is a repository query), staff first.
    """
    return role in ('platform', 'organizer') or is_organization_owner() or has_active_committee_role()
