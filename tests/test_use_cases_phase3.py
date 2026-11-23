"""Phase-3 use-case tests against in-memory ports: collection, access scope, phone binding."""
import uuid

import pytest

from app.application import access, collection_service, phone_accounts
from app.application.audit_service import AuditedDenial
from app.application.ports import persistence
from app.domain import Conflict, Forbidden, InvalidInput, NotFound
from app.domain.site_config import default_config
from test_use_cases import FakeAudit, FakeSites, FakeTransactions


class FakeSubmissions:
    def __init__(self):
        self.rows = {}

    def get(self, tx, submission_id):
        return self.rows.get(submission_id)

    def add(self, tx, row):
        self.rows[row['id']] = row


class FakeAdmission:
    def policy_config(self, tx, event_id):
        return None


class FakeAccess:
    """Facts of one user: assignments by site, active memberships, participations."""

    def __init__(self, assignments=(), org_ids=(), participations=()):
        self._assignments, self._org_ids, self._participations = list(assignments), list(org_ids), list(participations)

    def assignments(self, tx, user_id, site_id, roles=None):
        return [a for a in self._assignments if roles is None or a['role'] in roles]

    def active_membership_org_ids(self, tx, user_id, roles):
        return self._org_ids

    def participations_of(self, tx, organization_ids, site_id, active_only=False):
        return [p for p in self._participations if not active_only or p['status'] == 'active']

    def participations_for_agency_site(self, tx, site_id):
        return []

    def memberships_in(self, tx, user_id, organization_ids):
        return []

    def has_active_membership(self, tx, user_id, organization_id=None, role=None):
        return False

    def organization_in_event(self, tx, organization_id, event_id):
        return False


def install(**fakes):
    saved = dict(persistence._adapters)
    persistence.install(transactions=FakeTransactions(), audit=FakeAudit(), **fakes)
    return saved


@pytest.fixture
def restore_ports():
    saved = dict(persistence._adapters)
    yield
    persistence._adapters.clear()
    persistence._adapters.update(saved)


def site(site_id='event', kind='event', **values):
    return {'id': site_id, 'kind': kind, 'event_id': 'event', 'slug': site_id, 'parent_id': 'platform',
            'draft': default_config(site_id, kind), 'draft_rev': 1, 'published_version': 1, **values}


def visit(**values):
    return {'id': str(uuid.uuid4()), 'visitor_id': str(uuid.uuid4()), 'session_id': str(uuid.uuid4()),
            'site_id': 'event', 'version': 1, 'kind': 'visit', 'source': 'web', **values}


@pytest.fixture
def collection(restore_ports):
    sites = FakeSites(site())
    sites.add_version(None, 'event', 1, default_config('event', 'event'), 't')
    fakes = dict(sites=sites, submissions=FakeSubmissions(), admission=FakeAdmission())
    install(**fakes)
    return fakes


def test_collect_accepts_replays_and_rejects_conflicting_ids(collection):
    body = visit()
    assert collection_service.collect('db', [body]) == [{'id': body['id'], 'status': 'accepted'}]
    assert collection_service.collect('db', [body]) == [{'id': body['id'], 'status': 'duplicate'}]
    changed = {**body, 'source': 'qr'}
    assert collection_service.collect('db', [changed]) == [
        {'id': body['id'], 'status': 'rejected', 'error': 'IDEMPOTENCY_BODY_CONFLICT'}]
    assert len(collection['submissions'].rows) == 1


def test_collect_rejects_each_bad_item_on_its_own_and_oversized_batches(collection):
    good, unknown_site = visit(), visit(site_id='missing')
    receipts = collection_service.collect('db', [good, unknown_site, 'not-an-object', {**visit(), 'preview': True}])
    assert [r['status'] for r in receipts] == ['accepted', 'rejected', 'rejected', 'rejected']
    assert receipts[1]['error'] == 'SITE_NOT_FOUND'
    assert receipts[2]['error'] == 'SUBMISSION_OBJECT_REQUIRED'
    assert receipts[3]['error'] == 'PREVIEW_WRITES_FORBIDDEN'
    for bad in ([], [visit()] * 51):
        with pytest.raises(InvalidInput, match='BATCH_1_TO_50_ITEMS'):
            collection_service.collect('db', bad)


def test_feedback_scope_is_enforced_through_the_use_case(collection):
    sites = collection['sites']
    sites.rows['agency'] = site('agency', 'agency', published_version=1)
    sites.rows['other'] = site('other', 'agency', published_version=0)
    sites.rows['foreign'] = site('foreign', 'agency', event_id='elsewhere')
    for sid in ('agency', 'other', 'foreign'):
        sites.add_version(None, sid, 1, default_config(sid, 'agency'), 't')
    feedback = visit(kind='feedback', payload={'rating': 4})
    assert collection_service.collect('db', [{**feedback, 'target': 'agency:general'}])[0]['status'] == 'accepted'
    for target, error in (('other:general', 'FEEDBACK_SCOPE'), ('foreign:general', 'FEEDBACK_SCOPE'),
                          ('nowhere:general', 'SITE_NOT_FOUND'), ('agency:nothing', 'FEEDBACK_TARGET')):
        receipt = collection_service.collect('db', [{**feedback, 'id': str(uuid.uuid4()), 'target': target}])[0]
        assert receipt == {'id': receipt['id'], 'status': 'rejected', 'error': error}


def user(role='member', **values):
    return {'id': 'u1', 'role': role, 'scope_id': None, 'active': 1, **values}


def test_scope_checks_audit_denials_and_conceal_unknown_sites(restore_ports):
    install(sites=FakeSites(site('agency', 'agency')), access=FakeAccess())
    with pytest.raises(NotFound, match='SITE_NOT_FOUND'):
        access.require_scope(None, user('platform'), 'missing')
    assert access.require_scope(None, user('platform'), 'agency')['id'] == 'agency'
    with pytest.raises(AuditedDenial, match='FORBIDDEN_SCOPE') as denial:
        access.require_scope(None, user(), 'agency')
    assert denial.value.kind == 'forbidden' and denial.value.audit_action == 'scope_denied' and denial.value.audit_site_id == 'agency'


def test_event_permissions_fail_closed(restore_ports):
    install(sites=FakeSites(site('agency', 'agency'), site()), access=FakeAccess())
    with pytest.raises(InvalidInput, match='EVENT_REQUIRED'):
        access.event_permissions(None, user('platform'), 'agency')
    with pytest.raises(AuditedDenial, match='FORBIDDEN_EVENT_PERMISSION') as unknown:
        access.require_event_permission(None, user('platform'), 'event', 'guests.delete')
    assert unknown.value.audit_site_id is None          # unknown names are denied without touching the site
    with pytest.raises(AuditedDenial) as denied:
        access.require_event_permission(None, user(), 'event', 'guests.read')
    assert denied.value.audit_site_id == 'event'
    assert access.require_event_permission(None, user('organizer', scope_id='event'), 'event', 'guests.read')['id'] == 'event'
    assert access.event_permissions(None, user('platform', active=0), 'event') == frozenset()


def test_read_scope_comes_from_analyst_assignment_but_does_not_manage(restore_ports):
    analyst = {'role': 'analyst', 'status': 'active'}
    install(sites=FakeSites(site('agency', 'agency')), access=FakeAccess(assignments=[analyst]))
    assert access.require_read_scope(None, user(), 'agency')['id'] == 'agency'
    with pytest.raises(AuditedDenial, match='FORBIDDEN_SCOPE'):
        access.require_scope(None, user(), 'agency')


class FakeIdentity:
    def __init__(self, bindings=()):
        self.bound = {phone: user_id for phone, user_id in bindings}
        self.added = []

    def phone_binding(self, tx, phone):
        return {'phone': phone, 'user_id': self.bound[phone]} if phone in self.bound else None

    def phone_binding_of(self, tx, user_id):
        return next(({'phone': p, 'user_id': u} for p, u in self.bound.items() if u == user_id), None)

    def bind_phone(self, tx, phone, user_id):
        self.added.append((phone, user_id))
        self.bound[phone] = user_id


def test_bind_phone_binds_once_and_refuses_takeover_or_change(restore_ports):
    identity = FakeIdentity([('+967771234567', 'u1'), ('+967772222222', 'u2')])
    install(identity=identity)
    phone_accounts.bind_phone(None, 'u1', '+967771234567')       # already theirs: no write
    assert identity.added == []
    phone_accounts.bind_phone(None, 'u3', '+967773333333')
    assert identity.added == [('+967773333333', 'u3')]
    with pytest.raises(Conflict, match='PHONE_ALREADY_REGISTERED'):
        phone_accounts.bind_phone(None, 'u1', '+967772222222')
    with pytest.raises(Conflict, match='PHONE_CHANGE_REQUIRES_SUPPORT'):
        phone_accounts.bind_phone(None, 'u1', '+967774444444')


class FakeSiteAdmin:
    def __init__(self):
        self.organizations = {'org1': {'id': 'org1', 'slug': 'org-one', 'name': 'Org'}}
        self.people = {'p1': {'id': 'p1', 'organization_id': 'org1', 'name': 'P', 'email': '', 'phone': '', 'user_id': None}}
        self.added = []

    def organization(self, tx, organization_id):
        return self.organizations.get(organization_id)

    def person(self, tx, person_id):
        return self.people.get(person_id)

    def add_person(self, tx, person):
        self.added.append(person)

    def membership(self, tx, member_id, organization_id):
        return None

    def is_active_owner(self, tx, user_id, organization_id):
        return False


class PeopleAccess(FakeAccess):
    def __init__(self, membership=None, member_of=()):
        super().__init__()
        self.role, self.member_of = membership, set(member_of)

    def has_active_membership(self, tx, user_id, organization_id=None, role=None):
        return organization_id in self.member_of

    def membership_role(self, tx, user_id, organization_id):
        return self.role


def test_people_management_conceals_hidden_organizations_and_denies_plain_members(restore_ports):
    from app.application import site_admin
    admin = FakeSiteAdmin()
    install(sites=FakeSites(), site_admin=admin, access=PeopleAccess(membership='editor', member_of={'org1'}))
    body = {'name': 'New person', 'email': '', 'phone': ''}
    with pytest.raises(NotFound, match='ORGANIZATION_NOT_FOUND'):
        site_admin.add_person(None, user('agency'), 'ghost', body)
    with pytest.raises(Forbidden, match='FORBIDDEN_ROLE'):
        site_admin.add_person(None, user('agency'), 'org1', body)
    assert admin.added == []
    # an organization the actor cannot see is not found, even for an existing person
    install(sites=FakeSites(), site_admin=admin, access=PeopleAccess(member_of=()))
    with pytest.raises(NotFound, match='PERSON_NOT_FOUND'):
        site_admin.update_person(None, user('agency'), 'org1', 'p1', {'name': 'X'})
    with pytest.raises(NotFound, match='PERSON_NOT_FOUND'):
        site_admin.request_person_account(None, user('agency'), 'org1', 'p1', {})


def test_people_managers_can_add_people(restore_ports):
    from app.application import site_admin
    admin = FakeSiteAdmin()
    install(sites=FakeSites(), site_admin=admin, access=PeopleAccess(membership='admin', member_of={'org1'}))
    result = site_admin.add_person(None, user('agency'), 'org1', {'name': 'New person'})
    assert result['organization_id'] == 'org1' and admin.added[0]['name'] == 'New person'
