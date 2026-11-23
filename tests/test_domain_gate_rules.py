"""Domain unit tests: scan replay and admission guards (no database, web framework or HTTP)."""
import pytest

from app.domain import Conflict, Forbidden, InvalidInput
from app.domain.gate import (
    require_invitation_when_managed,
    require_scan_replay,
    require_unmanaged_quantity,
    require_valid_admission,
)

SCAN = {'event_id': 'e1', 'guest_number': 'G-1', 'direction': 'entry', 'checkpoint': 'main'}
SAME = dict(event_id='e1', guest_number='g-1', mode='entry', checkpoint='main', quantity=1)


def test_exact_scan_replay_is_accepted_case_insensitively_on_the_pass_number():
    require_scan_replay(SCAN, None, **SAME)
    require_scan_replay(SCAN, {'quantity': 1}, **SAME)


@pytest.mark.parametrize('change', [{'event_id': 'e2'}, {'guest_number': 'g-2'}, {'mode': 'exit'},
                                    {'checkpoint': 'vip'}])
def test_scan_id_reuse_for_a_different_scan_conflicts(change):
    with pytest.raises(Conflict) as raised:
        require_scan_replay(SCAN, None, **{**SAME, **change})
    assert raised.value.code == 'SCAN_ID_CONFLICT'


def test_scan_id_reuse_with_a_different_quantity_conflicts():
    with pytest.raises(Conflict):
        require_scan_replay(SCAN, {'quantity': 2}, **SAME)


def test_managed_admission_requires_an_entitlement():
    require_invitation_when_managed(False, {'managed': False})
    require_invitation_when_managed(True, {'managed': True})
    with pytest.raises(Forbidden) as raised:
        require_invitation_when_managed(True, {'managed': False})
    assert raised.value.code == 'INVITATION_REQUIRED'


def test_invalid_validation_surfaces_its_reason_or_a_generic_denial():
    require_valid_admission({'status': 'valid'})
    with pytest.raises(Forbidden) as raised:
        require_valid_admission({'status': 'invalid', 'reason': 'GATE_CLOSED'})
    assert raised.value.code == 'GATE_CLOSED'
    with pytest.raises(Forbidden) as raised:
        require_valid_admission({'status': 'invalid'})
    assert raised.value.code == 'ACCESS_DENIED'


def test_unmanaged_scan_admits_one_person():
    require_unmanaged_quantity(1)
    with pytest.raises(InvalidInput):
        require_unmanaged_quantity(2)


def test_a_pass_number_must_belong_to_a_registered_guest():
    from app.domain import NotFound
    from app.domain.gate import require_registered_guest
    guest = {'id': 'g'}
    assert require_registered_guest(guest) is guest
    with pytest.raises(NotFound) as error:
        require_registered_guest(None)
    assert error.value.code == 'GUEST_NOT_REGISTERED'
