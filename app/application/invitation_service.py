"""Invitation lifecycle, atomic day entitlements and bounded CSV/XLSX import.

Use cases lock the event's admission policy before changing admission state.
No publicly supplied phone number is treated as a credential. The rules live in
app.domain.admission (AdmissionPolicy, Invitation, Entitlement).
"""
from __future__ import annotations

import base64
import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.application.audit_service import new_id
from app.application.guest_service import register_guest
from app.application.ports import persistence
from app.core.security import digest, new_session_token
from app.domain import Conflict, Forbidden, NotFound, fail, now, text
from app.domain.admission import (
    DEFAULT_POLICY,
    AdmissionPolicy,
    Entitlement,
    GuestImport,
    Invitation,
    check_window,
    day_list,
    integer,
    invitation_limits,
    iso_time,
    new_invitation,
    policy_from_record,
    require_active,
    require_token_shape,
    validate_current_days,
)
from app.domain.admission import assert_public_registration as _assert_public_registration
from app.domain.admission import clean_invitation as _clean_identity
from app.domain.guests import guest_qr_payload, new_event_pass_number
from app.xlsx_reader import Rejected, parse_xlsx

# Rules re-exported for callers of the previous module layout.
__all__ = [
    'DEFAULT_POLICY', 'assert_public_registration', 'by_token', 'check_window', 'clean_invitation',
    'consume_entitlement', 'create_invitation', 'day_list', 'entitlement_status', 'event_view', 'get_invitation',
    'get_policy', 'integer', 'iso_time', 'lock_policy', 'parse_guest_file', 'public_view', 'reserved_people',
    'respond', 'review', 'revoke', 'rotate', 'save_policy', 'staff_view', 'validate_current_days',
]


def _admission():
    return persistence.admission


def get_policy(tx, event_id):
    return policy_from_record(_admission().policy_record(tx, event_id))


def lock_policy(tx, event_id):
    _admission().lock_policy(tx, event_id)
    return get_policy(tx, event_id)


def _used(tx, invitation_id) -> bool:
    return _admission().consumed_total(tx, invitation_id) > 0


def reserved_people(tx, event_id, day, exclude=None) -> int:
    total = 0
    for invitation in _admission().invitations(tx, event_id):
        if invitation['id'] == exclude or day not in invitation['days']:
            continue
        consumed = 0 if invitation['status'] == 'approved' else _admission().consumed_for_day(tx, invitation['id'], day)
        total += Invitation.reserved_people(invitation, consumed)
    return total


def save_policy(tx, event_id, body):
    previous = get_policy(tx, event_id)
    current = lock_policy(tx, event_id)
    if previous['rev'] == 0:
        current['rev'] = 0
    revised = AdmissionPolicy.revise(current, body)
    all_invitations = _admission().invitations(tx, event_id)
    fixed = [inv for inv in all_invitations if inv['status'] == 'approved' or _used(tx, inv['id'])]
    AdmissionPolicy.guard_fixed_admissions(current, revised, fixed)
    if revised['enabled'] and not current['enabled']:
        _require_migrated_legacy_passes(tx, event_id)
    reserved = {item['date']: reserved_people(tx, event_id, item['date']) for item in revised['days']}
    AdmissionPolicy.guard_days(revised, fixed, reserved)
    _admission().save_policy(tx, event_id, revised, current['rev'] + 1)
    return {**revised, 'rev': current['rev'] + 1}


def _require_migrated_legacy_passes(tx, event_id) -> None:
    """Enabling managed admission requires every registered pass to belong to an invitation."""
    for registration in persistence.guests.registrations(tx, event_id, status='registered'):
        invitation_id = (registration['metadata_json'] or {}).get('invitation_id')
        linked = invitation_id and _admission().invitation_links_guest(tx, invitation_id, event_id, registration['guest_id'])
        if not linked:
            fail('LEGACY_PASSES_REQUIRE_MIGRATION', Conflict)


def assert_public_registration(tx, event_id):
    return _assert_public_registration(get_policy(tx, event_id))


def clean_invitation(tx, event_id, body):
    policy = get_policy(tx, event_id)
    values = _clean_identity(policy, body)
    if values['list_id'] and not _admission().guest_list_in_event(tx, values['list_id'], event_id):
        fail('GUEST_LIST_SCOPE', Forbidden)
    return {**values, **invitation_limits(policy, body)}


def create_invitation(tx, event_id, body):
    lock_policy(tx, event_id)
    values = clean_invitation(tx, event_id, body)
    if _admission().invitation_with_phone_exists(tx, event_id, values['phone']):
        fail('INVITATION_ALREADY_EXISTS', Conflict)
    token = new_session_token()
    row = new_invitation(new_id(), event_id, values, digest(token))
    _admission().add_invitation(tx, row)
    return row, token


def get_invitation(tx, event_id, invitation_id):
    row = _admission().invitation(tx, event_id, invitation_id)
    if not row:
        fail('INVITATION_NOT_FOUND', NotFound)
    return row


def by_token(tx, token):
    require_token_shape(token)
    row = _admission().invitation_by_token_hash(tx, digest(token))
    if not row:
        fail('INVITATION_NOT_FOUND', NotFound)
    return row


def _block_pass(tx, invitation, status):
    if invitation.get('guest_id'):
        persistence.guests.update_registration_of_guest(tx, invitation['event_id'], invitation['guest_id'],
                                                        {'status': status, 'updated_at': now()})
    _admission().revoke_entitlements(tx, invitation['id'])


def _approve(tx, event, invitation, policy, reviewer=None):
    reserved = {item['date']: reserved_people(tx, event['id'], item['date'], invitation['id'])
                for item in policy['days'] if item['date'] in invitation['days'] and item['capacity']}
    Invitation.check_capacity(invitation, policy, reserved)
    profile = {'phone': invitation['phone'], 'consent': True}
    if not persistence.guests.find_id_by_phone(tx, invitation['phone']):
        profile['name'] = invitation['name']
    guest = register_guest(tx, event, profile, allow_profile_update=True)
    registration = persistence.guests.registration(tx, event['id'], guest['id'])
    persistence.guests.update_registration(tx, registration['id'], {
        'status': 'registered',
        'metadata_json': {**registration['metadata_json'], 'invitation_id': invitation['id'],
                          'selected_days': invitation['days'], 'party_size': 1 + invitation['companions']},
        'updated_at': now(),
    })
    _admission().replace_entitlements(tx, invitation['id'], [
        {'id': new_id(), 'invitation_id': invitation['id'], 'event_id': event['id'], 'guest_id': guest['id'],
         'day': day, 'quantity': 1 + invitation['companions'], 'consumed': 0, 'status': 'active'}
        for day in Invitation.entitlement_slots(invitation, policy)
    ])
    return {'guest_id': guest['id'], 'status': 'approved', 'reviewed_by': reviewer, 'reviewed_at': now()}


def respond(tx, event, token, body):
    invitation = by_token(tx, token)
    if invitation['event_id'] != event['id']:
        fail('INVITATION_NOT_FOUND', NotFound)
    policy = lock_policy(tx, event['id'])
    invitation = by_token(tx, token)
    changes = Invitation.rsvp(invitation, policy, body)
    if changes is None:
        return invitation
    Invitation.forbid_after_attendance(_used(tx, invitation['id']))
    outcome = Invitation.outcome_after_rsvp(changes, policy)
    if outcome == 'declined':
        changes['status'] = 'declined'
        _block_pass(tx, invitation, 'cancelled')
    elif outcome == 'pending_approval':
        changes['status'] = 'pending_approval'
        _block_pass(tx, invitation, 'pending')
    else:
        changes.update(_approve(tx, event, {**invitation, **changes}, policy))
    _admission().update_invitation(tx, invitation['id'], changes)
    return {**invitation, **changes}


def review(tx, event, invitation_id, decision, reviewer, revision):
    policy = lock_policy(tx, event['id'])
    invitation = get_invitation(tx, event['id'], invitation_id)
    Invitation.check_review(invitation, decision, revision)
    Invitation.forbid_after_attendance(_used(tx, invitation_id))
    if decision == 'approve':
        values = _approve(tx, event, invitation, policy, reviewer)
    else:
        values = {'status': 'rejected', 'reviewed_by': reviewer, 'reviewed_at': now()}
        _block_pass(tx, invitation, 'cancelled')
    values.update(revision=invitation['revision'] + 1, updated_at=now())
    _admission().update_invitation(tx, invitation_id, values)
    return {**invitation, **values}


def revoke(tx, event_id, invitation_id):
    lock_policy(tx, event_id)
    invitation = get_invitation(tx, event_id, invitation_id)
    _block_pass(tx, invitation, 'revoked')
    _admission().update_invitation(tx, invitation_id, {'status': 'revoked', 'revision': invitation['revision'] + 1,
                                                       'updated_at': now()})
    return get_invitation(tx, event_id, invitation_id)


def rotate(tx, event_id, invitation_id):
    lock_policy(tx, event_id)
    invitation = get_invitation(tx, event_id, invitation_id)
    require_active(invitation)
    token = new_session_token()
    _admission().update_invitation(tx, invitation_id, {'token_hash': digest(token),
                                                       'revision': invitation['revision'] + 1, 'updated_at': now()})
    # Rotate the admission pass as well, invalidating the old printed QR.
    if invitation.get('guest_id'):
        persistence.guests.update_registration_of_guest(tx, event_id, invitation['guest_id'], {
            'pass_number': new_event_pass_number(), 'pass_token_hash': digest(new_session_token()),
            'updated_at': now(),
        })
    return get_invitation(tx, event_id, invitation_id), token


def staff_view(invitation):
    return {key: value for key, value in invitation.items() if key != 'token_hash'}


def event_view(event):
    config = event.get('draft') or {}
    return {'id': event['id'], 'slug': event['slug'], 'title': config.get('title') or event['slug'],
            **{key: config.get(key) or '' for key in ('start', 'end', 'location', 'description')}}


def public_view(tx, event, invitation, origin):
    fields = ('name', 'status', 'response', 'max_companions', 'companions', 'days', 'allowed_days', 'revision')
    result = {'invitation': {key: invitation[key] for key in fields}, 'event': event_view(event),
              'policy': get_policy(tx, event['id'])}
    if invitation['status'] == 'approved' and invitation.get('guest_id'):
        registration = persistence.guests.registration(tx, event['id'], invitation['guest_id'])
        if registration and registration.get('pass_number') and registration['status'] == 'registered':
            pass_url = guest_qr_payload(event['slug'], registration['pass_number'], origin)
            result.update(guest_number=registration['pass_number'], qr_url=pass_url, pass_url=pass_url,
                          qr_image_url=f"/api/public/events/{event['slug']}/guests/{registration['pass_number']}/qr")
    return result


def entitlement_status(tx, event, guest, body=None):
    body = body or {}
    invitation_id = (guest.get('metadata_json') or {}).get('invitation_id')
    if not invitation_id:
        return {'managed': False}
    invitation = get_invitation(tx, event['id'], invitation_id)
    Entitlement.check_scope(invitation, guest)
    policy = get_policy(tx, event['id'])
    # The server's event-local day is authoritative; client clocks cannot extend validity.
    day, slot = Entitlement.admission_day(invitation, policy, datetime.now(ZoneInfo(policy['timezone'])))
    entitlement = _admission().active_entitlement(tx, invitation_id, event['id'], guest['id'], slot)
    if not entitlement:
        fail('ENTITLEMENT_NOT_FOUND', Conflict)
    quantity = Entitlement.requested_quantity(entitlement, body)
    return {'managed': True, 'entitlement_id': entitlement['id'], 'quantity': quantity,
            'remaining': entitlement['quantity'] - entitlement['consumed'], 'day': day}


def admission_use(tx, scan_id):
    return _admission().admission_use(tx, scan_id)


def consume_entitlement(tx, event, guest, body):
    # Shared lifecycle lock prevents changing/rotating an entitlement while a
    # gate commits consumption. The gate takes this before presence locks.
    if (guest.get('metadata_json') or {}).get('invitation_id'):
        lock_policy(tx, event['id'])
    scan_id = text(body.get('scan_id'), 64, True)
    existing = _admission().admission_use(tx, scan_id)
    if existing:
        entitlement = _admission().entitlement(tx, existing['entitlement_id'])
        Entitlement.check_replay(entitlement, existing, event['id'], guest['id'], body.get('quantity', 1))
        return {'managed': True, 'duplicate': True, 'quantity': existing['quantity']}
    status = entitlement_status(tx, event, guest, body)
    if not status['managed']:
        return status
    if not _admission().consume(tx, status['entitlement_id'], status['quantity']):
        fail('ADMISSION_ALREADY_USED', Conflict)
    _admission().add_admission_use(tx, {'scan_id': scan_id, 'entitlement_id': status['entitlement_id'],
                                        'quantity': status['quantity'], 'used_at': now()})
    return {**status, 'remaining': status['remaining'] - status['quantity']}


# Staff use cases behind the invitation HTTP routes ---------------------------

def list_guest_lists(tx, event_id):
    return _admission().guest_lists(tx, event_id)


def create_guest_list(tx, event_id, body):
    row = {'id': new_id(), 'event_id': event_id, 'name': text(body.get('name'), 160, True), 'created_at': now()}
    if not _admission().add_guest_list_if_absent(tx, row):
        fail('GUEST_LIST_ALREADY_EXISTS', Conflict)
    return row


def invitation_overview(tx, event, origin):
    rows = [staff_view(row) for row in _admission().invitations(tx, event['id'], newest_first=True)]
    for row in rows:
        credential = public_view(tx, event, row, origin)
        row.update({key: credential[key] for key in ('guest_number', 'qr_url', 'pass_url', 'qr_image_url')
                    if key in credential})
    counts = {state: sum(row['status'] == state for row in rows)
              for state in ('invited', 'pending_approval', 'approved', 'declined', 'rejected', 'revoked')}
    people = sum(1 + row['companions'] for row in rows if row['status'] == 'approved')
    return {'invitations': rows, 'counts': counts, 'confirmed_people': people,
            'admission_uses': _admission().consumed_for_event(tx, event['id'])}


def preview_import(tx, event_id, user, body):
    raw = parse_guest_file(text(body.get('filename'), 200, True), body.get('content_base64'))
    rows, errors, seen = [], [], set()
    for index, item in enumerate(raw, 2):
        if body.get('list_id') and not item.get('list_id'):
            item['list_id'] = body['list_id']
        try:
            clean = clean_invitation(tx, event_id, item)
            if clean['phone'] in seen:
                fail('DUPLICATE_PHONE_IN_FILE')
            if _admission().invitation_with_phone_exists(tx, event_id, clean['phone']):
                fail('INVITATION_ALREADY_EXISTS', Conflict)
            seen.add(clean['phone'])
            rows.append({'name': clean['name'], 'phone': clean['phone'], 'list_id': clean['list_id'],
                         'max_companions': clean['max_companions'], 'days': clean['allowed_days']})
        except Exception as error:
            if not hasattr(error, 'detail'):
                raise
            errors.append({'row': index, 'error': error.detail})
    import_id = new_id()
    _admission().add_import(tx, {'id': import_id, 'event_id': event_id, 'user_id': user['id'], 'rows': rows,
                                 'errors': errors, 'state': 'preview', 'created_at': now()})
    return {'import_id': import_id, 'rows': rows, 'errors': errors, 'valid_count': len(rows), 'total_count': len(raw)}


def commit_import(tx, event_id, user, import_id):
    """Create every previewed invitation; returns (preview id, [(row, token), ...])."""
    preview = _admission().lock_import(tx, text(import_id, 64, True), event_id, user['id'])
    GuestImport.require_committable(preview, datetime.now(timezone.utc))
    created = [create_invitation(tx, event_id, row) for row in preview['rows']]
    _admission().mark_import_committed(tx, preview['id'])
    return preview['id'], created


def register_publicly(tx, event, body):
    """Public self-registration; returns (invitation, token) or None when verification is required."""
    from app.domain.guests import DEFAULT_COUNTRY_CODE, normalize_phone

    lock_policy(tx, event['id'])
    policy = assert_public_registration(tx, event['id'])
    phone = normalize_phone(body.get('phone'), body.get('country_code') or DEFAULT_COUNTRY_CODE)
    # Knowing a phone number must never recover an existing invitation/pass.
    if (_admission().invitation_with_phone_exists(tx, event['id'], phone)
            or persistence.guests.registered_with_phone(tx, event['id'], phone)):
        return None
    row, token = create_invitation(tx, event['id'], {'name': body.get('name'), 'phone': phone,
                                                     'max_companions': policy['max_companions']})
    return respond(tx, event, token, {**body, 'response': 'accepted'}), token


def parse_guest_file(filename, content_base64):
    raw = GuestImport.decode_upload(content_base64)
    kind = GuestImport.file_kind(filename)
    if kind == 'xlsx':
        try:
            workbook = parse_xlsx(raw)['workbook']
        except (Rejected, ValueError, KeyError):
            fail('IMPORT_XLSX_INVALID')
        if len(workbook) != 1:
            fail('IMPORT_ONE_SHEET_REQUIRED')
        values = next(iter(workbook.values()))
    else:
        try:
            values = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        except (UnicodeDecodeError, csv.Error):
            fail('IMPORT_CSV_INVALID')
    return GuestImport.rows_from_table(values)
