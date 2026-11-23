"""Gate use cases: validate a pass, record entry/exit scans, build offline manifests.

The rules (anti-passback, re-entry, checkpoint windows and guest types, offline
clock/policy checks) live in app.domain.gate and app.domain.access_control;
this module loads the aggregates, applies them and persists the outcome.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime

from app.application.audit_service import new_id
from app.application.guest_service import event_guest_by_number, list_event_guests
from app.application.invitation_service import admission_use, consume_entitlement, entitlement_status, get_policy, lock_policy
from app.application.ports import persistence
from app.domain import DomainError, NotFound, fail, now, text
from app.domain.access_control import AccessPolicy
from app.domain.gate import (
    ACCEPTED,
    ENTRY,
    EXIT,
    PRESENCE_STATES,
    SCAN_MODES,
    VALIDATE,
    GuestPresence,
    admission_denial,
    blocked_status,
    checkpoint_key,
    offline_scan_time,
    require_invitation_when_managed,
    require_scan_replay,
    require_unmanaged_quantity,
    require_valid_admission,
    scan_mode,
)
from app.domain.guests import registration_status, staff_guest_view

__all__ = [
    'PRESENCE_STATES', 'SCAN_MODES', 'access_config', 'access_policy_version', 'attendance_report',
    'build_guest_manifest', 'checkin_overview', 'event_presence_map', 'guest_presence_state', 'record_checkin',
    'validate_guest',
]


def _event(tx, event_or_id) -> dict:
    if isinstance(event_or_id, Mapping):
        return dict(event_or_id)
    event = persistence.sites.get(tx, event_or_id)
    if not event or event['kind'] != 'event':
        fail('EVENT_REQUIRED', NotFound)
    return event


def access_config(event: dict) -> dict:
    return AccessPolicy.from_site_config(event.get('draft')).to_dict()


def access_policy_version(access: dict) -> str:
    return AccessPolicy.from_site_config({'access_control': access}).version()


def _presence(tx, event_id: str, guest_id: str) -> GuestPresence:
    current = persistence.presence.get(tx, event_id, guest_id)
    if current is not None:
        return current
    return persistence.presence.add_if_absent(tx, GuestPresence.new(event_id, guest_id, now()))


def guest_presence_state(tx, event_id: str, guest_id: str) -> dict:
    return _presence(tx, event_id, guest_id).to_record()


def event_presence_map(tx, event_id: str) -> dict[str, dict]:
    return persistence.presence.for_event(tx, event_id)


def validate_guest(tx, event_or_id, guest_number: str, checkpoint: str = 'main', at_time: datetime | None = None,
                   *, check_admission=True, body=None) -> dict:
    event = _event(tx, event_or_id)
    event_id = event['id']
    guest = event_guest_by_number(tx, event_id, guest_number)
    if not guest:
        fail('GUEST_NOT_REGISTERED', NotFound)
    presence = _presence(tx, event_id, guest['id']).state
    view = staff_guest_view(guest)
    policy = AccessPolicy.from_site_config(event.get('draft'))
    reason = admission_denial(registration_status(guest), policy, checkpoint, guest.get('guest_type'), at_time)
    if reason:
        return {'status': 'invalid', 'reason': reason, 'guest': view, 'presence': presence}
    admission = {'managed': False}
    if check_admission:
        try:
            admission = entitlement_status(tx, event, guest, body)
            require_invitation_when_managed(get_policy(tx, event_id)['enabled'], admission)
        except DomainError as error:
            return {'status': 'invalid', 'reason': error.code, 'guest': view, 'presence': presence}
    return {
        'status': 'valid', 'guest': view, 'presence': presence,
        'checkpoint': policy.checkpoint_dict(checkpoint), 'access_control': policy.to_dict(), 'admission': admission,
    }


def _duplicate_scan_result(tx, event_id: str, guest_number: str, scan_id: str, mode: str, checkpoint: str,
                           existing: dict, quantity=1) -> dict:
    """An exact replay of an already recorded scan is idempotent; anything else conflicts."""
    use = admission_use(tx, scan_id)
    require_scan_replay(existing, use, event_id=event_id, guest_number=guest_number, mode=mode,
                        checkpoint=checkpoint, quantity=quantity)
    replay_guest = event_guest_by_number(tx, event_id, guest_number)
    if not replay_guest:
        fail('GUEST_NOT_REGISTERED', NotFound)
    current = _presence(tx, event_id, replay_guest['id'])
    return {
        'scan_id': scan_id, 'status': 'duplicate', 'mode': existing['direction'], 'direction': existing['direction'],
        'checkpoint': existing['checkpoint'], 'presence': current.state, 'guest': staff_guest_view(replay_guest),
        'admission': {'managed': bool(use), 'quantity': use['quantity'] if use else 1},
    }


def record_checkin(tx, event_or_id, guest_number: str, body: dict, *, scanner_id: str | None, source: str) -> dict:
    # Each scan is atomic even when the batch caller catches a rejected sibling.
    with persistence.transactions.savepoint(tx):
        return _record_checkin(tx, event_or_id, guest_number, body, scanner_id=scanner_id, source=source)


def _replay(tx, event_id, guest_number, scan_id, mode, checkpoint, body):
    existing = persistence.checkins.get(tx, scan_id)
    if existing:
        return _duplicate_scan_result(tx, event_id, guest_number, scan_id, mode, checkpoint, existing,
                                      body.get('quantity', 1))
    return None


def _record_checkin(tx, event_or_id, guest_number: str, body: dict, *, scanner_id: str | None, source: str) -> dict:
    event = _event(tx, event_or_id)
    event_id = event['id']
    mode = scan_mode(body.get('mode') or body.get('direction'))
    checkpoint = checkpoint_key(body.get('checkpoint'))

    # Resolve an exact replay before evaluating mutable access rules. If an ACK
    # was lost, the same scan stays idempotent even after a gate closes or changes.
    scan_id = None
    if mode != VALIDATE:
        scan_id = text(body.get('scan_id') or new_id(), 64, True)
        replay = _replay(tx, event_id, guest_number, scan_id, mode, checkpoint, body)
        if replay:
            return replay

    raw_guest = event_guest_by_number(tx, event_id, guest_number)
    if not raw_guest:
        fail('GUEST_NOT_REGISTERED', NotFound)
    if get_policy(tx, event_id)['enabled'] or (raw_guest.get('metadata_json') or {}).get('invitation_id'):
        lock_policy(tx, event_id)
    if mode != VALIDATE:
        _presence(tx, event_id, raw_guest['id'])
        # Serialize all entrances for one ticket on PostgreSQL as well as SQLite.
        persistence.presence.lock(tx, event_id, raw_guest['id'])
        replay = _replay(tx, event_id, guest_number, scan_id, mode, checkpoint, body)
        if replay:
            return replay

    admission_policy = get_policy(tx, event_id)
    policy = AccessPolicy.from_site_config(event.get('draft'))
    at_time = None
    if body.get('offline_scan') is True:
        at_time = offline_scan_time(policy, admission_managed=admission_policy['enabled'],
                                    supplied_version=body.get('access_policy_version'),
                                    client_time=body.get('client_time'))
    validated = validate_guest(tx, event, guest_number, checkpoint, at_time=at_time,
                               check_admission=mode != EXIT, body=body)
    guest = validated['guest']
    if mode == VALIDATE:
        return {
            'scan_id': text(body.get('scan_id') or new_id(), 64, True), 'status': validated['status'],
            'reason': validated.get('reason'), 'mode': VALIDATE, 'direction': None, 'checkpoint': checkpoint,
            'presence': validated['presence'], 'guest': guest, 'admission': validated.get('admission'),
        }
    require_valid_admission(validated)

    presence = _presence(tx, event_id, guest['id'])
    admission = validated.get('admission') or {'managed': False}
    managed = bool(admission.get('managed')) and mode == ENTRY
    if managed:
        admission = consume_entitlement(tx, event, raw_guest, {**body, 'scan_id': scan_id})
    else:
        require_unmanaged_quantity(body.get('quantity', 1))

    transition = presence.pass_gate(mode, checkpoint, scan_id, policy, entitlement_managed=managed, at=now())
    if not (transition.accepted and persistence.presence.save(tx, presence, transition)):
        return _blocked(tx, event_id, guest_number, scan_id, mode, checkpoint, body, guest, presence)

    recorded = persistence.checkins.add_if_absent(tx, {
        'id': scan_id, 'event_id': event_id, 'guest_id': guest['id'], 'guest_number': guest['guest_number'],
        'scanner_id': scanner_id, 'source': source, 'direction': mode, 'checkpoint': checkpoint,
        'client_time': text(body.get('client_time'), 64), 'scanned_at': now(),
    })
    if not recorded:
        replay = _replay(tx, event_id, guest_number, scan_id, mode, checkpoint, body)
        if replay:
            return replay
        raise RuntimeError('SCAN_RECORD_FAILED')
    return {
        'scan_id': scan_id, 'status': ACCEPTED, 'mode': mode, 'direction': mode, 'checkpoint': checkpoint,
        'presence': transition.next_state, 'guest': guest, 'admission': admission,
    }


def _blocked(tx, event_id, guest_number, scan_id, mode, checkpoint, body, guest, presence) -> dict:
    """Anti-passback refused the scan (in the domain, or by a concurrent change)."""
    replay = _replay(tx, event_id, guest_number, scan_id, mode, checkpoint, body)
    if replay:
        return replay
    current = persistence.presence.get(tx, event_id, guest['id']) or presence
    return {
        'scan_id': scan_id, 'status': blocked_status(mode), 'mode': mode, 'direction': mode,
        'checkpoint': checkpoint, 'presence': current.state, 'last_scan_id': current.last_scan_id,
        'last_checkpoint': current.last_checkpoint, 'guest': guest,
    }


def build_guest_manifest(tx, event_or_id) -> dict:
    event = _event(tx, event_or_id)
    event_id = event['id']
    presence = event_presence_map(tx, event_id)
    guests = []
    for guest in list_event_guests(tx, event_id):
        state = presence.get(guest['id'], {})
        guests.append({
            'guest_number': guest['guest_number'],
            'name': guest.get('name') or '',
            'organization': guest.get('organization') or '',
            'job_title': guest.get('job_title') or '',
            'guest_type': guest.get('guest_type') or 'visitor',
            'status': guest.get('status') or 'registered',
            'registered_at': guest.get('registered_at'),
            'presence': state.get('state', 'outside'),
            'last_direction': state.get('last_direction') or '',
            'last_checkpoint': state.get('last_checkpoint') or '',
            'presence_updated_at': state.get('updated_at') or '',
        })
    policy = AccessPolicy.from_site_config(event.get('draft'))
    access = policy.to_dict()
    source = json.dumps({'guests': guests, 'access_control': access}, ensure_ascii=False, sort_keys=True,
                        separators=(',', ':'))
    admission_managed = get_policy(tx, event_id)['enabled']
    return {
        'event_id': event_id,
        'generated_at': now(),
        'credential_version': 2,
        'manifest_version': hashlib.sha256(source.encode('utf-8')).hexdigest()[:20],
        'access_policy_version': policy.version(),
        'guest_count': len(guests),
        'admission_managed': admission_managed,
        'requires_online': admission_managed,
        'access_control': access,
        'guests': guests,
    }


def checkin_overview(tx, event_id: str) -> dict:
    presence = event_presence_map(tx, event_id)
    return {
        'checkins': persistence.checkins.for_event(tx, event_id, newest_first=True, limit=500),
        'total_checkins': persistence.checkins.count_for_event(tx, event_id),
        'admitted_people': persistence.admission.admitted_people(tx, event_id),
        'presence': [
            {'guest_id': guest_id, 'state': item.get('state', 'outside'), 'last_direction': item.get('last_direction'),
             'last_checkpoint': item.get('last_checkpoint'), 'updated_at': item.get('updated_at')}
            for guest_id, item in presence.items()
        ],
        'inside_count': sum(1 for item in presence.values() if item.get('state') == 'inside'),
    }


def attendance_report(tx, event_id: str) -> tuple[list[dict], dict[str, dict]]:
    """Registered guests plus per-guest entry/exit statistics (for the CSV export)."""
    guests = list_event_guests(tx, event_id)
    stats: dict[str, dict] = {}
    for scan in persistence.checkins.for_event(tx, event_id, newest_first=False):
        item = stats.setdefault(scan['guest_id'], {'entries': 0, 'exits': 0, 'first_entry': '', 'last_entry': ''})
        if scan['direction'] == ENTRY:
            item['entries'] += 1
            item['first_entry'] = item['first_entry'] or scan['scanned_at']
            item['last_entry'] = scan['scanned_at']
        else:
            item['exits'] += 1
    return guests, stats
