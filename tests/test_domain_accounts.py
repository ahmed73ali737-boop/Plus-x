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


# Phase 3: session identification ---------------------------------------------------------------

def test_a_session_must_exist_and_be_unexpired():
    from app.domain.accounts import require_live_session
    live = {'expires_at': '2026-10-19T13:00:00+00:00'}
    assert require_live_session(live, '2026-10-19T12:00:00+00:00') is live
    for session, at in ((None, '2026-10-19T12:00:00+00:00'), (live, '2026-10-19T13:00:00+00:00'),
                        (live, '2026-10-20T00:00:00+00:00')):
        with pytest.raises(Unauthenticated) as error:
            require_live_session(session, at)
        assert error.value.code == 'LOGIN_REQUIRED'


def test_the_session_account_must_still_be_active():
    from app.domain.accounts import require_active_account
    user = {'id': 'u', 'active': 1}
    assert require_active_account(user) is user
    for gone in (None, {'id': 'u', 'active': 0}):
        with pytest.raises(Unauthenticated):
            require_active_account(gone)


def test_writes_must_echo_the_session_csrf_secret():
    from app.domain.accounts import require_csrf
    require_csrf('secret', 'secret')
    for sent in ('', 'other', 'secre'):
        with pytest.raises(Forbidden) as error:
            require_csrf(sent, 'secret')
        assert error.value.code == 'CSRF_REQUIRED'


def test_notification_and_message_targets():
    from app.domain.accounts import require_active_target_account, require_notification
    require_notification(True)
    with pytest.raises(NotFound):
        require_notification(False)
    active = {'id': 'u', 'active': 1}
    assert require_active_target_account(active) is active
    for target in (None, {'id': 'u', 'active': 0}):
        with pytest.raises(NotFound) as error:
            require_active_target_account(target)
        assert error.value.code == 'ACCOUNT_NOT_FOUND'
