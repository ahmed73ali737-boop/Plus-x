"""Invitation lifecycle, atomic day entitlements and bounded CSV/XLSX import.

PostgreSQL serializes admission changes with the event policy row; SQLite uses
BEGIN IMMEDIATE. No publicly supplied phone number is treated as a credential.
"""
from __future__ import annotations
import base64
import csv
import io
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.exc import IntegrityError
from app.db import sites, event_guests, guests
from app.invitations_db import admission_policies, guest_lists, invitations, entitlements, admission_uses
from app.application.audit_service import new_id
from app.application.guest_service import normalize_phone, register_guest, guest_qr_payload
from app.core.security import digest, new_session_token
from app.domain import fail, now, text
from app.xlsx_reader import parse_xlsx, Rejected

DEFAULT_POLICY = {'enabled': False, 'visibility': 'public', 'timezone': 'Asia/Aden', 'registration_mode': 'auto',
                  'entry_mode': 'single', 'days': [], 'max_companions': 0, 'rsvp_deadline': None,
                  'registration_opens_at': None, 'registration_closes_at': None}

def integer(value, low, high, code):
    if isinstance(value, bool): fail(code)
    try:
        if str(int(value)) != str(value).strip(): fail(code)
        result = int(value)
    except (TypeError, ValueError): fail(code)
    if result < low or result > high: fail(code)
    return result

def iso_time(value):
    if not value: return None
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None: fail('TIMEZONE_OFFSET_REQUIRED')
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError): fail('DATETIME_INVALID')

def day_list(value):
    if not isinstance(value, list) or len(value) > 366: fail('DAYS_INVALID')
    result = []
    for item in value:
        try:
            day = date.fromisoformat(item).isoformat()
        except (ValueError, TypeError): fail('DAY_INVALID')
        if day != item or day in result: fail('DAY_INVALID_OR_DUPLICATE')
        result.append(day)
    return sorted(result)

def get_policy(conn, event_id):
    row = conn.execute(select(admission_policies).where(admission_policies.c.event_id == event_id)).mappings().first()
    return {**DEFAULT_POLICY, **(row['config'] if row else {}), 'rev': row['rev'] if row else 0}

def lock_policy(conn, event_id):
    row = conn.execute(select(admission_policies).where(admission_policies.c.event_id == event_id).with_for_update()).mappings().first()
    if not row:
        try:
            with conn.begin_nested():
                conn.execute(insert(admission_policies).values(event_id=event_id, config=DEFAULT_POLICY, rev=1, updated_at=now()))
        except IntegrityError: pass
        conn.execute(select(admission_policies).where(admission_policies.c.event_id == event_id).with_for_update()).first()
    return get_policy(conn, event_id)

def save_policy(conn, event_id, body):
    previous = get_policy(conn, event_id)
    old = lock_policy(conn, event_id)
    if previous['rev'] == 0: old['rev'] = 0
    if body.get('rev') is not None and body['rev'] != old['rev']: fail('ADMISSION_POLICY_REVISION_CONFLICT', 409)
    p = {k: body.get(k, old[k]) for k in DEFAULT_POLICY}
    if not isinstance(p['enabled'], bool): fail('ENABLED_BOOLEAN_REQUIRED')
    if p['visibility'] not in ('public', 'private', 'unlisted'): fail('VISIBILITY_INVALID')
    if p['registration_mode'] not in ('auto', 'manual'): fail('REGISTRATION_MODE_INVALID')
    if p['entry_mode'] not in ('single', 'daily'): fail('ENTRY_MODE_INVALID')
    try: ZoneInfo(p['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError): fail('TIMEZONE_INVALID')
    p['max_companions'] = integer(p['max_companions'], 0, 50, 'MAX_COMPANIONS_INVALID')
    if not isinstance(p['days'], list) or len(p['days']) > 366: fail('DAYS_INVALID')
    days = day_list([d.get('date') for d in p['days'] if isinstance(d, dict)])
    if len(days) != len(p['days']): fail('DAYS_INVALID')
    p['days'] = sorted([{'date': d['date'], 'capacity': integer(d.get('capacity', 0), 0, 1000000, 'CAPACITY_INVALID')} for d in p['days']], key=lambda d: d['date'])
    for key in ('rsvp_deadline', 'registration_opens_at', 'registration_closes_at'): p[key] = iso_time(p[key])
    if p['registration_opens_at'] and p['registration_closes_at'] and p['registration_opens_at'] >= p['registration_closes_at']: fail('REGISTRATION_WINDOW_INVALID')
    # Do not silently invalidate admitted people by shrinking days/capacity.
    all_invites = conn.execute(select(invitations).where(invitations.c.event_id == event_id)).mappings().all()
    approved = [inv for inv in all_invites if inv['status'] == 'approved']
    fixed = [inv for inv in all_invites if inv['status'] == 'approved' or _used(conn, inv['id'])]
    if fixed and p['entry_mode'] != old['entry_mode']: fail('ENTRY_MODE_HAS_APPROVALS', 409)
    if fixed and p['timezone'] != old['timezone']: fail('TIMEZONE_HAS_APPROVALS', 409)
    if fixed and old['enabled'] and not p['enabled']: fail('ADMISSION_POLICY_HAS_APPROVALS', 409)
    if p['enabled'] and not old['enabled']:
        legacy = conn.execute(select(event_guests).where(event_guests.c.event_id == event_id, event_guests.c.status == 'registered')).mappings().all()
        for row in legacy:
            iid = (row['metadata_json'] or {}).get('invitation_id')
            linked = conn.execute(select(invitations.c.id).where(invitations.c.id == iid, invitations.c.event_id == event_id, invitations.c.guest_id == row['guest_id'])).first() if iid else None
            if not linked: fail('LEGACY_PASSES_REQUIRE_MIGRATION', 409)
    for inv in fixed:
        if any(d not in days for d in inv['days']): fail('DAY_HAS_APPROVALS', 409)
        if not inv['days'] and days: fail('UNDATED_APPROVALS_EXIST', 409)
    for d in p['days']:
        reserved = reserved_people(conn, event_id, d['date'])
        if d['capacity'] and reserved > d['capacity']: fail('CAPACITY_BELOW_RESERVED', 409)
    conn.execute(update(admission_policies).where(admission_policies.c.event_id == event_id).values(config=p, rev=old['rev'] + 1, updated_at=now()))
    return {**p, 'rev': old['rev'] + 1}

def assert_public_registration(conn, event_id):
    p = get_policy(conn, event_id)
    if not p['enabled']: fail('ADMISSION_REGISTRATION_DISABLED', 409)
    if p['visibility'] == 'private': fail('INVITATION_REQUIRED', 403)
    check_window(p)
    return p

def check_window(policy):
    current = now()
    if policy['registration_opens_at'] and current < policy['registration_opens_at']: fail('REGISTRATION_NOT_OPEN', 409)
    if policy['registration_closes_at'] and current >= policy['registration_closes_at']: fail('REGISTRATION_CLOSED', 409)
    if policy['rsvp_deadline'] and current >= policy['rsvp_deadline']: fail('RSVP_DEADLINE_PASSED', 409)

def clean_invitation(conn, event_id, body):
    p = get_policy(conn, event_id)
    name = text(body.get('name'), 160, True)
    phone = normalize_phone(body.get('phone'), body.get('country_code') or '+967')
    list_id = text(body.get('list_id'), 64) or None
    if list_id and not conn.execute(select(guest_lists.c.id).where(guest_lists.c.id == list_id, guest_lists.c.event_id == event_id)).first(): fail('GUEST_LIST_SCOPE', 403)
    maximum = integer(body.get('max_companions', p['max_companions']), 0, p['max_companions'], 'MAX_COMPANIONS_INVALID')
    days = day_list(body.get('days', []))
    policy_days = {d['date'] for d in p['days']}
    if policy_days and any(d not in policy_days for d in days): fail('DAY_NOT_IN_EVENT')
    return {'name': name, 'phone': phone, 'list_id': list_id, 'max_companions': maximum, 'allowed_days': days}

def create_invitation(conn, event_id, body):
    lock_policy(conn, event_id)
    values = clean_invitation(conn, event_id, body)
    if conn.execute(select(invitations.c.id).where(invitations.c.event_id == event_id, invitations.c.phone == values['phone'])).first(): fail('INVITATION_ALREADY_EXISTS', 409)
    token = new_session_token()
    row = {'id': new_id(), 'event_id': event_id, **values, 'token_hash': digest(token), 'guest_id': None,
           'status': 'invited', 'response': 'pending', 'companions': 0, 'days': [], 'answers': {}, 'consent_at': None,
           'reviewed_by': None, 'reviewed_at': None, 'revision': 1, 'created_at': now(), 'updated_at': now()}
    conn.execute(insert(invitations).values(**row))
    return row, token

def get_invitation(conn, event_id, invitation_id):
    row = conn.execute(select(invitations).where(invitations.c.id == invitation_id, invitations.c.event_id == event_id)).mappings().first()
    if not row: fail('INVITATION_NOT_FOUND', 404)
    return dict(row)

def by_token(conn, token):
    if not isinstance(token, str) or len(token) < 32 or len(token) > 200: fail('INVITATION_NOT_FOUND', 404)
    row = conn.execute(select(invitations).where(invitations.c.token_hash == digest(token))).mappings().first()
    if not row: fail('INVITATION_NOT_FOUND', 404)
    return dict(row)

def _used(conn, invitation_id):
    return conn.execute(select(func.coalesce(func.sum(entitlements.c.consumed), 0)).where(entitlements.c.invitation_id == invitation_id)).scalar_one() > 0

def _block_pass(conn, invitation, status):
    if invitation.get('guest_id'):
        conn.execute(update(event_guests).where(event_guests.c.event_id == invitation['event_id'], event_guests.c.guest_id == invitation['guest_id']).values(status=status, updated_at=now()))
    conn.execute(update(entitlements).where(entitlements.c.invitation_id == invitation['id']).values(status='revoked'))

def reserved_people(conn, event_id, day, exclude=None):
    rows = conn.execute(select(invitations).where(invitations.c.event_id == event_id)).mappings().all()
    total = 0
    for row in rows:
        if row['id'] == exclude or day not in row['days']: continue
        if row['status'] == 'approved': total += 1 + row['companions']
        else:
            total += conn.execute(select(func.coalesce(func.sum(entitlements.c.consumed), 0)).where(entitlements.c.invitation_id == row['id'], entitlements.c.day.in_([day, '*']))).scalar_one()
    return total

def validate_current_days(invitation, policy):
    available = {d['date'] for d in policy['days']}
    if available and (not invitation['days'] or any(d not in available for d in invitation['days'])): fail('ATTENDANCE_DAYS_REQUIRED_OR_INVALID')
    if not available and invitation['days']: fail('DAY_NOT_IN_EVENT')

def _approve(conn, event, invitation, policy, reviewer=None):
    validate_current_days(invitation, policy)
    for d in policy['days']:
        if d['date'] in invitation['days'] and d['capacity']:
            total = reserved_people(conn, event['id'], d['date'], invitation['id'])
            if total + 1 + invitation['companions'] > d['capacity']: fail('DAY_CAPACITY_FULL', 409)
    known_profile = conn.execute(select(guests.c.id).where(guests.c.phone_e164 == invitation['phone'])).first()
    profile = {'phone': invitation['phone'], 'consent': True}
    if not known_profile: profile['name'] = invitation['name']
    guest = register_guest(conn, event, profile, allow_profile_update=True)
    reg = conn.execute(select(event_guests).where(event_guests.c.event_id == event['id'], event_guests.c.guest_id == guest['id'])).mappings().one()
    conn.execute(update(event_guests).where(event_guests.c.id == reg['id']).values(status='registered', metadata_json={**reg['metadata_json'], 'invitation_id': invitation['id'], 'selected_days': invitation['days'], 'party_size': 1 + invitation['companions']}, updated_at=now()))
    conn.execute(delete(entitlements).where(entitlements.c.invitation_id == invitation['id']))
    slots = invitation['days'] if policy['entry_mode'] == 'daily' and invitation['days'] else ['*']
    for day in slots:
        conn.execute(insert(entitlements).values(id=new_id(), invitation_id=invitation['id'], event_id=event['id'], guest_id=guest['id'], day=day, quantity=1 + invitation['companions'], consumed=0, status='active'))
    return {'guest_id': guest['id'], 'status': 'approved', 'reviewed_by': reviewer, 'reviewed_at': now()}

def respond(conn, event, token, body):
    invitation = by_token(conn, token)
    if invitation['event_id'] != event['id']: fail('INVITATION_NOT_FOUND', 404)
    p = lock_policy(conn, event['id'])
    invitation = by_token(conn, token)
    if invitation['status'] in ('revoked', 'rejected'): fail('INVITATION_INACTIVE', 409)
    check_window(p)
    response = body.get('response')
    if response not in ('accepted', 'declined'): fail('RSVP_RESPONSE_INVALID')
    if body.get('consent') is not True: fail('GUEST_CONSENT_REQUIRED')
    companions = integer(body.get('companions', 0), 0, invitation['max_companions'], 'COMPANIONS_INVALID')
    days = day_list(body.get('days', []))
    allowed = invitation['allowed_days'] or [d['date'] for d in p['days']]
    if response == 'accepted' and allowed and (not days or any(d not in allowed for d in days)): fail('ATTENDANCE_DAYS_REQUIRED_OR_INVALID')
    if not allowed and days: fail('DAY_NOT_IN_EVENT')
    if response == 'accepted': validate_current_days({**invitation, 'days': days}, p)
    answers = body.get('answers', {})
    if not isinstance(answers, dict) or len(json.dumps(answers, ensure_ascii=False)) > 8000: fail('ANSWERS_INVALID')
    if invitation['response'] == response and invitation['companions'] == companions and invitation['days'] == days and invitation['answers'] == answers:
        return invitation
    if _used(conn, invitation['id']): fail('ATTENDANCE_ALREADY_STARTED', 409)
    values = {'response': response, 'companions': companions, 'days': days, 'answers': answers, 'consent_at': now(), 'revision': invitation['revision'] + 1, 'updated_at': now(), 'reviewed_at': None, 'reviewed_by': None}
    pending = {**invitation, **values}
    if response == 'declined':
        values['status'] = 'declined'
        _block_pass(conn, invitation, 'cancelled')
    elif p['registration_mode'] == 'manual':
        values['status'] = 'pending_approval'
        _block_pass(conn, invitation, 'pending')
    else: values.update(_approve(conn, event, pending, p))
    conn.execute(update(invitations).where(invitations.c.id == invitation['id']).values(**values))
    return {**invitation, **values}

def review(conn, event, invitation_id, decision, reviewer, revision):
    p = lock_policy(conn, event['id'])
    invitation = get_invitation(conn, event['id'], invitation_id)
    if revision is None or isinstance(revision, bool) or revision != invitation['revision']: fail('INVITATION_REVISION_CONFLICT', 409)
    if decision not in ('approve', 'reject'): fail('REVIEW_DECISION_INVALID')
    if invitation['status'] != 'pending_approval' or invitation['response'] != 'accepted': fail('INVITATION_NOT_PENDING_REVIEW', 409)
    if _used(conn, invitation_id): fail('ATTENDANCE_ALREADY_STARTED', 409)
    if decision == 'approve': values = _approve(conn, event, invitation, p, reviewer)
    else:
        values = {'status': 'rejected', 'reviewed_by': reviewer, 'reviewed_at': now()}
        _block_pass(conn, invitation, 'cancelled')
    values.update(revision=invitation['revision'] + 1, updated_at=now())
    conn.execute(update(invitations).where(invitations.c.id == invitation_id).values(**values))
    return {**invitation, **values}

def revoke(conn, event_id, invitation_id):
    lock_policy(conn, event_id)
    invitation = get_invitation(conn, event_id, invitation_id)
    _block_pass(conn, invitation, 'revoked')
    conn.execute(update(invitations).where(invitations.c.id == invitation_id).values(status='revoked', revision=invitation['revision'] + 1, updated_at=now()))
    return get_invitation(conn, event_id, invitation_id)

def rotate(conn, event_id, invitation_id):
    lock_policy(conn, event_id)
    invitation = get_invitation(conn, event_id, invitation_id)
    if invitation['status'] in ('revoked', 'rejected'): fail('INVITATION_INACTIVE', 409)
    token = new_session_token()
    conn.execute(update(invitations).where(invitations.c.id == invitation_id).values(token_hash=digest(token), revision=invitation['revision'] + 1, updated_at=now()))
    # Rotate the admission pass as well, invalidating the old printed QR.
    if invitation.get('guest_id'):
        import secrets
        conn.execute(update(event_guests).where(event_guests.c.event_id == event_id, event_guests.c.guest_id == invitation['guest_id']).values(pass_number='G-' + secrets.token_hex(15).upper(), pass_token_hash=digest(new_session_token()), updated_at=now()))
    return get_invitation(conn, event_id, invitation_id), token

def staff_view(invitation):
    return {key: value for key, value in invitation.items() if key != 'token_hash'}

def event_view(event):
    config=event.get('draft') or {}
    return {'id':event['id'],'slug':event['slug'],'title':config.get('title') or event['slug'],
            **{key:config.get(key) or '' for key in ('start','end','location','description')}}


def public_view(conn, event, invitation, origin):
    fields = ('name', 'status', 'response', 'max_companions', 'companions', 'days', 'allowed_days', 'revision')
    result = {'invitation': {k: invitation[k] for k in fields}, 'event': event_view(event), 'policy': get_policy(conn, event['id'])}
    if invitation['status'] == 'approved' and invitation.get('guest_id'):
        reg = conn.execute(select(event_guests).where(event_guests.c.event_id == event['id'], event_guests.c.guest_id == invitation['guest_id'])).mappings().first()
        if reg and reg.get('pass_number') and reg['status'] == 'registered':
            result.update(guest_number=reg['pass_number'], qr_url=guest_qr_payload(event['slug'], reg['pass_number'], origin), pass_url=guest_qr_payload(event['slug'], reg['pass_number'], origin), qr_image_url=f"/api/public/events/{event['slug']}/guests/{reg['pass_number']}/qr")
    return result

def entitlement_status(conn, event, guest, body=None):
    body = body or {}
    meta = guest.get('metadata_json') or {}
    invitation_id = meta.get('invitation_id')
    if not invitation_id: return {'managed': False}
    invitation = get_invitation(conn, event['id'], invitation_id)
    if invitation['guest_id'] != guest['id']: fail('ENTITLEMENT_GUEST_SCOPE', 403)
    if invitation['status'] != 'approved': fail('INVITATION_INACTIVE', 409)
    p = get_policy(conn, event['id'])
    # The server's event-local day is authoritative; client clocks cannot extend validity.
    day = datetime.now(ZoneInfo(p['timezone'])).date().isoformat()
    if invitation['days'] and day not in invitation['days']: fail('ATTENDANCE_DAY_NOT_ALLOWED', 409)
    slot = day if p['entry_mode'] == 'daily' and invitation['days'] else '*'
    entitlement = conn.execute(select(entitlements).where(entitlements.c.invitation_id == invitation_id, entitlements.c.event_id == event['id'], entitlements.c.guest_id == guest['id'], entitlements.c.day == slot, entitlements.c.status == 'active')).mappings().first()
    if not entitlement: fail('ENTITLEMENT_NOT_FOUND', 409)
    quantity = integer(body.get('quantity', 1), 1, 51, 'ADMISSION_QUANTITY_INVALID')
    if quantity > entitlement['quantity'] - entitlement['consumed']: fail('ADMISSION_ALREADY_USED', 409)
    return {'managed': True, 'entitlement_id': entitlement['id'], 'quantity': quantity, 'remaining': entitlement['quantity'] - entitlement['consumed'], 'day': day}

def consume_entitlement(conn, event, guest, body):
    # Shared lifecycle lock prevents changing/rotating an entitlement while a
    # gate commits consumption. Gate adapter takes this before presence locks.
    if (guest.get('metadata_json') or {}).get('invitation_id'): lock_policy(conn, event['id'])
    scan_id = text(body.get('scan_id'), 64, True)
    existing = conn.execute(select(admission_uses).where(admission_uses.c.scan_id == scan_id)).mappings().first()
    if existing:
        entitlement = conn.execute(select(entitlements).where(entitlements.c.id == existing['entitlement_id'])).mappings().one()
        if entitlement['event_id'] != event['id'] or entitlement['guest_id'] != guest['id'] or existing['quantity'] != body.get('quantity', 1): fail('SCAN_ID_CONFLICT', 409)
        return {'managed': True, 'duplicate': True, 'quantity': existing['quantity']}
    status = entitlement_status(conn, event, guest, body)
    if not status['managed']: return status
    changed = conn.execute(update(entitlements).where(entitlements.c.id == status['entitlement_id'], entitlements.c.status == 'active', entitlements.c.consumed + status['quantity'] <= entitlements.c.quantity).values(consumed=entitlements.c.consumed + status['quantity']))
    if changed.rowcount != 1: fail('ADMISSION_ALREADY_USED', 409)
    conn.execute(insert(admission_uses).values(scan_id=scan_id, entitlement_id=status['entitlement_id'], quantity=status['quantity'], used_at=now()))
    return {**status, 'remaining': status['remaining'] - status['quantity']}

def parse_guest_file(filename, content_base64):
    try:
        if not isinstance(content_base64, str) or len(content_base64) > 4 * 1024 * 1024: fail('IMPORT_FILE_LIMIT')
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, TypeError): fail('IMPORT_BASE64_INVALID')
    if len(raw) > 3 * 1024 * 1024: fail('IMPORT_FILE_LIMIT')
    if filename.lower().endswith('.xlsx'):
        try:
            workbook = parse_xlsx(raw)['workbook']
        except (Rejected, ValueError, KeyError): fail('IMPORT_XLSX_INVALID')
        if len(workbook) != 1: fail('IMPORT_ONE_SHEET_REQUIRED')
        values = next(iter(workbook.values()))
    elif filename.lower().endswith('.csv'):
        try: values = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        except (UnicodeDecodeError, csv.Error): fail('IMPORT_CSV_INVALID')
    else: fail('IMPORT_CSV_OR_XLSX_REQUIRED')
    if not values or len(values) < 2 or len(values) > 1001: fail('IMPORT_ROWS_1_TO_1000')
    headers = [str(v).strip().lower() for v in values[0]]
    if len(set(headers)) != len(headers) or not {'name', 'phone'}.issubset(headers): fail('IMPORT_HEADERS_NAME_PHONE')
    if set(headers) - {'name', 'phone', 'list_id', 'max_companions', 'days'}: fail('IMPORT_UNKNOWN_COLUMN')
    rows = []
    for value in values[1:]:
        if not any(str(v).strip() for v in value): continue
        if len(value) > len(headers): fail('IMPORT_COLUMN_COUNT')
        row = {k: value[i] if i < len(value) else '' for i, k in enumerate(headers)}
        if not row.get('max_companions'): row.pop('max_companions', None)
        row['days'] = [x.strip() for x in str(row.get('days', '')).split(';') if x.strip()]
        rows.append(row)
    return rows
