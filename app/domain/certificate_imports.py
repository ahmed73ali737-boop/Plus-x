"""Bulk certificate issuance rules: upload limits, column mapping, row validation and the
preview -> commit lifecycle that turns a validated preview into queued issue jobs.

Parsing the spreadsheet itself is an adapter concern; these rules start from a table
(a list of rows of cells) so they stay free of file formats and the database.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.domain.certificates import FIELDS
from app.domain.errors import Conflict, DomainError, NotFound, fail
from app.domain.values import number, stamp, text

MAX_ENCODED_BYTES = 4 * 1024 * 1024
MAX_BYTES = 3 * 1024 * 1024
MAX_HEADERS = 32
PREVIEW_TTL = timedelta(hours=1)
REQUIRED_MAPPING = frozenset({'recipient_key', 'award_key', *FIELDS[:3]})
ALLOWED_MAPPING = REQUIRED_MAPPING | {'grade', 'training_hours'}
KEY_LIMITS = {'award_key': 80, 'recipient_key': 160}


def decode_upload(content_base64) -> bytes:
    if not isinstance(content_base64, str) or len(content_base64) > MAX_ENCODED_BYTES:
        fail('IMPORT_FILE_LIMIT')
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, TypeError):
        fail('IMPORT_BASE64_INVALID')
    if len(raw) > MAX_BYTES:
        fail('IMPORT_FILE_LIMIT')
    return raw


def table_kind(filename: str) -> str:
    if filename.endswith('.xlsx'):
        return 'xlsx'
    if filename.endswith('.csv'):
        return 'csv'
    fail('IMPORT_CSV_OR_XLSX_REQUIRED')


def headers_of(table: list) -> list[str]:
    if not 2 <= len(table) <= 1001:
        fail('IMPORT_ROWS_1_TO_1000')
    headers = [str(cell).strip() for cell in table[0]]
    if not all(headers) or len(set(headers)) != len(headers) or len(headers) > MAX_HEADERS:
        fail('CERTIFICATE_IMPORT_HEADERS')
    return headers


def check_mapping(mapping, headers: list[str]) -> dict:
    """Every required certificate field maps to exactly one existing column."""
    if (not isinstance(mapping, dict) or not REQUIRED_MAPPING.issubset(mapping)
            or set(mapping) - ALLOWED_MAPPING or any(column not in headers for column in mapping.values())):
        fail('CERTIFICATE_IMPORT_MAPPING')
    return mapping


def preview_rows(table: list, headers: list[str], mapping: dict, *, template_id: str, timezone_name: str,
                 award_exists: Callable[[str, str], bool]) -> tuple[list[dict], list[dict]]:
    """Validate each data row; bad rows become errors, never silently dropped."""
    rows, errors, seen = [], [], set()
    for index, value in enumerate(table[1:], 2):
        if not any(str(cell).strip() for cell in value):
            continue
        try:
            if len(value) > len(headers):
                fail('IMPORT_COLUMN_COUNT')
            record = dict(zip(headers, [*value, *[''] * (len(headers) - len(value))]))
            mapped = {key: text(record[column], KEY_LIMITS.get(key, 250), key in REQUIRED_MAPPING)
                      for key, column in mapping.items()}
            pair = (mapped['recipient_key'], mapped['award_key'])
            if pair in seen:
                fail('CERTIFICATE_DUPLICATE_IN_FILE')
            seen.add(pair)
            if mapped.get('training_hours'):
                number(mapped['training_hours'], low=0, high=100000)
            if award_exists(*pair):
                fail('CERTIFICATE_ALREADY_ISSUED')
            rows.append({'template_id': template_id, 'recipient_key': pair[0], 'award_key': pair[1],
                         'timezone': timezone_name, 'data': {key: mapped.get(key, '') for key in FIELDS[:5]}})
        except DomainError as exc:
            errors.append({'row': index, 'error': exc.detail})
    if not rows and not errors:
        fail('IMPORT_ROWS_1_TO_1000')
    return rows, errors


class IssuanceBatch:
    """A stored preview that can be committed exactly once, while fresh and error-free."""

    @staticmethod
    def require_found(row: dict | None) -> dict:
        if not row:
            fail('IMPORT_PREVIEW_NOT_FOUND', NotFound)
        return row

    @staticmethod
    def is_replay(row: dict) -> bool:
        return bool(row['committed_at'])

    @staticmethod
    def require_committable(row: dict, at: datetime) -> None:
        if row['errors'] or not row['rows']:
            fail('IMPORT_ERRORS_MUST_BE_FIXED', Conflict)
        if datetime.fromisoformat(row['created_at']) < at - PREVIEW_TTL:
            fail('IMPORT_PREVIEW_EXPIRED', Conflict)

    @staticmethod
    def available_at(requested, current: str) -> str:
        """Canonical UTC so string ordering stays chronological across workers."""
        return datetime.fromisoformat(stamp(requested) or current).astimezone(timezone.utc).isoformat()

    @staticmethod
    def request_key(import_id: str, index: int) -> str:
        """One idempotency key per row: a replayed job can never issue twice."""
        return f'{import_id}:{index}'
