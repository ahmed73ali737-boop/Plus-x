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
