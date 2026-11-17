"""Managed admission: event admission policy, invitations and day entitlements.

Invitation lifecycle (state machine)::

    invited --respond(accepted, auto)--> approved
    invited --respond(accepted, manual)--> pending_approval --review--> approved | rejected
    any --respond(declined)--> declined
    any --revoke--> revoked
    revoked/rejected: inactive (no RSVP, no rotation)

An approved invitation owns one entitlement per selected day (``daily`` entry
mode) or a single ``*`` entitlement, each admitting ``1 + companions`` people.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.errors import Conflict, Forbidden, NotFound, fail
from app.domain.guests import DEFAULT_COUNTRY_CODE, normalize_phone
from app.domain.values import now, text

DEFAULT_POLICY = {
    'enabled': False, 'visibility': 'public', 'timezone': 'Asia/Aden', 'registration_mode': 'auto',
    'entry_mode': 'single', 'days': [], 'max_companions': 0, 'rsvp_deadline': None,
    'registration_opens_at': None, 'registration_closes_at': None,
}
VISIBILITIES = ('public', 'private', 'unlisted')
INACTIVE_INVITATION_STATUSES = ('revoked', 'rejected')
MAX_DAYS = 366
MAX_COMPANIONS = 50
MAX_CAPACITY = 1000000
MAX_PARTY_QUANTITY = 51
MAX_ANSWERS_JSON = 8000
ALL_DAYS = '*'


def integer(value, low, high, code):
    if isinstance(value, bool):
        fail(code)
    try:
        if str(int(value)) != str(value).strip():
            fail(code)
        result = int(value)
    except (TypeError, ValueError):
        fail(code)
    if result < low or result > high:
        fail(code)
    return result


def iso_time(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            fail('TIMEZONE_OFFSET_REQUIRED')
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        fail('DATETIME_INVALID')


def day_list(value):
    if not isinstance(value, list) or len(value) > MAX_DAYS:
        fail('DAYS_INVALID')
    result = []
    for item in value:
        try:
            day = date.fromisoformat(item).isoformat()
        except (ValueError, TypeError):
            fail('DAY_INVALID')
        if day != item or day in result:
            fail('DAY_INVALID_OR_DUPLICATE')
        result.append(day)
    return sorted(result)


def policy_from_record(record: dict | None) -> dict:
    """Stored policy merged over defaults; ``rev`` 0 means never saved."""
    return {**DEFAULT_POLICY, **(record['config'] if record else {}), 'rev': record['rev'] if record else 0}


class AdmissionPolicy:
    """Factory and change guards for an event's admission policy."""

    @staticmethod
    def revise(current: dict, body: dict) -> dict:
        """Validate a requested policy change against the current (locked) policy."""
        if body.get('rev') is not None and body['rev'] != current['rev']:
            fail('ADMISSION_POLICY_REVISION_CONFLICT', Conflict)
        policy = {key: body.get(key, current[key]) for key in DEFAULT_POLICY}
        if not isinstance(policy['enabled'], bool):
            fail('ENABLED_BOOLEAN_REQUIRED')
        if policy['visibility'] not in VISIBILITIES:
            fail('VISIBILITY_INVALID')
        if policy['registration_mode'] not in ('auto', 'manual'):
            fail('REGISTRATION_MODE_INVALID')
        if policy['entry_mode'] not in ('single', 'daily'):
            fail('ENTRY_MODE_INVALID')
        try:
            ZoneInfo(policy['timezone'])
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            fail('TIMEZONE_INVALID')
        policy['max_companions'] = integer(policy['max_companions'], 0, MAX_COMPANIONS, 'MAX_COMPANIONS_INVALID')
        if not isinstance(policy['days'], list) or len(policy['days']) > MAX_DAYS:
            fail('DAYS_INVALID')
        days = day_list([item.get('date') for item in policy['days'] if isinstance(item, dict)])
        if len(days) != len(policy['days']):
            fail('DAYS_INVALID')
        policy['days'] = sorted(
            [{'date': item['date'], 'capacity': integer(item.get('capacity', 0), 0, MAX_CAPACITY, 'CAPACITY_INVALID')}
             for item in policy['days']],
            key=lambda item: item['date'],
        )
        for key in ('rsvp_deadline', 'registration_opens_at', 'registration_closes_at'):
            policy[key] = iso_time(policy[key])
        if (policy['registration_opens_at'] and policy['registration_closes_at']
                and policy['registration_opens_at'] >= policy['registration_closes_at']):
            fail('REGISTRATION_WINDOW_INVALID')
        return policy

    @staticmethod
    def guard_fixed_admissions(current: dict, revised: dict, fixed: list[dict]) -> None:
        """Do not silently invalidate admitted people (approved or already used)."""
        if fixed and revised['entry_mode'] != current['entry_mode']:
            fail('ENTRY_MODE_HAS_APPROVALS', Conflict)
        if fixed and revised['timezone'] != current['timezone']:
            fail('TIMEZONE_HAS_APPROVALS', Conflict)
        if fixed and current['enabled'] and not revised['enabled']:
            fail('ADMISSION_POLICY_HAS_APPROVALS', Conflict)

    @staticmethod
    def guard_days(revised: dict, fixed: list[dict], reserved_by_day: dict[str, int]) -> None:
        days = [item['date'] for item in revised['days']]
        for invitation in fixed:
            if any(day not in days for day in invitation['days']):
                fail('DAY_HAS_APPROVALS', Conflict)
            if not invitation['days'] and days:
                fail('UNDATED_APPROVALS_EXIST', Conflict)
        for item in revised['days']:
            if item['capacity'] and reserved_by_day.get(item['date'], 0) > item['capacity']:
                fail('CAPACITY_BELOW_RESERVED', Conflict)


def check_window(policy: dict, current: str | None = None) -> None:
    current = current or now()
    if policy['registration_opens_at'] and current < policy['registration_opens_at']:
        fail('REGISTRATION_NOT_OPEN', Conflict)
    if policy['registration_closes_at'] and current >= policy['registration_closes_at']:
        fail('REGISTRATION_CLOSED', Conflict)
    if policy['rsvp_deadline'] and current >= policy['rsvp_deadline']:
        fail('RSVP_DEADLINE_PASSED', Conflict)


def assert_public_registration(policy: dict) -> dict:
    if not policy['enabled']:
        fail('ADMISSION_REGISTRATION_DISABLED', Conflict)
    if policy['visibility'] == 'private':
        fail('INVITATION_REQUIRED', Forbidden)
    check_window(policy)
    return policy


def clean_invitation(policy: dict, body: dict) -> dict:
    """Validate staff/import input for one invitation against the event policy."""
    name = text(body.get('name'), 160, True)
    phone = normalize_phone(body.get('phone'), body.get('country_code') or DEFAULT_COUNTRY_CODE)
    list_id = text(body.get('list_id'), 64) or None
    return {'name': name, 'phone': phone, 'list_id': list_id}


def invitation_limits(policy: dict, body: dict) -> dict:
    maximum = integer(body.get('max_companions', policy['max_companions']), 0, policy['max_companions'],
                      'MAX_COMPANIONS_INVALID')
    days = day_list(body.get('days', []))
    policy_days = {item['date'] for item in policy['days']}
    if policy_days and any(day not in policy_days for day in days):
        fail('DAY_NOT_IN_EVENT')
    return {'max_companions': maximum, 'allowed_days': days}


def new_invitation(invitation_id: str, event_id: str, values: dict, token_hash: str) -> dict:
    return {
        'id': invitation_id, 'event_id': event_id, **values, 'token_hash': token_hash, 'guest_id': None,
        'status': 'invited', 'response': 'pending', 'companions': 0, 'days': [], 'answers': {},
        'consent_at': None, 'reviewed_by': None, 'reviewed_at': None, 'revision': 1,
        'created_at': now(), 'updated_at': now(),
    }


def validate_current_days(invitation: dict, policy: dict) -> None:
    available = {item['date'] for item in policy['days']}
    if available and (not invitation['days'] or any(day not in available for day in invitation['days'])):
        fail('ATTENDANCE_DAYS_REQUIRED_OR_INVALID')
    if not available and invitation['days']:
        fail('DAY_NOT_IN_EVENT')


def require_active(invitation: dict) -> None:
    if invitation['status'] in INACTIVE_INVITATION_STATUSES:
        fail('INVITATION_INACTIVE', Conflict)


def require_token_shape(token) -> None:
    if not isinstance(token, str) or len(token) < 32 or len(token) > 200:
        fail('INVITATION_NOT_FOUND', NotFound)


class Invitation:
    """Invitation aggregate rules; state is the stored invitation record."""

    @staticmethod
    def rsvp(invitation: dict, policy: dict, body: dict) -> dict | None:
        """Validate an RSVP. Returns the changed fields, or None for an exact repeat."""
        require_active(invitation)
        check_window(policy)
        response = body.get('response')
        if response not in ('accepted', 'declined'):
            fail('RSVP_RESPONSE_INVALID')
        if body.get('consent') is not True:
            fail('GUEST_CONSENT_REQUIRED')
        companions = integer(body.get('companions', 0), 0, invitation['max_companions'], 'COMPANIONS_INVALID')
        days = day_list(body.get('days', []))
        allowed = invitation['allowed_days'] or [item['date'] for item in policy['days']]
        if response == 'accepted' and allowed and (not days or any(day not in allowed for day in days)):
            fail('ATTENDANCE_DAYS_REQUIRED_OR_INVALID')
        if not allowed and days:
            fail('DAY_NOT_IN_EVENT')
        if response == 'accepted':
            validate_current_days({**invitation, 'days': days}, policy)
        answers = body.get('answers', {})
        if not isinstance(answers, dict) or len(json.dumps(answers, ensure_ascii=False)) > MAX_ANSWERS_JSON:
            fail('ANSWERS_INVALID')
        if (invitation['response'] == response and invitation['companions'] == companions
                and invitation['days'] == days and invitation['answers'] == answers):
            return None
        return {
            'response': response, 'companions': companions, 'days': days, 'answers': answers,
            'consent_at': now(), 'revision': invitation['revision'] + 1, 'updated_at': now(),
            'reviewed_at': None, 'reviewed_by': None,
        }

    @staticmethod
    def outcome_after_rsvp(changes: dict, policy: dict) -> str:
        """declined | pending_approval | approve (caller approves and allocates)."""
        if changes['response'] == 'declined':
            return 'declined'
        return 'pending_approval' if policy['registration_mode'] == 'manual' else 'approve'

    @staticmethod
    def check_review(invitation: dict, decision, revision) -> None:
        if revision is None or isinstance(revision, bool) or revision != invitation['revision']:
            fail('INVITATION_REVISION_CONFLICT', Conflict)
        if decision not in ('approve', 'reject'):
            fail('REVIEW_DECISION_INVALID')
        if invitation['status'] != 'pending_approval' or invitation['response'] != 'accepted':
            fail('INVITATION_NOT_PENDING_REVIEW', Conflict)

    @staticmethod
    def forbid_after_attendance(used: bool) -> None:
        if used:
            fail('ATTENDANCE_ALREADY_STARTED', Conflict)

    @staticmethod
    def check_capacity(invitation: dict, policy: dict, reserved_by_day: dict[str, int]) -> None:
        """Approving must fit every selected day's remaining capacity."""
        validate_current_days(invitation, policy)
        party = 1 + invitation['companions']
        for item in policy['days']:
            if item['date'] in invitation['days'] and item['capacity']:
                if reserved_by_day.get(item['date'], 0) + party > item['capacity']:
                    fail('DAY_CAPACITY_FULL', Conflict)

    @staticmethod
    def entitlement_slots(invitation: dict, policy: dict) -> list[str]:
        return invitation['days'] if policy['entry_mode'] == 'daily' and invitation['days'] else [ALL_DAYS]

    @staticmethod
    def reserved_people(invitation: dict, consumed_for_day: int) -> int:
        """Approved invitations reserve their whole party; others only what they used."""
        return 1 + invitation['companions'] if invitation['status'] == 'approved' else consumed_for_day


class Entitlement:
    """Admission entitlement rules (consumption is counted per scan)."""

    @staticmethod
    def admission_day(invitation: dict, policy: dict, current: datetime | None = None) -> tuple[str, str]:
        """Today's event-local day and the entitlement slot it consumes.

        The server's event-local day is authoritative; client clocks cannot extend validity.
        """
        current = current or datetime.now(ZoneInfo(policy['timezone']))
        day = current.astimezone(ZoneInfo(policy['timezone'])).date().isoformat()
        if invitation['days'] and day not in invitation['days']:
            fail('ATTENDANCE_DAY_NOT_ALLOWED', Conflict)
        slot = day if policy['entry_mode'] == 'daily' and invitation['days'] else ALL_DAYS
        return day, slot

    @staticmethod
    def check_scope(invitation: dict, guest: dict) -> None:
        if invitation['guest_id'] != guest['id']:
            fail('ENTITLEMENT_GUEST_SCOPE', Forbidden)
        if invitation['status'] != 'approved':
            fail('INVITATION_INACTIVE', Conflict)

    @staticmethod
    def requested_quantity(entitlement: dict, body: dict) -> int:
        quantity = integer(body.get('quantity', 1), 1, MAX_PARTY_QUANTITY, 'ADMISSION_QUANTITY_INVALID')
        if quantity > entitlement['quantity'] - entitlement['consumed']:
            fail('ADMISSION_ALREADY_USED', Conflict)
        return quantity

    @staticmethod
    def check_replay(entitlement: dict, use: dict, event_id: str, guest_id: str, quantity) -> None:
        if entitlement['event_id'] != event_id or entitlement['guest_id'] != guest_id or use['quantity'] != quantity:
            fail('SCAN_ID_CONFLICT', Conflict)
