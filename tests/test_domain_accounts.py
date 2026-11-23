"""Domain unit tests: account administration guards (no database, web framework or HTTP)."""
import pytest

from app.domain import Conflict, Forbidden, InvalidInput, NotFound, Unauthenticated
from app.domain.accounts import (
    platform_status,
    require_credentials,
    require_known_user,
    require_organizer_reset_scope,
    require_reset_authority,
    site_user_status,
)


def test_only_staff_reset_passwords_and_organizers_only_scoped_accounts():
    for role in ('platform', 'organizer'):
        require_reset_authority({'role': role})
    with pytest.raises(Forbidden):
        require_reset_authority({'role': 'agency'})
    require_organizer_reset_scope({'role': 'agency', 'scope_id': 's1'})
    for target in ({'role': 'platform', 'scope_id': 's1'}, {'role': 'agency', 'scope_id': None}):
        with pytest.raises(Forbidden):
            require_organizer_reset_scope(target)


def test_unknown_user_is_not_found():
    assert require_known_user({'id': 'u'}) == {'id': 'u'}
    with pytest.raises(NotFound):
        require_known_user(None)


def test_platform_status_needs_a_boolean_and_never_suspends_self():
    actor = {'id': 'a'}
    assert platform_status(False, actor, 'b') is False
    for bad in (0, 'false', None):
        with pytest.raises(InvalidInput):
            platform_status(bad, actor, 'b')
    with pytest.raises(Conflict) as raised:
        platform_status(False, actor, 'a')
    assert raised.value.code == 'CANNOT_SUSPEND_SELF'


def test_site_user_status_accepts_booleans_and_flags_only():
    assert site_user_status(1) is True and site_user_status(False) is False
    for bad in ('yes', None, 2):
        with pytest.raises(InvalidInput):
            site_user_status(bad)


def test_failed_password_reentry_is_one_indistinguishable_error():
    require_credentials(True)
    with pytest.raises(Unauthenticated) as raised:
        require_credentials(False)
    assert raised.value.code == 'INVALID_CREDENTIALS'
