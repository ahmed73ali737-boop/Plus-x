"""Domain unit tests: signed capability token and request nonce rules (no keys, no HMAC)."""
import pytest

from app.domain import Forbidden, NotFound, Unavailable
from app.domain import capability_tokens as tokens


def test_only_plain_identifiers_can_be_signed():
    assert tokens.require_identifier('abc_DEF-123') == 'abc_DEF-123'
    for bad in ('', 'a.b', 'a b', 'x' * 65, None, 5, 'ü'):
        with pytest.raises(NotFound) as error:
            tokens.require_identifier(bad)
        assert error.value.code == 'TOKEN_INVALID'


def test_a_token_is_exactly_three_plain_parts_and_bounded():
    assert tokens.parse_token('v1.ident.sig') == ('v1', 'ident', 'sig')
    for bad in ('v1.ident', 'v1.ident.sig.extra', 'v1..sig', 'v1.id ent.sig', 'x' * 221, None, 5, ['a', 'b', 'c']):
        with pytest.raises(NotFound) as error:
            tokens.parse_token(bad)
        assert error.value.code == 'NOT_FOUND'          # a probe never learns which part was wrong


def test_unknown_key_versions_are_unavailability_and_bad_signatures_are_not_found():
    tokens.require_known_key_version(True)
    with pytest.raises(Unavailable) as error:
        tokens.require_known_key_version(False)
    assert error.value.code == 'CERTIFICATE_KEY_VERSION_UNAVAILABLE'
    tokens.require_valid_signature(True)
    with pytest.raises(NotFound):
        tokens.require_valid_signature(False)


def test_nonce_shape():
    assert tokens.parse_nonce('v1.123.sig') == ('v1', '123', 'sig')
    for bad in ('v1.123', 'a.b.c.d', 'x' * 181, None, 5):
        with pytest.raises(Forbidden) as error:
            tokens.parse_nonce(bad)
        assert error.value.code == 'REQUEST_NONCE_INVALID'


def test_nonce_freshness_window_is_the_current_fifteen_minutes_plus_or_minus_one():
    now = 900 * 1000 + 17
    assert tokens.current_epoch(now) == 1000
    for epoch in ('999', '1000', '1001'):
        tokens.require_fresh_epoch(epoch, now)
    for epoch in ('998', '1002', '', 'abc', '-1', '10.0'):
        with pytest.raises(Forbidden) as error:
            tokens.require_fresh_epoch(epoch, now)
        assert error.value.code == 'REQUEST_NONCE_EXPIRED'


def test_a_nonce_needs_a_known_key_and_a_valid_signature():
    tokens.require_valid_nonce(True, True)
    for known, valid in ((False, True), (True, False), (False, False)):
        with pytest.raises(Forbidden) as error:
            tokens.require_valid_nonce(known, valid)
        assert error.value.code == 'REQUEST_NONCE_INVALID'
