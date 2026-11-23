"""Domain unit tests: self-declared certificate request rules (no database, web framework or HTTP)."""
from datetime import datetime, timezone

import pytest

from app.domain import Conflict, Forbidden, InvalidInput, NotFound, Unavailable
from app.domain.self_certificates import (
    browser_remaining_seconds,
    declared_phone,
    require_accepting,
    require_browser_not_expired,
    require_failed_job,
    require_failed_request,
    require_revision_intact,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_declared_phone_accepts_any_digit_script_and_strips_separators():
    assert declared_phone('+٩٦٧ ٧٧٧-١٢٣(٤٥٦)') == '+967777123456'
    assert declared_phone('0777 123 456') == '0777123456'
    for bad in ('12345', 'abcdefgh', '+' + '1' * 21, ''):
        with pytest.raises(InvalidInput) as raised:
            declared_phone(bad)
        assert raised.value.code == 'PHONE_INVALID'


def test_browser_window_counts_down_and_rejects_naive_or_malformed_stamps():
    assert browser_remaining_seconds('2026-10-19T11:00:00+00:00', 7200, NOW) == 3600
    for bad in ('2026-10-19T11:00:00', 'garbage', None):
        with pytest.raises(Forbidden) as raised:
            browser_remaining_seconds(bad, 7200, NOW)
        assert raised.value.code == 'BROWSER_SESSION_INVALID'
    require_browser_not_expired(1)
    with pytest.raises(Forbidden) as raised:
        require_browser_not_expired(0)
    assert raised.value.code == 'BROWSER_SESSION_EXPIRED'


def test_new_requests_need_the_switch_and_an_active_link():
    require_accepting(True, {'status': 'active'})
    with pytest.raises(Conflict) as raised:
        require_accepting(False, {'status': 'active'})
    assert raised.value.code == 'CERTIFICATE_REQUESTS_PAUSED'
    with pytest.raises(Conflict) as raised:
        require_accepting(True, {'status': 'paused'})
    assert raised.value.code == 'CERTIFICATE_LINK_PAUSED'


def test_a_tampered_revision_is_unavailable_not_silently_used():
    require_revision_intact('h', 'h')
    with pytest.raises(Unavailable) as raised:
        require_revision_intact('h', 'other')
    assert raised.value.code == 'REVISION_INTEGRITY_ERROR'


def test_retry_needs_a_failed_request_and_a_failed_job():
    assert require_failed_request({'status': 'failed'})
    with pytest.raises(NotFound):
        require_failed_request(None)
    with pytest.raises(Conflict):
        require_failed_request({'status': 'registered'})
    require_failed_job({'status': 'failed'})
    with pytest.raises(Conflict):
        require_failed_job({'status': 'pending'})
