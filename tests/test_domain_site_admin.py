"""Domain unit tests: site administration (no database, web framework or HTTP)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import Conflict, DomainError, Forbidden, InvalidInput, NotFound

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_directory_administration_is_staff_only_and_agencies_cannot_manage_users():
    from app.domain.sites import require_not_agency, require_platform_or_organizer
    for role in ('platform', 'organizer'):
        require_platform_or_organizer({'role': role})
    for role in ('agency', 'member'):
        with pytest.raises(Forbidden):
            require_platform_or_organizer({'role': role})
    require_not_agency({'role': 'organizer'}, {'kind': 'event'})
    with pytest.raises(Forbidden):
        require_not_agency({'role': 'agency'})
    with pytest.raises(Forbidden):
        require_not_agency({'role': 'platform'}, {'kind': 'platform'})


def test_public_signup_role_rules():
    from app.domain.organizations import require_participation_event, signup_role
    assert signup_role('organizer', {'kind': 'platform'}) == 'organizer'
    assert signup_role('participant', {'kind': 'event'}) == 'participant'
    with pytest.raises(InvalidInput):
        signup_role('admin', {'kind': 'platform'})
    with pytest.raises(Forbidden):
        signup_role('organizer', {'kind': 'event'})
    with pytest.raises(InvalidInput):
        require_participation_event('participant', None)
    require_participation_event('organizer', None)


def test_person_and_membership_rules():
    from app.domain.organizations import (
        requested_membership_role, require_membership_manager, require_unlinked_person)
    with pytest.raises(Conflict):
        require_unlinked_person({'user_id': 'u1'})
    require_unlinked_person({'user_id': None})
    require_membership_manager({'role': 'platform'}, False)
    require_membership_manager({'role': 'agency'}, True)
    with pytest.raises(Forbidden):
        require_membership_manager({'role': 'agency'}, False)
    assert requested_membership_role({'role': 'editor'}, {}) is None
    assert requested_membership_role({'role': 'editor'}, {'role': 'editor'}) is None
    assert requested_membership_role({'role': 'editor'}, {'role': 'admin'}) == 'admin'


def test_content_import_commits_once_to_the_previewed_revision():
    from app.domain.sites import ContentImport
    job = {'site_id': 's', 'user_id': 'u', 'errors': [], 'base_rev': 3}
    assert ContentImport.require_owned(job, 's', 'u') is job
    for other in (None, {**job, 'site_id': 'x'}, {**job, 'user_id': 'x'}):
        with pytest.raises(NotFound):
            ContentImport.require_owned(other, 's', 'u')
    ContentImport.require_committable(job, 3)
    with pytest.raises(Conflict):
        ContentImport.require_committable(job, 4)
    with pytest.raises(InvalidInput):
        ContentImport.require_committable({**job, 'errors': ['bad']}, 3)


# Phase 3: lookups, concealment and people management -------------------------------------------

def test_site_request_and_slug_rules():
    from app.domain.sites import (
        require_draft_saved, require_free_slug, require_request_in_scope, require_requestable_target,
        require_site, require_workflow_request, requested_role_for)
    require_requestable_target({'kind': 'event'})
    require_requestable_target({'kind': 'agency'})
    with pytest.raises(InvalidInput) as platform:
        require_requestable_target({'kind': 'platform'})
    assert platform.value.code == 'EVENT_REQUIRED'
    assert requested_role_for({'kind': 'event'}) == 'organizer'
    assert requested_role_for({'kind': 'agency'}) == 'agency'
    assert require_workflow_request('req-1') == 'req-1'
    with pytest.raises(Conflict) as legacy:
        require_workflow_request(None)
    assert legacy.value.code == 'LEGACY_REQUEST_REQUIRES_RESUBMISSION'
    require_request_in_scope('s1', 's1')
    with pytest.raises(NotFound) as other:
        require_request_in_scope('s2', 's1')
    assert other.value.code == 'ACCOUNT_REQUEST_NOT_FOUND'
    require_free_slug(None)
    with pytest.raises(Conflict) as taken:
        require_free_slug({'id': 'x'})
    assert taken.value.code == 'SLUG_EXISTS'
    assert require_site({'id': 'x'}) == {'id': 'x'}
    with pytest.raises(NotFound):
        require_site(None)
    require_draft_saved(True)
    with pytest.raises(Conflict) as stale:
        require_draft_saved(False)
    assert stale.value.code == 'DRAFT_CHANGED_REFRESH_REQUIRED'


def test_hidden_organizations_look_missing_not_forbidden():
    from app.domain.organizations import require_visible_organization
    org = {'id': 'o'}
    assert require_visible_organization(org, lambda: True) is org
    for organization, visible in ((None, True), (org, False)):
        with pytest.raises(NotFound) as error:
            require_visible_organization(organization, lambda: visible)
        assert error.value.code == 'ORGANIZATION_NOT_FOUND'
    # visibility is not even asked for a missing organization
    require_missing = []
    with pytest.raises(NotFound):
        require_visible_organization(None, lambda: require_missing.append(1) or True)
    assert require_missing == []


def test_who_manages_the_people_of_an_organization():
    from app.domain.organizations import may_manage_people, require_people_manager
    visible, hidden = (lambda: True), (lambda: False)
    assert may_manage_people({'role': 'platform'}, visible, lambda: None)
    assert not may_manage_people({'role': 'platform'}, hidden, lambda: None)
    assert may_manage_people({'role': 'agency'}, hidden, lambda: 'owner')
    assert may_manage_people({'role': 'agency'}, visible, lambda: 'admin')
    assert not may_manage_people({'role': 'agency'}, visible, lambda: 'editor')
    assert not may_manage_people({'role': 'agency'}, visible, lambda: None)
    require_people_manager(True)
    with pytest.raises(Forbidden) as denied:
        require_people_manager(False)
    assert denied.value.code == 'FORBIDDEN_ROLE'


def test_people_of_other_organizations_are_concealed():
    from app.domain.organizations import require_manageable_person, require_person_of_visible_organization
    org, person = {'id': 'o'}, {'organization_id': 'o'}
    assert require_person_of_visible_organization(org, person, 'o', lambda: True) is person
    for args in ((None, person, 'o', True), (org, None, 'o', True), (org, {'organization_id': 'x'}, 'o', True),
                 (org, person, 'o', False)):
        organization, found, organization_id, visible = args
        with pytest.raises(NotFound) as error:
            require_person_of_visible_organization(organization, found, organization_id, lambda: visible)
        assert error.value.code == 'PERSON_NOT_FOUND'
    assert require_manageable_person(person, 'o', lambda: True) is person
    for found, allowed in ((None, True), ({'organization_id': 'x'}, True), (person, False)):
        with pytest.raises(NotFound):
            require_manageable_person(found, 'o', lambda: allowed)


def test_organization_participation_and_membership_lookups():
    from app.domain.organizations import (
        require_free_organization_slug, require_membership, require_new_participation, require_organization,
        require_participation)
    for lookup, code in ((require_organization, 'ORGANIZATION_NOT_FOUND'), (require_participation, 'PARTICIPATION_NOT_FOUND'),
                         (require_membership, 'MEMBERSHIP_NOT_FOUND')):
        assert lookup({'id': 1}) == {'id': 1}
        with pytest.raises(NotFound) as error:
            lookup(None)
        assert error.value.code == code
    require_free_organization_slug(None)
    require_new_participation(False)
    with pytest.raises(Conflict) as slug:
        require_free_organization_slug({'id': 'o'})
    assert slug.value.code == 'ORGANIZATION_SLUG_EXISTS'
    with pytest.raises(Conflict) as dup:
        require_new_participation(True)
    assert dup.value.code == 'PARTICIPATION_EXISTS'


def test_legacy_access_request_status_and_lookup():
    from app.domain.sites import require_access_request, require_access_request_status
    for status in ('pending', 'approved', 'rejected'):
        assert require_access_request_status(status) == status
    with pytest.raises(InvalidInput) as bad:
        require_access_request_status('deleted')
    assert bad.value.code == 'REQUEST_STATUS_INVALID'
    assert require_access_request({'id': 1}) == {'id': 1}
    with pytest.raises(NotFound) as missing:
        require_access_request(None)
    assert missing.value.code == 'ACCESS_REQUEST_NOT_FOUND'
