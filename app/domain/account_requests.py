"""Account approval rules (AccountRequest aggregate).

Lifecycle: pending -> approved | rejected | expired | cancelled. A request is
reviewed by one independent supervisor; nobody reviews a request they made,
for themselves, or for an account they already own. Approval creates (or
links) the login identity and grants exactly the approved scope.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.domain.authorization import EVENT_ROLE_PERMISSIONS
from app.domain.errors import Conflict, Forbidden, NotFound, Unavailable, fail
from app.domain.site_config import default_config
from app.domain.values import stamp, text

REQUESTABLE_ROLES = ('platform', 'organizer', 'agency', 'member')
MEMBERSHIP_ROLES = (None, 'owner', 'admin', 'editor', 'analyst')
SOURCES = {'personal': 'signup', 'site': 'admin', 'signup': 'signup', 'access': 'access',
           'committee': 'committee', 'organization': 'organization'}
REVIEW_ACTIONS = ('approved', 'rejected')
# Explicit projection: future storage fields are private until consciously exposed.
PUBLIC_FIELDS = (
    'id', 'email', 'name', 'phone', 'requested_role', 'scope_type', 'scope_id',
    'site_id', 'organization_id', 'event_id', 'person_id', 'participation_id',
    'membership_role', 'assignment_role', 'source', 'supervisor_id', 'requested_by',
    'reviewed_by', 'status', 'created_at', 'expires_at', 'reviewed_at', 'decision_reason',
)
PENDING_DAYS = 7
SETUP_DAYS = 1


def public_account_request(record) -> dict:
    return {key: record[key] for key in PUBLIC_FIELDS}


def expires(days=PENDING_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def check_roles(role, membership_role, assignment_role) -> None:
    if role not in REQUESTABLE_ROLES:
        fail('ACCOUNT_REQUEST_ROLE_INVALID')
    if membership_role not in MEMBERSHIP_ROLES:
        fail('MEMBERSHIP_ROLE_INVALID')
    if assignment_role is not None and assignment_role not in EVENT_ROLE_PERMISSIONS:
        fail('COMMITTEE_ROLE_INVALID')


def check_target(purpose: str, role: str, target, body: dict) -> None:
    """Rules about an account that already exists for the submitted contact."""
    if role == 'platform' and target and target['role'] != 'platform':
        fail('EXISTING_ACCOUNT_ROLE_CONFLICT', Conflict)
    if purpose == 'personal' and target:
        fail('PHONE_ALREADY_REGISTERED', Conflict)
    if target and not target['active']:
        fail('ACCOUNT_SUSPENDED', Conflict)
    if body.get('user_id') and (not target or target['id'] != body['user_id']):
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)


def submitted_password(actor, body: dict):
    """Only a self-service submitter may choose a password (never staff on their behalf)."""
    password = body.get('password') if actor is None else None
    if password is not None and password != body.get('confirmation'):
        fail('PASSWORD_CONFIRMATION_MISMATCH')
    return password


def request_key(raw, generated: str) -> str:
    token = raw or generated
    if (not isinstance(token, str) or not 32 <= len(token) <= 80
            or not all(char.isalnum() or char in '_-' for char in token)):
        fail('ACCOUNT_REQUEST_KEY_INVALID')
    return token


def payload_fingerprint_source(email, phone, name, purpose, scope_type, scope_id, role, membership_role,
                               assignment_role, person_id, body: dict) -> str:
    """Canonical text of everything an idempotent resubmission must repeat exactly."""
    signup = purpose == 'signup'
    return json.dumps([
        email, phone, name, purpose, scope_type, scope_id, role, membership_role, assignment_role, person_id,
        body.get('valid_from'), body.get('valid_until'),
        body.get('organization_name') if signup else None,
        body.get('participation_type') if signup else None,
        body.get('wants_account', True) if signup else None,
        body.get('message') if signup else None,
    ], separators=(',', ':'))


def assignment_window(body: dict) -> tuple[str | None, str | None]:
    start, end = stamp(body.get('valid_from')), stamp(body.get('valid_until'))
    start = datetime.fromisoformat(start).astimezone(timezone.utc).isoformat() if start else None
    end = datetime.fromisoformat(end).astimezone(timezone.utc).isoformat() if end else None
    if start and end and start >= end:
        fail('ASSIGNMENT_WINDOW_INVALID')
    return start, end


def supervisor_preference(actor_id):
    """Prefer a scoped owner/organizer, and an independent reviewer where available."""
    def key(user):
        rank = 2 if user['role'] == 'platform' else 1 if user['role'] == 'organizer' else 0
        return (user['id'] == actor_id, rank)
    return key


def may_supervise(candidate: dict, record: dict, actor_id) -> bool:
    return (candidate['id'] != actor_id and candidate['id'] != record.get('existing_user_id')
            and candidate['email'].lower() != record['email'].lower())


def delegated_grant_allowed(assignment_role: str, reviewer_permissions: frozenset[str]) -> bool:
    """A delegated committee manager cannot grant a capability they do not hold."""
    return ('committee.manage' in reviewer_permissions
            and EVENT_ROLE_PERMISSIONS[assignment_role] <= reviewer_permissions)


def check_reviewer(actor: dict, record: dict, workflow: dict, action) -> None:
    if (actor['id'] == record['requested_by'] or actor['email'].lower() == record['email'].lower()
            or actor['id'] == workflow['existing_user_id']):
        fail('ACCOUNT_REQUEST_SELF_REVIEW', Forbidden)
    if action not in REVIEW_ACTIONS:
        fail('REQUEST_STATUS_INVALID')


def decision_reason(action: str, reason) -> str | None:
    """A rejection must explain itself; an approval reason is optional."""
    return text(reason, 500, action == 'rejected') or None


def granted_assignment_role(record: dict, workflow: dict, organization_id) -> str | None:
    """Existing accounts keep their global role/scope; grant only the approved scope."""
    role = record['assignment_role']
    if workflow['purpose'] == 'signup' and record['requested_role'] == 'organizer':
        role = 'event_manager'
    if (not role and not organization_id and record['requested_role'] != 'platform'
            and workflow['purpose'] in ('site', 'access', 'signup')):
        role = 'event_manager' if record['requested_role'] == 'organizer' else 'site_manager'
    return role


def new_login(user_id: str, record: dict, workflow: dict, site_id, password_hash: str) -> dict:
    """The identity an approval creates; without a chosen password it stays inactive until setup."""
    personal = workflow['purpose'] == 'personal'
    return {
        'id': user_id, 'email': record['email'], 'name': record['name'],
        'role': 'attendee' if personal else record['requested_role'],
        'scope_id': None if personal else site_id, 'password_hash': password_hash,
        'active': 1 if record['password_hash'] else 0, 'must_change_password': 0,
    }


def check_person_link(person, organization_id, user_id) -> None:
    if not person or person['organization_id'] != organization_id or person['user_id'] not in (None, user_id):
        fail('PERSON_ACCOUNT_CONFLICT', Conflict)


def signup_entities(request_id: str, signup: dict, organization_id: str, site_id: str, participation_id: str,
                    at: str) -> tuple[dict, dict, dict | None]:
    """Organization, page (event or agency) and participation created by a sign-up."""
    slug = 'org-' + request_id.replace('-', '')[:16]
    organization = {'id': organization_id, 'slug': slug, 'name': signup['organization_name'],
                    'profile': {'description': signup['details'].get('message', '')}, 'status': 'active',
                    'created_at': at}
    kind = 'event' if signup['requested_role'] == 'organizer' else 'agency'
    parent = 'platform' if kind == 'event' else signup['event_id']
    if kind == 'agency' and not parent:
        fail('EVENT_REQUIRED')
    site = {'id': site_id, 'parent_id': parent, 'event_id': site_id if kind == 'event' else parent, 'kind': kind,
            'slug': slug, 'draft': default_config(signup['organization_name'], kind), 'draft_rev': 1,
            'published_version': 0}
    participation = None
    if kind == 'agency':
        participation = {'id': participation_id, 'event_id': parent, 'organization_id': organization_id,
                         'agency_site_id': site_id, 'participation_type': signup['participation_type'] or 'exhibitor',
                         'status': 'active', 'services': [], 'created_at': at}
    return organization, site, participation


def require_tracking_token(token) -> None:
    if not isinstance(token, str) or not 32 <= len(token) <= 80:
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)


def setup_available(record: dict, workflow: dict, at: str) -> bool:
    return record['status'] == 'approved' and bool(workflow['setup_expires_at']) and workflow['setup_expires_at'] > at


def requests_accepting(flag: str) -> None:
    """Operators can pause new requests without redeploying."""
    if str(flag).lower() not in ('true', '1', 'yes'):
        fail('ACCOUNT_REQUESTS_PAUSED', Unavailable)


def require_active_actor(actor: dict) -> None:
    if not actor['active']:
        fail('FORBIDDEN_ROLE', Forbidden)


def organizer_may_submit_for_platform(actor: dict, record: dict) -> bool:
    """An organizer may submit organizer requests for platform review in their own event."""
    return (record['requested_role'] == 'organizer' and actor['role'] == 'organizer'
            and actor['scope_id'] == record['scope_id'])


def require_assigned_supervisor(actor: dict, record: dict | None) -> None:
    """Only the designated supervisor sees a request; everyone else gets not-found."""
    if not record or record['supervisor_id'] != actor['id']:
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)


def review_disposition(record: dict, at: str) -> str:
    """What a review attempt does to a request: nothing more, expire it, or proceed."""
    if record['status'] != 'pending':
        return 'already_reviewed'
    if record['expires_at'] <= at:
        return 'expired'
    return 'proceed'


def require_unclaimed_identity(workflow: dict, target) -> None:
    """Approval must not collide with, or silently adopt, an existing login."""
    if workflow['purpose'] == 'personal' and target:
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)
    if workflow['existing_user_id'] and (not target or target['id'] != workflow['existing_user_id']):
        fail('CONTACT_IDENTITIES_CONFLICT', Conflict)


def require_active_target(target) -> None:
    if target and not target['active']:
        fail('ACCOUNT_SUSPENDED', Conflict)


def require_password_setup(record: dict, workflow: dict, at: str, body: dict) -> None:
    if not setup_available(record, workflow, at):
        fail('ACCOUNT_SETUP_UNAVAILABLE', Conflict)
    if body.get('password') != body.get('confirmation'):
        fail('PASSWORD_CONFIRMATION_MISMATCH')


def require_setup_renewable(record: dict, workflow: dict, target, actor: dict) -> None:
    """The requester cannot renew their own setup; only an approved, not-yet-used setup renews."""
    if record['requested_by'] == actor['id']:
        fail('ACCOUNT_REQUEST_SELF_REVIEW', Forbidden)
    if record['status'] != 'approved' or not workflow['setup_expires_at'] or not target or target['active']:
        fail('ACCOUNT_SETUP_UNAVAILABLE', Conflict)


def require_platform_inviter(actor: dict) -> None:
    if actor['role'] != 'platform' or not actor['active']:
        fail('FORBIDDEN_ROLE', Forbidden)


def require_invitation_usable(row: dict, at: str) -> None:
    if not row['request_id'] and row['expires_at'] <= at:
        fail('ACCOUNT_INVITATION_EXPIRED', Conflict)
