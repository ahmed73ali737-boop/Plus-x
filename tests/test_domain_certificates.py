"""Domain unit tests: certificates (no database, web framework or HTTP)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import Conflict, DomainError, Forbidden, InvalidInput, NotFound, fail

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _png_stub(raw):
    return raw


def _issue_request(**overrides):
    from app.domain.certificates import IssueRequest
    body = {'template_id': 't1', 'request_key': 'k1', 'recipient_key': 'r1', 'award_key': 'a1',
            'data': {'participant_name': 'Sara', 'course_title': 'Safety', 'issuer_name': 'Eventna'}}
    body.update(overrides)
    return IssueRequest.parse(body)


def _issued(request=None, **overrides):
    from app.domain.certificates import Certificate
    values = dict(certificate_id='c1', event_id='e1', serial='CERT-1', access_hash='h', font_hash='f',
                  issued_at='2026-10-20T23:30:00+00:00', check_layout=lambda design, data: None)
    values.update(overrides)
    return Certificate.issue(request or _issue_request(timezone='Asia/Aden'),
                             {'design': {'layers': []}}, **values)


def test_certificate_design_rejects_unknown_variable_font_alignment_and_color():
    from app.domain.certificates import CertificateDesign, default_design
    assert CertificateDesign.normalize(default_design(), _png_stub)['layers']
    for layer, code in (({'text': '{{nope}}'}, 'CERTIFICATE_VARIABLE_UNKNOWN'),
                        ({'text': 'x', 'font': 'Comic'}, 'CERTIFICATE_FONT_INVALID'),
                        ({'text': 'x', 'align': 'left'}, 'CERTIFICATE_ALIGNMENT_INVALID'),
                        ({'text': 'x', 'color': 'red'}, 'CERTIFICATE_COLOR_INVALID')):
        with pytest.raises(InvalidInput) as raised:
            CertificateDesign.normalize({'layers': [layer]}, _png_stub)
        assert raised.value.code == code


def test_certificate_design_bounds_layers_and_shape():
    from app.domain.certificates import CertificateDesign
    for raw, code in (([], 'CERTIFICATE_DESIGN_INVALID'), ({'layers': []}, 'CERTIFICATE_LAYERS_INVALID'),
                      ({'layers': ['x']}, 'CERTIFICATE_LAYER_INVALID'),
                      ({'layers': [{'text': 'x'}], 'qr': 3}, 'CERTIFICATE_QR_INVALID')):
        with pytest.raises(InvalidInput) as raised:
            CertificateDesign.normalize(raw, _png_stub)
        assert raised.value.code == code


def test_issue_request_requires_core_fields_and_known_data_keys():
    from app.domain.certificates import IssueRequest
    with pytest.raises(InvalidInput) as raised:
        IssueRequest.parse({'template_id': 't', 'request_key': 'k', 'recipient_key': 'r', 'award_key': 'a',
                            'data': {'participant_name': 'x', 'course_title': 'y', 'issuer_name': 'z', 'extra': 1}})
    assert raised.value.code == 'CERTIFICATE_DATA_INVALID'
    with pytest.raises(InvalidInput):
        _issue_request(timezone='no/such-zone')


def test_issue_request_idempotency_and_legacy_utc_replay():
    from app.domain.certificates import fingerprint
    request = _issue_request()
    assert request.require_replay_of({'request_hash': request.request_hash})
    with pytest.raises(Conflict):
        request.require_replay_of({'request_hash': 'other'})
    legacy = fingerprint(request._core())
    assert request.matches(legacy)
    assert not _issue_request(timezone='Asia/Aden').matches(legacy)


def test_issue_request_rejects_past_expiry():
    request = _issue_request(expires_at='2020-01-01T00:00:00+00:00')
    with pytest.raises(InvalidInput):
        request.require_future_expiry(NOW)
    _issue_request(expires_at='2030-01-01T00:00:00+00:00').require_future_expiry(NOW)


def test_certificate_issue_freezes_snapshot_in_issuer_timezone():
    row = _issued()
    assert row['status'] == 'issued' and row['snapshot']['data']['serial'] == 'CERT-1'
    assert row['snapshot']['data']['issue_date'] == '2026-10-21'
    assert row['snapshot']['issue_timezone'] == 'Asia/Aden'


def test_certificate_layout_check_can_veto_issue():
    def overflow(design, data):
        fail('CERTIFICATE_TEXT_OVERFLOW')
    with pytest.raises(InvalidInput):
        _issued(check_layout=overflow)


def test_certificate_state_is_derived_from_row():
    from app.domain.certificates import Certificate
    row = _issued()
    assert Certificate.state(row, NOW) == 'valid'
    assert Certificate.state({**row, 'status': 'revoked'}, NOW) == 'revoked'
    assert Certificate.state({**row, 'expires_at': '2026-10-01T00:00:00+00:00'}, NOW) == 'expired'
    tampered = {**row, 'snapshot': {**row['snapshot'], 'data': {**row['snapshot']['data'], 'grade': 'A+'}}}
    assert Certificate.state(tampered, NOW) == 'integrity_error'
    with pytest.raises(DomainError) as raised:
        Certificate.require_valid({**row, 'status': 'revoked'}, NOW)
    assert raised.value.code == 'CERTIFICATE_NOT_VALID'


def test_replacement_award_key_is_bound_to_the_original():
    from app.domain.certificates import Certificate
    assert Certificate.replacement_award_key({'id': 'c9'}) == 'replacement/c9'
