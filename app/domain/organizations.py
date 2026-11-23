"""Organizations (exhibitors, sponsors, ...), their people, memberships and
event participations."""
from __future__ import annotations

from app.domain.errors import Conflict, Forbidden, fail
from app.domain.values import EMAIL, SLUG, boolean, text

PERSON_ROLES = ('owner', 'manager', 'member', 'representative', 'staff', 'speaker')
PERSON_STATUSES = ('active', 'inactive', 'archived')
MEMBERSHIP_ROLES = ('owner', 'admin', 'editor', 'analyst')
MEMBERSHIP_STATUSES = ('active', 'suspended', 'archived')
PARTICIPATION_TYPES = ('exhibitor', 'sponsor', 'partner', 'speaker', 'media', 'staff', 'vendor')
SIGNUP_PARTICIPATION_TYPES = ('exhibitor', 'sponsor', 'partner', 'speaker', 'media', 'vendor')
PARTICIPATION_STATUSES = ('pending', 'active', 'suspended', 'expired', 'archived')
DEFAULT_PRIMARY = '#176B73'


def new_organization(organization_id: str, body: dict, at: str) -> dict:
    name = text(body.get('name'), 200, True)
    slug = text(body.get('slug'), 80, True).lower()
    if not SLUG.fullmatch(slug):
        fail('SLUG_INVALID')
    profile = {'description': text(body.get('description'), 3000), 'logo': '', 'primary': DEFAULT_PRIMARY, 'website': ''}
    return {'id': organization_id, 'slug': slug, 'name': name, 'profile': profile, 'status': 'active', 'created_at': at}


def new_participation(participation_id: str, event: dict, organization_id: str, agency_site_id: str,
                      body: dict, at: str) -> dict:
    """An organization joins an event; validity defaults to the event's dates."""
    return {
        'id': participation_id, 'event_id': event['id'], 'organization_id': organization_id,
        'agency_site_id': agency_site_id,
        'participation_type': text(body.get('participation_type') or 'exhibitor', 40),
        'status': 'active', 'booth': text(body.get('booth'), 120), 'summary': text(body.get('summary'), 2000),
        'services': [], 'valid_from': event['draft'].get('start') or '', 'valid_until': event['draft'].get('end') or '',
        'created_at': at,
    }


def require_event_operator(user: dict, event: dict) -> None:
    """Participations are managed on events by the platform or the event's organizer."""
    if event['kind'] != 'event' or user['role'] not in ('platform', 'organizer'):
        fail('FORBIDDEN_ROLE', Forbidden)


def participation_changes(body: dict) -> dict:
    values = {}
    if body.get('status') in PARTICIPATION_STATUSES:
        values['status'] = body['status']
    if body.get('participation_type') in PARTICIPATION_TYPES:
        values['participation_type'] = body['participation_type']
    for key, limit in (('booth', 120), ('summary', 2000), ('valid_from', 64), ('valid_until', 64)):
        if key in body:
            values[key] = text(body.get(key), limit)
    if not values:
        fail('NO_CHANGES')
    return values


def can_manage_people_by_role(user: dict) -> bool:
    return user['role'] in ('platform', 'organizer')


def _email(value) -> str:
    if value and not EMAIL.fullmatch(value):
        fail('EMAIL_INVALID')
    return value


def person_values(person_id: str, organization_id: str, body: dict, at: str) -> dict:
    email = _email(text(body.get('email'), 200).lower())
    phone = text(body.get('phone'), 60)
    role = body.get('person_role') if body.get('person_role') in PERSON_ROLES else 'member'
    return {
        'id': person_id, 'organization_id': organization_id, 'user_id': None,
        'name': text(body.get('name'), 160, True), 'email': email, 'phone': phone,
        'job_title': text(body.get('job_title'), 160), 'person_role': role,
        'public_visible': 1 if boolean(body.get('public_visible', False)) else 0, 'status': 'active', 'created_at': at,
    }


def person_changes(body: dict) -> dict:
    values = {}
    for key, limit in (('name', 160), ('email', 200), ('phone', 60), ('job_title', 160)):
        if key in body:
            values[key] = text(body.get(key), limit, key == 'name')
    if 'email' in values:
        _email(values['email'])
    if body.get('person_role') in PERSON_ROLES:
        values['person_role'] = body['person_role']
    if body.get('status') in PERSON_STATUSES:
        values['status'] = body['status']
    if 'public_visible' in body:
        values['public_visible'] = 1 if boolean(body.get('public_visible')) else 0
    if not values:
        fail('NO_CHANGES')
    return values


def membership_changes(body: dict) -> dict:
    values = {}
    if body.get('role') in MEMBERSHIP_ROLES:
        values['role'] = body['role']
    if body.get('status') in MEMBERSHIP_STATUSES:
        values['status'] = body['status']
    if not values:
        fail('NO_CHANGES')
    return values


def signup_values(request_id: str, site_id: str, event_id, role: str, email: str, phone, body: dict, at: str) -> dict:
    organization_name = text(body.get('organization_name'), 200, True)
    contact = text(body.get('contact_name') or organization_name, 160, True)
    participation_type = body.get('participation_type')
    return {
        'id': request_id, 'site_id': site_id, 'event_id': event_id if role == 'participant' else None,
        'requested_role': role, 'organization_name': organization_name, 'contact_name': contact,
        'email': email, 'phone': phone,
        'participation_type': participation_type if participation_type in SIGNUP_PARTICIPATION_TYPES else 'exhibitor',
        'wants_account': 1 if boolean(body.get('wants_account', True)) else 0, 'status': 'pending',
        'details': {'message': text(body.get('message'), 1500)}, 'created_at': at,
    }


def signup_role(role, site: dict) -> str:
    """Public signup may ask to organize (from the platform site) or to participate."""
    if role not in ('organizer', 'participant'):
        fail('REQUESTED_ROLE_INVALID')
    if role == 'organizer' and site['kind'] != 'platform':
        fail('FORBIDDEN_SCOPE', Forbidden)
    return role


def require_participation_event(role: str, event_id) -> None:
    if role == 'participant' and not event_id:
        fail('EVENT_REQUIRED')


def require_unlinked_person(person: dict) -> None:
    if person['user_id']:
        fail('PERSON_ALREADY_LINKED', Conflict)


def require_membership_manager(user: dict, is_active_owner: bool) -> None:
    if user['role'] not in ('platform', 'organizer') and not is_active_owner:
        fail('FORBIDDEN_ROLE', Forbidden)


def requested_membership_role(membership: dict, body: dict):
    """The new role when a change is requested (needs a reviewed request), else None."""
    role = body.get('role', membership['role'])
    return role if role != membership['role'] else None
