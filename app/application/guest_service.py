"""Guest registration use cases (public, offline sync and staff registration)."""
from __future__ import annotations

import hashlib
import hmac
import os

from app.application.audit_service import new_id
from app.application.ports import persistence
from app.core.security import digest, new_session_token
from app.domain import now
from app.domain.guests import (
    EVENT_PASS_PATTERN,
    GuestRegistration,
    event_guest_view,
    new_event_pass_number,
    normalize_phone,
    pass_lookup_number,
    staff_guest_view,
)

# EVENT_PASS_PATTERN and normalize_phone remain importable from here for callers
# of the previous module layout (ops tools and tests).
__all__ = [
    'EVENT_PASS_PATTERN', 'backfill_event_pass_numbers', 'event_guest_by_number', 'guest_number_for_phone',
    'list_event_guests', 'normalize_phone', 'phone_hash', 'register_guest',
]


def _guest_identity_key() -> bytes:
    # Production requires GUEST_ID_SECRET via the release gate. The deterministic
    # fallback exists only so local/demo/test databases remain reproducible.
    raw = os.environ.get('GUEST_ID_SECRET') or 'pulsex-local-development-guest-identity-v1'
    return raw.encode('utf-8')


def _guest_hmac(namespace: str, phone_e164: str) -> str:
    return hmac.new(_guest_identity_key(), (namespace + ':' + phone_e164).encode('utf-8'), hashlib.sha256).hexdigest()


def phone_hash(phone_e164: str) -> str:
    # A keyed digest prevents an exported hash column from becoming a simple
    # phone-number enumeration oracle.
    return _guest_hmac('phone', phone_e164)


def guest_number_for_phone(phone_e164: str) -> str:
    # This stable identity is INTERNAL ONLY. A phone number is a deduplication
    # key, never evidence that its holder owns a pass for any event.
    value = _guest_hmac('guest-number', phone_e164).upper()
    return f'G-{value[:4]}-{value[4:8]}-{value[8:12]}-{value[12:16]}'


def backfill_event_pass_numbers(tx, event_id: str | None = None) -> int:
    """Upgrade legacy registrations inside a caller-owned write transaction."""
    return persistence.guests.backfill_pass_numbers(tx, event_id)


def _find_or_create_guest(tx, request: GuestRegistration, allow_profile_update: bool) -> tuple[dict, bool]:
    guests = persistence.guests
    p_hash = phone_hash(request.phone)
    g_number = guest_number_for_phone(request.phone)
    guest = guests.find_by_identity(tx, request.phone, p_hash, g_number)
    updated_at = now()
    if guest:
        updates = {'updated_at': updated_at, **request.profile_updates(allow_profile_update)}
        guests.update(tx, guest['id'], updates)
        return {**guest, **updates}, False
    candidate = {
        'id': new_id(), 'phone_e164': request.phone, 'phone_hash': p_hash, 'guest_number': g_number,
        **request.profile, 'updated_at': updated_at, 'status': 'active', 'created_at': now(),
    }
    if guests.add_if_absent(tx, candidate):
        return candidate, True
    guest = guests.find_by_identity(tx, request.phone, p_hash, g_number)
    if not guest:
        raise RuntimeError('GUEST_IDENTITY_RACE_UNRESOLVED')
    return guest, False


def register_guest(tx, event: dict, body: dict, *, allow_profile_update: bool = False,
                   allow_guest_type: bool = False) -> dict:
    request = GuestRegistration(event, body, allow_guest_type=allow_guest_type)
    guests = persistence.guests
    guest, created = _find_or_create_guest(tx, request, allow_profile_update)

    registration = guests.registration(tx, event['id'], guest['id'])
    registration_created = False
    issued_pass_token = None
    verified = False
    if not registration:
        issued_pass_token = request.supplied_pass_token or new_session_token()
        candidate = {
            'id': new_id(), 'event_id': event['id'], 'guest_id': guest['id'], 'status': 'registered',
            'guest_type': request.guest_type, 'pass_number': new_event_pass_number(),
            'pass_token_hash': digest(issued_pass_token), 'metadata_json': request.metadata,
            'registered_at': now(), 'updated_at': now(),
        }
        if guests.add_registration_if_absent(tx, candidate):
            registration = candidate
            registration_created = True
            verified = True
        else:
            issued_pass_token = None
            registration = guests.registration(tx, event['id'], guest['id'])
            if not registration:
                raise RuntimeError('GUEST_REGISTRATION_RACE_UNRESOLVED')
    if not registration_created:
        token_hash = registration.get('pass_token_hash')
        verified = bool(allow_profile_update or (
            token_hash and request.supplied_pass_token
            and hmac.compare_digest(token_hash, digest(request.supplied_pass_token))))
        if allow_profile_update and not token_hash:
            issued_pass_token = new_session_token()
            guests.update_registration(tx, registration['id'], {'pass_token_hash': digest(issued_pass_token), 'updated_at': now()})
            registration = {**registration, 'pass_token_hash': digest(issued_pass_token), 'updated_at': now()}
            verified = True
    if allow_guest_type and request.guest_type != registration.get('guest_type'):
        guests.update_registration(tx, registration['id'], {'guest_type': request.guest_type, 'updated_at': now()})
        registration = {**registration, 'guest_type': request.guest_type, 'updated_at': now()}
    pass_number = persistence.guests.ensure_pass_number(tx, registration)
    return {
        'id': guest['id'],
        'guest_number': pass_number,
        'phone': guest['phone_e164'],
        'name': guest.get('name') or '',
        'job_title': guest.get('job_title') or '',
        'organization': guest.get('organization') or '',
        'status': registration['status'],
        'guest_type': registration.get('guest_type') or 'visitor',
        'created': created,
        'event_registration_created': registration_created,
        'verified': verified,
        'pass_token': issued_pass_token,
    }


def event_guest_by_number(tx, event_id: str, guest_number: str):
    number = pass_lookup_number(guest_number)
    if number is None:
        return None
    row = persistence.guests.by_pass_number(tx, event_id, number)
    return event_guest_view(row) if row else None


def list_event_guests(tx, event_id: str) -> list[dict]:
    return [staff_guest_view(event_guest_view(row)) for row in persistence.guests.for_event(tx, event_id)]

