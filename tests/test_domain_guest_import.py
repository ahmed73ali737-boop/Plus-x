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
