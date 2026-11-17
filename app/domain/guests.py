"""Guest identity, event passes and guest registration rules."""
from __future__ import annotations

import re
import secrets

from app.domain.errors import Gone, NotFound, fail
from app.domain.values import boolean, text

PHONE_DIGIT_TRANSLATION = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
EVENT_PASS_PATTERN = re.compile(r'G-[0-9A-F]{30}')
# Admission links are server-owned; a registration body may never set these.
RESERVED_ADMISSION_METADATA = {'invitation_id', 'selected_days', 'party_size', 'entitlement_id', 'admission_managed'}
ACTIVE_PASS_STATUSES = ('registered', 'active')
DEFAULT_COUNTRY_CODE = '+967'
MIN_PASS_TOKEN_LENGTH = 32
PASS_ALLOCATION_ATTEMPTS = 8


def normalize_phone(raw, country_code=DEFAULT_COUNTRY_CODE) -> str:
    """Normalize a phone number to a stable E.164-like representation.

    Local numbers are combined with country_code so the same guest cannot be
    created twice merely because one entry used a local format and another used
    an international format.
    """
    value = text(raw, 40, True).translate(PHONE_DIGIT_TRANSLATION)
    compact = re.sub(r'[\s().-]+', '', value)
    if compact.startswith('00'):
        compact = '+' + compact[2:]
    if compact.startswith('+'):
        digits = compact[1:]
    else:
        digits = re.sub(r'\D', '', compact)
        prefix = re.sub(r'\D', '', text(country_code, 8, True).translate(PHONE_DIGIT_TRANSLATION))
        if not prefix:
            fail('COUNTRY_CODE_INVALID')
        local = digits.lstrip('0')
        digits = local if local.startswith(prefix) and len(local) >= len(prefix) + 6 else prefix + local
    if not digits.isdigit() or len(digits) < 8 or len(digits) > 15:
        fail('PHONE_INVALID')
    return '+' + digits


def new_event_pass_number() -> str:
    """120 random bits, independent of phone, global identity and other events."""
    return 'G-' + secrets.token_hex(15).upper()


def is_event_pass(number) -> bool:
    return bool(number) and bool(EVENT_PASS_PATTERN.fullmatch(number))


def pass_lookup_number(raw) -> str | None:
    """Canonical pass number for lookups; None when it cannot be a pass at all."""
    number = str(raw or '').upper()
    return number if EVENT_PASS_PATTERN.fullmatch(number) else None


def guest_qr_payload(event_slug: str, guest_number: str, public_origin: str) -> str:
    return f"{public_origin.rstrip('/')}/e/{event_slug}/guest/{guest_number}"


def registration_status(row: dict) -> str:
    return row.get('event_guest_status') or row.get('status') or 'registered'


def require_active_pass(guest: dict | None) -> dict:
    """A pass page/QR is only served for an existing, still-active registration."""
    if not guest:
        fail('GUEST_NOT_FOUND', NotFound)
    if guest.get('event_guest_status') not in ACTIVE_PASS_STATUSES:
        fail('GUEST_PASS_INACTIVE', Gone)
    return guest


def event_guest_view(row: dict) -> dict:
    """Joined guest+registration row; the public guest_number is the event pass."""
    result = dict(row)
    result['internal_guest_number'] = result['guest_number']
    result['guest_number'] = result.get('pass_number') or ''
    return result


def public_guest_view(row: dict) -> dict:
    # Possession of a pass URL is enough to render/scan the credential, but it
    # should not expose attendee classification, profile, phone, or timestamps.
    return {'guest_number': row['guest_number'], 'status': registration_status(row)}


def staff_guest_view(row: dict) -> dict:
    return {
        'id': row['id'],
        'guest_number': row['guest_number'],
        'phone': row['phone_e164'],
        'name': row.get('name') or '',
        'job_title': row.get('job_title') or '',
        'organization': row.get('organization') or '',
        'status': registration_status(row),
        'guest_type': row.get('guest_type') or 'visitor',
        'registered_at': row.get('registered_at'),
    }


class GuestRegistration:
    """Validated registration request for one event (value object).

    Every request-level value that can reject the registration is validated
    before any guest row is created or changed, so direct registration and
    offline sync stay atomic.
    """

    PROFILE_FIELDS = ('name', 'job_title', 'organization')

    def __init__(self, event: dict, body: dict, *, allow_guest_type: bool):
        if event['kind'] != 'event':
            fail('EVENT_REQUIRED', NotFound)
        if body.get('consent') is not True and not boolean(body.get('consent', False)):
            fail('GUEST_CONSENT_REQUIRED')
        self.supplied_pass_token = text(body.get('pass_token'), 200)
        if self.supplied_pass_token and len(self.supplied_pass_token) < MIN_PASS_TOKEN_LENGTH:
            fail('PASS_TOKEN_INVALID')
        requested_type = text(body.get('guest_type') or 'visitor', 40).lower()
        configured_types = {
            item.get('key')
            for item in (event.get('draft') or {}).get('access_control', {}).get('guest_types', [])
            if isinstance(item, dict)
        }
        self.guest_type = requested_type if allow_guest_type else 'visitor'
        if configured_types and self.guest_type not in configured_types:
            fail('GUEST_TYPE_INVALID')
        self.phone = normalize_phone(body.get('phone'), body.get('country_code') or DEFAULT_COUNTRY_CODE)
        self.profile = {
            'name': text(body.get('name'), 160),
            'job_title': text(body.get('job_title') or body.get('job'), 160),
            'organization': text(body.get('organization'), 200),
        }
        metadata = body.get('metadata')
        self.metadata = ({key: value for key, value in metadata.items() if key not in RESERVED_ADMISSION_METADATA}
                         if isinstance(metadata, dict) else {})

    def profile_updates(self, allow_profile_update: bool) -> dict:
        """A phone number is a deduplication key, not proof of possession.

        Public re-registration must not let somebody who knows a phone number
        overwrite an established profile; admin flows opt in explicitly.
        """
        if not allow_profile_update:
            return {}
        return {key: value for key, value in self.profile.items() if value}
