"""Domain unit tests: account approval (no database, web framework or HTTP)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import Conflict, DomainError, Forbidden, InvalidInput, NotFound

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_account_requests_can_be_paused_by_operators():
    from app.domain import Unavailable
    from app.domain.account_requests import requests_accepting
    requests_accepting('true')
    requests_accepting('YES')
    with pytest.raises(Unavailable) as raised:
        requests_accepting('false')
    assert raised.value.code == 'ACCOUNT_REQUESTS_PAUSED'


def test_only_designated_supervisor_sees_a_request():
    from app.domain.account_requests import require_assigned_supervisor
    require_assigned_supervisor({'id': 'u1'}, {'supervisor_id': 'u1'})
    for record in (None, {'supervisor_id': 'u2'}):
        with pytest.raises(NotFound):
            require_assigned_supervisor({'id': 'u1'}, record)


def test_review_disposition_covers_replay_expiry_and_proceed():
    from app.domain.account_requests import review_disposition
    at = '2026-10-19T12:00:00+00:00'
    assert review_disposition({'status': 'approved', 'expires_at': '2030-01-01'}, at) == 'already_reviewed'
    assert review_disposition({'status': 'pending', 'expires_at': '2026-10-19T11:00:00+00:00'}, at) == 'expired'
    assert review_disposition({'status': 'pending', 'expires_at': '2026-10-20T11:00:00+00:00'}, at) == 'proceed'


def test_approval_never_adopts_or_collides_with_an_existing_login():
    from app.domain.account_requests import require_active_target, require_unclaimed_identity
    with pytest.raises(Conflict):
        require_unclaimed_identity({'purpose': 'personal', 'existing_user_id': None}, {'id': 'u'})
    with pytest.raises(Conflict):
        require_unclaimed_identity({'purpose': 'site', 'existing_user_id': 'u1'}, {'id': 'u2'})
    with pytest.raises(Conflict):
        require_unclaimed_identity({'purpose': 'site', 'existing_user_id': 'u1'}, None)
    require_unclaimed_identity({'purpose': 'site', 'existing_user_id': 'u1'}, {'id': 'u1'})
    with pytest.raises(Conflict) as raised:
        require_active_target({'active': False})
    assert raised.value.code == 'ACCOUNT_SUSPENDED'


def test_password_setup_needs_an_open_window_and_matching_confirmation():
    from app.domain.account_requests import require_password_setup
    record = {'status': 'approved'}
    workflow = {'setup_expires_at': '2026-10-20T00:00:00+00:00'}
    at = '2026-10-19T12:00:00+00:00'
    require_password_setup(record, workflow, at, {'password': 'x', 'confirmation': 'x'})
    with pytest.raises(InvalidInput):
        require_password_setup(record, workflow, at, {'password': 'x', 'confirmation': 'y'})
    with pytest.raises(Conflict):
        require_password_setup(record, {'setup_expires_at': '2026-10-18T00:00:00+00:00'}, at, {})
    with pytest.raises(Conflict):
        require_password_setup({'status': 'pending'}, workflow, at, {})


def test_setup_renewal_blocks_self_service_and_used_setups():
    from app.domain.account_requests import require_setup_renewable
    record = {'requested_by': 'u9', 'status': 'approved'}
    workflow = {'setup_expires_at': '2026-10-19T00:00:00+00:00'}
    require_setup_renewable(record, workflow, {'active': False}, {'id': 'u1'})
    with pytest.raises(Forbidden):
        require_setup_renewable(record, workflow, {'active': False}, {'id': 'u9'})
    with pytest.raises(Conflict):
        require_setup_renewable(record, workflow, {'active': True}, {'id': 'u1'})
    with pytest.raises(Conflict):
        require_setup_renewable(record, {'setup_expires_at': None}, {'active': False}, {'id': 'u1'})


def test_platform_invitation_rules():
    from app.domain.account_requests import require_invitation_usable, require_platform_inviter
    require_platform_inviter({'role': 'platform', 'active': True})
    for actor in ({'role': 'organizer', 'active': True}, {'role': 'platform', 'active': False}):
        with pytest.raises(Forbidden):
            require_platform_inviter(actor)
    at = '2026-10-19T12:00:00+00:00'
    require_invitation_usable({'request_id': None, 'expires_at': '2026-10-20T00:00:00+00:00'}, at)
    require_invitation_usable({'request_id': 'r', 'expires_at': '2020-01-01T00:00:00+00:00'}, at)
    with pytest.raises(Conflict):
        require_invitation_usable({'request_id': None, 'expires_at': '2026-10-18T00:00:00+00:00'}, at)


def test_organizer_may_submit_organizer_requests_for_their_event_only():
    from app.domain.account_requests import organizer_may_submit_for_platform
    record = {'requested_role': 'organizer', 'scope_id': 'e1'}
    assert organizer_may_submit_for_platform({'role': 'organizer', 'scope_id': 'e1'}, record)
    assert not organizer_may_submit_for_platform({'role': 'organizer', 'scope_id': 'e2'}, record)
    assert not organizer_may_submit_for_platform({'role': 'agency', 'scope_id': 'e1'}, record)
