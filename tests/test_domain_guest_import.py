"""Domain unit tests: guest import (no database, web framework or HTTP)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import Conflict, DomainError, Forbidden, InvalidInput, NotFound

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_guest_import_upload_limits_and_kind():
    import base64
    from app.domain.admission import GuestImport
    assert GuestImport.decode_upload(base64.b64encode(b'name,phone').decode()) == b'name,phone'
    for content, code in ((None, 'IMPORT_FILE_LIMIT'), ('!!', 'IMPORT_BASE64_INVALID'),
                          (base64.b64encode(b'x' * (3 * 1024 * 1024 + 1)).decode(), 'IMPORT_FILE_LIMIT')):
        with pytest.raises(InvalidInput) as raised:
            GuestImport.decode_upload(content)
        assert raised.value.code == code
    assert GuestImport.file_kind('Guests.XLSX') == 'xlsx' and GuestImport.file_kind('g.csv') == 'csv'
    with pytest.raises(InvalidInput):
        GuestImport.file_kind('g.txt')


def test_guest_import_table_shape_rules():
    from app.domain.admission import GuestImport
    rows = GuestImport.rows_from_table([['Name', 'Phone', 'Days', 'max_companions'],
                                        ['Ali', '777', 'a; b', ''], ['', '', '', '']])
    assert rows == [{'name': 'Ali', 'phone': '777', 'days': ['a', 'b']}]
    for table, code in (([], 'IMPORT_ROWS_1_TO_1000'), ([['name', 'phone']], 'IMPORT_ROWS_1_TO_1000'),
                        ([['name'], ['x']], 'IMPORT_HEADERS_NAME_PHONE'),
                        ([['name', 'name', 'phone'], ['a', 'b', 'c']], 'IMPORT_HEADERS_NAME_PHONE'),
                        ([['name', 'phone', 'role'], ['a', 'b', 'c']], 'IMPORT_UNKNOWN_COLUMN'),
                        ([['name', 'phone'], ['a', 'b', 'c']], 'IMPORT_COLUMN_COUNT')):
        with pytest.raises(InvalidInput) as raised:
            GuestImport.rows_from_table(table)
        assert raised.value.code == code


def test_guest_import_preview_commit_lifecycle():
    from app.domain.admission import GuestImport
    fresh = {'state': 'preview', 'errors': [], 'rows': [{}], 'created_at': (NOW - timedelta(minutes=5)).isoformat()}
    GuestImport.require_committable(fresh, NOW)
    cases = ((None, NotFound), ({**fresh, 'state': 'committed'}, Conflict), ({**fresh, 'errors': [1]}, Conflict),
             ({**fresh, 'rows': []}, Conflict),
             ({**fresh, 'created_at': (NOW - timedelta(hours=2)).isoformat()}, Conflict))
    for preview, error in cases:
        with pytest.raises(error):
            GuestImport.require_committable(preview, NOW)


# Phase 3: admission orchestration guards -------------------------------------------------------

def test_managed_admission_orchestration_guards():
    import pytest as _pytest
    from app.domain import Conflict, Forbidden, InvalidInput, NotFound
    from app.domain import admission

    admission.require_legacy_pass_linked(True)
    with _pytest.raises(Conflict) as legacy:
        admission.require_legacy_pass_linked(False)
    assert legacy.value.code == 'LEGACY_PASSES_REQUIRE_MIGRATION'

    asked = []
    admission.require_guest_list_in_scope(None, lambda: asked.append(1) or False)   # no list: nothing to check
    assert asked == []
    admission.require_guest_list_in_scope('l1', lambda: True)
    with _pytest.raises(Forbidden) as scope:
        admission.require_guest_list_in_scope('l1', lambda: False)
    assert scope.value.code == 'GUEST_LIST_SCOPE'

    admission.require_new_invitation(False)
    with _pytest.raises(Conflict) as duplicate:
        admission.require_new_invitation(True)
    assert duplicate.value.code == 'INVITATION_ALREADY_EXISTS'

    assert admission.require_invitation({'id': 'i'}) == {'id': 'i'}
    with _pytest.raises(NotFound):
        admission.require_invitation(None)
    admission.require_invitation_of_event({'event_id': 'e'}, 'e')
    with _pytest.raises(NotFound) as elsewhere:
        admission.require_invitation_of_event({'event_id': 'e'}, 'other')
    assert elsewhere.value.code == 'INVITATION_NOT_FOUND'

    assert admission.require_active_entitlement({'id': 1}) == {'id': 1}
    with _pytest.raises(Conflict) as none_left:
        admission.require_active_entitlement(None)
    assert none_left.value.code == 'ENTITLEMENT_NOT_FOUND'
    admission.require_consumed(True)
    with _pytest.raises(Conflict) as used:
        admission.require_consumed(False)
    assert used.value.code == 'ADMISSION_ALREADY_USED'
    admission.require_new_guest_list(True)
    with _pytest.raises(Conflict):
        admission.require_new_guest_list(False)

    seen = {'+967771111111'}
    admission.require_unique_in_file('+967772222222', seen)
    with _pytest.raises(InvalidInput) as repeated:
        admission.require_unique_in_file('+967771111111', seen)
    assert repeated.value.code == 'DUPLICATE_PHONE_IN_FILE'

    admission.require_direct_registration_open(False)
    with _pytest.raises(Conflict) as closed:
        admission.require_direct_registration_open(True)
    assert closed.value.code == 'ADMISSION_REGISTRATION_REQUIRED'
