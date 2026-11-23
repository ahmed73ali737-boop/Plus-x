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


# Phase 3: request links, models and assets, participant browser sessions ------------------

LINK_BODY = {'event_id': 'e1', 'model_id': 'm1', 'share_text': ' hello ', 'idempotency_key': 'k' * 16}


def test_link_request_shape_is_strict_and_precedes_field_validation():
    from app.domain.self_certificates import LinkRequest
    for bad in (None, [], {}, {**LINK_BODY, 'extra': 1}, {k: v for k, v in LINK_BODY.items() if k != 'model_id'}):
        with pytest.raises(InvalidInput) as error:
            LinkRequest.check_shape(bad)
        assert error.value.code == 'LINK_INPUT_INVALID'
    with pytest.raises(InvalidInput) as blank:
        LinkRequest.parse({**LINK_BODY, 'share_text': '  '})
    assert blank.value.code == 'TEXT_LENGTH'


def test_link_request_identity_changes_with_any_input():
    from app.domain.self_certificates import LinkRequest
    base = LinkRequest.parse(LINK_BODY)
    assert base.share_text == 'hello'
    assert 'expected_revision_id' not in base.identity()
    pinned = LinkRequest.parse({**LINK_BODY, 'expected_revision_id': 'r1'})
    assert pinned.identity() == {**base.identity(), 'expected_revision_id': 'r1'}
    assert LinkRequest.parse({**LINK_BODY, 'event_id': 'e2'}).identity() != base.identity()


def test_idempotent_replays_need_identical_input_and_pilot_gate_must_allow():
    from app.domain.self_certificates import require_pilot_available, require_same_operation
    require_same_operation('h', 'h')
    with pytest.raises(Conflict) as replay:
        require_same_operation('h', 'other')
    assert replay.value.code == 'IDEMPOTENCY_CONFLICT'
    require_pilot_available(True)
    with pytest.raises(Conflict) as gate:
        require_pilot_available(False)
    assert gate.value.code == 'CERTIFICATE_PILOT_UNAVAILABLE'


def test_link_creation_needs_the_expected_revision_current_schema_and_owned_assets():
    from app.domain.self_certificates import (
        require_asset_owned, require_current_schema, require_expected_revision, require_revision_available)
    require_expected_revision(None, 'r2')
    require_expected_revision('r2', 'r2')
    with pytest.raises(Conflict) as changed:
        require_expected_revision('r1', 'r2')
    assert changed.value.code == 'MODEL_REVISION_CHANGED'
    require_current_schema({'schema_version': 2})
    with pytest.raises(Conflict) as old:
        require_current_schema({'schema_version': 1})
    assert old.value.code == 'MODEL_UPGRADE_REQUIRED'
    with pytest.raises(Conflict) as missing:
        require_revision_available(None)
    assert missing.value.code == 'REVISION_UNAVAILABLE'
    with pytest.raises(Conflict) as foreign:
        require_asset_owned(None)
    assert foreign.value.code == 'ASSET_OWNER_MISMATCH'


def test_optimistic_row_versions_are_strict():
    from app.domain.self_certificates import require_changed, require_row_version
    require_row_version(3, {'row_version': 3})
    for bad in (2, '3', True, None):
        with pytest.raises(Conflict) as error:
            require_row_version(bad, {'row_version': 1 if bad is True else 3})
        assert error.value.code == 'VERSION_CONFLICT'
    require_changed(True)
    with pytest.raises(Conflict):
        require_changed(False)


def test_link_state_change_accepts_only_pause_or_resume_of_the_current_version():
    from app.domain.self_certificates import LinkStateChange
    link = {'row_version': 4}
    assert LinkStateChange.parse({'status': 'paused', 'row_version': 4}, link).resumes is False
    assert LinkStateChange.parse({'status': 'active', 'row_version': 4}, link).resumes is True
    for bad in ({'status': 'deleted', 'row_version': 4}, {'status': 'active'}, {'status': 'active', 'row_version': 4, 'x': 1}, 'x'):
        with pytest.raises(InvalidInput) as error:
            LinkStateChange.parse(bad, link)
        assert error.value.code == 'LINK_STATE_INVALID'
    with pytest.raises(Conflict):
        LinkStateChange.parse({'status': 'active', 'row_version': 3}, link)


def test_public_links_are_concealed_unless_the_token_matches():
    from app.domain.self_certificates import require_public_link
    row = {'id': 'l1'}
    assert require_public_link(row, True) is row
    for args in ((None, False), (row, False), (None, True)):
        with pytest.raises(NotFound):
            require_public_link(*args)


def test_pagination_filter_and_asset_reference_rules():
    from app.domain.self_certificates import (
        page_window, require_asset_of_kind, require_asset_reference, require_model_operation_key, search_filter)
    assert page_window(0, 100) == (0, 100)
    for bad in ((-1, 10), (0, 0), (0, 101), ('0', 10), (True, 10), (0, 1.5)):
        with pytest.raises(InvalidInput) as error:
            page_window(*bad)
        assert error.value.code == 'PAGE_INVALID'
    assert search_filter('  x ') == 'x'
    for bad in (None, 'x' * 161, 5):
        with pytest.raises(InvalidInput):
            search_filter(bad)
    for bad in ('', 5, 'x' * 65):
        with pytest.raises(NotFound):
            require_asset_reference(bad)
    assert require_asset_of_kind({'kind': 'stamp'}, 'stamp') == {'kind': 'stamp'}
    assert require_asset_of_kind({'kind': 'stamp'}, None)
    with pytest.raises(NotFound):
        require_asset_of_kind({'kind': 'stamp'}, 'background')
    with pytest.raises(NotFound):
        require_asset_of_kind(None, None)
    require_model_operation_key(None, 'a' * 16)
    for model_id, key in (('m', 'a' * 16), (None, 'short'), (None, 'a' * 81), (None, 5), (None, 'bad key bad key!')):
        with pytest.raises(InvalidInput):
            require_model_operation_key(model_id, key)


def test_upload_gate_checks_kind_emptiness_and_size_before_any_decoding():
    from app.domain.self_certificates import (
        MAX_BACKGROUND_BYTES, MAX_STAMP_BYTES, asset_worker_error, require_normalized_size, require_upload)
    require_upload(b'x', 'background')
    cases = [(b'x', 'logo', 'ASSET_KIND_INVALID'), (b'', 'stamp', 'FILE_EMPTY'), ('x', 'stamp', 'FILE_EMPTY'),
             (b'x' * (MAX_STAMP_BYTES + 1), 'stamp', 'STAMP_TOO_LARGE'),
             (b'x' * (MAX_BACKGROUND_BYTES + 1), 'background', 'BACKGROUND_TOO_LARGE')]
    for data, kind, code in cases:
        with pytest.raises(InvalidInput) as error:
            require_upload(data, kind)
        assert error.value.code == code
    require_upload(b'x' * MAX_BACKGROUND_BYTES, 'background')
    with pytest.raises(InvalidInput):
        require_normalized_size(b'')
    with pytest.raises(Unavailable) as isolation:
        asset_worker_error('ASSET_PROCESS_ISOLATION_UNAVAILABLE')
    assert isolation.value.code == 'ASSET_PROCESS_ISOLATION_UNAVAILABLE'
    with pytest.raises(InvalidInput):
        asset_worker_error('IMAGE_DECODE_FAILED')


def test_participant_browser_session_rules():
    from app.domain.self_certificates import (
        require_browser_seed, require_browser_token, require_issued_certificate, require_key_version_available,
        require_owner_still_authorised)
    require_browser_seed('a' * 64)
    for bad in ('A' * 64, 'a' * 63, None, 5):
        with pytest.raises(InvalidInput) as error:
            require_browser_seed(bad)
        assert error.value.code == 'BROWSER_STORAGE_REQUIRED'
    row = {'id': 'b'}
    assert require_browser_token(row, True) is row
    for args in ((None, True), (row, False)):
        with pytest.raises(Forbidden) as invalid:
            require_browser_token(*args)
        assert invalid.value.code == 'BROWSER_SESSION_INVALID'
    assert require_key_version_available('v1') == 'v1'
    with pytest.raises(Unavailable):
        require_key_version_available(None)
    require_owner_still_authorised(True)
    with pytest.raises(Conflict) as revoked:
        require_owner_still_authorised(False)
    assert revoked.value.code == 'CERTIFICATE_LINK_UNAVAILABLE'
    assert require_issued_certificate({'id': 'c'}) == {'id': 'c'}
    with pytest.raises(Unavailable):
        require_issued_certificate(None)
