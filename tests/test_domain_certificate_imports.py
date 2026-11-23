"""Domain unit tests: bulk certificate issuance rules (no database, spreadsheet library or HTTP)."""
import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import Conflict, InvalidInput, NotFound
from app.domain import certificate_imports as imports
from app.domain.certificate_imports import IssuanceBatch

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
HEADERS = ['who', 'award', 'name', 'course', 'issuer', 'hours']
MAPPING = {'recipient_key': 'who', 'award_key': 'award', 'participant_name': 'name', 'course_title': 'course',
           'issuer_name': 'issuer', 'training_hours': 'hours'}


def table(*rows):
    return [HEADERS, *rows]


def preview(rows, exists=lambda recipient, award: False):
    return imports.preview_rows(table(*rows), HEADERS, MAPPING, template_id='t1', timezone_name='UTC',
                                award_exists=exists)


def test_upload_limits_and_kind():
    assert imports.decode_upload(base64.b64encode(b'a,b').decode()) == b'a,b'
    for content, code in ((5, 'IMPORT_FILE_LIMIT'), ('%%', 'IMPORT_BASE64_INVALID'),
                          (base64.b64encode(b'x' * (imports.MAX_BYTES + 1)).decode(), 'IMPORT_FILE_LIMIT')):
        with pytest.raises(InvalidInput) as raised:
            imports.decode_upload(content)
        assert raised.value.code == code
    assert imports.table_kind('a.xlsx') == 'xlsx' and imports.table_kind('a.csv') == 'csv'
    with pytest.raises(InvalidInput):
        imports.table_kind('a.pdf')


def test_headers_must_be_unique_non_blank_and_bounded():
    assert imports.headers_of([[' a ', 'b'], ['1', '2']]) == ['a', 'b']
    for bad in ([['a', 'b']], [['a', 'a'], ['1', '2']], [['a', ''], ['1', '2']],
                [[f'h{i}' for i in range(33)], ['x'] * 33]):
        with pytest.raises(InvalidInput):
            imports.headers_of(bad)


def test_mapping_requires_every_core_field_and_known_columns():
    assert imports.check_mapping(MAPPING, HEADERS) is MAPPING
    for bad in (None, {k: v for k, v in MAPPING.items() if k != 'award_key'}, {**MAPPING, 'extra': 'who'},
                {**MAPPING, 'grade': 'missing-column'}):
        with pytest.raises(InvalidInput) as raised:
            imports.check_mapping(bad, HEADERS)
        assert raised.value.code == 'CERTIFICATE_IMPORT_MAPPING'


def test_preview_rows_reports_each_bad_row_instead_of_dropping_it():
    rows, errors = preview([
        ['r1', 'a1', 'Sara', 'Safety', 'Eventna', '8'],
        ['r1', 'a1', 'Sara', 'Safety', 'Eventna', '8'],
        ['r2', 'a1', 'Omar', 'Safety', 'Eventna', 'many'],
        ['r3', 'a1', '', 'Safety', 'Eventna', ''],
        ['', '', '', '', '', ''],
        ['r4', 'a1', 'Ali', 'Safety', 'Eventna', '', 'extra'],
    ])
    assert [row['recipient_key'] for row in rows] == ['r1']
    assert rows[0]['data']['participant_name'] == 'Sara' and rows[0]['timezone'] == 'UTC'
    assert {error['row']: error['error'] for error in errors} == {
        3: 'CERTIFICATE_DUPLICATE_IN_FILE', 4: 'NUMBER_INVALID', 5: 'TEXT_LENGTH', 7: 'IMPORT_COLUMN_COUNT'}


def test_preview_flags_awards_that_already_exist_and_empty_files():
    rows, errors = preview([['r1', 'a1', 'Sara', 'Safety', 'Eventna', '']], exists=lambda recipient, award: True)
    assert rows == [] and errors[0]['error'] == 'CERTIFICATE_ALREADY_ISSUED'
    with pytest.raises(InvalidInput):
        preview([['', '', '', '', '', '']])


def test_batch_commit_lifecycle():
    fresh = {'errors': [], 'rows': [{}], 'committed_at': None, 'created_at': (NOW - timedelta(minutes=1)).isoformat()}
    with pytest.raises(NotFound):
        IssuanceBatch.require_found(None)
    assert IssuanceBatch.require_found(fresh) is fresh
    assert not IssuanceBatch.is_replay(fresh) and IssuanceBatch.is_replay({**fresh, 'committed_at': 'x'})
    IssuanceBatch.require_committable(fresh, NOW)
    for bad in ({**fresh, 'errors': ['x']}, {**fresh, 'rows': []},
                {**fresh, 'created_at': (NOW - timedelta(hours=2)).isoformat()}):
        with pytest.raises(Conflict):
            IssuanceBatch.require_committable(bad, NOW)


def test_availability_is_canonical_utc_and_request_keys_are_per_row():
    assert IssuanceBatch.available_at('2026-10-19T15:00:00+03:00', 'ignored') == '2026-10-19T12:00:00+00:00'
    assert IssuanceBatch.available_at('', '2026-10-19T09:00:00+00:00') == '2026-10-19T09:00:00+00:00'
    with pytest.raises(InvalidInput):
        IssuanceBatch.available_at('2026-10-19T15:00:00', 'x')
    assert IssuanceBatch.request_key('imp', 3) == 'imp:3'


def test_workbook_shape_template_and_commit_guards():
    import pytest as _pytest
    from app.domain import Conflict, InvalidInput, NotFound
    from app.domain.certificate_imports import (
        require_commit_recorded, require_import_template, require_single_sheet, unreadable_table)
    require_single_sheet({'a': []})
    for workbook in ({}, {'a': [], 'b': []}):
        with _pytest.raises(InvalidInput) as sheets:
            require_single_sheet(workbook)
        assert sheets.value.code == 'IMPORT_ONE_SHEET_REQUIRED'
    with _pytest.raises(InvalidInput) as unreadable:
        unreadable_table()
    assert unreadable.value.code == 'CERTIFICATE_IMPORT_INVALID'
    assert require_import_template({'id': 't'}) == {'id': 't'}
    with _pytest.raises(NotFound):
        require_import_template(None)
    require_commit_recorded(True)
    with _pytest.raises(Conflict) as committed:
        require_commit_recorded(False)
    assert committed.value.code == 'IMPORT_ALREADY_COMMITTED'
