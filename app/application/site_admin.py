"""Site administration use cases: sites, drafts, publishing, content imports,
organizations, people, memberships, participations, requests and audit views.
"""
from __future__ import annotations

import secrets

from app.application import account_requests as account_request_service
from app.application.access import can_manage, can_read, get_site, organization_visible, require_read_scope, require_scope
from app.application.access_request_service import list_requests
from app.application.audit_service import new_id, write_audit
from app.application.event_visibility import event_id_for_site, require_public_event
from app.application.phone_accounts import contact_identity
from app.application.ports import persistence
from app.application.publishing import publish_site_version
from app.domain import Conflict, DomainError, Forbidden, NotFound, fail, normalize_config, now, text
from app.domain.organizations import (
    can_manage_people_by_role,
    membership_changes,
    new_organization,
    new_participation,
    participation_changes,
    person_changes,
    person_values,
    require_event_operator,
    signup_values,
)
from app.domain.site_config import KINDS, QTYPES, SECTIONS
from app.domain.sites import (
    agency_draft,
    agency_slug,
    authorize_new_site,
    fallback_agency_slug,
    new_site,
    new_site_draft,
    public_path,
    require_draft_revision,
    require_publish_revision,
    site_slug,
)

AUDIT_PAGE_MAX = 500


# Public requests ------------------------------------------------------------

def request_access(tx, body: dict) -> dict:
    site_id = text(body.get('site_id'), 64, True)
    target = get_site(tx, site_id)
    require_public_event(tx, event_id_for_site(tx, target))
    if target['kind'] == 'platform':
        fail('EVENT_REQUIRED')
    role = 'organizer' if target['kind'] == 'event' else 'agency'
    request_id = new_id()
    email, _phone = contact_identity(body, preserve_email=True)
    persistence.site_admin.add_access_request(tx, {
        'id': request_id, 'site_id': site_id, 'email': email, 'name': text(body.get('name'), 160, True),
        'created_at': now(), 'status': 'pending',
    })
    result = account_request_service.submit(tx, actor=None, body=body, purpose='access', scope_type='site',
                                            scope_id=site_id, role=role, access_id=request_id)
    if result.get('already_pending'):
        persistence.site_admin.delete_access_request(tx, request_id)
    return result


def request_signup(tx, body: dict) -> dict:
    site_id = text(body.get('site_id'), 64, True)
    site = get_site(tx, site_id)
    require_public_event(tx, event_id_for_site(tx, site))
    role = body.get('requested_role')
    if role not in ('organizer', 'participant'):
        fail('REQUESTED_ROLE_INVALID')
    if role == 'organizer' and site['kind'] != 'platform':
        fail('FORBIDDEN_SCOPE', Forbidden)
    event_id = event_id_for_site(tx, site)
    if role == 'participant' and not event_id:
        fail('EVENT_REQUIRED')
    email, phone = contact_identity(body, preserve_email=True)
    request_id = new_id()
    row = signup_values(request_id, site_id, event_id, role, email, phone, body, now())
    persistence.site_admin.add_signup_request(tx, row)
    result = account_request_service.submit(
        tx, actor=None, body={**body, 'name': row['contact_name']}, purpose='signup', scope_type='site',
        scope_id=event_id if role == 'participant' else site_id,
        role='organizer' if role == 'organizer' else 'agency', membership_role='owner', signup_id=request_id)
    if result.get('already_pending'):
        persistence.site_admin.delete_signup_request(tx, request_id)
    return result


def signup_requests_for(tx, user, site_id: str | None) -> list[dict]:
    if user['role'] not in ('platform', 'organizer'):
        fail('FORBIDDEN_ROLE', Forbidden)
    rows = persistence.site_admin.signup_requests(tx)
    if user['role'] == 'organizer':
        rows = [row for row in rows if row.get('event_id') == user['scope_id']]
    if site_id:
        rows = [row for row in rows if row.get('site_id') == site_id or row.get('event_id') == site_id]
    return rows


def review_signup_request(tx, user, signup_id: str, status, reason):
    linked = persistence.site_admin.workflow_request_id(tx, signup_id=signup_id)
    if not linked:
        fail('LEGACY_REQUEST_REQUIRES_RESUBMISSION', Conflict)
    return account_request_service.review(tx, user, linked, status, reason)


def review_access_request(tx, user, site_id: str, access_id: str, status, reason):
    require_scope(tx, user, site_id)
    linked = persistence.site_admin.workflow_request_id(tx, access_id=access_id)
    if not linked:
        fail('LEGACY_REQUEST_REQUIRES_RESUBMISSION', Conflict)
    if account_request_service.request_scope_id(tx, linked) != site_id:
        fail('ACCOUNT_REQUEST_NOT_FOUND', NotFound)
    return account_request_service.review(tx, user, linked, status, reason)


# Sites -------------------------------------------------------------------------

def readable_sites(tx, user) -> dict:
    sites = [
        {'id': site['id'], 'slug': site['slug'], 'kind': site['kind'], 'event_id': site['event_id'],
         'title': site['draft']['title'], 'draft_rev': site['draft_rev'], 'published_version': site['published_version']}
        for site in persistence.sites.list_all(tx) if can_read(tx, user, site)
    ]
    return {'sites': sites, 'types': QTYPES, 'kinds': KINDS, 'sections': SECTIONS}


def create_site(tx, user, body: dict) -> dict:
    kind = body.get('kind')
    parent = require_scope(tx, user, body.get('parent_id'))
    authorize_new_site(user['role'], parent, kind)
    slug = site_slug(body.get('slug'))
    if persistence.sites.get_by_slug(tx, slug):
        fail('SLUG_EXISTS', Conflict)
    site_id = new_id()
    persistence.sites.add(tx, new_site(site_id, parent, kind, slug, new_site_draft(body, kind)))
    write_audit(tx, user, site_id, 'site_created')
    return {'id': site_id, 'draft_rev': 1}


def admin_site_view(tx, user, site_id: str) -> dict:
    site = dict(require_read_scope(tx, user, site_id))
    site['can_manage'] = can_manage(tx, user, site)
    site['event_slug'] = get_site(tx, site['event_id'])['slug'] if site['event_id'] else None
    return site


def save_draft(tx, user, site_id: str, revision, config: dict, authorize) -> dict:
    site = require_scope(tx, user, site_id)
    authorize(user, site, 'event.configure')
    revision = require_draft_revision(site, revision)
    if not persistence.sites.save_draft(tx, site_id, revision, config):
        fail('DRAFT_CHANGED_REFRESH_REQUIRED', Conflict)
    write_audit(tx, user, site_id, 'draft_saved', {'revision': revision + 1})
    return {'draft_rev': revision + 1}


def publish(tx, user, site_id: str, revision, authorize) -> dict:
    site = require_scope(tx, user, site_id)
    authorize(user, site, 'event.publish')
    require_publish_revision(site, revision)
    return {'published_version': publish_site_version(tx, site, user)}


def site_by_slug(tx, slug: str) -> dict:
    site = persistence.sites.get_by_slug(tx, slug)
    if not site:
        fail('SITE_NOT_FOUND', NotFound)
    return site


def site_users(tx, user, site_id: str) -> dict:
    require_scope(tx, user, site_id)
    if user['role'] == 'agency':
        fail('FORBIDDEN_ROLE', Forbidden)
    awaiting_setup = persistence.identity.users_awaiting_setup(tx, site_id)
    rows = [{**row, 'setup_required': row['id'] in awaiting_setup,
             'email': None if row['email'].startswith('tel:') else row['email']}
            for row in persistence.identity.users_in_scope(tx, site_id)]
    return {'users': rows, 'requests': list_requests(tx, site_id)}


def request_site_user(tx, user, site_id: str, body: dict) -> dict:
    site = require_scope(tx, user, site_id)
    if user['role'] == 'agency' or site['kind'] == 'platform':
        fail('FORBIDDEN_ROLE', Forbidden)
    return account_request_service.submit(tx, actor=user, body=body, purpose='site', scope_type='site',
                                          scope_id=site_id, role='organizer' if site['kind'] == 'event' else 'agency')


def qr_path(tx, user, site_id: str) -> str:
    site = require_scope(tx, user, site_id)
    event_slug = get_site(tx, site['event_id'])['slug'] if site['kind'] == 'agency' else None
    return public_path(site, event_slug)


# Content imports ----------------------------------------------------------

def preview_import(tx, user, site: dict, records: list, errors: list, ignored_sheets) -> dict:
    """Validate parsed records against the current draft; ``site`` is already scope-checked."""
    site_id = site['id']
    existing = {record['code'] for record in site['draft']['records']}
    for record in records:
        if record['code'] in existing:
            errors.append({'sheet': '', 'row': 0, 'error': 'CODE_EXISTS:' + record['code']})
    if not errors:
        try:
            normalize_config({**site['draft'], 'records': site['draft']['records'] + records})
        except DomainError as error:
            errors.append({'sheet': '', 'row': 0, 'error': error.code})
    import_id = new_id()
    persistence.site_admin.add_import(tx, {
        'id': import_id, 'site_id': site_id, 'user_id': user['id'], 'base_rev': site['draft_rev'],
        'records': records, 'errors': errors, 'state': 'preview', 'created_at': now(),
    })
    return {'id': import_id, 'records': records, 'errors': errors, 'ignored_sheets': ignored_sheets,
            'base_rev': site['draft_rev'], 'valid': not errors}


def commit_import(tx, user, site_id: str, import_id: str) -> dict:
    site = require_scope(tx, user, site_id)
    job = persistence.site_admin.content_import(tx, import_id)
    if not job or job['site_id'] != site_id or job['user_id'] != user['id']:
        fail('IMPORT_NOT_FOUND', NotFound)
    if job['state'] == 'committed':
        return {'status': 'already_committed', 'added': len(job['records'])}
    if job['errors']:
        fail('IMPORT_HAS_ERRORS')
    if job['base_rev'] != site['draft_rev']:
        fail('DRAFT_CHANGED_REPREVIEW_REQUIRED', Conflict)
    config = normalize_config({**site['draft'], 'records': site['draft']['records'] + job['records']})
    if not persistence.sites.save_draft(tx, site_id, job['base_rev'], config):
        fail('DRAFT_CHANGED_REPREVIEW_REQUIRED', Conflict)
    persistence.site_admin.mark_import_committed(tx, import_id)
    write_audit(tx, user, site_id, 'import_committed', {'job': import_id, 'records': len(job['records'])})
    return {'status': 'committed', 'added': len(job['records'])}


# Organizations, people and memberships -----------------------------------

def organizations_for(tx, user) -> list[dict]:
    result = []
    for organization in persistence.site_admin.organizations(tx):
        if not organization_visible(tx, user, organization['id']):
            continue
        result.append({
            **organization,
            'can_request_account': account_request_service.org_reviewer(tx, user, organization['id'], False),
            'participations': persistence.site_admin.participations_of_organization(tx, organization['id']),
        })
    return result


def _unique_agency_slug(tx, organization_slug: str, event_slug: str) -> str:
    slug = agency_slug(organization_slug, event_slug)
    if persistence.sites.get_by_slug(tx, slug):
        slug = fallback_agency_slug(organization_slug, secrets.token_hex(3))
    return slug


def _add_agency_participation(tx, event, organization, body, draft) -> tuple[str, str]:
    site_id = new_id()
    slug = _unique_agency_slug(tx, organization['slug'], event['slug'])
    persistence.sites.add(tx, new_site(site_id, event, 'agency', slug, draft))
    participation = new_participation(new_id(), event, organization['id'], site_id, body, now())
    persistence.site_admin.add_participation(tx, participation)
    return participation['id'], site_id


def create_organization(tx, user, body: dict) -> dict:
    if user['role'] not in ('platform', 'organizer'):
        fail('FORBIDDEN_ROLE', Forbidden)
    organization = new_organization(new_id(), body, now())
    if persistence.site_admin.organization_by_slug(tx, organization['slug']):
        fail('ORGANIZATION_SLUG_EXISTS', Conflict)
    persistence.site_admin.add_organization(tx, organization)
    write_audit(tx, user, user['scope_id'], 'organization_created',
                {'organization_id': organization['id'], 'name': organization['name']})
    if user['role'] == 'organizer':
        event = get_site(tx, user['scope_id'])
        _add_agency_participation(tx, event, organization, body, agency_draft(organization, normalized=False))
    return {'id': organization['id'], 'name': organization['name'], 'slug': organization['slug']}


def event_participations(tx, user, event_id: str) -> list[dict]:
    event = require_scope(tx, user, event_id)
    if event['kind'] != 'event':
        fail('EVENT_REQUIRED')
    return persistence.site_admin.participations_of_event(tx, event_id)


def add_participation(tx, user, event_id: str, body: dict) -> dict:
    event = require_scope(tx, user, event_id)
    require_event_operator(user, event)
    organization_id = text(body.get('organization_id'), 64, True)
    organization = persistence.site_admin.organization(tx, organization_id)
    if not organization:
        fail('ORGANIZATION_NOT_FOUND', NotFound)
    if persistence.site_admin.participation_exists(tx, event_id, organization_id):
        fail('PARTICIPATION_EXISTS', Conflict)
    participation_id, site_id = _add_agency_participation(tx, event, organization, body,
                                                          agency_draft(organization, normalized=True))
    write_audit(tx, user, event_id, 'participation_added', {'organization_id': organization_id, 'agency_site_id': site_id})
    return {'id': participation_id, 'agency_site_id': site_id}


def update_participation(tx, user, participation_id: str, body: dict) -> dict:
    participation = persistence.site_admin.participation(tx, participation_id)
    if not participation:
        fail('PARTICIPATION_NOT_FOUND', NotFound)
    event = require_scope(tx, user, participation['event_id'])
    require_event_operator(user, event)
    values = participation_changes(body)
    persistence.site_admin.update_participation(tx, participation_id, values)
    write_audit(tx, user, participation['event_id'], 'participation_updated', {'participation_id': participation_id, **values})
    return {'ok': True, **values}


def _visible_organization(tx, user, organization_id: str, error: str = 'ORGANIZATION_NOT_FOUND') -> dict:
    organization = persistence.site_admin.organization(tx, organization_id)
    if not organization or not organization_visible(tx, user, organization_id):
        fail(error, NotFound)
    return organization


def _can_manage_people(tx, user, organization_id: str) -> bool:
    if can_manage_people_by_role(user) and organization_visible(tx, user, organization_id):
        return True
    return persistence.access.membership_role(tx, user['id'], organization_id) in ('owner', 'admin')


def organization_people(tx, user, organization_id: str) -> list[dict]:
    _visible_organization(tx, user, organization_id)
    return persistence.site_admin.people(tx, organization_id)


def add_person(tx, user, organization_id: str, body: dict) -> dict:
    _visible_organization(tx, user, organization_id)
    if not _can_manage_people(tx, user, organization_id):
        fail('FORBIDDEN_ROLE', Forbidden)
    person = person_values(new_id(), organization_id, body, now())
    persistence.site_admin.add_person(tx, person)
    write_audit(tx, user, user['scope_id'], 'organization_person_added',
                {'organization_id': organization_id, 'person_id': person['id'], 'has_account': False})
    return {'id': person['id'], 'organization_id': organization_id, 'has_account': False}


def update_person(tx, user, organization_id: str, person_id: str, body: dict) -> dict:
    organization = persistence.site_admin.organization(tx, organization_id)
    person = persistence.site_admin.person(tx, person_id)
    if (not organization or not person or person['organization_id'] != organization_id
            or not organization_visible(tx, user, organization_id)):
        fail('PERSON_NOT_FOUND', NotFound)
    if not _can_manage_people(tx, user, organization_id):
        fail('FORBIDDEN_ROLE', Forbidden)
    values = person_changes(body)
    persistence.site_admin.update_person(tx, person_id, values)
    write_audit(tx, user, user['scope_id'], 'organization_person_updated',
                {'organization_id': organization_id, 'person_id': person_id, **values})
    return {'id': person_id, **values}


def request_person_account(tx, user, organization_id: str, person_id: str, body: dict) -> dict:
    person = persistence.site_admin.person(tx, person_id)
    if not person or person['organization_id'] != organization_id or not _can_manage_people(tx, user, organization_id):
        fail('PERSON_NOT_FOUND', NotFound)
    if person['user_id']:
        fail('PERSON_ALREADY_LINKED', Conflict)
    contact = {**body, 'name': person['name'], 'email': body.get('email') or person['email'],
               'phone': body.get('phone') or person['phone']}
    return account_request_service.submit(tx, actor=user, body=contact, purpose='organization',
                                          scope_type='organization', scope_id=organization_id, role='agency',
                                          person_id=person_id, membership_role=body.get('role', 'editor'))


def request_organization_user(tx, user, organization_id: str, body: dict) -> dict:
    return account_request_service.submit(tx, actor=user, body=body, purpose='organization', scope_type='organization',
                                          scope_id=organization_id, role='agency',
                                          membership_role=body.get('role', 'editor'))


def organization_members(tx, user, organization_id: str) -> list[dict]:
    _visible_organization(tx, user, organization_id)
    return persistence.site_admin.members(tx, organization_id)


def update_member(tx, user, organization_id: str, member_id: str, body: dict) -> dict:
    _visible_organization(tx, user, organization_id)
    is_owner = persistence.site_admin.is_active_owner(tx, user['id'], organization_id)
    if user['role'] not in ('platform', 'organizer') and not is_owner:
        fail('FORBIDDEN_ROLE', Forbidden)
    membership = persistence.site_admin.membership(tx, member_id, organization_id)
    if not membership:
        fail('MEMBERSHIP_NOT_FOUND', NotFound)
    if body.get('role', membership['role']) != membership['role']:
        # A role change is a new reviewed account request, never a silent update.
        target = persistence.identity.user(tx, member_id)
        contact = {'name': target['name'], 'email': target['email'] if not target['email'].startswith('tel:') else None,
                   'phone': persistence.identity.phone_of(tx, member_id)}
        return account_request_service.submit(tx, actor=user, body=contact, purpose='organization',
                                              scope_type='organization', scope_id=organization_id, role='agency',
                                              membership_role=body['role'])
    values = membership_changes(body)
    persistence.site_admin.update_membership(tx, member_id, organization_id, values)
    write_audit(tx, user, user['scope_id'], 'membership_updated',
                {'organization_id': organization_id, 'member_id': member_id, **values})
    return {'ok': True, **values}


# Audit and exports -----------------------------------------------------------

def audit_entries(tx, user, site_id: str | None, limit: int) -> list[dict]:
    limit = max(1, min(limit, AUDIT_PAGE_MAX))
    if site_id:
        require_scope(tx, user, site_id)
        return persistence.audit.recent(tx, limit, site_id=site_id)
    if user['role'] != 'platform':
        manageable = [site['id'] for site in persistence.sites.list_all(tx) if can_manage(tx, user, site)]
        return persistence.audit.recent(tx, limit, site_ids=manageable or ['__none__'])
    return persistence.audit.recent(tx, limit)


def raw_submissions(tx, user, site_id: str) -> list[dict]:
    """Raw responses of one site. Organizer aggregates never imply exhibitors' raw contacts."""
    require_scope(tx, user, site_id)
    entries = persistence.submissions.for_site(tx, site_id)
    write_audit(tx, user, site_id, 'raw_export', {'rows': len(entries)})
    return entries

