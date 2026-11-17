"""Account approval use cases. All writes run inside the caller's transaction.

No route may insert a login identity. Guest/RSVP/QR paths never call this module.
A tracking capability is returned only to its holder, never to reviewers.
The rules live in app.domain.account_requests.
"""
import os
import secrets

from app.application.access import active_window, event_permissions, organization_visible
from app.application.audit_service import new_id, write_audit
from app.application.phone_accounts import bind_phone, contact_identity, find_contact_user
from app.application.ports import persistence
from app.core.security import digest, hash_password
from app.domain import Conflict, Forbidden, NotFound, Unavailable, fail, now, text
from app.domain.account_requests import (
    SETUP_DAYS,
    SOURCES,
    assignment_window,
    check_person_link,
    check_reviewer,
    check_roles,
    check_target,
    decision_reason,
    delegated_grant_allowed,
    expires,
    granted_assignment_role,
    may_supervise,
    new_login,
    payload_fingerprint_source,
    public_account_request,
    request_key,
    require_tracking_token,
    setup_available,
    signup_entities as new_signup_entities,
    submitted_password,
    supervisor_preference,
)

__all__ = [
    'accept_platform_invite', 'active_window', 'authorized', 'cancel', 'expire_pending', 'expires',
    'inspect_platform_invite', 'invite_platform_candidate', 'list_for_reviewer', 'list_submitted', 'org_reviewer',
    'organization_visible', 'renew_setup', 'request_scope_id', 'review', 'setup_password', 'status', 'submit', 'view',
]


def _requests():
    return persistence.account_requests


def _close(tx, request_id, status, *, only_pending=False, **extra):
    values = {'status': status, 'password_hash': None, 'reviewed_at': now(), **extra}
    _requests().close(tx, request_id, values, only_pending=only_pending)
    sync_legacy(tx, request_id, status)
    return values


def expire_pending(tx):
    ids = _requests().expired_pending_ids(tx, now())
    for request_id in ids:
        _close(tx, request_id, 'expired', only_pending=True)
        write_audit(tx, None, None, 'account_request_expired', {'request_id': request_id})
    return len(ids)


def org_reviewer(tx, actor, organization_id, sensitive=False):
    if actor['role'] == 'platform':
        return True
    if actor['role'] == 'organizer' and _requests().organizer_runs_organization(tx, organization_id, actor['scope_id']):
        return True
    return not sensitive and persistence.site_admin.is_active_owner(tx, actor['id'], organization_id)


def authorized(tx, actor, record):
    if not actor or not actor['active']:
        return False
    if record['scope_type'] == 'organization':
        return org_reviewer(tx, actor, record['scope_id'], record.get('membership_role') in ('owner', 'admin'))
    site = persistence.sites.get(tx, record['scope_id'])
    if not site:
        return False
    if record['requested_role'] in ('platform', 'organizer') or site['kind'] == 'platform':
        return actor['role'] == 'platform'
    event_id = site['id'] if site['kind'] == 'event' else site['event_id']
    if actor['role'] == 'platform':
        return True
    if record.get('assignment_role'):
        return delegated_grant_allowed(record['assignment_role'], event_permissions(tx, actor, event_id))
    return actor['role'] == 'organizer' and actor['scope_id'] == event_id


def choose_supervisor(tx, record, actor=None):
    actor_id = (actor or {}).get('id')
    for candidate in sorted(_requests().active_users(tx), key=supervisor_preference(actor_id)):
        if may_supervise(candidate, record, actor_id) and authorized(tx, candidate, record):
            return candidate['id']
    fail('ACCOUNT_REQUEST_SUPERVISOR_UNAVAILABLE', Conflict)


def check_submitter(tx, actor, record):
    if actor is None:
        return
    if not actor['active']:
        fail('FORBIDDEN_ROLE', Forbidden)
    if record['scope_type'] == 'organization':
        if not org_reviewer(tx, actor, record['scope_id'], False):
            fail('FORBIDDEN_SCOPE', Forbidden)
    elif not authorized(tx, actor, record):
        # An organizer may submit organizer requests for platform review in their event.
        if not (record['requested_role'] == 'organizer' and actor['role'] == 'organizer'
                and actor['scope_id'] == record['scope_id']):
            fail('FORBIDDEN_SCOPE', Forbidden)


def submit(tx, *, actor, body, purpose, scope_type, scope_id, role, membership_role=None,
           assignment_role=None, person_id=None, signup_id=None, access_id=None):
    if os.environ.get('ACCOUNT_REQUESTS_ACCEPTING', 'true').lower() not in ('true', '1', 'yes'):
        fail('ACCOUNT_REQUESTS_PAUSED', Unavailable)
    expire_pending(tx)
    email, phone = contact_identity(body, preserve_email=True)
    initial_target = find_contact_user(tx, email, phone)
    name = text(body.get('name') or body.get('contact_name') or (initial_target['name'] if initial_target else None),
                160, True)
    check_roles(role, membership_role, assignment_role)
    record = dict(email=email, requested_role=role, scope_type=scope_type, scope_id=scope_id,
                  membership_role=membership_role, assignment_role=assignment_role)
    check_submitter(tx, actor, record)
    target = find_contact_user(tx, email, phone)
    check_target(purpose, role, target, body)
    password = submitted_password(actor, body)
    token = request_key(body.get('request_key'), secrets.token_urlsafe(32))
    key = digest(token)
    fingerprint = digest(payload_fingerprint_source(email, phone, name, purpose, scope_type, scope_id, role,
                                                    membership_role, assignment_role, person_id, body))
    old = _requests().by_request_key(tx, key)
    if old:
        if old['payload_hash'] != fingerprint:
            fail('ACCOUNT_REQUEST_KEY_EXISTS', Conflict)
        return {**view(tx, old), 'tracking_token': token, 'already_pending': True, 'grants_access': False}
    start, end = assignment_window(body)
    supervisor = choose_supervisor(tx, {**record, 'existing_user_id': target['id'] if target else None}, actor)
    saved = _requests().add_pending(
        tx, **record, name=name, phone=phone, supervisor_id=supervisor, requested_by=actor['id'] if actor else None,
        expires_at=expires(), request_key=key, source=SOURCES[purpose],
        password=password if not target else None, person_id=person_id, allow_existing=True)
    _requests().add_workflow(tx, {
        'request_id': saved['id'], 'purpose': purpose, 'tracking_hash': key, 'payload_hash': fingerprint,
        'existing_user_id': target['id'] if target else None, 'signup_id': signup_id, 'access_id': access_id,
        'valid_from': start or None, 'valid_until': end or None,
    })
    write_audit(tx, actor, scope_id if scope_type == 'site' else None, 'account_request_submitted',
                {'request_id': saved['id'], 'scope_type': scope_type, 'scope_id': scope_id})
    return {**view(tx, saved), 'tracking_token': token, 'grants_access': False}


def context(tx, request_id):
    row = _requests().workflow(tx, request_id)
    if not row:
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)
    return row


def request_scope_id(tx, request_id):
    return _requests().request(tx, request_id)['scope_id']


def view(tx, record):
    result = public_account_request(record)
    workflow = context(tx, record['id'])
    signup = _requests().signup(tx, workflow['signup_id']) if workflow['signup_id'] else None
    if record['scope_type'] == 'organization':
        scope_name = _requests().organization_name(tx, record['scope_id'])
    else:
        scope_name = _requests().site_title(tx, record['scope_id'])
    setup_expires_at = workflow['setup_expires_at']
    result.update(
        account_requested=bool(signup['wants_account']) if signup else True,
        organization_name=signup['organization_name'] if signup else None,
        scope_name=scope_name or record['scope_id'],
        purpose=workflow['purpose'], user_id=workflow['user_id'],
        supervisor_name=_requests().user_name(tx, record['supervisor_id']),
        setup_required=bool(setup_expires_at and record['status'] == 'approved'),
        setup_expired=bool(setup_expires_at and setup_expires_at <= now()),
        setup_expires_at=setup_expires_at, result_site_id=workflow['result_site_id'],
        result_organization_id=workflow['result_organization_id'],
    )
    if result['email'].startswith('tel:'):
        result['email'] = None
    return result


def list_for_reviewer(tx, actor, status=None, scope_id=None):
    expire_pending(tx)
    return [view(tx, record) for record in _requests().supervised_by(tx, actor['id'], status, scope_id)
            if authorized(tx, actor, record)]


def sync_legacy(tx, request_id, status):
    workflow = _requests().workflow(tx, request_id)
    if workflow:
        _requests().sync_legacy_status(tx, workflow, status)


def signup_entities(tx, record, workflow):
    signup = _requests().signup(tx, workflow['signup_id'])
    organization, site, participation = new_signup_entities(record['id'], signup, new_id(), new_id(), new_id(), now())
    _requests().add_organization(tx, organization)
    _requests().add_site(tx, site)
    if participation:
        _requests().add_participation(tx, participation)
    return site['id'], organization['id']


def approve_links(tx, record, workflow, target, site_id, organization_id):
    user_id = target['id']
    if organization_id:
        _requests().upsert_membership(tx, user_id, organization_id,
                                      {'role': record['membership_role'] or 'owner', 'status': 'active'}, now())
    assignment_role = granted_assignment_role(record, workflow, organization_id)
    if assignment_role:
        _requests().upsert_assignment(tx, new_id(), user_id, site_id, assignment_role, {
            'status': 'active', 'valid_from': workflow['valid_from'], 'valid_until': workflow['valid_until'],
        }, now())
    if record['person_id']:
        person = _requests().person(tx, record['person_id'])
        check_person_link(person, organization_id, user_id)
        _requests().link_person(tx, person['id'], user_id)


def _approve_identity(tx, record, workflow, request_id):
    _requests().lock_identities(tx, {record['email'], record['phone'] or record['email']})
    target = find_contact_user(tx, record['email'], record['phone'])
    if workflow['purpose'] == 'personal' and target:
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)
    if workflow['existing_user_id'] and (not target or target['id'] != workflow['existing_user_id']):
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)
    site_id = record['scope_id'] if record['scope_type'] == 'site' else None
    organization_id = record['organization_id']
    if workflow['purpose'] == 'signup':
        site_id, organization_id = signup_entities(tx, record, workflow)
    if organization_id and not site_id:
        site_id = _requests().latest_active_agency_site(tx, organization_id)
    is_new = not target
    if target and not target['active']:
        fail('ACCOUNT_SUSPENDED', Conflict)
    if not target:
        hashed = record['password_hash'] or hash_password(secrets.token_urlsafe(32))
        target = new_login(new_id(), record, workflow, site_id, hashed)
        _requests().add_user(tx, target)
        if record['phone']:
            bind_phone(tx, target['id'], record['phone'])
    approve_links(tx, record, workflow, target, site_id, organization_id)
    _requests().update_workflow(tx, request_id, {
        'user_id': target['id'], 'result_site_id': site_id, 'result_organization_id': organization_id,
        'setup_expires_at': expires(SETUP_DAYS) if is_new and not record['password_hash'] else None,
    })


def review(tx, actor, request_id, action, reason=None):
    actor = persistence.identity.user(tx, actor['id'], for_update=True)
    record = _requests().request(tx, request_id, for_update=True)
    if not record or record['supervisor_id'] != actor['id'] or not authorized(tx, actor, record):
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)
    workflow = context(tx, request_id)
    check_reviewer(actor, record, workflow, action)
    if record['status'] != 'pending':
        return {**view(tx, record), 'already_reviewed': True}
    if record['expires_at'] <= now():
        values = _close(tx, request_id, 'expired')
        return view(tx, dict(record, **values))
    reason = decision_reason(action, reason)
    if action == 'approved':
        signup = _requests().signup(tx, workflow['signup_id']) if workflow['signup_id'] else None
        if signup is not None and not signup['wants_account']:
            site_id, organization_id = signup_entities(tx, record, workflow)
            _requests().update_workflow(tx, request_id, {'result_site_id': site_id,
                                                         'result_organization_id': organization_id})
        else:
            _approve_identity(tx, record, workflow, request_id)
    values = _close(tx, request_id, action, only_pending=True, reviewed_by=actor['id'], decision_reason=reason)
    write_audit(tx, actor, record['scope_id'] if record['scope_type'] == 'site' else None, 'account_request_' + action,
                {'request_id': request_id, 'scope_type': record['scope_type'], 'scope_id': record['scope_id'],
                 'result': action})
    return view(tx, dict(record, **values))


def owned(tx, token, lock=False):
    require_tracking_token(token)
    record = _requests().by_tracking_hash(tx, digest(token), for_update=lock)
    if not record:
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)
    return record


def status(tx, token):
    expire_pending(tx)
    return view(tx, owned(tx, token))


def cancel(tx, token):
    expire_pending(tx)
    record = owned(tx, token, True)
    if record['status'] != 'pending':
        return view(tx, record)
    values = _close(tx, record['id'], 'cancelled')
    write_audit(tx, None, None, 'account_request_cancelled', {'request_id': record['id']})
    return view(tx, dict(record, **values))


def setup_password(tx, token, body):
    record = owned(tx, token, True)
    workflow = context(tx, record['id'])
    if not setup_available(record, workflow, now()):
        fail('ACCOUNT_SETUP_UNAVAILABLE', Conflict)
    if body.get('password') != body.get('confirmation'):
        fail('PASSWORD_CONFIRMATION_MISMATCH')
    if not _requests().activate_with_password(tx, workflow['user_id'], hash_password(body.get('password'))):
        fail('ACCOUNT_SETUP_UNAVAILABLE', Conflict)
    _requests().update_workflow(tx, record['id'], {'setup_expires_at': None})
    write_audit(tx, None, None, 'account_password_set', {'request_id': record['id']})
    return {'ok': True, 'login_required': True}


def renew_setup(tx, actor, request_id):
    record = _requests().request(tx, request_id, for_update=True)
    if not record or record['supervisor_id'] != actor['id'] or not authorized(tx, actor, record):
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)
    if record['requested_by'] == actor['id']:
        fail('ACCOUNT_REQUEST_SELF_REVIEW', Forbidden)
    workflow = context(tx, request_id)
    target = persistence.identity.user(tx, workflow['user_id'])
    if record['status'] != 'approved' or not workflow['setup_expires_at'] or not target or target['active']:
        fail('ACCOUNT_SETUP_UNAVAILABLE', Conflict)
    _requests().update_workflow(tx, request_id, {'setup_expires_at': expires(SETUP_DAYS)})
    write_audit(tx, actor, None, 'account_setup_renewed', {'request_id': request_id})
    return view(tx, record)


def list_submitted(tx, actor, status=None):
    return [view(tx, record) for record in _requests().submitted_by(tx, actor['id'], status)]


def invite_platform_candidate(tx, actor, body):
    if actor['role'] != 'platform' or not actor['active']:
        fail('FORBIDDEN_ROLE', Forbidden)
    email, phone = contact_identity(body, preserve_email=True)
    if find_contact_user(tx, email, phone):
        fail('ACCOUNT_ALREADY_EXISTS', Conflict)
    token = secrets.token_urlsafe(32)
    invite_id = new_id()
    expires_at = expires(SETUP_DAYS)
    _requests().add_platform_invite(tx, {
        'id': invite_id, 'token_hash': digest(token), 'email': email, 'phone': phone,
        'name': text(body.get('name'), 160, True), 'created_by': actor['id'], 'created_at': now(),
        'expires_at': expires_at,
    })
    write_audit(tx, actor, 'platform', 'platform_account_invitation_created', {'invitation_id': invite_id})
    return {'id': invite_id, 'status': 'invited', 'invitation_token': token, 'expires_at': expires_at,
            'grants_access': False}


def platform_invite(tx, token, lock=False):
    require_tracking_token(token)
    row = _requests().platform_invite(tx, digest(token), for_update=lock)
    if not row:
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)
    if not row['request_id'] and row['expires_at'] <= now():
        fail('ACCOUNT_INVITATION_EXPIRED', Conflict)
    return row


def inspect_platform_invite(tx, token):
    row = platform_invite(tx, token)
    return {'name': row['name'], 'email': None if row['email'].startswith('tel:') else row['email'],
            'phone': row['phone'], 'expires_at': row['expires_at'], 'submitted': bool(row['request_id'])}


def accept_platform_invite(tx, token, body):
    row = platform_invite(tx, token, True)
    if row['request_id']:
        return {**view(tx, owned(tx, token)), 'tracking_token': token, 'already_pending': True, 'grants_access': False}
    result = submit(tx, actor=None, body={
        'email': None if row['email'].startswith('tel:') else row['email'], 'phone': row['phone'],
        'name': row['name'], 'password': body.get('password'), 'confirmation': body.get('confirmation'),
        'request_key': token,
    }, purpose='site', scope_type='site', scope_id='platform', role='platform')
    _requests().link_platform_invite(tx, row['id'], result['id'])
    return result
