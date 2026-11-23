"""Domain unit tests: phone/password account contact rules (no database, no HTTP)."""
import pytest

from app.domain import Conflict, InvalidInput
from app.domain import contacts


@pytest.mark.parametrize('raw,expected', [
    ('+967771234567', '+967771234567'),
    ('00967 77 123 4567', '+967771234567'),
    ('٠٠٩٦٧٧٧١٢٣٤٥٦٧', '+967771234567'),
    ('+44 20 7946 0958', '+442079460958'),
])
def test_account_phone_normalises_to_e164(raw, expected):
    assert contacts.account_phone(raw) == expected


@pytest.mark.parametrize('raw', ['abc', '+967 12 345 678', '+0123456789', '+12', 'tel:+967771234567', '12ab34567890'])
def test_account_phone_rejects_malformed_and_non_mobile_yemeni_numbers(raw):
    with pytest.raises(InvalidInput) as error:
        contacts.account_phone(raw)
    assert error.value.code == 'PHONE_INVALID'


def test_contact_identity_prefers_phone_principal_unless_email_is_preserved():
    assert contacts.contact_identity({'phone': '+967771234567'}) == ('tel:+967771234567', '+967771234567')
    assert contacts.contact_identity({'email': 'A@B.co'}) == ('a@b.co', None)
    both = {'phone': '+967771234567', 'email': 'a@b.co'}
    assert contacts.contact_identity(both) == ('tel:+967771234567', '+967771234567')
    assert contacts.contact_identity(both, preserve_email=True) == ('a@b.co', '+967771234567')


def test_contact_identity_needs_a_phone_or_a_valid_email():
    with pytest.raises(InvalidInput) as missing:
        contacts.contact_identity({})
    assert missing.value.code == 'PHONE_REQUIRED'
    with pytest.raises(InvalidInput) as bad:
        contacts.contact_identity({'email': 'not-an-email'})
    assert bad.value.code == 'EMAIL_INVALID'


def test_phone_principal_never_leaks_as_an_email():
    assert contacts.public_email('tel:+967771234567') is None
    assert contacts.public_email('a@b.co') == 'a@b.co'
    assert not contacts.looks_up_by_email('tel:+967771234567')
    assert contacts.looks_up_by_email('a@b.co')


def test_one_person_per_contact():
    a, b = {'id': 'a'}, {'id': 'b'}
    assert contacts.resolve_contact_user(None, []) is None
    assert contacts.resolve_contact_user(a, []) is a
    assert contacts.resolve_contact_user(None, [b]) is b
    assert contacts.resolve_contact_user(a, [a]) is a
    for args in ((a, [b]), (None, [a, b])):
        with pytest.raises(Conflict) as error:
            contacts.resolve_contact_user(*args)
        assert error.value.code == 'CONTACT_IDENTITIES_CONFLICT'


def test_phone_binding_rules():
    mine = {'user_id': 'u1', 'phone': '+1'}
    assert contacts.phone_binding_action(None, None, 'u1', '+1') == 'bind'
    assert contacts.phone_binding_action(mine, mine, 'u1', '+1') == 'keep'
    with pytest.raises(Conflict) as taken:
        contacts.phone_binding_action({'user_id': 'u2'}, None, 'u1', '+1')
    assert taken.value.code == 'PHONE_ALREADY_REGISTERED'
    with pytest.raises(Conflict) as change:
        contacts.phone_binding_action(None, {'phone': '+2'}, 'u1', '+1')
    assert change.value.code == 'PHONE_CHANGE_REQUIRES_SUPPORT'


def test_account_review_queue_visibility_is_lazy_and_staff_first():
    calls = []

    def fact(name, value):
        def read():
            calls.append(name)
            return value
        return read

    assert contacts.may_review_accounts('platform', fact('owner', False), fact('committee', False))
    assert calls == []
    assert contacts.may_review_accounts('agency', fact('owner', True), fact('committee', False))
    assert calls == ['owner']
    assert contacts.may_review_accounts('agency', fact('owner', False), fact('committee', True))
    assert not contacts.may_review_accounts('agency', fact('owner', False), fact('committee', False))
