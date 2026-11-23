"""Domain unit tests: site management/read scope and certificate library authority (no database, no HTTP)."""
import pytest

from app.domain import Forbidden, InvalidInput, NotFound, PreconditionRequired, Unauthenticated
from app.domain import authorization as auth
from app.domain.guards import reject_existing, require_found

NOW = '2026-10-19T12:00:00+00:00'


class Facts:
    """In-memory SiteAccessFacts; counts reads so lazy ordering is part of the contract."""

    def __init__(self, linked=(), memberships=(), assignments=(), org_ids=(), participations=()):
        self.linked, self.memberships = list(linked), list(memberships)
        self._assignments, self.org_ids, self.participations = list(assignments), list(org_ids), list(participations)
        self.reads = []

    def participations_for_agency_site(self):
        self.reads.append('linked')
        return self.linked

    def memberships_in(self, organization_ids):
        self.reads.append('memberships')
        return self.memberships

    def assignments(self, roles=None):
        self.reads.append('assignments')
        return [a for a in self._assignments if roles is None or a['role'] in roles]

    def active_membership_org_ids(self, roles):
        self.reads.append('org_ids')
        return self.org_ids

    def participations_of(self, organization_ids, active_only=False):
        self.reads.append('participations_of')
        return [p for p in self.participations if not active_only or auth.active_participation(p)]


def user(role='agency', **values):
    return {'id': 'u1', 'role': role, 'scope_id': 'site1', 'active': 1, **values}


SITE = {'id': 'site1', 'event_id': 'ev1', 'kind': 'agency'}
ASSIGN = {'role': 'event_manager', 'status': 'active', 'valid_from': None, 'valid_until': None}


def test_guards_name_the_failure_category():
    assert require_found({'a': 1}, 'X') == {'a': 1}
    with pytest.raises(NotFound) as missing:
        require_found(None, 'SITE_NOT_FOUND')
    assert missing.value.code == 'SITE_NOT_FOUND'
    with pytest.raises(Forbidden):
        require_found(None, 'FORBIDDEN', Forbidden)
    reject_existing(None, 'DUP')
    with pytest.raises(Exception) as dup:
        reject_existing({'id': 1}, 'SLUG_EXISTS')
    assert dup.value.kind == 'conflict'


def test_inactive_user_manages_and_reads_nothing_and_asks_for_no_facts():
    facts = Facts()
    assert not auth.can_manage_site(user('platform', active=0), SITE, facts)
    assert not auth.can_read_site(user('platform', active=0), SITE, facts)
    assert facts.reads == []


def test_platform_and_owning_organizer_manage_without_reading_facts():
    facts = Facts()
    assert auth.can_manage_site(user('platform'), SITE, facts)
    assert auth.can_manage_site(user('organizer', scope_id='ev1'), SITE, facts)
    assert not auth.can_manage_site(user('organizer', scope_id='other'), SITE, Facts())
    assert facts.reads == []


def test_agency_page_follows_the_participation_lifecycle():
    org = {'organization_id': 'o1', 'status': 'active'}
    member = {'organization_id': 'o1', 'status': 'active', 'role': 'editor'}
    assert auth.can_manage_site(user(), SITE, Facts())  # legacy standalone page keeps direct access
    assert auth.can_manage_site(user(), SITE, Facts(linked=[org], memberships=[member]))
    assert not auth.can_manage_site(user(), SITE, Facts(linked=[{**org, 'status': 'ended'}], memberships=[member]))
    assert not auth.can_manage_site(user(), SITE, Facts(linked=[org], memberships=[{**member, 'role': 'analyst'}]))
    # an agency user on another page does not get this shortcut
    assert not auth.can_manage_site(user(scope_id='elsewhere'), SITE, Facts(linked=[org], memberships=[member]))


def test_management_by_assignment_needs_a_management_role_in_its_window():
    assert auth.can_manage_site(user('member'), SITE, Facts(assignments=[ASSIGN]), NOW)
    expired = {**ASSIGN, 'valid_until': '2026-10-19T11:00:00+00:00'}
    assert not auth.can_manage_site(user('member'), SITE, Facts(assignments=[expired]), NOW)
    assert not auth.can_manage_site(user('member'), SITE, Facts(assignments=[{**ASSIGN, 'role': 'analyst'}]), NOW)


def test_management_by_organization_needs_an_active_participation():
    facts = Facts(org_ids=['o1'], participations=[{'status': 'ended'}])
    assert not auth.can_manage_site(user('member'), SITE, facts, NOW)
    assert auth.can_manage_site(user('member'), SITE, Facts(org_ids=['o1'], participations=[{'status': 'active'}]), NOW)


def test_read_scope_never_flows_back_into_management():
    analyst = {'role': 'analyst', 'status': 'active'}
    facts = Facts(assignments=[analyst])
    assert not auth.can_manage_site(user('member'), SITE, facts, NOW)
    assert auth.can_read_site(user('member'), SITE, Facts(assignments=[analyst]), NOW)
    assert auth.can_read_site(user('member'), SITE, Facts(org_ids=['o1'], participations=[{'status': 'active'}]), NOW)
    assert not auth.can_read_site(user('member'), SITE, Facts(org_ids=['o1'], participations=[{'status': 'ended'}]), NOW)
    assert not auth.can_read_site(user('member'), SITE, Facts(), NOW)


def test_organization_visibility_rules():
    assert auth.organization_visible('platform', False, False)
    assert auth.organization_visible('agency', True, False)
    assert auth.organization_visible('organizer', False, True)
    assert not auth.organization_visible('agency', False, True)
    assert not auth.organization_visible('organizer', False, False)


def test_event_kind_and_unknown_permission_fail_closed():
    auth.require_event_kind({'kind': 'event'})
    with pytest.raises(InvalidInput):
        auth.require_event_kind({'kind': 'agency'})
    assert auth.is_known_event_permission('guests.read')
    assert not auth.is_known_event_permission('guests.delete')


def test_live_principal_requires_active_account_and_finished_password_change():
    good = {'active': 1, 'must_change_password': 0}
    assert auth.require_live_principal(good) is good
    for missing in (None, {}):
        with pytest.raises(Unauthenticated):
            auth.require_live_principal(missing)
    with pytest.raises(Unauthenticated):
        auth.require_live_principal({'active': 0, 'must_change_password': 0})
    with pytest.raises(PreconditionRequired):
        auth.require_live_principal({'active': 1, 'must_change_password': 1})


def test_library_authority_and_capabilities():
    assert auth.can_manage_library('platform', False, False)
    assert auth.can_manage_library('organizer', False, False)
    assert auth.can_manage_library('member', True, False)
    assert auth.can_manage_library('member', False, True)
    assert not auth.can_manage_library('member', False, False)
    auth.require_library_authority(True)
    with pytest.raises(Forbidden):
        auth.require_library_authority(False)
    with pytest.raises(Forbidden):
        auth.require_event_authority(False)
    assert auth.require_library_capability('models.manage') is True
    assert auth.require_library_capability('links.manage') is True
    # own-account reads stay possible without library authority
    assert auth.require_library_capability('requests.read') is False
    assert auth.require_library_capability('requests.export') is False
    with pytest.raises(Forbidden):
        auth.require_library_capability('models.delete')


def test_eligible_events_and_direct_authority_and_owner_only():
    assert auth.eligible_event_ids('organizer', 'ev1', ['ev2'], ['ev3']) == {'ev1', 'ev2', 'ev3'}
    assert auth.eligible_event_ids('member', 'ev1', ['ev2'], []) == {'ev2'}
    assert auth.has_direct_event_authority('platform', None, 'ev1')
    assert auth.has_direct_event_authority('organizer', 'ev1', 'ev1')
    assert not auth.has_direct_event_authority('organizer', 'ev2', 'ev1')
    assert not auth.has_direct_event_authority('member', 'ev1', 'ev1')
    auth.require_owner_account('a', 'a')
    with pytest.raises(NotFound):
        auth.require_owner_account('a', 'b')
